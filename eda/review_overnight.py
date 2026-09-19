"""Audit saved predictions on matched timestamps; no training or reselection."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from forensics_utils import parse_lims

EDA=Path(__file__).resolve().parent
OUT=EDA/'artifacts/overnight_review'
OUT.mkdir(parents=True,exist_ok=True)
PRIMARY=EDA/'experiments/overnight_20260915_13h'
STABILITY=EDA/'experiments/overnight_20260915_stability'


def bootstrap_difference(df, a, b, seed=42):
    """Resample whole calendar months, keeping paired observations together."""
    errors=pd.DataFrame({'month':df.timestamp.dt.to_period('M').astype(str),
        'delta':np.abs(df.actual-df[a])-np.abs(df.actual-df[b])})
    blocks=errors.groupby('month').delta.agg(['sum','count'])
    rng=np.random.default_rng(seed)
    ix=rng.integers(0,len(blocks),size=(2000,len(blocks)))
    stats=blocks['sum'].to_numpy()[ix].sum(axis=1)/blocks['count'].to_numpy()[ix].sum(axis=1)
    return {'delta_mae_vs_last24':float(errors.delta.mean()),'delta_ci_low':float(np.quantile(stats,.025)),
            'delta_ci_high':float(np.quantile(stats,.975)),'bootstrap_months':len(blocks)}


def main():
    labs=parse_lims(next((EDA.parent/'docs').glob('ЛИМС*.xlsx')))
    labs=labs[(labs.installation=='Гидроочистка')&(labs.sampling_point=='2')]
    histories={target:g.groupby('timestamp',as_index=False).value.median().sort_values('timestamp')
               for target,g in labs.groupby('quality_parameter')}
    rows=[]; observations=[]; monthly=[]; baseline_risk=[]
    for source,folder in [('primary',PRIMARY),('stability',STABILITY)]:
        for meta_path in sorted((folder/'final').glob('*.json')):
            meta=json.loads(meta_path.read_text()); c=meta['config']; year=meta['metrics']['year']
            d=pd.read_csv(meta_path.with_suffix('.csv'),parse_dates=['timestamp']).sort_values('timestamp')
            assert d.timestamp.is_unique
            d['origin']=d.timestamp-pd.Timedelta(hours=c['horizon'])
            lab=histories[c['target']]
            cutoff=pd.Timestamp(2025 if year==2026 else year,1,1)
            train=lab[lab.timestamp<cutoff].value
            d['median']=train.median()
            for delay in [6,24,48]:
                h=lab.rename(columns={'timestamp':'lab_time','value':'last'})
                h['available']=h.lab_time+pd.Timedelta(hours=delay)
                matched=pd.merge_asof(d[['origin']],h,left_on='origin',right_on='available',direction='backward')
                d[f'last{delay}']=matched['last'].fillna(train.median()).to_numpy()
                d[f'age{delay}']=(d.origin.reset_index(drop=True)-matched.lab_time).dt.total_seconds().to_numpy()/3600
            row={'source':source,'trial':c['id'],'objective':c['objective'],'horizon':c['horizon'],'year':year,
                 'seed':c['seed'],'history_delay':c['history'],'exclude_f25':c['exclude_f25'],'n':len(d)}
            for k,v in [('source',source),('trial',c['id']),('objective',c['objective']),('horizon',c['horizon']),('year',year),('seed',c['seed'])]:
                d[k]=v
            risk=c['objective']=='risk'
            if risk:
                a=d.actual>10; alarm=d.alarm.astype(bool)
                tp=int((a&alarm).sum());fp=int((~a&alarm).sum());fn=int((a&~alarm).sum());tn=int((~a&~alarm).sum())
                row.update({'ap':float(average_precision_score(a,d.prediction)), 'prevalence':a.mean(),
                    'tp':tp,'fp':fp,'fn':fn,'tn':tn,'recall':tp/(tp+fn) if tp+fn else np.nan,
                    'precision':tp/(tp+fp) if tp+fp else np.nan,'fpr':fp/(fp+tn) if fp+tn else np.nan,
                    'alert_rate':alarm.mean(),'threshold':meta['metrics']['threshold']})
                if source=='primary':
                    for delay in [6,24,48]:
                        b=d[f'last{delay}']>10
                        baseline_risk.append({'year':year,'horizon':c['horizon'],'delay':delay,'n':len(d),
                            'ap':float(average_precision_score(a,d[f'last{delay}'])),
                            'recall':float(b[a].mean()),'fpr':float(b[~a].mean()),
                            'tp':int((a&b).sum()),'fp':int((~a&b).sum()),'fn':int((a&~b).sum())})
                    d['outcome']=np.select([a&alarm,~a&alarm,a&~alarm],['TP','FP','FN'],default='TN')
                    for month,g in d.groupby(d.timestamp.dt.to_period('M').astype(str)):
                        counts=g.outcome.value_counts()
                        monthly.append({'objective':'risk','year':year,'horizon':c['horizon'],'month':month,'n':len(g),
                            **{k:int(counts.get(k,0)) for k in ['TP','FP','FN','TN']}})
            else:
                row['mae']=float((d.actual-d.prediction).abs().mean())
                row['rmse']=float(np.sqrt(((d.actual-d.prediction)**2).mean()))
                row['bias']=float((d.prediction-d.actual).mean())
                for name in ['median','last6','last24','last48']:
                    row[f'mae_{name}']=float((d.actual-d[name]).abs().mean())
                row['coverage90']=float(((d.actual>=d.lower90)&(d.actual<=d.upper90)).mean())
                row['interval_width']=float((d.upper90-d.lower90).mean())
                if source=='primary':
                    if year==2026:
                        row.update(bootstrap_difference(d,'prediction','last24'))
                    for month,g in d.groupby(d.timestamp.dt.to_period('M').astype(str)):
                        monthly.append({'objective':c['objective'],'year':year,'horizon':c['horizon'],'month':month,'n':len(g),
                            'mae':float((g.actual-g.prediction).abs().mean()),'mae_last24':float((g.actual-g.last24).abs().mean()),
                            'coverage90':float(((g.actual>=g.lower90)&(g.actual<=g.upper90)).mean())})
            rows.append(row)
            if source=='primary': observations.append(d)
    metrics=pd.DataFrame(rows);metrics.to_csv(OUT/'matched_metrics.csv',index=False)
    obs=pd.concat(observations,ignore_index=True);obs.to_csv(OUT/'primary_observations.csv',index=False)
    pd.DataFrame(monthly).to_csv(OUT/'monthly_metrics.csv',index=False)
    pd.DataFrame(baseline_risk).to_csv(OUT/'risk_baselines.csv',index=False)
    obs[(obs.objective=='risk')&(obs.outcome=='FN')].to_csv(OUT/'missed_exceedances.csv',index=False)
    metrics.groupby(['objective','horizon','year'])[[c for c in ['mae','ap','recall','precision','fpr','coverage90'] if c in metrics]].agg(['count','mean','std','min','max']).to_csv(OUT/'five_seed_dispersion.csv')
    results=[json.loads(line) for line in (PRIMARY/'results.jsonl').read_text().splitlines()]
    selection=pd.DataFrame([{**r['config'],'score':r['selection_score']} for r in results])
    selection.groupby(['objective','horizon','history','exclude_f25']).score.agg(['count','mean','median','max']).to_csv(OUT/'search_summary_confounded.csv')
    print('Saved',len(metrics),'evaluations;',len(obs),'primary observations;',OUT)
    print(metrics[(metrics.source=='primary')&(metrics.year==2026)&(metrics.objective!='risk')][['objective','horizon','mae','mae_last6','mae_last24','mae_last48','delta_ci_low','delta_ci_high']].to_string(index=False))
    print(pd.DataFrame(baseline_risk).query('year==2026').to_string(index=False))


if __name__=='__main__': main()
