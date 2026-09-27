import pandas as pd, numpy as np, json, hashlib, urllib.request
from collections import defaultdict, deque
from pathlib import Path
Y=range(2021,2026); R=Path('resilience_temporal_raw'); O=Path('alphaodds/winner_dna/outputs/resilience_temporal'); R.mkdir(exist_ok=True); O.mkdir(parents=True,exist_ok=True)
H={2021:'35f5d0b49905daa7d63ace9710346c48c7eb32ce0b8686629491954308013354',2022:'8aeb0e505d43950e09fec35a241a4e62720422454cdd3ac8f98c95650d54ab54',2023:'4aeca98ebe6357c5f1a13165533007964605d1f17bd54561937769b952c67613',2024:'6ae564c2c49378ec531303292966caee596982278b9fcdad9c9dd0a0dc16bfa7',2025:'8ce0001826f0f7b895b7a1068e4db7f43696c699db7064ccb1201855768fd06c'}
A={'LAR':'LA','STL':'LA','WSH':'WAS','OAK':'LV','SD':'LAC','JAC':'JAX'}
def ct(x):
 s=str(x).strip().upper(); return A.get(s,s)
def dl(u,p):
 req=urllib.request.Request(u,headers={'User-Agent':'AlphaNFL-Resilience/1.0'})
 with urllib.request.urlopen(req,timeout=300) as r,p.open('wb') as w:
  while 1:
   b=r.read(1<<20)
   if not b: break
   w.write(b)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def scores_at_end(d,q):
 z=d[d.qtr<=q]
 if z.empty:return (np.nan,np.nan)
 r=z.iloc[-1]; return (r.total_home_score,r.total_away_score)
def main():
 allg=[]; receipts=[]
 for y in Y:
  p=R/f'pbp{y}.csv'; u=f'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv'; dl(u,p); z=sha(p); assert z==H[y]
  hd=pd.read_csv(p,nrows=0).columns.tolist(); want=['game_id','qtr','posteam','home_team','away_team','total_home_score','total_away_score','fixed_drive','drive','posteam_score','posteam_score_post','epa','pass','rush','no_play','qb_kneel','qb_spike']
  use=[c for c in want if c in hd]; d=pd.read_csv(p,usecols=use,low_memory=False); d['posteam']=d.posteam.map(ct); d['home_team']=d.home_team.map(ct); d['away_team']=d.away_team.map(ct)
  for c in ['qtr','total_home_score','total_away_score','posteam_score','posteam_score_post','epa','pass','rush','no_play','qb_kneel','qb_spike']:
   if c in d: d[c]=pd.to_numeric(d[c],errors='coerce')
  if 'no_play' in d:d=d[d.no_play.fillna(0).eq(0)]
  receipts.append({'season':y,'sha256':z,'rows':len(d),'columns':use})
  dc='fixed_drive' if 'fixed_drive' in d else 'drive'
  for gid,g in d.groupby('game_id',sort=False):
   ht=g.home_team.dropna().iloc[0] if g.home_team.notna().any() else None; at=g.away_team.dropna().iloc[0] if g.away_team.notna().any() else None
   if not ht or not at: continue
   h2,a2=scores_at_end(g,2); h3,a3=scores_at_end(g,3); hf={ht:h2-a2 if pd.notna(h2) and pd.notna(a2) else np.nan,at:a2-h2 if pd.notna(h2) and pd.notna(a2) else np.nan}; q3={ht:h3-a3 if pd.notna(h3) and pd.notna(a3) else np.nan,at:a3-h3 if pd.notna(h3) and pd.notna(a3) else np.nan}
   last=g.iloc[-1]; hs,as_=last.total_home_score,last.total_away_score; winner=ht if hs>as_ else at if as_>hs else None
   q4=g[g.qtr.eq(4) & g.posteam.notna() & g.epa.notna()]
   q4epa=q4.groupby('posteam').epa.mean().to_dict()
   resp={ht:[0,0],at:[0,0]}
   if dc in g:
    drives=[]
    for dv,x in g[g[dc].notna()&g.posteam.notna()].groupby(dc,sort=False):
     team=x.posteam.iloc[0]; pts=0.0
     if 'posteam_score' in x and 'posteam_score_post' in x:
      pre=x.posteam_score.dropna(); post=x.posteam_score_post.dropna()
      if len(pre) and len(post): pts=max(0.0,float(post.max()-pre.iloc[0]))
     drives.append((dv,team,pts))
    drives=sorted(drives,key=lambda v:v[0])
    for i in range(1,len(drives)):
     if drives[i-1][1]!=drives[i][1] and drives[i-1][2]>0:
      team=drives[i][1]; resp.setdefault(team,[0,0]); resp[team][1]+=1; resp[team][0]+=int(drives[i][2]>0)
   for team,opp in [(ht,at),(at,ht)]:
    allg.append({'game_id':gid,'season':y,'team':team,'opp':opp,'win':1.0 if winner==team else 0.0,'halftime_deficit':pd.notna(hf[team]) and hf[team]<0,'close_q4':pd.notna(q3[team]) and abs(q3[team])<=8,'q4_epa':q4epa.get(team,np.nan),'response_success':resp.get(team,[0,0])[0],'response_opps':resp.get(team,[0,0])[1]})
  p.unlink(missing_ok=True)
 t=pd.DataFrame(allg).merge(pd.read_csv('alphaodds/winner_dna/outputs/root_cause_phase1/WINNER_DNA_OPPONENT_ADJUSTED_GAME_AUDIT.csv')[['game_id','gameday','week']].drop_duplicates(),on='game_id',how='left'); t.gameday=pd.to_datetime(t.gameday); t=t.sort_values(['team','season','gameday','game_id'])
 hist=defaultdict(lambda:deque(maxlen=8)); out=[]
 for r in t.itertuples(index=False):
  pr=list(hist[(r.team,r.season)]); z=r._asdict()
  for m,f in {'comeback_resilience':lambda x:x['halftime_deficit'],'close_q4_resilience':lambda x:x['close_q4']}.items():
   e=[x for x in pr if f(x)]; z[m]=np.mean([x['win'] for x in e]) if len(e)>=2 else np.nan
  e=[x for x in pr if x['close_q4'] and pd.notna(x['q4_epa'])]; z['close_q4_epa']=np.mean([x['q4_epa'] for x in e]) if len(e)>=2 else np.nan
  ro=sum(x['response_opps'] for x in pr); rs=sum(x['response_success'] for x in pr); z['scoring_response_rate']=rs/ro if ro>=3 else np.nan
  out.append(z); hist[(r.team,r.season)].append(r._asdict())
 p=pd.DataFrame(out); p.to_csv(O/'TEMPORAL_TEAM_PREGAME_RESILIENCE.csv',index=False); (O/'TEMPORAL_RECEIPTS.json').write_text(json.dumps(receipts,indent=2)); print(json.dumps({'receipts':receipts,'rows':len(p)},indent=2))
if __name__=='__main__':main()
