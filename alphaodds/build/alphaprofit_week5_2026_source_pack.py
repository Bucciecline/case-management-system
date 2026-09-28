#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, urllib.request
from collections import defaultdict
from pathlib import Path
import pandas as pd
import numpy as np

CANDIDATES = {
    "BAL_TEN_2026-10-04": {"favorite":"BAL","opponent":"TEN","spread_checkpoint":-10.5,"source":"Covers current NFL odds board","as_of":"2026-09-27"},
    "MIN_MIA_2026-10-04": {"favorite":"MIN","opponent":"MIA","spread_checkpoint":-10.5,"source":"Covers current NFL odds board","as_of":"2026-09-27"},
}
SEASONS=(2025,2026)
BASE="https://github.com/nflverse/nflverse-data/releases/download"
PBP_URL=BASE+"/pbp/play_by_play_{season}.csv"
ROSTER_URL=BASE+"/weekly_rosters/roster_weekly_{season}.csv"
SCHEDULE_URL="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
CUTOFF=pd.Timestamp("2026-10-04")

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def dl(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"AlphaProfit-Prospective-Matchup/1.0"})
    with urllib.request.urlopen(req,timeout=180) as r, open(path,"wb") as w:
        while True:
            b=r.read(1024*1024)
            if not b: break
            w.write(b)

def route(row,posmap):
    posteam=None if pd.isna(row.posteam) else str(row.posteam)
    tdteam=None if pd.isna(row.td_team) else str(row.td_team)
    if not posteam or tdteam!=posteam: return "OTHER"
    rid=getattr(row,"rusher_player_id",np.nan)
    if pd.notna(rid): return "GROUND"
    rec=getattr(row,"receiver_player_id",np.nan)
    if pd.notna(rec):
        p=posmap.get(str(rec))
        if p in {"WR","TE"}: return "WRTE_REC"
        if p=="RB": return "RB_REC"
    return "OTHER"

def smooth(c):
    keys=("GROUND","WRTE_REC","RB_REC")
    total=sum(c.get(k,0) for k in keys)
    return {k:(c.get(k,0)+1)/(total+3) for k in keys}

def main():
    root=Path(os.environ.get("ALPHAPROFIT_WEEK5_OUT","alphaprofit_week5_runtime"))
    raw,out=root/"raw",root/"out"; raw.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    receipts=[]
    for season in SEASONS:
        for fam,url,name in [
            ("pbp",PBP_URL.format(season=season),f"play_by_play_{season}.csv"),
            ("roster",ROSTER_URL.format(season=season),f"roster_weekly_{season}.csv")
        ]:
            p=raw/name; dl(url,p)
            receipts.append({"family":fam,"season":season,"url":url,"name":name,"size":p.stat().st_size,"sha256":sha256(p)})
    sp=raw/"games.csv"; dl(SCHEDULE_URL,sp)
    receipts.append({"family":"schedule","url":SCHEDULE_URL,"name":"games.csv","size":sp.stat().st_size,"sha256":sha256(sp)})

    rosters=[]
    for s in SEASONS:
        p=raw/f"roster_weekly_{s}.csv"
        head=pd.read_csv(p,nrows=0).columns
        cols=[c for c in ["season","week","team","gsis_id","position"] if c in head]
        d=pd.read_csv(p,usecols=cols,low_memory=False); rosters.append(d)
    rr=pd.concat(rosters,ignore_index=True)
    rr["season"]=pd.to_numeric(rr["season"],errors="coerce")
    rr["week"]=pd.to_numeric(rr["week"],errors="coerce")
    rr["position"]=rr["position"].astype(str).str.upper()
    posidx={}
    for (s,w,t),g in rr.groupby(["season","week","team"]):
        posidx[(int(s),int(w),str(t))]={str(x.gsis_id):str(x.position) for x in g[["gsis_id","position"]].dropna().drop_duplicates("gsis_id").itertuples(index=False)}

    pbps=[]
    need=["game_id","season","week","posteam","touchdown","td_team","rusher_player_id","receiver_player_id"]
    for s in SEASONS:
        p=raw/f"play_by_play_{s}.csv"; head=pd.read_csv(p,nrows=0).columns
        cols=[c for c in need if c in head]; d=pd.read_csv(p,usecols=cols,low_memory=False); pbps.append(d)
    pbp=pd.concat(pbps,ignore_index=True)
    pbp["touchdown"]=pd.to_numeric(pbp["touchdown"],errors="coerce").fillna(0)
    td=pbp[pbp["touchdown"].eq(1)].copy()

    sched=pd.read_csv(sp,low_memory=False)
    sched["gameday"]=pd.to_datetime(sched["gameday"],errors="coerce")
    sched=sched[(sched["season"].isin(SEASONS)) & (sched["game_type"].astype(str).eq("REG")) & (sched["gameday"]<CUTOFF)].copy()
    sched=sched.sort_values(["gameday","gametime","game_id"])

    game_routes=defaultdict(lambda:defaultdict(int))
    for row in td.itertuples(index=False):
        if int(row.season) not in SEASONS: continue
        team=None if pd.isna(row.posteam) else str(row.posteam)
        if not team: continue
        r=route(row,posidx.get((int(row.season),int(row.week),team),{}))
        if r!="OTHER": game_routes[(str(row.game_id),team)][r]+=1

    results={}
    for key,c in CANDIDATES.items():
        fav,opp=c["favorite"],c["opponent"]
        fav_games=[]; opp_games=[]
        for g in sched.itertuples(index=False):
            teams={str(g.home_team),str(g.away_team)}
            if fav in teams: fav_games.append(str(g.game_id))
            if opp in teams: opp_games.append(str(g.game_id))
        fav_games=fav_games[-8:]; opp_games=opp_games[-8:]

        offc=defaultdict(int)
        for gid in fav_games:
            for r,n in game_routes.get((gid,fav),{}).items(): offc[r]+=n

        allow=defaultdict(int)
        for gid in opp_games:
            sg=sched[sched["game_id"].astype(str).eq(gid)]
            if sg.empty: continue
            g=sg.iloc[0]; other=str(g["away_team"]) if str(g["home_team"])==opp else str(g["home_team"])
            for r,n in game_routes.get((gid,other),{}).items(): allow[r]+=n

        off=smooth(offc); deff=smooth(allow); comp={r:off[r]*deff[r] for r in off}
        offense_top=max(off,key=lambda r:(off[r],r)); defense_top=max(deff,key=lambda r:(deff[r],r)); route_top=max(comp,key=lambda r:(comp[r],r))
        results[key]={
            **c,
            "favorite_prior_games":fav_games,
            "opponent_prior_games":opp_games,
            "offense_route_counts":dict(offc),"opponent_allowed_route_counts":dict(allow),
            "offense_route_shares":off,"opponent_allowed_shares":deff,"compatibility":comp,
            "offense_top_route":offense_top,"defense_top_route":defense_top,
            "style_alignment":offense_top==defense_top,"matchup_route":route_top,
            "history_complete":len(fav_games)==8 and len(opp_games)==8
        }

    report={
      "gate":"ALPHAPROFIT 2026 WEEK-5 EARLY PROSPECTIVE QUALIFIER SOURCE PACK",
      "status":"EARLY_CHECKPOINT_LINES_NOT_FINAL",
      "candidates":results,
      "controls":{
        "cutoff":"all schedule/PBP rows strictly before 2026-10-04",
        "spreads":"Covers early board checkpoint; must be rechecked before final freeze",
        "source_receipts":"SHA-256 captured for 2025/2026 PBP, weekly rosters, schedule",
        "outcome_use":"none from target games",
        "wager_execution":"DISABLED"
      }
    }
    (out/"week5_candidate_source_pack.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")
    print("ALPHAPROFIT_WEEK5_SOURCE_PACK_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHAPROFIT_WEEK5_SOURCE_PACK_END")

if __name__=="__main__": main()
