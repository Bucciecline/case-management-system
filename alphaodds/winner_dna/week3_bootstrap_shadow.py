#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, math, urllib.request
from collections import defaultdict, deque
from pathlib import Path
import numpy as np
import pandas as pd

FREEZE_LOCAL="2026-09-26T19:31:20-05:00"
YEARS=(2021,2022,2023,2024,2025)
DOMAINS=("elo","offense","defense","net","schedule_strength","prior_win_pct","prior_point_diff")
CORE=("elo","offense","defense","net")
MIN_PRIOR=2; ROLL=6; K=20.0; CARRY=.67
OUT=Path("alphaodds/winner_dna/outputs/week3_bootstrap_shadow")
OUT.mkdir(parents=True,exist_ok=True)

def loadmod():
    p=Path("alphaodds/winner_dna/qb_first_gate.py")
    s=importlib.util.spec_from_file_location("base",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def schedule(mod):
    p=Path("week3_bootstrap_games.csv")
    u="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    q=urllib.request.Request(u,headers={"User-Agent":"AlphaNFL-Week3Bootstrap/1.0"})
    with urllib.request.urlopen(q,timeout=240) as r,p.open("wb") as w:
        while True:
            b=r.read(1<<20)
            if not b: break
            w.write(b)
    d=pd.read_csv(p,low_memory=False)
    d=d[d.season.isin(range(2019,2027))].copy()
    d=d[d.game_type.astype(str).str.upper().eq("REG")].copy()
    d["gameday"]=pd.to_datetime(d.gameday,errors="coerce")
    d["home_team"]=d.home_team.map(mod.ct); d["away_team"]=d.away_team.map(mod.ct)
    for c in ["home_score","away_score","week"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    return d.sort_values(["gameday","game_id"],kind="mergesort").reset_index(drop=True),u

def prior_table(scored):
    out={}
    for season,df in scored.groupby("season"):
        a=defaultdict(lambda:{"gp":0,"w":0.,"pd":0.})
        for r in df.itertuples(index=False):
            for t,pf,pa in [(r.home_team,r.home_score,r.away_score),(r.away_team,r.away_score,r.home_score)]:
                x=a[t]; x["gp"]+=1; x["pd"]+=float(pf-pa); x["w"]+=1 if pf>pa else .5 if pf==pa else 0
        for t,x in a.items(): out[(int(season),t)]={"win_pct":x["w"]/x["gp"],"pd_per_game":x["pd"]/x["gp"]}
    return out

def compute(d):
    scored=d[d.home_score.notna()&d.away_score.notna()].copy()
    prior=prior_table(scored)
    elo=defaultdict(lambda:1500.); hist=defaultdict(lambda:deque(maxlen=ROLL)); cs=None; rows=[]
    for r in d.itertuples(index=False):
        y=int(r.season)
        if cs is None: cs=y
        if y!=cs:
            for t in list(elo): elo[t]=1500.+CARRY*(elo[t]-1500.)
            hist=defaultdict(lambda:deque(maxlen=ROLL)); cs=y
        h,a=r.home_team,r.away_team; he,ae=float(elo[h]),float(elo[a])
        v={"elo":h if he>ae else a if ae>he else None}
        def rv(t,k):
            z=list(hist[t])
            if len(z)<MIN_PRIOR:return np.nan
            if k=="offense":return float(np.mean([x["pf"] for x in z]))
            if k=="defense":return float(np.mean([x["pa"] for x in z]))
            if k=="net":return float(np.mean([x["pf"]-x["pa"] for x in z]))
            return float(np.mean([x["opp_elo"] for x in z]))
        for k in ["offense","defense","net","schedule_strength"]:
            hv,av=rv(h,k),rv(a,k)
            v[k]=None if not np.isfinite(hv) or not np.isfinite(av) or hv==av else (h if (hv<av if k=="defense" else hv>av) else a)
        hp,ap=prior.get((y-1,h)),prior.get((y-1,a))
        for k,key in [("prior_win_pct","win_pct"),("prior_point_diff","pd_per_game")]:
            hv=hp.get(key) if hp else np.nan; av=ap.get(key) if ap else np.nan
            v[k]=None if not np.isfinite(hv) or not np.isfinite(av) or hv==av else (h if hv>av else a)
        if int(r.week)==3 and y in (*YEARS,2026):
            def un(ds):
                z=[v[k] for k in ds]
                return z[0] if all(x is not None for x in z) and len(set(z))==1 else None
            winner=h if pd.notna(r.home_score) and pd.notna(r.away_score) and r.home_score>r.away_score else (a if pd.notna(r.home_score) and pd.notna(r.away_score) and r.away_score>r.home_score else None)
            rows.append({"game_id":r.game_id,"season":y,"week":3,"gameday":str(r.gameday.date()),"away_team":a,"home_team":h,"winner":winner,
                         **{f"vote_{k}":v[k] for k in DOMAINS},
                         "bootstrap_elite_pick":un(DOMAINS),"bootstrap_core_pick":un(CORE)})
        if pd.notna(r.home_score) and pd.notna(r.away_score):
            hist[h].append({"pf":float(r.home_score),"pa":float(r.away_score),"opp_elo":ae})
            hist[a].append({"pf":float(r.away_score),"pa":float(r.home_score),"opp_elo":he})
            res=1. if r.home_score>r.away_score else .5 if r.home_score==r.away_score else 0.; exp=1/(1+10**(-(he-ae)/400)); mult=1.
            if res!=.5:
                mov=abs(float(r.home_score-r.away_score)); adv=(he-ae)*(1 if res==1 else -1); mult=math.log(mov+1)*2.2/(adv*.001+2.2)
            de=K*mult*(res-exp); elo[h]+=de; elo[a]-=de
    return pd.DataFrame(rows)

def grade(h,col):
    x=h[h[col].notna()&h.winner.notna()].copy()
    by={}
    for y,z in x.groupby("season"): by[str(int(y))]={"n":int(len(z)),"wins":int((z[col]==z.winner).sum()),"accuracy":float((z[col]==z.winner).mean())}
    return {"n":int(len(x)),"wins":int((x[col]==x.winner).sum()),"accuracy":float((x[col]==x.winner).mean()) if len(x) else None,"by_season":by}

def main():
    mod=loadmod(); d,u=schedule(mod); rows=compute(d)
    hist=rows[rows.season.isin(YEARS)].copy(); cur=rows[(rows.season==2026)&rows.winner.isna()].copy()
    elite=grade(hist,"bootstrap_elite_pick"); core=grade(hist,"bootstrap_core_pick")
    # predeclared usability: at least 25 historical signals and >55% pooled accuracy, plus >50% in >=3 seasons with signals.
    def usable(g):
        yrs=[v for v in g["by_season"].values() if v["n"]>=3]
        return bool(g["n"]>=25 and g["accuracy"]>.55 and sum(v["accuracy"]>.5 for v in yrs)>=3)
    report={"gate":"ALPHANFL WEEK 3 TWO-GAME BOOTSTRAP SHADOW","freeze_local":FREEZE_LOCAL,
            "official_model_status":"UNCHANGED_MIN_PRIOR_3","shadow_min_prior":2,
            "historical_week3_2021_2025":{"elite":elite,"core":core},
            "usability":{"elite":usable(elite),"core":usable(core)},
            "rules":{"elite":"same seven domains, MIN_PRIOR=2, unanimity only","core":"Elo+Offense+Defense+NET, MIN_PRIOR=2, unanimity only",
                     "purpose":"Week 3 bridge only; never merged into official Winner DNA history or prospective Tier 1/Tier 2 grading"},
            "2026_unplayed_signals":{"games":int(len(cur)),"elite_signals":int(cur.bootstrap_elite_pick.notna().sum()),"core_signals":int(cur.bootstrap_core_pick.notna().sum())},
            "cca15":{"official_freeze_mutation":"NONE","backfill":"PROHIBITED","post_outcome_tuning":"NONE","wager_execution":"DISABLED"}}
    cur.to_csv(OUT/"WEEK3_2026_BOOTSTRAP_SHADOW_LEDGER.csv",index=False)
    hist.to_csv(OUT/"WEEK3_2021_2025_BOOTSTRAP_BACKTEST.csv",index=False)
    (OUT/"WEEK3_BOOTSTRAP_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("WEEK3_BOOTSTRAP_REPORT_BEGIN"); print(json.dumps(report,indent=2)); print("WEEK3_2026_SIGNALS_BEGIN")
    print(cur[["game_id","gameday","away_team","home_team","bootstrap_elite_pick","bootstrap_core_pick"]+[f"vote_{k}" for k in DOMAINS]].to_json(orient="records",indent=2))
    print("WEEK3_2026_SIGNALS_END")

if __name__=="__main__":
    main()
