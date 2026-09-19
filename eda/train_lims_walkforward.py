"""Retrospective rolling-origin experiments; isolated tuning/calibration/evaluation."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error
from forensics_utils import parse_lims


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--run-id', default='lims_walkforward_20260914_v2')
    p.add_argument('--resume', action='store_true')
    args = p.parse_args()
    out = args.root/'eda/experiments'/args.run_id
    out.mkdir(parents=True, exist_ok=args.resume)
    if (out/'COMPLETE.json').exists():
        raise RuntimeError('Run already complete; use a new run id')
    paths = [args.root/'data/242000_tags.csv',next((args.root/'docs').glob('ЛИМС*.xlsx'))]
    manifest_path = out/('resume_manifest.json' if args.resume else 'manifest.json')
    manifest_path.write_text(json.dumps({'source_sha256':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in paths},
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'years':[2024,2025],
        'horizon_hours':6,'alpha':.1,'seed':42,'gpu':'0',
        'split':'train before year; validation Jan-Jun; calibration Jul-Sep; evaluation Oct-Dec; 48h gaps',
        'note':'Retrospective robustness analysis. Periods already explored; not a new blind holdout. No action-effect validation.'},indent=2))
    t=pd.read_csv(paths[0],parse_dates=['date']).set_index('date').sort_index()
    t=t.drop(columns=[c for c in t if c.startswith('Unnamed:')]).astype(float)
    assert t.index.is_unique and (t.index.to_series().diff().dropna()==pd.Timedelta('10min')).all()
    t=t.replace([np.inf,-np.inf],np.nan)
    f=t.add_suffix('_now')
    for h in [1,6,24]:
        r=t.rolling(f'{h}h',min_periods=h*6)
        f=f.join(r.mean().add_suffix(f'_mean_{h}h')).join(r.std().add_suffix(f'_std_{h}h'))
    f.index.name='feature_time'
    labs=parse_lims(paths[1])
    labs=labs[(labs.installation=='Гидроочистка') & (labs.sampling_point=='2')]
    metrics=pd.read_csv(out/'metrics.csv').to_dict('records') if args.resume else []
    predictions=[pd.read_csv(out/'predictions.csv')] if args.resume else []
    tuning=pd.read_csv(out/'tuning.csv').to_dict('records') if args.resume else []
    skipped=[]
    for target in ['Mg.Sulfur','D15','FlashPoint']:
        lab=labs[labs.quality_parameter==target][['timestamp','value']].groupby('timestamp',as_index=False).value.median().sort_values('timestamp')
        d=lab.assign(origin=lab.timestamp-pd.Timedelta(hours=6))
        d=pd.merge_asof(d,f.reset_index(),left_on='origin',right_on='feature_time',direction='backward',tolerance=pd.Timedelta('10min'))
        d=d[d.feature_time.notna()].reset_index(drop=True)
        for delay in [24,48]:
            hist=lab.rename(columns={'timestamp':f'lab_time_{delay}','value':f'last_lab_{delay}'})
            hist['available']=hist[f'lab_time_{delay}']+pd.Timedelta(hours=delay)
            merged=pd.merge_asof(d[['origin']],hist,left_on='origin',right_on='available',direction='backward')
            assert (merged.available.dropna()<=merged.loc[merged.available.notna(),'origin']).all()
            d[f'last_lab_{delay}']=merged[f'last_lab_{delay}']
            d[f'age_{delay}']=(d.origin-merged[f'lab_time_{delay}']).dt.total_seconds()/3600
            d[f'missing_{delay}']=d[f'last_lab_{delay}'].isna().astype(int)
        assert (d.feature_time<=d.origin).all()
        for year in [2024,2025]:
            masks={'train':d.timestamp<pd.Timestamp(year,1,1),
                'validation':(d.timestamp>=pd.Timestamp(year,1,3))&(d.timestamp<pd.Timestamp(year,7,1)),
                'calibration':(d.timestamp>=pd.Timestamp(year,7,3))&(d.timestamp<pd.Timestamp(year,10,1)),
                'evaluation':(d.timestamp>=pd.Timestamp(year,10,3))&(d.timestamp<pd.Timestamp(year+1,1,1))}
            counts={k:int(m.sum()) for k,m in masks.items()}
            if min(counts.values())<20:
                skipped.append({'target':target,'year':year,**counts,'reason':'fewer than 20 observations in a partition'})
                pd.DataFrame(skipped).to_csv(out/'skipped.csv',index=False)
                print('SKIP',target,year,counts,flush=True)
                continue
            y=d.value
            for variant in ['telemetry','history24','history48','median','last24','last48']:
                if any(r['target']==target and r['year']==year and r['variant']==variant for r in metrics):
                    continue
                cols=list(f.columns)
                if variant.startswith('history'):
                    delay=int(variant[7:]); cols += [f'last_lab_{delay}',f'age_{delay}',f'missing_{delay}']
                selected='baseline'
                if variant in ['median','last24','last48']:
                    pred=np.full(len(d),y[masks['train']].median()) if variant=='median' else d[f'last_lab_{variant[4:]}'].fillna(y[masks['train']].median()).to_numpy()
                else:
                    med=d.loc[masks['train'],cols].median().fillna(0)
                    X=d[cols].fillna(med).astype('float32')
                    candidates=[]
                    for loss in ['MAE','RMSE']:
                        model=CatBoostRegressor(iterations=500,depth=4,loss_function=loss,eval_metric='MAE',learning_rate=.04,
                            l2_leaf_reg=10,task_type='GPU',devices='0',thread_count=4,random_seed=42,verbose=False,allow_writing_files=False)
                        model.fit(X[masks['train']],y[masks['train']],eval_set=(X[masks['validation']],y[masks['validation']]),early_stopping_rounds=50)
                        score=mean_absolute_error(y[masks['validation']],model.predict(X[masks['validation']]))
                        candidates.append((score,loss,model))
                        tuning.append({'target':target,'year':year,'variant':variant,'loss':loss,'validation_mae':score})
                    _,selected,model=min(candidates,key=lambda c:c[0])
                    pred=model.predict(X)
                    stem=f'{target}_{year}_{variant}'
                    model.save_model(str(out/f'{stem}.cbm'))
                    (out/f'{stem}.json').write_text(json.dumps({'columns':cols,'imputation':med.to_dict(),'loss':selected}))
                residual=np.abs(y[masks['calibration']].to_numpy()-pred[masks['calibration']])
                rank=min(len(residual),int(np.ceil((len(residual)+1)*.9)))
                q=float(np.sort(residual)[rank-1])
                m=masks['evaluation']; actual=y[m].to_numpy(); point=pred[m]
                lo=point-q; hi=point+q
                row={'target':target,'year':year,'variant':variant,'loss':selected,'n':len(actual),
                    'mae':float(np.mean(np.abs(actual-point))),'median_ae':float(np.median(np.abs(actual-point))),
                    'rmse':float(np.sqrt(np.mean((actual-point)**2))),'calibration_n':len(residual),
                    'interval_halfwidth':q,'coverage':float(np.mean((actual>=lo)&(actual<=hi)))}
                if target=='Mg.Sulfur':
                    exceed=actual>10
                    for label,alert in [('point',point>10),('upper90',hi>10)]:
                        tp=int((exceed&alert).sum()); fp=int((~exceed&alert).sum()); fn=int((exceed&~alert).sum())
                        row.update({f'{label}_tp':tp,f'{label}_fp':fp,f'{label}_fn':fn,
                            f'{label}_recall':tp/(tp+fn) if tp+fn else None,
                            f'{label}_precision':tp/(tp+fp) if tp+fp else None})
                metrics.append(row)
                predictions.append(pd.DataFrame({'timestamp':d.loc[m,'timestamp'],'target':target,'year':year,'variant':variant,
                    'actual':actual,'prediction':point,'lower90':lo,'upper90':hi}))
                pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False)
                pd.concat(predictions).to_csv(out/'predictions.csv',index=False)
                pd.DataFrame(tuning).to_csv(out/'tuning.csv',index=False)
                print(target,year,variant,'MAE',round(row['mae'],3),'coverage',round(row['coverage'],3),flush=True)
    (out/'COMPLETE.json').write_text(json.dumps({'status':'complete','models_trained':len(tuning),'evaluations':len(metrics)}))
    print('COMPLETE',flush=True)


if __name__=='__main__':
    main()
