"""Bounded unattended GPU campaign. All selection uses development folds only.

python eda/overnight_a100.py --root ROOT --run-id NAME --hours 13
Workers are isolated processes with timeouts. STOP file requests graceful completion.
"""
import argparse
import hashlib
import json
import os
import pickle
import platform
import signal
import subprocess
import sys
import time
import traceback
import threading
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    tmp.replace(path)


def prepare(root, out):
    from forensics_utils import parse_lims
    sources=[root/'data/242000_tags.csv', next((root/'docs').glob('ЛИМС*.xlsx'))]
    t=pd.read_csv(sources[0],parse_dates=['date']).set_index('date').sort_index()
    t=t.drop(columns=[c for c in t if c.startswith('Unnamed:')]).astype(float)
    assert t.index.is_unique and (t.index.to_series().diff().dropna()==pd.Timedelta('10min')).all()
    t=t.replace([np.inf,-np.inf],np.nan)
    f=t.add_suffix('_now')
    for h in [1,3,6,12,24,48]:
        roll=t.rolling(f'{h}h',min_periods=h*6)
        f=f.join(roll.mean().add_suffix(f'_mean_{h}h'))
        f=f.join(roll.std().add_suffix(f'_std_{h}h'))
        f=f.join((t-t.shift(h*6)).add_suffix(f'_change_{h}h'))
    # Trailing diagnostics are causal; no interpretation as operating limits.
    f['zero_count']=(t==0).sum(axis=1)
    f['negative_count']=(t<0).sum(axis=1)
    f['unchanged_count']=(t==t.shift(1)).sum(axis=1)
    f.index.name='feature_time'
    labs=parse_lims(sources[1])
    labs=labs[(labs.installation=='Гидроочистка')&(labs.sampling_point=='2')]
    cache={}
    counts=[]
    for target in ['Mg.Sulfur','D15','FlashPoint']:
        lab=labs[labs.quality_parameter==target][['timestamp','value']].groupby('timestamp',as_index=False).value.median().sort_values('timestamp')
        for horizon in [0,3,6,12]:
            d=lab.assign(origin=lab.timestamp-pd.Timedelta(hours=horizon))
            d=pd.merge_asof(d,f.reset_index(),left_on='origin',right_on='feature_time',direction='backward',tolerance=pd.Timedelta('10min'))
            d=d[d.feature_time.notna()].reset_index(drop=True)
            assert (d.feature_time<=d.origin).all()
            for delay in [6,24,48]:
                hist=lab.rename(columns={'timestamp':'lab_time','value':'last'})
                hist['recent_median']=hist['last'].rolling(3,min_periods=1).median()
                hist['available']=hist.lab_time+pd.Timedelta(hours=delay)
                m=pd.merge_asof(d[['origin']],hist,left_on='origin',right_on='available',direction='backward')
                assert (m.available.dropna()<=m.loc[m.available.notna(),'origin']).all()
                d[f'lab_{delay}']=m['last']
                d[f'labmedian_{delay}']=m.recent_median
                d[f'labage_{delay}']=(d.origin-m.lab_time).dt.total_seconds()/3600
                d[f'labmissing_{delay}']=m['last'].isna().astype(float)
            cache[(target,horizon)]=d
            counts.append({'target':target,'horizon':horizon,'n':len(d)})
    with (out/'cache.pkl').open('wb') as fh:
        pickle.dump(cache,fh)
    pd.DataFrame(counts).to_csv(out/'data_inventory.csv',index=False)
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}


def features(d, cfg):
    cols=[c for c in d if c.endswith('_now') or c in ['zero_count','negative_count','unchanged_count']]
    windows={'short':[1,3,6],'long':[6,12,24,48],'all':[1,3,6,12,24,48]}[cfg['windows']]
    cols += [c for c in d if any(c.endswith(f'_{h}h') for h in windows)]
    if cfg['history']:
        cols += [f'{prefix}_{cfg["history"]}' for prefix in ['lab','labmedian','labage','labmissing']]
    # F25 semantics suspect: explicit ablation, not a silent physical re-mapping.
    if cfg['exclude_f25']:
        cols=[c for c in cols if not c.startswith('F25_')]
    return cols


def masks(d, year, final=False):
    if year==2026:
        return {'train':d.timestamp<'2025-01-01',
                'validation':(d.timestamp>='2025-01-04')&(d.timestamp<'2025-07-01'),
                'calibration':(d.timestamp>='2025-07-04')&(d.timestamp<'2026-01-01'),
                'evaluation':d.timestamp>='2026-01-04'}
    return {'train':d.timestamp<pd.Timestamp(year,1,1),
            'validation':(d.timestamp>=pd.Timestamp(year,1,4))&(d.timestamp<pd.Timestamp(year,7,1)),
            'calibration':(d.timestamp>=pd.Timestamp(year,7,4))&(d.timestamp<pd.Timestamp(year,10,1)),
            'evaluation':(d.timestamp>=pd.Timestamp(year,10,4))&(d.timestamp<pd.Timestamp(year+1,1,1))}


def fit(d, cfg, ms):
    from catboost import CatBoostClassifier, CatBoostRegressor
    cols=features(d,cfg)
    med=d.loc[ms['train'],cols].median().fillna(0)
    x=d[cols].fillna(med).astype('float32')
    risk=cfg['objective']=='risk'
    y=(d.value>10).astype(int) if risk else d.value.copy()
    if cfg['objective']=='sulfur_log':
        y=np.log1p(y.clip(lower=0))
    params=dict(iterations=cfg['iterations'],depth=cfg['depth'],learning_rate=cfg['lr'],
        l2_leaf_reg=cfg['l2'],random_strength=cfg['random_strength'],border_count=cfg['borders'],
        task_type='GPU',devices='0',gpu_ram_part=.85,thread_count=8,random_seed=cfg['seed'],
        verbose=False,allow_writing_files=False)
    if risk:
        if y[ms['train']].nunique()<2 or y[ms['validation']].nunique()<2:
            raise ValueError('One class in development fold')
        model=CatBoostClassifier(**params,loss_function='Logloss',eval_metric='Logloss',
                                class_weights=[1,cfg['positive_weight']])
    else:
        model=CatBoostRegressor(**params,loss_function=cfg['loss'],eval_metric='MAE')
    model.fit(x[ms['train']],y[ms['train']],eval_set=(x[ms['validation']],y[ms['validation']]),early_stopping_rounds=120)
    def predict(mask):
        pred=model.predict_proba(x[mask])[:,1] if risk else model.predict(x[mask])
        return np.expm1(pred) if cfg['objective']=='sulfur_log' else pred
    return model,predict,cols,med


def worker(out, job_path):
    from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
    cfg=json.loads(job_path.read_text())
    with (out/'cache.pkl').open('rb') as fh:
        d=pickle.load(fh)[(cfg['target'],cfg['horizon'])]
    final=cfg.get('final',False)
    records=[]
    saved=[]
    for year in ([2024,2025,2026] if final else [2024,2025]):
        ms=masks(d,year)
        count={k:int(v.sum()) for k,v in ms.items()}
        if min(count['train'],count['validation'])<30:
            continue
        if final and min(count['calibration'],count['evaluation'])<15:
            records.append({'year':year,'skipped':True,'counts':count})
            continue
        model,predict,cols,med=fit(d,cfg,ms)
        pv=predict(ms['validation'])
        yv=d.value[ms['validation']].to_numpy()
        risk=cfg['objective']=='risk'
        baseline=float(np.mean(d.value[ms['train']]>10)) if risk else float(d.value[ms['train']].median())
        if risk:
            score=float(average_precision_score(yv>10,pv))
            rec={'year':year,'score':score,'validation_ap':score,'validation_prevalence':float(np.mean(yv>10)),
                 'validation_brier':float(brier_score_loss(yv>10,pv)),'counts':count}
        else:
            mae=float(np.mean(np.abs(yv-pv)))
            base_mae=float(np.mean(np.abs(yv-baseline)))
            rec={'year':year,'score':-mae/max(base_mae,1e-8),'validation_mae':mae,'baseline_mae':base_mae,'counts':count}
        rec['trees']=model.tree_count_
        if final:
            pc=predict(ms['calibration']); yc=d.value[ms['calibration']].to_numpy()
            pe=predict(ms['evaluation']); ye=d.value[ms['evaluation']].to_numpy()
            data={'timestamp':d.loc[ms['evaluation'],'timestamp'],'actual':ye,'prediction':pe}
            if risk:
                # Threshold chosen only on calibration, explicit false-alarm constraint.
                choices=[]
                for threshold in np.linspace(0,1,201):
                    alarm=pc>=threshold; a=yc>10
                    fpr=float(np.mean(alarm[~a])) if (~a).any() else 1.
                    recall=float(np.mean(alarm[a])) if a.any() else 0.
                    if fpr<=.10:
                        choices.append((recall,-fpr,threshold))
                threshold=max(choices)[2] if choices else 1.000001
                alarm=pe>=threshold; a=ye>10
                tp=int((alarm&a).sum()); fp=int((alarm&~a).sum()); fn=int((~alarm&a).sum())
                rec.update({'threshold':threshold,'tp':tp,'fp':fp,'fn':fn,'tn':int((~alarm&~a).sum()),
                    'evaluation_ap':float(average_precision_score(a,pe)) if a.any() else None,
                    'evaluation_prevalence':float(a.mean()),'brier':float(brier_score_loss(a,pe)),
                    'baseline_brier':float(brier_score_loss(a,np.full(len(a),baseline)))})
                data['alarm']=alarm
            else:
                residual=np.abs(yc-pc); rank=min(len(residual),int(np.ceil((len(residual)+1)*.9)))
                q=float(np.sort(residual)[rank-1])
                rec.update({'evaluation_mae':float(np.mean(np.abs(ye-pe))),
                    'evaluation_rmse':float(np.sqrt(np.mean((ye-pe)**2))),
                    'baseline_mae':float(np.mean(np.abs(ye-baseline))),
                    'halfwidth90':q,'coverage90':float(np.mean(np.abs(ye-pe)<=q))})
                data['lower90']=pe-q; data['upper90']=pe+q
            stem=out/'final'/f'{cfg["id"]}_{year}'
            pd.DataFrame(data).to_csv(stem.with_suffix('.csv'),index=False)
            model.save_model(str(stem.with_suffix('.cbm')))
            write_json(stem.with_suffix('.json'),{'config':cfg,'features':cols,'imputation':med.to_dict(),'metrics':rec})
            saved.append(str(stem))
        records.append(rec)
    scores=[r['score'] for r in records if 'score' in r and r['year'] in [2024,2025]]
    if not scores:
        raise RuntimeError('No usable development folds')
    write_json(job_path.with_suffix('.result.json'),{'id':cfg['id'],'config':cfg,'folds':records,
        'selection_score':float(np.mean(scores)-.2*np.std(scores)),'saved':saved,'finished_utc':utc()})


def execute(out, cfg, timeout):
    job=out/'jobs'/f'{cfg["id"]}.json'
    write_json(job,cfg)
    log=job.with_suffix('.log')
    with log.open('w') as stream:
        proc=subprocess.Popen([sys.executable,__file__,'--worker',str(job),'--out',str(out)],
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            code=proc.wait(timeout=max(1,timeout))
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL); proc.wait()
            return None,'timeout'
    result=job.with_suffix('.result.json')
    if code==0 and result.exists():
        return json.loads(result.read_text()),None
    return None,log.read_text()[-3000:]


def sample(rng, i):
    objective=['risk','sulfur','sulfur_log','density','flash'][i%5]
    target={'risk':'Mg.Sulfur','sulfur':'Mg.Sulfur','sulfur_log':'Mg.Sulfur','density':'D15','flash':'FlashPoint'}[objective]
    # Round robin guarantees early coverage across tasks and horizons.
    return {'id':f'trial_{i:06d}','objective':objective,'target':target,'horizon':[0,3,6,12][(i//5)%4],
        'history':int(rng.choice([0,6,24,48])),'windows':str(rng.choice(['short','long','all'])),
        'exclude_f25':bool(rng.integers(2)),'depth':int(rng.choice([4,5,6,7,8,9])),
        'iterations':int(rng.choice([1200,2000,3000])), 'lr':float(rng.choice([.015,.03,.05,.08])),
        'l2':float(rng.choice([3,10,30,100])), 'random_strength':float(rng.choice([.2,1,3])),
        'borders':int(rng.choice([64,128,254])), 'loss':str(rng.choice(['MAE','RMSE'])),
        'positive_weight':float(rng.choice([1,2,4,8])), 'seed':int(rng.choice([17,42,101,2026,3407]))}


def campaign(args):
    out=args.root/'eda/experiments'/args.run_id
    out.mkdir(parents=True,exist_ok=False)
    (out/'jobs').mkdir(); (out/'final').mkdir()
    start=time.time(); deadline=start+args.hours*3600
    reserve=min(5400,args.hours*3600*.2)
    manifest={'run_id':args.run_id,'started_utc':utc(),'deadline_utc':datetime.fromtimestamp(deadline,timezone.utc).isoformat(),
        'hours':args.hours,'search_reserve_seconds':reserve,'python':platform.python_version(),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'pid':os.getpid(),'selection':'mean development fold score minus 0.2 std; no evaluation selection',
        'limitations':'Retrospective explored periods. LIMS delays assumed. Models predict observations, not action effects. No production deployment.'}
    write_json(out/'manifest.json',manifest)
    (out/'environment.txt').write_text(subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True).stdout)
    health_stop=threading.Event()
    def health_monitor():
        while not health_stop.is_set():
            try:
                gpu=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw',
                                    '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10).stdout.strip()
                with (out/'health.jsonl').open('a') as fh:
                    fh.write(json.dumps({'utc':utc(),'gpu_util_mem_temp_power':gpu,'disk_free_gb':shutil.disk_usage(out).free/1e9})+'\n')
            except Exception as e:
                print('HEALTH_ERROR',str(e),flush=True)
            health_stop.wait(60)
    threading.Thread(target=health_monitor,daemon=True).start()
    write_json(out/'status.json',{'phase':'preparing','updated_utc':utc(),'pid':os.getpid()})
    manifest['source_sha256']=prepare(args.root,out); write_json(out/'manifest.json',manifest)
    rng=np.random.default_rng(20260915)
    records=[]; failures=[]; consecutive=0; seen=set(); i=0
    stop_reason='time_budget'
    while time.time()<deadline-reserve:
        if shutil.disk_usage(out).free<20*10**9:
            stop_reason='disk_free_below_20GB'; break
        if (out/'STOP').exists():
            stop_reason='STOP_requested'; break
        if args.max_trials and i>=args.max_trials:
            stop_reason='max_trials'; break
        cfg=sample(rng,i); i+=1
        fingerprint=json.dumps({k:v for k,v in cfg.items() if k!='id'},sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        write_json(out/'status.json',{'phase':'search','trial':cfg,'successes':len(records),'failures':len(failures),
            'remaining_hours':max(0,(deadline-time.time())/3600),'updated_utc':utc(),'pid':os.getpid()})
        result,error=execute(out,cfg,min(900,deadline-reserve-time.time()))
        if result:
            records.append(result); consecutive=0
            print(utc(),cfg['id'],cfg['objective'],cfg['horizon'],round(result['selection_score'],5),flush=True)
            with (out/'results.jsonl').open('a') as fh:
                fh.write(json.dumps(result)+'\n')
        else:
            consecutive+=1; failures.append({'id':cfg['id'],'error':error,'time':utc()})
            write_json(out/'failures.json',failures)
            print('FAILED',cfg['id'],error,flush=True)
        if consecutive>=8:
            stop_reason='eight_consecutive_failures'; break
    write_json(out/'status.json',{'phase':'final_evaluation','successes':len(records),'updated_utc':utc(),'pid':os.getpid()})
    # Freeze one development winner per objective/horizon BEFORE examining evaluation.
    groups={}
    for r in records:
        key=(r['config']['objective'],r['config']['horizon'])
        if key not in groups or r['selection_score']>groups[key]['selection_score']:
            groups[key]=r
    write_json(out/'frozen_winners.json',list(groups.values()))
    final=[]
    for r in groups.values():
        if time.time()>deadline-5:
            break
        cfg=dict(r['config'],id='final_'+r['id'],final=True)
        result,error=execute(out,cfg,min(900,deadline-time.time()))
        final.append(result if result else {'id':cfg['id'],'error':error})
        write_json(out/'final_results.json',final)
    pd.DataFrame([dict(r['config'],selection_score=r['selection_score']) for r in records]).to_csv(out/'leaderboard.csv',index=False)
    rows=[]
    for result in final:
        for fold in result.get('folds',[]):
            rows.append(dict(objective=result['config']['objective'],horizon=result['config']['horizon'],
                             trial=result['id'],**fold))
    pd.DataFrame(rows).to_csv(out/'final_metrics.csv',index=False)
    status={'phase':'finished','stop_reason':stop_reason,'trials_successful':len(records),'trials_failed':len(failures),
        'frozen_winners':len(groups),'final_evaluations':sum('folds' in r for r in final),
        'final_evaluations_pending':len(groups)-sum('folds' in r for r in final),
        'elapsed_hours':(time.time()-start)/3600,'finished_utc':utc()}
    write_json(out/'status.json',status); write_json(out/'COMPLETE.json',status)
    report=['# A100 campaign report',json.dumps(status,ensure_ascii=False,indent=2),
        'Selection used development folds only. Inspect calibration/evaluation in final_results.json.',
        'Do not rank by evaluation or claim causal/production validity. Pending final evaluations must be completed before review.']
    (out/'REPORT.md').write_text('\n\n'.join(report))
    health_stop.set()
    print('FINISHED',json.dumps(status),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--run-id',default='overnight_20260915')
    ap.add_argument('--hours',type=float,default=13)
    ap.add_argument('--max-trials',type=int,default=0)
    ap.add_argument('--worker',type=Path)
    ap.add_argument('--out',type=Path)
    args=ap.parse_args()
    if args.worker:
        worker(args.out,args.worker)
    else:
        try:
            campaign(args)
        except Exception:
            path=args.root/'eda/experiments'/args.run_id
            if path.exists():
                write_json(path/'FAILED.json',{'time':utc(),'traceback':traceback.format_exc()})
            raise
