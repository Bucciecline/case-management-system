#!/usr/bin/env python3
from __future__ import annotations

import hashlib, json, math, os, urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

CONTEXT_SEASONS=(2020,2021,2022,2023,2024,2025,2026)
TRAIN_SEASONS=(2021,2022)
CAL_SEASON=2023
VAL_SEASON=2024
TARGET_SEASON=2026
TARGET_WEEK=4
WINDOWS=(3,5,8)
CONF_GRID=(0.03,0.05,0.07,0.10,0.12,0.15,0.18,0.20)
MIN_CAL_N=40

BASE="https://github.com/nflverse/nflverse-data/releases/download"
PBP_URL=BASE+"/pbp/play_by_play_{season}.csv"
SCHEDULE_URL="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

# Current market checkpoint frozen from CBS Sports Week 4 page on 2026-09-28 morning.
# spread_line uses nflverse convention: positive = home favorite, negative = away favorite.
MARKET_CHECKPOINT={
    "PIT@CLE":{"spread_line":-2.5,"total_line":37.5},
    "IND@WAS":{"spread_line":-4.5,"total_line":46.5},
    "ARI@NYG":{"spread_line": 2.5,"total_line":43.5},
    "DAL@HOU":{"spread_line": 3.0,"total_line":47.5},
    "GB@TB":{"spread_line":-1.5,"total_line":45.5},
    "JAC@CIN":{"spread_line": 3.0,"total_line":49.5},
    "LA@PHI":{"spread_line":-2.5,"total_line":46.5},
    "NE@BUF":{"spread_line": 5.5,"total_line":49.5},
    "NYJ@CHI":{"spread_line": 3.0,"total_line":43.5},
    "TEN@BAL":{"spread_line":10.5,"total_line":44.5},
    "MIA@MIN":{"spread_line":10.5,"total_line":42.5},
    "DEN@SF":{"spread_line": 3.0,"total_line":45.5},
    "KC@LV":{"spread_line":-6.0,"total_line":45.5},
    "LAC@SEA":{"spread_line": 6.5,"total_line":43.5},
    "DET@CAR":{"spread_line":-3.0,"total_line":49.5},
    "ATL@NO":{"spread_line": 3.5,"total_line":45.5},
}

TEAM_METRICS=[
    "pf","pa","margin","total","win",
    "off_epa","off_success","off_explosive","off_rz_td_rate",
    "off_pressure_allowed","off_sack_allowed","off_pass_rate","off_plays",
    "def_epa_allowed","def_success_allowed","def_explosive_allowed","def_rz_td_allowed",
    "def_pressure_generated","def_sack_generated","def_plays_faced",
]

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def dl(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"AlphaBreadth-Matchup-Upgrade/1.0"})
    with urllib.request.urlopen(req,timeout=180) as r, open(path,"wb") as w:
        while True:
            b=r.read(1024*1024)
            if not b: break
            w.write(b)

def safe_mean(s):
    x=pd.to_numeric(s,errors="coerce").dropna()
    return float(x.mean()) if len(x) else np.nan

def game_team_metrics(pbp):
    p=pbp.copy()
    for c in ["epa","success","yards_gained","yardline_100","touchdown","sack","qb_hit","pass","rush","qb_kneel","qb_spike","drive"]:
        if c in p.columns:
            p[c]=pd.to_numeric(p[c],errors="coerce")
    p["qb_kneel"]=p.get("qb_kneel",0)
    p["qb_spike"]=p.get("qb_spike",0)
    out={}
    grouped=p[p["posteam"].notna()].groupby(["game_id","posteam"],sort=False)
    for (gid,team),g in grouped:
        g=g.copy()
        scr=g[(g.get("pass",0).fillna(0).eq(1)|g.get("rush",0).fillna(0).eq(1)) & ~g.get("qb_kneel",0).fillna(0).eq(1)].copy()
        n=len(scr)
        passplays=scr[scr.get("pass",0).fillna(0).eq(1)]
        pressures=((passplays.get("sack",0).fillna(0).eq(1))|(passplays.get("qb_hit",0).fillna(0).eq(1))).sum() if len(passplays) else 0
        sacks=passplays.get("sack",pd.Series(dtype=float)).fillna(0).eq(1).sum() if len(passplays) else 0

        rz=g[g["yardline_100"].le(20,fill_value=False)] if "yardline_100" in g.columns else g.iloc[0:0]
        rz_drives=set(str(x) for x in rz["drive"].dropna().tolist()) if "drive" in rz.columns else set()
        tdg=g[g.get("touchdown",0).fillna(0).eq(1) & g.get("td_team",pd.Series(index=g.index,dtype=object)).astype(str).eq(str(team))]
        td_drives=set(str(x) for x in tdg["drive"].dropna().tolist()) if "drive" in tdg.columns else set()
        rz_tds=len(rz_drives & td_drives)

        out[(str(gid),str(team))]={
            "off_epa": safe_mean(scr.get("epa",pd.Series(dtype=float))),
            "off_success": safe_mean(scr.get("success",pd.Series(dtype=float))),
            "off_explosive": float((pd.to_numeric(scr.get("yards_gained",0),errors="coerce").fillna(0)>=20).mean()) if n else np.nan,
            "off_rz_td_rate": float(rz_tds/len(rz_drives)) if rz_drives else np.nan,
            "off_pressure_allowed": float(pressures/len(passplays)) if len(passplays) else np.nan,
            "off_sack_allowed": float(sacks/len(passplays)) if len(passplays) else np.nan,
            "off_pass_rate": float(scr.get("pass",0).fillna(0).eq(1).mean()) if n else np.nan,
            "off_plays": float(n),
        }
    return out

def make_team_game_records(schedule, offmetrics):
    recs={}
    for g in schedule.itertuples(index=False):
        if pd.isna(getattr(g,"home_score",np.nan)) or pd.isna(getattr(g,"away_score",np.nan)): continue
        gid=str(g.game_id); h=str(g.home_team); a=str(g.away_team)
        hs=float(g.home_score); as_=float(g.away_score)
        ho=offmetrics.get((gid,h),{}); ao=offmetrics.get((gid,a),{})
        def record(team_off,opp_off,pf,pa):
            return {
                "pf":pf,"pa":pa,"margin":pf-pa,"total":pf+pa,"win":1.0 if pf>pa else 0.0,
                **team_off,
                "def_epa_allowed":opp_off.get("off_epa",np.nan),
                "def_success_allowed":opp_off.get("off_success",np.nan),
                "def_explosive_allowed":opp_off.get("off_explosive",np.nan),
                "def_rz_td_allowed":opp_off.get("off_rz_td_rate",np.nan),
                "def_pressure_generated":opp_off.get("off_pressure_allowed",np.nan),
                "def_sack_generated":opp_off.get("off_sack_allowed",np.nan),
                "def_plays_faced":opp_off.get("off_plays",np.nan),
            }
        recs[(gid,h)]=record(ho,ao,hs,as_)
        recs[(gid,a)]=record(ao,ho,as_,hs)
    return recs

def avg(hist,w,key):
    vals=[x.get(key,np.nan) for x in hist[-w:]]
    vals=pd.to_numeric(pd.Series(vals),errors="coerce").dropna()
    return float(vals.mean()) if len(vals) else np.nan

def build_feature_rows(schedule, records):
    hist=defaultdict(list)
    last_date={}
    rows=[]
    schedule=schedule.sort_values(["gameday","gametime","game_id"],kind="mergesort").reset_index(drop=True)
    for g in schedule.itertuples(index=False):
        gid=str(g.game_id); season=int(g.season); week=int(g.week)
        home=str(g.home_team); away=str(g.away_team); date=pd.Timestamp(g.gameday)
        row={
            "game_id":gid,"season":season,"week":week,"gameday":str(date.date()),
            "home_team":home,"away_team":away,
            "spread_line":float(g.spread_line) if pd.notna(g.spread_line) else np.nan,
            "total_line":float(g.total_line) if pd.notna(g.total_line) else np.nan,
            "home_score":float(g.home_score) if pd.notna(g.home_score) else np.nan,
            "away_score":float(g.away_score) if pd.notna(g.away_score) else np.nan,
            "home_prior_games":len(hist[home]),"away_prior_games":len(hist[away]),
            "home_rest_days":float((date-last_date[home]).days) if home in last_date else np.nan,
            "away_rest_days":float((date-last_date[away]).days) if away in last_date else np.nan,
        }
        for team,label in [(home,"home"),(away,"away")]:
            for w in WINDOWS:
                for m in TEAM_METRICS:
                    row[f"{label}_w{w}_{m}"]=avg(hist[team],w,m)

        # Matchup interactions. Positive means favorable to the named offense for performance metrics.
        for w in WINDOWS:
            row[f"w{w}_home_epa_match"]=row[f"home_w{w}_off_epa"]-row[f"away_w{w}_def_epa_allowed"]
            row[f"w{w}_away_epa_match"]=row[f"away_w{w}_off_epa"]-row[f"home_w{w}_def_epa_allowed"]
            row[f"w{w}_home_success_match"]=row[f"home_w{w}_off_success"]-row[f"away_w{w}_def_success_allowed"]
            row[f"w{w}_away_success_match"]=row[f"away_w{w}_off_success"]-row[f"home_w{w}_def_success_allowed"]
            row[f"w{w}_home_explosive_match"]=row[f"home_w{w}_off_explosive"]-row[f"away_w{w}_def_explosive_allowed"]
            row[f"w{w}_away_explosive_match"]=row[f"away_w{w}_off_explosive"]-row[f"home_w{w}_def_explosive_allowed"]
            row[f"w{w}_home_rz_match"]=row[f"home_w{w}_off_rz_td_rate"]-row[f"away_w{w}_def_rz_td_allowed"]
            row[f"w{w}_away_rz_match"]=row[f"away_w{w}_off_rz_td_rate"]-row[f"home_w{w}_def_rz_td_allowed"]
            row[f"w{w}_home_pressure_match"]=row[f"away_w{w}_def_pressure_generated"]-row[f"home_w{w}_off_pressure_allowed"]
            row[f"w{w}_away_pressure_match"]=row[f"home_w{w}_def_pressure_generated"]-row[f"away_w{w}_off_pressure_allowed"]
            row[f"w{w}_pace_sum"]=row[f"home_w{w}_off_plays"]+row[f"away_w{w}_off_plays"]
            row[f"w{w}_pass_rate_sum"]=row[f"home_w{w}_off_pass_rate"]+row[f"away_w{w}_off_pass_rate"]

        rows.append(row)

        # update history only after the pregame row is built
        if (gid,home) in records and (gid,away) in records:
            hist[home].append(records[(gid,home)])
            hist[away].append(records[(gid,away)])
            last_date[home]=date; last_date[away]=date
    return pd.DataFrame(rows)

def model():
    return HistGradientBoostingClassifier(
        learning_rate=0.04,max_iter=300,max_leaf_nodes=15,min_samples_leaf=25,
        l2_regularization=2.0,random_state=261004
    )

def wilson_lower(h,n,z=1.96):
    if n<=0:return None
    p=h/n; den=1+z*z/n
    return (p+z*z/(2*n)-z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/den

def grade_prob(p,y):
    pred=(p>=0.5).astype(int)
    return pred==y

def choose_threshold(probs,y):
    rows=[]
    conf=np.abs(probs-0.5)
    correct=grade_prob(probs,y)
    for t in CONF_GRID:
        mask=conf>=t; n=int(mask.sum()); h=int(correct[mask].sum()) if n else 0
        rows.append({"threshold":t,"n":n,"wins":h,"rate":None if n==0 else h/n,"wilson":wilson_lower(h,n)})
    eligible=[r for r in rows if r["n"]>=MIN_CAL_N and r["wilson"] is not None]
    chosen=max(eligible,key=lambda r:(r["wilson"],r["n"],-r["threshold"])) if eligible else None
    return chosen,rows

def market_key(row):
    return f"{row['away_team']}@{row['home_team']}"

def main():
    root=Path(os.environ.get("ALPHABREADTH_MATCHUP_OUT","alphabreadth_matchup_upgrade_runtime"))
    raw,out=root/"raw",root/"out"; raw.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    receipts=[]; pbps=[]
    use=["game_id","posteam","defteam","epa","success","yards_gained","yardline_100","touchdown","td_team","sack","qb_hit","pass","rush","qb_kneel","qb_spike","drive"]
    for s in CONTEXT_SEASONS:
        p=raw/f"play_by_play_{s}.csv"; url=PBP_URL.format(season=s); dl(url,p)
        receipts.append({"family":"pbp","season":s,"size":p.stat().st_size,"sha256":sha256(p),"url":url})
        head=pd.read_csv(p,nrows=0).columns.tolist(); cols=[c for c in use if c in head]
        d=pd.read_csv(p,usecols=cols,low_memory=False); pbps.append(d)
    pbp=pd.concat(pbps,ignore_index=True,sort=False)
    offmetrics=game_team_metrics(pbp)

    sp=raw/"games.csv"; dl(SCHEDULE_URL,sp)
    receipts.append({"family":"schedule","size":sp.stat().st_size,"sha256":sha256(sp),"url":SCHEDULE_URL})
    sched=pd.read_csv(sp,low_memory=False)
    sched["gameday"]=pd.to_datetime(sched["gameday"],errors="coerce")
    sched=sched[sched["season"].isin(CONTEXT_SEASONS) & sched["game_type"].astype(str).eq("REG")].copy()

    records=make_team_game_records(sched,offmetrics)
    feats=build_feature_rows(sched,records)

    # overwrite only current target-market rows with authenticated checkpoint
    current_mask=feats["season"].eq(TARGET_SEASON) & feats["week"].eq(TARGET_WEEK)
    for idx,row in feats[current_mask].iterrows():
        key=market_key(row)
        if key in MARKET_CHECKPOINT:
            feats.at[idx,"spread_line"]=MARKET_CHECKPOINT[key]["spread_line"]
            feats.at[idx,"total_line"]=MARKET_CHECKPOINT[key]["total_line"]

    feats["actual_margin"]=feats["home_score"]-feats["away_score"]
    feats["actual_total"]=feats["home_score"]+feats["away_score"]
    feats["side_push"]=np.isclose(feats["actual_margin"],feats["spread_line"],equal_nan=False)
    feats["total_push"]=np.isclose(feats["actual_total"],feats["total_line"],equal_nan=False)
    feats["home_cover"]=(feats["actual_margin"]>feats["spread_line"]).astype(int)
    feats["over"]=(feats["actual_total"]>feats["total_line"]).astype(int)

    excluded={"game_id","season","week","gameday","home_team","away_team","home_score","away_score",
              "actual_margin","actual_total","home_cover","over","side_push","total_push"}
    feature_cols=[c for c in feats.columns if c not in excluded and c not in {"spread_line","total_line"}]
    # market lines are included as context features
    feature_cols += ["spread_line","total_line"]

    base=feats[(feats["home_prior_games"]>=3)&(feats["away_prior_games"]>=3)].copy()
    train=base[base["season"].isin(TRAIN_SEASONS)].copy()
    cal=base[base["season"].eq(CAL_SEASON)].copy()
    val=base[base["season"].eq(VAL_SEASON)].copy()
    current=base[base["season"].eq(TARGET_SEASON)&base["week"].eq(TARGET_WEEK)].copy()

    med=train[feature_cols].apply(pd.to_numeric,errors="coerce").median()
    def X(d): return d[feature_cols].apply(pd.to_numeric,errors="coerce").fillna(med).fillna(0)

    outputs={}
    current_out=current[["game_id","gameday","away_team","home_team","spread_line","total_line"]].copy()

    for lane,label,push in [("SIDE","home_cover","side_push"),("TOTAL","over","total_push")]:
        tr=train[~train[push]].copy(); ca=cal[~cal[push]].copy(); va=val[~val[push]].copy()
        m=model(); m.fit(X(tr),tr[label].to_numpy(int))
        pcal=m.predict_proba(X(ca))[:,1]
        chosen,grid=choose_threshold(pcal,ca[label].to_numpy(int))
        threshold=chosen["threshold"] if chosen else 0.20

        pval=m.predict_proba(X(va))[:,1]
        conf=np.abs(pval-0.5); mask=conf>=threshold; corr=grade_prob(pval,va[label].to_numpy(int))
        weekly=pd.DataFrame({"week":va["week"].to_numpy(),"take":mask}).query("take").groupby("week").size()
        validation={
            "threshold":threshold,
            "n":int(mask.sum()),
            "wins":int(corr[mask].sum()),
            "rate":None if mask.sum()==0 else float(corr[mask].mean()),
            "wilson95_lower":wilson_lower(int(corr[mask].sum()),int(mask.sum())),
            "avg_candidates_per_active_week":float(weekly.mean()) if len(weekly) else 0.0,
            "median_candidates_per_active_week":float(weekly.median()) if len(weekly) else 0.0,
        }

        # Refit on train+cal only after threshold is frozen, then project current.
        dev=pd.concat([tr,ca],ignore_index=True)
        med2=dev[feature_cols].apply(pd.to_numeric,errors="coerce").median()
        def X2(d): return d[feature_cols].apply(pd.to_numeric,errors="coerce").fillna(med2).fillna(0)
        m2=model(); m2.fit(X2(dev),dev[label].to_numpy(int))
        pc=m2.predict_proba(X2(current))[:,1] if len(current) else np.array([])
        current_out[f"{lane.lower()}_prob_home_or_over"]=pc
        current_out[f"{lane.lower()}_confidence"]=np.abs(pc-0.5)
        current_out[f"{lane.lower()}_direction"]=np.where(pc>=0.5,"HOME" if lane=="SIDE" else "OVER","AWAY" if lane=="SIDE" else "UNDER")
        current_out[f"{lane.lower()}_status"]=np.where(np.abs(pc-0.5)>=threshold,"CHALLENGER","SHADOW")

        outputs[lane]={
            "calibration_grid":grid,
            "chosen_calibration":chosen,
            "validation_2024":validation,
        }

    # independent risk clusters: one SIDE and one TOTAL per game at most
    current_out["side_cluster"]="SIDE_"+current_out["game_id"].astype(str)
    current_out["total_cluster"]="TOTAL_"+current_out["game_id"].astype(str)
    current_out["weather_status"]="OVERLAY_HOLD_CURRENT_FORECAST_NOT_CORE_MODEL"
    current_out["injury_status"]="OVERLAY_HOLD_NOT_CORE_MODEL"

    report={
        "gate":"ALPHABREADTH 2026 WEEK-4 SIDE/TOTAL MATCHUP UPGRADE GATE",
        "status":"VALIDATION_COMPLETE_CURRENT_CHALLENGERS_SHADOW_ONLY",
        "design":{
            "train":[2021,2022],"calibration":[2023],"validation":[2024],
            "features":"rolling 3/5/8 scoring + EPA + success + explosive + red-zone TD + pressure/sack + pass-rate + play-volume + opponent interaction + rest + home/away market context",
            "threshold_selection":"fixed confidence grid on 2023 only; max Wilson lower bound with >=40 calibration candidates",
            "weather":"separate source-safe overlay; not used in historical core",
            "injuries":"separate source-safe overlay; not used in historical core",
        },
        "lanes":outputs,
        "current_market_checkpoint":{
            "source":"CBS Sports Week 4 page observed 2026-09-28 morning",
            "games":len(MARKET_CHECKPOINT),
            "note":"lines are snapshot inputs and must be rechecked before any final pregame freeze",
        },
        "current_challenger_counts":{
            "SIDE":int(current_out["side_status"].eq("CHALLENGER").sum()),
            "TOTAL":int(current_out["total_status"].eq("CHALLENGER").sum()),
            "independent_game_lane_clusters":int(current_out["side_status"].eq("CHALLENGER").sum()+current_out["total_status"].eq("CHALLENGER").sum()),
        },
        "controls":{
            "same_game_leakage":"PASS_FEATURE_ROW_BUILT_BEFORE_HISTORY_UPDATE",
            "2024_threshold_tuning":"PROHIBITED",
            "2025_2026_model_training":"NO",
            "current_lines":"SNAPSHOT_RECHECK_REQUIRED",
            "profitability_claim":"PROHIBITED_WITHOUT_PRICE/VIG ECONOMICS",
            "wager_execution":"DISABLED",
        },
        "alphacreative":{
            "rule":"if 2024 validation fails to clear a credible cover-rate bar, reject the challenger even if it generates many current candidates",
            "anti_loop":"do not retune thresholds on 2024 or current slate",
        }
    }

    current_out.to_csv(out/"week4_2026_side_total_current_board.csv",index=False)
    val.to_csv(out/"side_total_2024_feature_rows.csv",index=False)
    (out/"SIDE_TOTAL_MATCHUP_UPGRADE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")
    print("ALPHABREADTH_MATCHUP_UPGRADE_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHABREADTH_MATCHUP_UPGRADE_END")

if __name__=="__main__":
    main()
