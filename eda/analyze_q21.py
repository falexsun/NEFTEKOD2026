"""Q21 descriptive audit. Diagnostic filters are not operating limits."""
from pathlib import Path
import numpy as np
import pandas as pd
from forensics_utils import parse_lims,parse_pak

EDA=Path(__file__).resolve().parent
OUT=EDA/'artifacts/q21'
OUT.mkdir(parents=True,exist_ok=True)
t=pd.read_csv(EDA.parent/'data/242000_tags.csv',parse_dates=['date']).set_index('date').sort_index()
t=t.drop(columns=[c for c in t if c.startswith('Unnamed:')])
q=t.Q21
profile=q.describe(percentiles=[.01,.05,.25,.5,.75,.95,.99]).to_frame('value')
for name,val in {'negative':(q<0).sum(),'zero':(q==0).sum(),'above50':(q>50).sum(),'equal251':(q==251).sum(),'equal307':(q==307).sum()}.items():profile.loc[name]=val
profile.to_csv(OUT/'profile.csv')
group=q.ne(q.shift()).cumsum()
episodes=pd.DataFrame({'value':q,'group':group,'time':q.index}).groupby('group').agg(start=('time','min'),end=('time','max'),value=('value','first'),n=('value','size'))
episodes['hours']=episodes.n/6
episodes[episodes.n>=6].sort_values('hours',ascending=False).to_csv(OUT/'constant_episodes.csv',index=False)
monthly=q.resample('MS').agg(['median','min','max','count'])
monthly['fraction_above50']=(q>50).resample('MS').mean()
monthly['fraction_negative']=(q<0).resample('MS').mean()
monthly.to_csv(OUT/'monthly.csv')
corr=pd.DataFrame({'spearman_level':t.corrwith(q,method='spearman'),'pearson_change':t.diff().corrwith(q.diff())})
corr.sort_values('spearman_level',ascending=False).to_csv(OUT/'tag_associations.csv')
labs=parse_lims(next((EDA.parent/'docs').glob('ЛИМС*.xlsx')))
labs=labs[(labs.installation=='Гидроочистка')&(labs.sampling_point=='2')&(labs.quality_parameter=='Mg.Sulfur')]
lab=labs[['timestamp','value']].sort_values('timestamp')
matches=pd.merge_asof(lab,t[['Q21']].reset_index(),left_on='timestamp',right_on='date',direction='backward',tolerance=pd.Timedelta('10min')).dropna(subset=['Q21'])
matches['year']=matches.timestamp.dt.year
matches.to_csv(OUT/'lims_matches.csv',index=False)
rows=[]
for year,g in matches.groupby('year'):
    for mode,mask in [('all',pd.Series(True,index=g.index)),('diagnostic_Q21_0_50',g.Q21.between(0,50))]:
        a=g[mask]
        rows.append({'year':year,'mask':mode,'n':len(a),'spearman':a.value.corr(a.Q21,method='spearman'),
            'mae':(a.value-a.Q21).abs().mean(),'median_ae':(a.value-a.Q21).abs().median(),
            'bias_q21_minus_lab':(a.Q21-a.value).mean()})
pd.DataFrame(rows).to_csv(OUT/'yearly_lims_metrics.csv',index=False)
pak=parse_pak(next((EDA.parent/'docs').glob('Выгрузка ПАК*.xlsx')))
s=pak[pak.tag.str.contains('Sulfur')].sort_values('timestamp')
pm=pd.merge_asof(s,t[['Q21']].reset_index(),left_on='timestamp',right_on='date',direction='backward',tolerance=pd.Timedelta('10min')).dropna(subset=['Q21'])
valid=pm.Q21.between(0,50)
records=[]
for name,a in [('all',pm),('diagnostic_Q21_0_50',pm[valid])]:
    records.append({'mask':name,'n':len(a),'spearman':a.value.corr(a.Q21,method='spearman'),
        'mae':(a.value-a.Q21).abs().mean(),'median_ae':(a.value-a.Q21).abs().median(),'near_equal_fraction':((a.value-a.Q21).abs()<1e-5).mean()})
pd.DataFrame(records).to_csv(OUT/'pak_comparison.csv',index=False)
pm.set_index('timestamp')[['value','Q21']].resample('D').median().to_csv(OUT/'daily_pak_q21.csv')
print(profile.to_string());print(pd.DataFrame(rows).to_string(index=False));print(episodes.nlargest(8,'hours').to_string(index=False));print(pd.DataFrame(records).to_string(index=False))
