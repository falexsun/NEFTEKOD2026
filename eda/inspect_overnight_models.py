"""Read-only inference audit of persisted primary models; no fitting."""
from pathlib import Path
import json
import pickle
import pandas as pd
from catboost import CatBoostRegressor, CatBoostClassifier
from overnight_a100 import masks

eda=Path(__file__).resolve().parent
run=eda/'experiments/overnight_20260915_13h'
out=eda/'artifacts/overnight_review'
out.mkdir(parents=True,exist_ok=True)
with (run/'cache.pkl').open('rb') as fh: cache=pickle.load(fh)
importance=[]; calibration=[]
for path in (run/'final').glob('*_2026.json'):
    meta=json.loads(path.read_text());cfg=meta['config'];risk=cfg['objective']=='risk'
    model=CatBoostClassifier() if risk else CatBoostRegressor()
    model.load_model(str(path.with_suffix('.cbm')))
    imp=model.get_feature_importance()
    for col,value in zip(meta['features'],imp):
        importance.append({'objective':cfg['objective'],'horizon':cfg['horizon'],'feature':col,'importance':value})
    if risk:
        d=cache[(cfg['target'],cfg['horizon'])];m=masks(d,2026)['calibration']
        X=d.loc[m,meta['features']].fillna(pd.Series(meta['imputation'])).astype('float32')
        prob=model.predict_proba(X)[:,1];a=d.loc[m,'value'].to_numpy()>10
        alarm=prob>=meta['metrics']['threshold']
        calibration.append({'horizon':cfg['horizon'],'n':len(a),'positive':int(a.sum()),
            'threshold':meta['metrics']['threshold'],'recall':float(alarm[a].mean()),
            'fpr':float(alarm[~a].mean()),'alert_rate':float(alarm.mean())})
pd.DataFrame(importance).to_csv(out/'feature_importance.csv',index=False)
pd.DataFrame(calibration).to_csv(out/'risk_calibration.csv',index=False)
print(pd.DataFrame(calibration).to_string(index=False))
for objective,horizon in [('risk',0),('risk',6),('density',0),('flash',0)]:
    f=pd.DataFrame(importance)
    print(objective,horizon,f[(f.objective==objective)&(f.horizon==horizon)].nlargest(8,'importance')[['feature','importance']].to_string(index=False))
