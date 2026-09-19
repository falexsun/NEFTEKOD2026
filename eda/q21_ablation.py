"""Matched Q21 ablations, frozen hyperparameters; no retuning on evaluation."""
from pathlib import Path
import json
import pickle
import numpy as np
import pandas as pd
import overnight_a100 as engine
from sklearn.metrics import average_precision_score,brier_score_loss

EDA=Path(__file__).resolve().parent
ROOT=EDA.parent
OUT=EDA/'experiments/q21_ablation_20260915'


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    parent=EDA/'experiments/overnight_20260915_13h'
    winners=json.loads((parent/'frozen_winners.json').read_text())
    cfg=next(r['config'] for r in winners if r['config']['objective']=='risk' and r['config']['horizon']==0)
    with (parent/'cache.pkl').open('rb') as fh: base=pickle.load(fh)[('Mg.Sulfur',0)]
    original_features=engine.features
    q=pd.read_csv(ROOT/'data/242000_tags.csv',usecols=['date','Q21'],parse_dates=['date']).set_index('date').Q21.sort_index()
    qf=pd.DataFrame({'Q21_now':q})
    for h in [1,3,6,12,24,48]:
        roll=q.rolling(f'{h}h',min_periods=h*6)
        qf[f'Q21_mean_{h}h']=roll.mean();qf[f'Q21_std_{h}h']=roll.std()
        qf[f'Q21_change_{h}h']=q-q.shift(h*6)
    qf=qf.shift(36)
    delayed=qf.reindex(pd.DatetimeIndex(base.feature_time)).reset_index(drop=True)
    variants=['full','without_q21','q21_only','without_q21_without_lab','q21_delayed6h']
    engine.write_json(OUT/'manifest.json',{'parent_config':cfg,'years':[2024,2026],'seeds':[17,42,2026],
        'variants':variants,'note':'Same hyperparameters and split/early-stopping procedure. Aggregate zero/negative/unchanged counts removed in ALL variants to eliminate indirect Q21 leakage. Retrospective diagnostic, not new blind test.',
        'source_hashes':json.loads((parent/'manifest.json').read_text())['source_sha256']})
    rows=[];predictions=[]
    for variant in variants:
        d=base.copy()
        if variant=='q21_delayed6h':
            for c in delayed: d[c]=delayed[c]
        def feature_selector(frame,config):
            cols=[c for c in original_features(frame,config) if c not in ['zero_count','negative_count','unchanged_count']]
            if variant.startswith('without_q21'): cols=[c for c in cols if not c.startswith('Q21_')]
            if variant=='without_q21_without_lab':cols=[c for c in cols if not c.startswith(('lab_','labmedian_','labage_','labmissing_'))]
            if variant=='q21_only':cols=[c for c in cols if c.startswith('Q21_')]
            return cols
        engine.features=feature_selector
        for year in [2024,2026]:
            ms=engine.masks(d,year)
            for seed in [17,42,2026]:
                c=dict(cfg,seed=seed)
                model,predict,cols,med=engine.fit(d,c,ms)
                pc=predict(ms['calibration']);yc=d.value[ms['calibration']].to_numpy()>10
                pe=predict(ms['evaluation']);ye=d.value[ms['evaluation']].to_numpy()>10
                candidates=[]
                for threshold in np.linspace(0,1,201):
                    a=pc>=threshold;fpr=float(a[~yc].mean()); recall=float(a[yc].mean())
                    if fpr<=.1:candidates.append((recall,-fpr,threshold))
                threshold=max(candidates)[2] if candidates else 1.000001
                alarm=pe>=threshold
                row={'variant':variant,'year':year,'seed':seed,'n':len(ye),'features':len(cols),'trees':model.tree_count_,
                    'ap':average_precision_score(ye,pe),'prevalence':ye.mean(),'brier':brier_score_loss(ye,pe),
                    'threshold':threshold,'recall':alarm[ye].mean(),'fpr':alarm[~ye].mean(),
                    'tp':int((alarm&ye).sum()),'fp':int((alarm&~ye).sum()),'fn':int((~alarm&ye).sum())}
                rows.append(row)
                stem=f'{variant}_{year}_{seed}'
                model.save_model(str(OUT/f'{stem}.cbm'))
                engine.write_json(OUT/f'{stem}.json',{'config':c,'features':cols,'imputation':med.to_dict(),'metrics':row})
                predictions.append(pd.DataFrame({'timestamp':d.loc[ms['evaluation'],'timestamp'],'actual':d.loc[ms['evaluation'],'value'],
                    'probability':pe,'alarm':alarm,'variant':variant,'year':year,'seed':seed}))
                pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
                pd.concat(predictions).to_csv(OUT/'predictions.csv',index=False)
                print(variant,year,seed,'AP',round(row['ap'],4),'recall',round(row['recall'],3),flush=True)
    engine.write_json(OUT/'COMPLETE.json',{'models':len(rows),'status':'complete'})


if __name__=='__main__':main()
