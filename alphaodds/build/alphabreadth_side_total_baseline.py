#!/usr/bin/env python3
from __future__ import annotations
import json, math, os, urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

SCHEDULE_URL="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
DEV=(2021,2022,2023)
VAL=2024
WINDOWS=(3,5,8)
EDGE_THRESHOLDS=(2.0,3.0,4.0,5.0)

def dl(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"AlphaBreadth-SideTotal/1.0"})
    with urllib.request.urlopen(req,timeout=120) as r, open(path,"wb") as w:
        w.write(r.read())

def rolling_team_features(games):
    hist=defaultdict(list)
    rows=[]
    games=games.sort_values(["gameday","gametime","game_id"]).reset_index(drop=True)
    for g in games.itertuples(index=False):
        home,away=str(g.home_team),str(g.away_team)
        row={
            "game_id":str(g.game_id),"season":int(g.season),"week":int(g.week),
            "home_team":home,"away_team":away,
            "spread_line":float(g.spread_line) if pd.notna(g.spread_line) else np.nan,
            "total_line":float(g.total_line) if pd.notna(g.total_line) else np.nan,
            "home_score":float(g.home_score) if pd.notna(g.home_score) else np.nan,
            "away_score":float(g.away_score) if pd.notna(g.away_score) else np.nan,
        }
        for team,label in [(home,"home"),(away,"away")]:
            h=hist[team]
            row[f"{label}_prior_games"]=len(h)
            for w in WINDOWS:
                x=h[-w:]
                if x:
                    row[f"{label}_w{w}_pf"]=float(np.mean([z["pf"] for z in x]))
                    row[f"{label}_w{w}_pa"]=float(np.mean([z["pa"] for z in x]))
                    row[f"{label}_w{w}_margin"]=float(np.mean([z["margin"] for z in x]))
                    row[f"{label}_w{w}_total"]=float(np.mean([z["total"] for z in x]))
                    row[f"{label}_w{w}_winrate"]=float(np.mean([z["win"] for z in x]))
                else:
                    for m in ["pf","pa","margin","total","winrate"]:
                        row[f"{label}_w{w}_{m}"]=np.nan
        rows.append(row)
        if pd.notna(g.home_score) and pd.notna(g.away_score):
            hs,as_=float(g.home_score),float(g.away_score)
            hist[home].append({"pf":hs,"pa":as_,"margin":hs-as_,"total":hs+as_,"win":1.0 if hs>as_ else 0.0})
            hist[away].append({"pf":as_,"pa":hs,"margin":as_-hs,"total":hs+as_,"win":1.0 if as_>hs else 0.0})
    return pd.DataFrame(rows)

def model():
    return HistGradientBoostingRegressor(
        learning_rate=0.05,max_iter=250,max_leaf_nodes=15,min_samples_leaf=20,
        l2_regularization=1.0,random_state=250025
    )

def cover_side(actual_margin, spread_line, direction):
    # nflverse spread_line: positive means home favorite, negative away favorite.
    if direction=="HOME":
        return actual_margin > spread_line
    return actual_margin < spread_line

def cover_total(actual_total,total_line,direction):
    if direction=="OVER": return actual_total > total_line
    return actual_total < total_line

def wilson_lower(h,n,z=1.96):
    if n<=0:return None
    p=h/n; den=1+z*z/n
    return (p+z*z/(2*n)-z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/den

def summarize(df,col):
    n=len(df); h=int(df[col].sum()) if n else 0
    return {"n":int(n),"wins":h,"rate":None if not n else float(h/n),"wilson95_lower":wilson_lower(h,n)}

def main():
    root=Path(os.environ.get("ALPHABREADTH_SIDE_TOTAL_OUT","alphabreadth_side_total_runtime"))
    raw,out=root/"raw",root/"out"; raw.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    p=raw/"games.csv"; dl(SCHEDULE_URL,p)
    g=pd.read_csv(p,low_memory=False)
    g["gameday"]=pd.to_datetime(g["gameday"],errors="coerce")
    g=g[g["season"].isin((*DEV,VAL)) & g["game_type"].astype(str).eq("REG")].copy()
    f=rolling_team_features(g)
    f["actual_margin"]=f["home_score"]-f["away_score"]
    f["actual_total"]=f["home_score"]+f["away_score"]
    feat=[c for c in f.columns if any(k in c for k in ["_w3_","_w5_","_w8_","prior_games"])]
    f=f[(f["home_prior_games"]>=3)&(f["away_prior_games"]>=3)&f["actual_margin"].notna()&f["actual_total"].notna()].copy()
    dev=f[f["season"].isin(DEV)].copy(); val=f[f["season"].eq(VAL)].copy()

    med=dev[feat].apply(pd.to_numeric,errors="coerce").median()
    Xd=dev[feat].apply(pd.to_numeric,errors="coerce").fillna(med).fillna(0)
    Xv=val[feat].apply(pd.to_numeric,errors="coerce").fillna(med).fillna(0)

    mm=model(); mt=model()
    mm.fit(Xd,dev["actual_margin"]); mt.fit(Xd,dev["actual_total"])
    val["pred_margin"]=mm.predict(Xv); val["pred_total"]=mt.predict(Xv)
    val["side_edge"]=val["pred_margin"]-val["spread_line"]
    val["total_edge"]=val["pred_total"]-val["total_line"]
    val["side_direction"]=np.where(val["side_edge"]>0,"HOME","AWAY")
    val["total_direction"]=np.where(val["total_edge"]>0,"OVER","UNDER")
    val["side_cover"]=val.apply(lambda r:cover_side(r.actual_margin,r.spread_line,r.side_direction) if pd.notna(r.spread_line) else False,axis=1)
    val["total_cover"]=val.apply(lambda r:cover_total(r.actual_total,r.total_line,r.total_direction) if pd.notna(r.total_line) else False,axis=1)

    thresholds={}
    for t in EDGE_THRESHOLDS:
        sd=val[val["spread_line"].notna() & val["side_edge"].abs().ge(t)].copy()
        td=val[val["total_line"].notna() & val["total_edge"].abs().ge(t)].copy()
        weekly_side=sd.groupby("week").size()
        weekly_total=td.groupby("week").size()
        thresholds[str(t)]={
            "SIDE":{**summarize(sd,"side_cover"),"avg_candidates_per_week":float(weekly_side.mean()) if len(weekly_side) else 0.0,"median_candidates_per_week":float(weekly_side.median()) if len(weekly_side) else 0.0},
            "TOTAL":{**summarize(td,"total_cover"),"avg_candidates_per_week":float(weekly_total.mean()) if len(weekly_total) else 0.0,"median_candidates_per_week":float(weekly_total.median()) if len(weekly_total) else 0.0},
        }

    report={
        "gate":"ALPHABREADTH SIDE + TOTAL HISTORICAL BREADTH BASELINE",
        "status":"2024_VALIDATION_DIAGNOSTIC_ONLY",
        "development":list(DEV),"validation":[VAL],
        "features":"strictly prior-team rolling PF/PA/margin/total/win-rate over 3/5/8 games; target game excluded",
        "edge_definition":{
            "SIDE":"predicted home margin minus market spread_line",
            "TOTAL":"predicted total points minus market total_line",
        },
        "thresholds":thresholds,
        "controls":{
            "price_economics":"NOT_TESTED; cover-rate diagnostic only",
            "vig":"NOT_MODELED",
            "threshold_promotion":"PROHIBITED_FROM_THIS_GATE",
            "same_game_leakage":"PASS_BY_HISTORY_UPDATE_AFTER_ROW",
            "2025_2026":"NOT_USED",
            "wager_execution":"DISABLED"
        },
        "alphacreative_question":"Which edge threshold offers useful weekly breadth without collapsing validation cover-rate confidence?"
    }
    val.to_csv(out/"side_total_2024_validation_rows.csv",index=False)
    (out/"SIDE_TOTAL_BREADTH_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("ALPHABREADTH_SIDE_TOTAL_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHABREADTH_SIDE_TOTAL_END")
if __name__=="__main__":main()
