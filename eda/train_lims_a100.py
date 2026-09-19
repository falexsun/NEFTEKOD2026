"""Reproducible LIMS experiments: python eda/train_lims_a100.py --root PATH."""
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error, median_absolute_error, mean_squared_error
from forensics_utils import parse_lims


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--run-id', default='lims_gpu_v1')
    args = ap.parse_args()
    root = args.root
    out = root / 'eda' / 'experiments' / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    sources = [root/'data/242000_tags.csv', next((root/'docs').glob('ЛИМС*.xlsx'))]
    manifest = {'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'python': platform.python_version(), 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'train': '<2025-01-01', 'validation': '2025-01-02..2025-12-31',
                'test': '>=2026-01-02', 'horizons_hours': [0, 6],
                'lab_availability_assumption_hours': 24, 'gpu': '0',
                'interpretation': 'Prediction of LIMS at recorded timestamp, NOT causal action effects; timestamp semantics unknown.'}
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    telemetry = pd.read_csv(sources[0], parse_dates=['date']).set_index('date').sort_index()
    telemetry = telemetry.drop(columns=[c for c in telemetry if c.startswith('Unnamed:')])
    assert telemetry.index.is_unique
    assert (telemetry.index.to_series().diff().dropna() == pd.Timedelta('10min')).all()
    telemetry = telemetry.apply(pd.to_numeric, errors='raise').replace([np.inf, -np.inf], np.nan)
    features = telemetry.add_suffix('_now')
    for hours in [1, 6, 24]:
        roll = telemetry.rolling(f'{hours}h', min_periods=hours*6)
        features = features.join(roll.mean().add_suffix(f'_mean_{hours}h'))
        features = features.join(roll.std().add_suffix(f'_std_{hours}h'))
    features.index.name = 'feature_time'
    labs = parse_lims(sources[1])
    labs = labs[(labs.installation == 'Гидроочистка') & (labs.sampling_point == '2')]
    results, predictions, inventory = [], [], []
    for target in ['Mg.Sulfur', 'D15', 'CetaneNumber', 'FlashPoint']:
        lab = labs[labs.quality_parameter == target][['timestamp','value']].sort_values('timestamp')
        lab = lab.groupby('timestamp', as_index=False).value.median()
        for horizon in [0, 6]:
            events = lab.assign(origin=lab.timestamp-pd.Timedelta(hours=horizon))
            df = pd.merge_asof(events, features.reset_index(), left_on='origin', right_on='feature_time',
                               direction='backward', tolerance=pd.Timedelta('10min'))
            history = lab.rename(columns={'timestamp':'lab_time', 'value':'last_lab'})
            history['available_time'] = history.lab_time + pd.Timedelta(hours=24)
            df = pd.merge_asof(df.sort_values('origin'), history.sort_values('available_time'),
                               left_on='origin', right_on='available_time', direction='backward')
            df = df[df.feature_time.notna()].reset_index(drop=True)
            assert (df.feature_time <= df.origin).all()
            assert (df.loc[df.available_time.notna(),'available_time'] <= df.loc[df.available_time.notna(),'origin']).all()
            masks = {'train': df.timestamp < '2025-01-01',
                     'validation': (df.timestamp >= '2025-01-02') & (df.timestamp < '2026-01-01'),
                     'test': df.timestamp >= '2026-01-02'}
            counts = {k:int(v.sum()) for k,v in masks.items()}
            inventory.append({'target':target, 'horizon':horizon, **counts})
            print(target, horizon, counts, flush=True)
            if min(counts.values()) < 20 or counts['train'] < 100:
                continue
            y = df.value
            cols = list(features.columns)
            X = df[cols]
            med = X.loc[masks['train']].median().fillna(0)
            X = X.fillna(med).astype('float32')
            stem = target.replace('.','_')+f'_h{horizon}'
            configs = [(depth, loss) for depth in [4, 6] for loss in ['RMSE', 'MAE']]
            candidates = []
            for depth, loss in configs:
                name = f'catboost_d{depth}_{loss}'
                model = CatBoostRegressor(iterations=600, depth=depth, loss_function=loss,
                    eval_metric='MAE', learning_rate=.04, l2_leaf_reg=10,
                    task_type='GPU', devices='0', random_seed=42, thread_count=4,
                    allow_writing_files=False, verbose=False)
                started = time.time()
                model.fit(X[masks['train']], y[masks['train']],
                          eval_set=(X[masks['validation']],y[masks['validation']]), early_stopping_rounds=60)
                score = mean_absolute_error(y[masks['validation']],model.predict(X[masks['validation']]))
                candidates.append((score,name,model))
                print(stem, name, 'validation MAE', round(score,4), 'seconds',round(time.time()-started,1),flush=True)
            winner = min(candidates,key=lambda x:x[0])[1]
            for score,name,model in candidates:
                if name == winner:
                    model.save_model(str(out/f'{stem}.cbm'))
                    (out/f'{stem}_features.json').write_text(json.dumps({'features':cols,'imputation':med.to_dict(),'selected':name}))
                    pd.DataFrame({'feature':cols,'importance':model.feature_importances_}).to_csv(out/f'{stem}_importance.csv',index=False)
                for split in ['validation','test']:
                    m = masks[split]
                    pred = model.predict(X[m])
                    results.append({'target':target,'horizon':horizon,'model':name,'split':split,'selected':name==winner,
                        'n':int(m.sum()), 'mae':mean_absolute_error(y[m],pred),'median_ae':median_absolute_error(y[m],pred),
                        'rmse':float(np.sqrt(mean_squared_error(y[m],pred)))})
                    if name == winner:
                        predictions.append(pd.DataFrame({'timestamp':df.loc[m,'timestamp'],'feature_time':df.loc[m,'feature_time'],
                            'target':target,'horizon':horizon,'split':split,'actual':y[m],'prediction':pred}))
            for name, pred in [('train_median',np.full(len(df),y[masks['train']].median())),
                               ('last_lab_delay24h',df.last_lab.fillna(y[masks['train']].median()).to_numpy())]:
                for split in ['validation','test']:
                    m=masks[split]
                    results.append({'target':target,'horizon':horizon,'model':name,'split':split,'selected':False,
                        'n':int(m.sum()),'mae':mean_absolute_error(y[m],pred[m]),'median_ae':median_absolute_error(y[m],pred[m]),
                        'rmse':float(np.sqrt(mean_squared_error(y[m],pred[m])))})
            pd.DataFrame(results).to_csv(out/'metrics.csv',index=False)
            pd.concat(predictions).to_csv(out/'predictions.csv',index=False)
    pd.DataFrame(inventory).to_csv(out/'target_inventory.csv',index=False)
    (out/'COMPLETE.json').write_text(json.dumps({'status':'complete','metric_rows':len(results)}))
    print('COMPLETE',out,flush=True)


if __name__ == '__main__':
    main()
