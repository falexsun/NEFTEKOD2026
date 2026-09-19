"""Wait for primary campaign, then repeat its frozen choices; no evaluation selection."""
import argparse
import hashlib
import json
import pickle
import shutil
import subprocess
import time
from pathlib import Path
import pandas as pd
from overnight_a100 import execute, utc, write_json


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--parent',default='overnight_20260915_13h')
    ap.add_argument('--run-id',default='overnight_20260915_stability')
    ap.add_argument('--hours',type=float,default=5)
    args=ap.parse_args()
    parent=args.root/'eda/experiments'/args.parent
    out=args.root/'eda/experiments'/args.run_id
    out.mkdir(parents=True,exist_ok=False)
    (out/'jobs').mkdir(); (out/'final').mkdir()
    write_json(out/'status.json',{'phase':'waiting_for_primary','parent':str(parent),'utc':utc()})
    wait_start=time.time()
    while not (parent/'COMPLETE.json').exists():
        if (parent/'FAILED.json').exists() or (out/'STOP').exists() or time.time()-wait_start>24*3600:
            write_json(out/'FAILED.json',{'reason':'parent_failed_stop_requested_or_wait_over_24h','utc':utc()})
            return
        time.sleep(30)
    primary=json.loads((parent/'COMPLETE.json').read_text())
    if primary['stop_reason'] not in ['time_budget','max_trials']:
        write_json(out/'FAILED.json',{'reason':'primary_did_not_finish_normally','primary':primary,'utc':utc()})
        return
    winners=json.loads((parent/'frozen_winners.json').read_text())
    winners.sort(key=lambda r:(r['config']['horizon'],r['config']['objective']))
    shutil.copyfile(parent/'cache.pkl',out/'cache.pkl')
    start=time.time(); deadline=start+args.hours*3600
    write_json(out/'manifest.json',{'started_utc':utc(),'hours':args.hours,'parent':args.parent,
        'parent_manifest':json.loads((parent/'manifest.json').read_text()),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'frozen_winners_sha256':hashlib.sha256((parent/'frozen_winners.json').read_bytes()).hexdigest(),
        'method':'Fixed winners, new seeds round robin. Do not select seed on evaluation. Report all results and dispersion.'})
    jobs=[]
    # Complete primary final evaluations omitted because of the time limit first.
    complete_ids={r['id'].removeprefix('final_') for r in json.loads((parent/'final_results.json').read_text()) if 'folds' in r} if (parent/'final_results.json').exists() else set()
    for w in winners:
        if w['id'] not in complete_ids:
            jobs.append(dict(w['config'],id='pending_'+w['id'],final=True,role='pending_primary'))
    for seed in [17,3407,101,42,2026]:
        for w in winners:
            if seed!=w['config']['seed']:
                jobs.append(dict(w['config'],id=f'stability_{w["id"]}_seed{seed}',seed=seed,final=True,role='stability'))
    write_json(out/'planned_jobs.json',jobs)
    rows=[]; successes=0; errors=[]; consecutive=0
    for cfg in jobs:
        if time.time()>=deadline-5 or (out/'STOP').exists():
            break
        write_json(out/'status.json',{'phase':'stability','job':cfg,'successes':successes,'errors':len(errors),
            'remaining_hours':(deadline-time.time())/3600,'utc':utc()})
        result,error=execute(out,cfg,min(900,deadline-time.time()))
        if result:
            successes+=1; consecutive=0
            with (out/'results.jsonl').open('a') as fh:
                fh.write(json.dumps(result)+'\n')
            for fold in result['folds']:
                rows.append(dict(objective=cfg['objective'],horizon=cfg['horizon'],seed=cfg['seed'],
                    role=cfg['role'],trial=cfg['id'],**fold))
            pd.DataFrame(rows).to_csv(out/'metrics.csv',index=False)
        else:
            consecutive+=1; errors.append({'config':cfg,'error':error})
            write_json(out/'errors.json',errors)
        print(utc(),cfg['id'],'ok' if result else 'error',flush=True)
        if consecutive>=8 or shutil.disk_usage(out).free<20*10**9:
            break
    if rows:
        frame=pd.DataFrame(rows)
        measures=[c for c in ['evaluation_mae','evaluation_ap','coverage90','brier','tp','fp','fn'] if c in frame]
        frame.groupby(['objective','horizon','year'])[measures].agg(['count','mean','std','min','max']).to_csv(out/'seed_dispersion.csv')
    status={'phase':'finished','successful_jobs':successes,'failed_jobs':len(errors),'planned_jobs':len(jobs),
        'unattempted_jobs':len(jobs)-successes-len(errors),'elapsed_hours':(time.time()-start)/3600,'utc':utc(),
        'stop_reason':'consecutive_failures' if consecutive>=8 else 'budget_stop_or_plan_complete'}
    write_json(out/'COMPLETE.json',status); write_json(out/'status.json',status)


if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        # The process log preserves a complete traceback even if startup failed.
        traceback.print_exc()
        raise
