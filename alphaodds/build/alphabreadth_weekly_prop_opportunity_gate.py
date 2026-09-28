#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

DEV_SEASONS=(2021,2022,2023)
CONTEXT_SEASONS=(2021,2022,2023,2024,2025,2026)
TARGET_SEASON=2026
TARGET_DATE_FROM=pd.Timestamp("2026-10-01")
TARGET_DATE_TO=pd.Timestamp("2026-10-05")
POSITIONS=("QB","RB","WR","TE")
ROLL_WINDOWS=(3,5,8)
TARGETS={
    "QB":["passing_yards"],
    "RB":["rushing_yards"],
    "WR":["receiving_yards","receptions"],
    "TE":["receiving_yards","receptions"],
}
BASE="https://github.com/nflverse/nflverse-data/releases/download"
STATS_URL=BASE+"/stats_player/stats_player_week_{season}.csv"
SNAP_URL=BASE+"/snap_counts/snap_counts_{season}.csv"
ROSTER_URL=BASE+"/weekly_rosters/roster_weekly_{season}.csv"
SCHEDULE_URL="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

MODEL_SPEC=dict(
    learning_rate=0.05,max_iter=250,max_leaf_nodes=15,min_samples_leaf=20,
    l2_regularization=1.0,random_state=190022,
)
STATE_VARS=[
    "attempts","completions","passing_yards","carries","rushing_yards",
    "targets","receptions","receiving_yards","target_share","air_yards_share","wopr",
]

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def dl(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"AlphaBreadth-Weekly-Prop/1.0"})
    with urllib.request.urlopen(req,timeout=180) as r, open(path,"wb") as w:
        while True:
            b=r.read(1024*1024)
            if not b: break
            w.write(b)

def add_team_shares(df):
    out=df.copy()
    team_col="recent_team" if "recent_team" in out.columns else ("team" if "team" in out.columns else None)
    if not team_col: return out
    keys=["season","week",team_col]
    for raw,name in [("attempts","pass_attempt_share"),("carries","carry_share"),("targets","target_share_rebuilt")]:
        if raw in out.columns:
            v=pd.to_numeric(out[raw],errors="coerce"); out[raw]=v
            tot=out.groupby(keys,dropna=False)[raw].transform("sum")
            out[name]=np.where(tot>0,v/tot,np.nan)
    return out

def add_eff(df):
    out=df.copy()
    def ratio(n,d,dest):
        if n in out.columns and d in out.columns:
            nn=pd.to_numeric(out[n],errors="coerce"); dd=pd.to_numeric(out[d],errors="coerce")
            out[dest]=np.where(dd>0,nn/dd,np.nan)
    ratio("passing_yards","attempts","pass_yards_per_attempt")
    ratio("completions","attempts","completion_rate")
    ratio("rushing_yards","carries","rush_yards_per_carry")
    ratio("receptions","targets","catch_rate")
    ratio("receiving_yards","targets","receiving_yards_per_target")
    ratio("receiving_yards","receptions","receiving_yards_per_reception")
    return out

def attach_snaps(base, snaps, rosters):
    s=snaps.rename(columns={"pfr_player_id":"pfr_id"}).copy()
    r=rosters.copy()
    for x in (s,r):
        for col in ["season","week"]:
            x[col]=pd.to_numeric(x[col],errors="coerce")
    join=["season","week","pfr_id"]
    if "team" in s.columns and "team" in r.columns: join.append("team")
    cross=r.dropna(subset=["pfr_id","gsis_id"]).drop_duplicates(join,keep="last")
    m=s.merge(cross[join+["gsis_id"]],on=join,how="left")
    m=m.rename(columns={"gsis_id":"player_id"})
    keep=[c for c in ["season","week","player_id","offense_snaps","offense_pct"] if c in m.columns]
    m=m[keep].dropna(subset=["player_id"]).drop_duplicates(["season","week","player_id"],keep="last")
    b=base.copy(); b["player_id"]=b["player_id"].astype(str); m["player_id"]=m["player_id"].astype(str)
    return b.merge(m,on=["season","week","player_id"],how="left")

def build_features(df):
    out=df.copy().sort_values(["player_id","season","week","is_target_row"],kind="mergesort").reset_index(drop=True)
    state=[c for c in STATE_VARS+[
        "pass_attempt_share","carry_share","target_share_rebuilt","pass_yards_per_attempt",
        "completion_rate","rush_yards_per_carry","catch_rate","receiving_yards_per_target",
        "receiving_yards_per_reception","offense_snaps","offense_pct"
    ] if c in out.columns]
    g=out.groupby("player_id",sort=False,group_keys=False)
    out["prior_games"]=g.cumcount()
    feats=["prior_games"]
    for col in state:
        s=pd.to_numeric(out[col],errors="coerce")
        lag=s.groupby(out["player_id"],sort=False).shift(1)
        ln=f"lag1__{col}"; out[ln]=lag; feats.append(ln)
        for w in ROLL_WINDOWS:
            mn=f"roll{w}_mean__{col}"; sd=f"roll{w}_std__{col}"
            out[mn]=lag.groupby(out["player_id"],sort=False).transform(lambda x:x.rolling(w,min_periods=1).mean())
            out[sd]=lag.groupby(out["player_id"],sort=False).transform(lambda x:x.rolling(w,min_periods=2).std())
            feats += [mn,sd]
    return out,feats

def features_for(pos,all_features):
    toks={
        "QB":("attempt","completion","passing","pass_","offense_snap","offense_pct"),
        "RB":("carry","rushing","rush_","target","reception","receiving","catch","offense_snap","offense_pct"),
        "WR":("target","reception","receiving","catch","offense_snap","offense_pct"),
        "TE":("target","reception","receiving","catch","offense_snap","offense_pct"),
    }[pos]
    return [c for c in all_features if c=="prior_games" or any(t in c for t in toks)]

def model_for(target):
    kw=dict(MODEL_SPEC)
    kw["loss"]="poisson" if target=="receptions" else "squared_error"
    return HistGradientBoostingRegressor(**kw)

def main():
    root=Path(os.environ.get("ALPHABREADTH_PROP_OUT","alphabreadth_prop_runtime"))
    raw,out=root/"raw",root/"out"; raw.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    receipts=[]
    stats=[]; snaps=[]; rosters=[]
    for s in CONTEXT_SEASONS:
        for fam,urlpat,prefix,bucket in [
            ("stats",STATS_URL,"stats_player_week",stats),
            ("snaps",SNAP_URL,"snap_counts",snaps),
            ("roster",ROSTER_URL,"roster_weekly",rosters)
        ]:
            url=urlpat.format(season=s); p=raw/f"{prefix}_{s}.csv"; dl(url,p)
            receipts.append({"family":fam,"season":s,"url":url,"size":p.stat().st_size,"sha256":sha256(p)})
            d=pd.read_csv(p,low_memory=False); 
            if "season" not in d.columns: d["season"]=s
            bucket.append(d)
    sp=raw/"games.csv"; dl(SCHEDULE_URL,sp)
    receipts.append({"family":"schedule","url":SCHEDULE_URL,"size":sp.stat().st_size,"sha256":sha256(sp)})

    st=pd.concat(stats,ignore_index=True,sort=False)
    if "season_type" in st.columns: st=st[st["season_type"].astype(str).eq("REG")].copy()
    for c in ["season","week"]: st[c]=pd.to_numeric(st[c],errors="coerce")
    if "player_id" not in st.columns and "player_id" not in st:
        raise RuntimeError("player_id missing")
    st["player_id"]=st["player_id"].astype(str)
    st["position"]=st["position"].astype(str).str.upper()
    st["is_target_row"]=False

    rr=pd.concat(rosters,ignore_index=True,sort=False)
    ss=pd.concat(snaps,ignore_index=True,sort=False)
    for c in ["season","week"]:
        if c in rr: rr[c]=pd.to_numeric(rr[c],errors="coerce")
        if c in ss: ss[c]=pd.to_numeric(ss[c],errors="coerce")

    sched=pd.read_csv(sp,low_memory=False)
    sched["gameday"]=pd.to_datetime(sched["gameday"],errors="coerce")
    target_games=sched[
        sched["season"].eq(TARGET_SEASON)
        & sched["game_type"].astype(str).eq("REG")
        & sched["gameday"].between(TARGET_DATE_FROM,TARGET_DATE_TO)
    ].copy()
    if target_games.empty: raise RuntimeError("No target games found")
    target_week=int(target_games["week"].mode().iloc[0])
    teams=set(target_games["home_team"].astype(str))|set(target_games["away_team"].astype(str))

    # Target-week roster only when available. If the feed has not yet published
    # target week, fall back to the latest week before it and disclose that fact.
    r26_all=rr[rr["season"].eq(TARGET_SEASON) & rr["team"].astype(str).isin(teams)].copy()
    r26_all=r26_all[r26_all["position"].astype(str).str.upper().isin(POSITIONS)]
    weeks=sorted(int(x) for x in pd.to_numeric(r26_all["week"],errors="coerce").dropna().unique() if int(x) <= target_week)
    roster_week=max(weeks) if weeks else None
    if roster_week is None:
        raise RuntimeError("No usable 2026 weekly roster week")
    r26=r26_all[pd.to_numeric(r26_all["week"],errors="coerce").eq(roster_week)].copy()
    if "status" in r26.columns:
        # nflverse status naming can vary; keep recognized active-like values,
        # otherwise rely on the recent-usage gate below.
        status_norm=r26["status"].astype(str).str.upper()
        active_mask=status_norm.isin(["ACT","ACTIVE","A","NORMAL"]) | status_norm.str.contains("ACTIVE",na=False)
        if active_mask.any():
            r26=r26[active_mask].copy()
    r26=r26.drop_duplicates(["team","gsis_id"],keep="last")
    name_col="full_name" if "full_name" in r26.columns else ("player_name" if "player_name" in r26.columns else None)

    # Recent participation gate from 2026 regular-season stats before target week.
    recent26=st[
        st["season"].eq(TARGET_SEASON)
        & st["week"].lt(target_week)
        & st["recent_team"].astype(str).isin(teams)
    ].copy()
    recent26=recent26.sort_values(["player_id","week"])
    recent_usage={}
    for pid,gp in recent26.groupby("player_id"):
        tail=gp.tail(3)
        def sm(col):
            return float(pd.to_numeric(tail[col],errors="coerce").fillna(0).sum()) if col in tail.columns else 0.0
        recent_usage[str(pid)]={
            "attempts":sm("attempts"),"carries":sm("carries"),"targets":sm("targets"),
            "receptions":sm("receptions"),"offense_games":int(len(tail))
        }

    target_rows=[]
    existing_cols=set(st.columns)
    participation_excluded=0
    for x in r26.itertuples(index=False):
        pid=str(getattr(x,"gsis_id")); pos=str(getattr(x,"position")).upper()
        u=recent_usage.get(pid,{"attempts":0.0,"carries":0.0,"targets":0.0,"receptions":0.0,"offense_games":0})
        if pos=="QB":
            qualifies=u["attempts"] >= 5
        elif pos=="RB":
            qualifies=(u["carries"] + u["targets"]) >= 3
        else:
            qualifies=u["targets"] >= 3
        if not qualifies:
            participation_excluded += 1
            continue
        row={c:np.nan for c in existing_cols}
        row["season"]=TARGET_SEASON; row["week"]=target_week
        row["player_id"]=pid; row["position"]=pos
        row["recent_team"]=str(getattr(x,"team")); row["team"]=str(getattr(x,"team"))
        if "player_display_name" in row: row["player_display_name"]=str(getattr(x,name_col)) if name_col else row["player_id"]
        if "player_name" in row: row["player_name"]=str(getattr(x,name_col)) if name_col else row["player_id"]
        row["is_target_row"]=True
        target_rows.append(row)
    targ=pd.DataFrame(target_rows)
    combined=pd.concat([st,targ],ignore_index=True,sort=False)
    combined=add_team_shares(combined); combined=add_eff(combined)
    combined=attach_snaps(combined,ss,rr)
    feat,all_features=build_features(combined)

    # development model remains 2021-2023 only; 2024/2025/2026 are feature context only.
    outputs=[]
    for pos in POSITIONS:
        fcols=features_for(pos,all_features)
        for target in TARGETS[pos]:
            d=feat[
                feat["season"].isin(DEV_SEASONS)
                & feat["position"].eq(pos)
                & pd.to_numeric(feat[target],errors="coerce").notna()
                & feat["prior_games"].ge(3)
                & ~feat["is_target_row"].fillna(False)
            ].copy()
            med=d[fcols].apply(pd.to_numeric,errors="coerce").median()
            Xd=d[fcols].apply(pd.to_numeric,errors="coerce").fillna(med).fillna(0)
            m=model_for(target); m.fit(Xd,pd.to_numeric(d[target],errors="coerce").to_numpy(float))

            q=feat[
                feat["is_target_row"].fillna(False)
                & feat["position"].eq(pos)
                & feat["prior_games"].ge(3)
            ].copy()
            if q.empty: continue
            Xq=q[fcols].apply(pd.to_numeric,errors="coerce").fillna(med).fillna(0)
            pred=m.predict(Xq)
            if target=="receptions": pred=np.clip(pred,0,None)
            for (_,r),pval in zip(q.iterrows(),pred):
                team=str(r["recent_team"]) if pd.notna(r.get("recent_team")) else str(r.get("team"))
                game=target_games[(target_games["home_team"].astype(str).eq(team))|(target_games["away_team"].astype(str).eq(team))]
                if game.empty: continue
                g=game.iloc[0]
                name=r.get("player_display_name")
                if pd.isna(name): name=r.get("player_name")
                if pd.isna(name): name=r["player_id"]
                outputs.append({
                    "game_id":str(g["game_id"]),"gameday":str(g["gameday"].date()),"week":int(g["week"]),
                    "team":team,"opponent":str(g["away_team"] if str(g["home_team"])==team else g["home_team"]),
                    "player_id":str(r["player_id"]),"player_name":str(name),"position":pos,"market":target,
                    "projection":float(pval),"prior_games":int(r["prior_games"]),
                    "market_line":None,"market_price":None,"price_status":"PRICE_HOLD_NOT_POSTED",
                    "model_training":"FROZEN_SPEC_FIT_2021_2023","context_history":"2021_2026_PAST_ROWS_ONLY",
                })

    board=pd.DataFrame(outputs)
    # opportunity volume if lines existed: all projections are candidates until market comparison.
    by_market=board.groupby(["position","market"]).size().reset_index(name="projection_count")
    report={
        "gate":"ALPHABREADTH PLAYER-PROP WEEKLY OPPORTUNITY GATE",
        "status":"ACTIVE_MARKET_PARTICIPANT_PROJECTIONS_FROZEN_PRICE_HOLD",
        "target_window":["2026-10-01","2026-10-05"],
        "target_week":target_week,
        "games":int(target_games["game_id"].nunique()),
        "projection_rows":int(len(board)),
        "roster_week_used":int(roster_week),
        "target_week_roster_players_before_recent_usage_gate":int(len(r26)),
        "players_excluded_for_insufficient_recent_usage":int(participation_excluded),
        "markets":by_market.to_dict(orient="records"),
        "controls":{
            "model_spec":"AP-RB1 unchanged",
            "model_fit_seasons":[2021,2022,2023],
            "2024_2025_2026_model_training":"NO",
            "2024_2025_2026_usage":"past-game feature context only",
            "minimum_prior_games":3,
            "target_week_roster_presence":"required using latest published roster week <= target week",
            "recent_participation_gate":"QB >=5 pass attempts; RB >=3 carries+targets; WR/TE >=3 targets over most recent 3 2026 games",
            "sportsbook_lines":"not imputed; PRICE_HOLD until authenticated",
            "same_game_target_stats":"not available to synthetic target row",
            "wager_execution":"DISABLED"
        },
        "alphacreative":{
            "mission":"freeze projections before sportsbook lines appear",
            "next_test":"when lines appear, compute projection-minus-line gap, line/price source timestamp, matchup/injury overlay, and correlation clusters",
            "promotion":"none; projections are research candidates only"
        }
    }
    board.to_csv(out/"week5_2026_prop_projection_board.csv",index=False)
    (out/"WEEK5_PROP_GATE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")
    print("ALPHABREADTH_PROP_GATE_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHABREADTH_PROP_GATE_END")
if __name__=="__main__":main()
