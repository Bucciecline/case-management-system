#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib.util, json, math, urllib.request
from collections import defaultdict, deque
from pathlib import Path
import numpy as np
import pandas as pd

AS_OF="2026-09-26 America/Chicago"
SEASONS=(2021,2022,2023,2024,2025)
ROLL=6
MIN_PRIOR=3
OUT=Path("alphaodds/winner_dna/outputs/team_chaos")
RAW=Path("winner_dna_team_runtime")
OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)

PBP_SHA={
2021:"35f5d0b49905daa7d63ace9710346c48c7eb32ce0b8686629491954308013354",
2022:"8aeb0e505d43950e09fec35a241a4e62720422454cdd3ac8f98c95650d54ab54",
2023:"4aeca98ebe6357c5f1a13165533007964605d1f17bd54561937769b952c67613",
2024:"6ae564c2c49378ec531303292966caee596982278b9fcdad9c9dd0a0dc16bfa7",
2025:"8ce0001826f0f7b895b7a1068e4db7f43696c699db7064ccb1201855768fd06c",
}
QB_REJECTED_REFERENCE={
"gate":"ALPHANFL WINNER DNA — QB-FIRST ADVANCED ENRICHMENT & CHAOS-SEPARATION",
"preserved_not_recomputed":True,
"epa":{"n":928,"wins":551,"accuracy":0.59375},
"qbr":{"n":468,"wins":269,"accuracy":269/468},
"continuity":{"n":827,"wins":514,"accuracy":514/827},
"composite":{"n":610,"wins":383,"accuracy":383/610},
"decision":"DIAGNOSTIC_ONLY_NO_WINNER_DNA_V2_PROMOTION"
}
ALIASES={"LAR":"LA","STL":"LA","WSH":"WAS","OAK":"LV","SD":"LAC","JAC":"JAX"}
METRICS={
"off_epa_play":{"higher":True,"label":"Offensive EPA/play"},
"def_epa_allowed":{"higher":False,"label":"Defensive EPA/play allowed"},
"success_rate":{"higher":True,"label":"Offensive success rate"},
"explosive_rate":{"higher":True,"label":"Explosive-play rate"},
"turnover_diff_rate":{"higher":True,"label":"Turnover differential tendency"},
"pressure_balance_rate":{"higher":True,"label":"Sack/QB-hit pressure balance"},
"redzone_td_drive_rate":{"higher":True,"label":"Red-zone drive TD conversion"},
}

def ct(x):
    if pd.isna(x): return None
    s=str(x).strip().upper()
    return ALIASES.get(s,s)

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def dl(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"AlphaNFL-WinnerDNA-TeamChaos/1.0"})
    with urllib.request.urlopen(req,timeout=300) as r,path.open("wb") as w:
        while True:
            b=r.read(1<<20)
            if not b: break
            w.write(b)

def load_frozen_qb_module():
    p=Path("alphaodds/winner_dna/qb_first_gate.py")
    spec=importlib.util.spec_from_file_location("winner_dna_qb_frozen",p)
    if spec is None or spec.loader is None: raise RuntimeError("Cannot load preserved QB gate module")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def download_schedule():
    p=RAW/"games.csv"
    dl("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",p)
    d=pd.read_csv(p,low_memory=False)
    d=d[d.season.isin(range(2019,2026))].copy()
    d=d[d.game_type.astype(str).str.upper().isin(["REG","WC","DIV","CON","SB","POST"])].copy()
    d["gameday"]=pd.to_datetime(d.gameday,errors="coerce")
    d["home_team"]=d.home_team.map(ct); d["away_team"]=d.away_team.map(ct)
    for c in ["home_score","away_score","week"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d[d.home_score.notna()&d.away_score.notna()].sort_values(["gameday","game_id"],kind="mergesort").reset_index(drop=True)
    return d,{"url":"https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv","size":p.stat().st_size,"sha256":sha256(p)}

def _n(x): return pd.to_numeric(x,errors="coerce")

def aggregate_year(y):
    url=f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv"
    p=RAW/f"play_by_play_{y}.csv"
    print("MATERIALIZE",y,url,flush=True); dl(url,p)
    digest=sha256(p); rec={"season":y,"url":url,"size":p.stat().st_size,"expected_sha256":PBP_SHA[y],"actual_sha256":digest,"sha_match":digest==PBP_SHA[y]}
    if not rec["sha_match"]: raise RuntimeError(f"PBP hash mismatch {y}: {digest}")
    header=list(pd.read_csv(p,nrows=0).columns)
    needed=["game_id","season","week","posteam","defteam","epa","success","pass","rush","qb_dropback","sack","qb_hit","interception","fumble_lost","yards_gained","yardline_100","drive","fixed_drive","touchdown","td_team","no_play","qb_kneel","qb_spike","play_type"]
    use=[c for c in needed if c in header]
    required={"game_id","posteam","defteam","epa","yards_gained"}
    miss=required-set(use)
    if miss: raise RuntimeError(f"Missing required PBP columns {y}: {sorted(miss)}")
    d=pd.read_csv(p,usecols=use,low_memory=False)
    for c in ["posteam","defteam","td_team"]:
        if c in d.columns: d[c]=d[c].map(ct)
    for c in ["epa","success","pass","rush","qb_dropback","sack","qb_hit","interception","fumble_lost","yards_gained","yardline_100","touchdown","no_play","qb_kneel","qb_spike"]:
        if c in d.columns: d[c]=_n(d[c])
    if "no_play" in d.columns: d=d[d.no_play.fillna(0).eq(0)].copy()
    if "qb_kneel" in d.columns: d=d[~d.qb_kneel.fillna(0).eq(1)].copy()
    if "qb_spike" in d.columns: d=d[~d.qb_spike.fillna(0).eq(1)].copy()
    if "pass" in d.columns and "rush" in d.columns:
        d=d[(d["pass"].fillna(0).eq(1))|(d["rush"].fillna(0).eq(1))].copy()
    elif "play_type" in d.columns:
        d=d[d.play_type.astype(str).isin(["pass","run"])].copy()
    d=d[d.posteam.notna()&d.defteam.notna()&d.epa.notna()].copy()
    if d.empty: raise RuntimeError(f"No eligible plays {y}")
    d["is_success"]=d["success"].fillna(d.epa.gt(0).astype(float)) if "success" in d.columns else d.epa.gt(0).astype(float)
    ispass=d["pass"].fillna(0).eq(1) if "pass" in d.columns else d.play_type.astype(str).eq("pass")
    isrush=d["rush"].fillna(0).eq(1) if "rush" in d.columns else d.play_type.astype(str).eq("run")
    d["explosive"]=((ispass & d.yards_gained.ge(20)) | (isrush & d.yards_gained.ge(10))).astype(float)
    ints=d["interception"].fillna(0).eq(1) if "interception" in d.columns else pd.Series(False,index=d.index)
    fum=d["fumble_lost"].fillna(0).eq(1) if "fumble_lost" in d.columns else pd.Series(False,index=d.index)
    d["giveaway"]=(ints|fum).astype(float)
    if "qb_dropback" in d.columns: drop=d.qb_dropback.fillna(0).eq(1)
    else: drop=ispass
    sack=d["sack"].fillna(0).eq(1) if "sack" in d.columns else pd.Series(False,index=d.index)
    hit=d["qb_hit"].fillna(0).eq(1) if "qb_hit" in d.columns else pd.Series(False,index=d.index)
    d["pressure_event"]=(drop & (sack|hit)).astype(float); d["dropback"]=drop.astype(float)
    d["redzone"]=d["yardline_100"].le(20) if "yardline_100" in d.columns else False
    if "td_team" in d.columns: d["off_td"]=(d.td_team==d.posteam).astype(float)
    elif "touchdown" in d.columns: d["off_td"]=d.touchdown.fillna(0).eq(1).astype(float)
    else: d["off_td"]=0.0

    # offense team-game
    grp=d.groupby(["game_id","posteam"],dropna=False)
    off=grp.agg(
        off_epa_play=("epa","mean"),
        success_rate=("is_success","mean"),
        explosive_rate=("explosive","mean"),
        giveaway_rate=("giveaway","mean"),
        plays=("epa","size"),
        pressure_events=("pressure_event","sum"),
        dropbacks=("dropback","sum"),
    ).reset_index().rename(columns={"posteam":"team"})
    off["pressure_allowed_rate"]=np.where(off.dropbacks>0,off.pressure_events/off.dropbacks,np.nan)

    # red-zone drive conversion: a possession drive is an opportunity if it reached opponent 20;
    # converted if the offense scored a TD on that same drive.
    drive_col="fixed_drive" if "fixed_drive" in d.columns else ("drive" if "drive" in d.columns else None)
    if drive_col:
        rz=d[d.redzone].copy()
        if not rz.empty:
            rzdrive=rz.groupby(["game_id","posteam",drive_col],dropna=False).agg(converted=("off_td","max")).reset_index()
            rzagg=rzdrive.groupby(["game_id","posteam"]).agg(redzone_drives=(drive_col,"size"),redzone_td_drives=("converted","sum")).reset_index().rename(columns={"posteam":"team"})
            rzagg["redzone_td_drive_rate"]=np.where(rzagg.redzone_drives>0,rzagg.redzone_td_drives/rzagg.redzone_drives,np.nan)
            off=off.merge(rzagg[["game_id","team","redzone_td_drive_rate","redzone_drives"]],on=["game_id","team"],how="left")
        else:
            off["redzone_td_drive_rate"]=np.nan; off["redzone_drives"]=0
    else:
        # transparent fallback if drive IDs disappear from source schema
        rz=d[d.redzone].groupby(["game_id","posteam"]).agg(redzone_td_drive_rate=("off_td","mean"),redzone_drives=("off_td","size")).reset_index().rename(columns={"posteam":"team"})
        off=off.merge(rz,on=["game_id","team"],how="left")

    # defense allowed/created from opponent offensive plays
    de=grp.agg(
        def_epa_allowed=("epa","mean"),
        takeaway_rate=("giveaway","mean"),
        pressure_events=("pressure_event","sum"),
        opponent_dropbacks=("dropback","sum"),
    ).reset_index().rename(columns={"posteam":"opponent"})
    # defteam is unique for an offense team-game in ordinary NFL games; map via first
    mapdef=grp["defteam"].first().reset_index().rename(columns={"posteam":"opponent","defteam":"team"})
    de=de.merge(mapdef,on=["game_id","opponent"],how="left")
    de["def_pressure_rate"]=np.where(de.opponent_dropbacks>0,de.pressure_events/de.opponent_dropbacks,np.nan)
    de=de[["game_id","team","def_epa_allowed","takeaway_rate","def_pressure_rate"]]
    out=off.merge(de,on=["game_id","team"],how="left",validate="1:1")
    out["turnover_diff_rate"]=out["takeaway_rate"]-out["giveaway_rate"]
    out["pressure_balance_rate"]=out["def_pressure_rate"]-out["pressure_allowed_rate"]
    out["season"]=y
    p.unlink(missing_ok=True)
    return out,rec,{"season":y,"drive_field":drive_col or "NONE","rows":int(len(d)),"team_games":int(len(out)),"columns_used":use}

def build_team_history(teamgames,sched):
    meta=[]
    for r in sched[sched.season.isin(SEASONS)].itertuples(index=False):
        meta.append({"game_id":r.game_id,"season":int(r.season),"week":int(r.week),"gameday":r.gameday,"home_team":r.home_team,"away_team":r.away_team})
    meta=pd.DataFrame(meta)
    t=teamgames.merge(meta[["game_id","season","week","gameday"]],on=["game_id","season"],how="left")
    t=t.sort_values(["team","season","gameday","game_id"],kind="mergesort").reset_index(drop=True)
    g=t.groupby(["team","season"],sort=False)
    t["prior_team_games"]=g.cumcount()
    for m in METRICS:
        lag=g[m].shift(1)
        t[f"pregame_{m}"]=lag.groupby([t.team,t.season],sort=False).transform(lambda x:x.rolling(ROLL,min_periods=MIN_PRIOR).mean())
    return t

def join_games(control,history):
    base=control[control.season.isin(SEASONS)].copy()
    cols=["game_id","team","prior_team_games"]+[f"pregame_{m}" for m in METRICS]
    for side in ["away","home"]:
        h=history[cols].copy()
        rename={"team":f"{side}_team","prior_team_games":f"{side}_prior_team_games"}
        rename.update({f"pregame_{m}":f"{side}_{m}" for m in METRICS})
        h=h.rename(columns=rename)
        base=base.merge(h,on=["game_id",f"{side}_team"],how="left",validate="1:1")
    for m,cfg in METRICS.items():
        a=base[f"away_{m}"]; h=base[f"home_{m}"]
        valid=a.notna()&h.notna()&a.ne(h)
        if cfg["higher"]:
            base[f"team_vote_{m}"]=np.where(valid,np.where(h>a,base.home_team,base.away_team),None)
            # positive support margin for home team
            base[f"home_margin_{m}"]=h-a
        else:
            base[f"team_vote_{m}"]=np.where(valid,np.where(h<a,base.home_team,base.away_team),None)
            base[f"home_margin_{m}"]=a-h
    votes=[f"team_vote_{m}" for m in METRICS]
    def convergence(r):
        av=[r[c] for c in votes if pd.notna(r[c]) and r[c] is not None]
        hc=av.count(r.home_team); ac=av.count(r.away_team)
        if hc>ac: pick=r.home_team; mx=hc
        elif ac>hc: pick=r.away_team; mx=ac
        else: pick=None; mx=hc
        return pd.Series({"team_factor_votes_available":len(av),"team_factor_home_votes":hc,"team_factor_away_votes":ac,
                          "team_factor_majority":pick,"team_factor_max_agreement":mx,
                          "team_factor_unanimous":bool(len(av)==7 and mx==7)})
    base=pd.concat([base,base.apply(convergence,axis=1)],axis=1)
    return base

def accuracy(d,col):
    x=d[d.winner.notna()&d[col].notna()].copy()
    return {"n":int(len(x)),"wins":int((x[col]==x.winner).sum()),"accuracy":float((x[col]==x.winner).mean()) if len(x) else None}

def metric_results(g):
    out={}
    for m in METRICS:
        col=f"team_vote_{m}"
        rec={"label":METRICS[m]["label"],"overall":accuracy(g,col),"by_season":{}}
        for s,x in g.groupby("season"): rec["by_season"][str(int(s))]=accuracy(x,col)
        valid_years=[v for v in rec["by_season"].values() if v["n"]>=25 and v["accuracy"] is not None]
        rec["stability"]={"years_n_ge_25":len(valid_years),"years_above_50pct":sum(v["accuracy"]>.5 for v in valid_years),
                          "survives_across_seasons":bool(len(valid_years)>=4 and sum(v["accuracy"]>.5 for v in valid_years)>=4)}
        out[m]=rec
    return out

def convergence_results(g):
    d=g[g.winner.notna()].copy(); out={"majority":accuracy(d,"team_factor_majority"),"by_max_agreement":{},"by_season":{}}
    for k in range(4,8):
        x=d[(d.team_factor_votes_available==7)&(d.team_factor_max_agreement==k)].copy()
        out["by_max_agreement"][str(k)]={"n":int(len(x)),"wins":int((x.team_factor_majority==x.winner).sum()),"accuracy":float((x.team_factor_majority==x.winner).mean()) if len(x) else None}
    u=d[d.team_factor_unanimous]
    out["unanimous_7_of_7"]={"n":int(len(u)),"wins":int((u.team_factor_majority==u.winner).sum()),"accuracy":float((u.team_factor_majority==u.winner).mean()) if len(u) else None}
    for s,x in d.groupby("season"): out["by_season"][str(int(s))]=accuracy(x,"team_factor_majority")
    yrs=[v for v in out["by_season"].values() if v["n"]>=25]
    out["stability"]={"years_n_ge_25":len(yrs),"years_above_50pct":sum(v["accuracy"]>.5 for v in yrs),
                      "survives_across_seasons":bool(len(yrs)>=4 and sum(v["accuracy"]>.5 for v in yrs)>=4)}
    return out

def unanimous_diagnostics(g):
    u=g[g.unanimous7 & g.winner.notna()].copy()
    u["control_correct"]=u.unanimous_pick==u.winner
    out={"n":int(len(u)),"wins":int(u.control_correct.sum()),"losses":int((~u.control_correct).sum()),"metrics":{}}
    for m in METRICS:
        col=f"team_vote_{m}"
        x=u[u[col].notna()].copy()
        wins=x[x.control_correct]; losses=x[~x.control_correct]
        ws=float((wins[col]==wins.unanimous_pick).mean()) if len(wins) else None
        ls=float((losses[col]==losses.unanimous_pick).mean()) if len(losses) else None
        warn_loss=float((losses[col]!=losses.unanimous_pick).mean()) if len(losses) else None
        false_warn=float((wins[col]!=wins.unanimous_pick).mean()) if len(wins) else None
        per={}
        for s,z in x.groupby("season"):
            zw=z[z.control_correct]; zl=z[~z.control_correct]
            if len(zw)>=5 and len(zl)>=2:
                per[str(int(s))]={"winner_support_rate":float((zw[col]==zw.unanimous_pick).mean()),
                                  "loss_support_rate":float((zl[col]==zl.unanimous_pick).mean()),
                                  "separation_gap":float((zw[col]==zw.unanimous_pick).mean()-(zl[col]==zl.unanimous_pick).mean()),
                                  "wins_n":int(len(zw)),"losses_n":int(len(zl))}
        stable=sum(v["separation_gap"]>0 for v in per.values())
        # numeric support margin from perspective of Winner DNA pick
        hm=x[f"home_margin_{m}"]
        support=np.where(x.unanimous_pick==x.home_team,hm,-hm)
        x=x.assign(control_support_margin=support)
        out["metrics"][m]={"label":METRICS[m]["label"],"available_n":int(len(x)),
            "winner_support_rate":ws,"loss_support_rate":ls,
            "winner_minus_loss_support_gap":(ws-ls) if ws is not None and ls is not None else None,
            "loss_warning_capture_rate":warn_loss,"win_false_warning_rate":false_warn,
            "mean_support_margin_control_wins":float(x.loc[x.control_correct,"control_support_margin"].mean()) if x.control_correct.any() else None,
            "mean_support_margin_control_losses":float(x.loc[~x.control_correct,"control_support_margin"].mean()) if (~x.control_correct).any() else None,
            "year_by_year_separation":per,"positive_separation_years":stable,
            "survives_across_seasons":bool(len(per)>=4 and stable>=4)}
    # convergence support count for frozen pick
    rows=[]
    for _,r in u.iterrows():
        a=0; n=0
        for m in METRICS:
            v=r[f"team_vote_{m}"]
            if pd.notna(v) and v is not None:
                n+=1
                if v==r.unanimous_pick: a+=1
        rows.append((n,a))
    u[["team_metrics_available_for_control","team_metrics_supporting_control"]]=pd.DataFrame(rows,index=u.index)
    out["support_count_bins"]={}
    for k,z in u[u.team_metrics_available_for_control==7].groupby("team_metrics_supporting_control"):
        out["support_count_bins"][str(int(k))]={"n":int(len(z)),"control_wins":int(z.control_correct.sum()),"control_accuracy":float(z.control_correct.mean())}
    out["mean_support_count"]={"control_wins":float(u.loc[u.control_correct,"team_metrics_supporting_control"].mean()),
                               "control_losses":float(u.loc[~u.control_correct,"team_metrics_supporting_control"].mean())}
    # majority relation
    q=u[u.team_factor_majority.notna()].copy()
    q["relation"]=np.where(q.team_factor_majority==q.unanimous_pick,"CONFIRM","WARNING")
    out["team_majority_relation"]={k:{"n":int(len(z)),"control_wins":int(z.control_correct.sum()),"control_accuracy":float(z.control_correct.mean())} for k,z in q.groupby("relation")}
    return out

def redundancy(g):
    out={}
    domains=["elo","offense","defense","net","schedule_strength","prior_win_pct","prior_point_diff"]
    for m in METRICS:
        mc=f"team_vote_{m}"; rec={}
        for d in domains:
            dc=f"vote_{d}"; x=g[g[mc].notna()&g[dc].notna()&g.winner.notna()].copy()
            disagree=x[x[mc]!=x[dc]]
            rec[d]={"n":int(len(x)),"agreement_rate":float((x[mc]==x[dc]).mean()) if len(x) else None,
                    "disagreement_n":int(len(disagree)),
                    "metric_side_accuracy_when_disagree":float((disagree[mc]==disagree.winner).mean()) if len(disagree) else None}
        out[m]=rec
    # against established majority
    for m in METRICS:
        mc=f"team_vote_{m}"; x=g[g[mc].notna()&g.majority_vote.notna()&g.winner.notna()]
        miss=x[x.majority_vote!=x.winner]; win=x[x.majority_vote==x.winner]
        out[m]["seven_domain_majority"]={
            "n":int(len(x)),"agreement_rate":float((x[mc]==x.majority_vote).mean()) if len(x) else None,
            "majority_misses_n":int(len(miss)),
            "misses_with_metric_opposition":int((miss[mc]!=miss.majority_vote).sum()),
            "miss_capture_rate":float((miss[mc]!=miss.majority_vote).mean()) if len(miss) else None,
            "majority_wins_n":int(len(win)),
            "false_opposition_rate":float((win[mc]!=win.majority_vote).mean()) if len(win) else None}
    return out

def main():
    qb=load_frozen_qb_module()
    sched,schedrec=download_schedule()
    control=qb.control(sched)
    control_summary=qb.control_summary(control); recon=qb.recon(control_summary)
    receipts=[]; schemas=[]; frames=[]
    for y in SEASONS:
        f,r,s=aggregate_year(y); frames.append(f); receipts.append(r); schemas.append(s)
    teamgames=pd.concat(frames,ignore_index=True,sort=False)
    history=build_team_history(teamgames,sched)
    g=join_games(control,history)
    metrics=metric_results(g); conv=convergence_results(g); ud=unanimous_diagnostics(g); red=redundancy(g)

    stable_individual=[m for m,v in metrics.items() if v["stability"]["survives_across_seasons"]]
    stable_sep=[m for m,v in ud["metrics"].items() if v["survives_across_seasons"]]
    promotion="NO_PROMOTION"
    rationale=[]
    if not recon["status"].startswith("PASS"): rationale.append("control reconstruction did not pass close-match check")
    if not conv["stability"]["survives_across_seasons"]: rationale.append("multi-factor majority did not survive predeclared cross-season stability check")
    if len(stable_sep)==0: rationale.append("no individual team metric consistently separated unanimous winners from unanimous losses across at least four seasons")
    if not rationale:
        # Even if exploratory diagnostics look stable, do not auto-promote: require a separately frozen prospective/holdout gate.
        rationale.append("retrospective convergence is hypothesis-generating only; prospective/frozen holdout is required before promotion")

    report={
      "gate":"ALPHANFL WINNER DNA — TEAM EPA / SUCCESS / EXPLOSIVENESS / TURNOVER / PRESSURE CHAOS-SEPARATION",
      "as_of":AS_OF,
      "status":"PASS_RETROSPECTIVE_DIAGNOSTIC_NO_PROMOTION" if recon["status"].startswith("PASS") else "PARTIAL_HOLD_CONTROL_RECONSTRUCTION",
      "frozen_controls":{"seven_domain_reference":qb.REF,"control_reconstruction":control_summary,"reconstruction_check":recon,
                         "rejected_qb_challenger":QB_REJECTED_REFERENCE,"mutation":"NONE"},
      "design":{"window":"trailing 6 team games within same season","minimum_prior_games":MIN_PRIOR,
                "pregame_rule":"aggregate same-game PBP to team-game state, then shift(1) before rolling; predicted game never contributes to its features",
                "metric_definitions":{
                  "off_epa_play":"mean EPA on eligible pass/rush plays; higher better",
                  "def_epa_allowed":"mean opponent offensive EPA/play allowed; lower better",
                  "success_rate":"mean nflverse success where available, otherwise EPA>0 fallback; higher better",
                  "explosive_rate":"pass gain >=20 yards OR rush gain >=10 yards per eligible offensive play; higher better",
                  "turnover_diff_rate":"defensive takeaway rate minus offensive giveaway rate per eligible play; higher better",
                  "pressure_balance_rate":"defensive (sack OR QB-hit)/opponent dropbacks minus offensive pressure-allowed/dropbacks; higher better; proxy, not complete charted pressure",
                  "redzone_td_drive_rate":"TD-scoring drives / offensive drives that reached opponent 20; higher better; drive-ID fallback disclosed if needed"},
                "independent_test":"better pregame metric gets one vote; no learned cutpoints or magnitude thresholds",
                "convergence_test":"report 4-3, 5-2, 6-1, and 7-0 factor agreement separately; no post-hoc winning threshold selected"},
      "source_receipts":{"schedule":schedrec,"play_by_play":receipts,"schema_audit":schemas},
      "independent_metric_results":metrics,
      "multi_factor_convergence":conv,
      "winner_dna_unanimous_chaos_separation":ud,
      "redundancy_analysis":red,
      "cross_season_stable_individual_metrics":stable_individual,
      "cross_season_stable_unanimous_separators":stable_sep,
      "cca15":{
        "authenticated_pbp_receipts":"PASS" if all(x["sha_match"] for x in receipts) else "FAIL",
        "same_game_leakage":"PASS_SHIFT1_BEFORE_ROLLING",
        "outcome_dependent_threshold_search":"NONE",
        "seven_domain_control_mutation":"NONE",
        "qb_challenger_mutation":"NONE",
        "retrospective_only":"YES_NOT_A_PRISTINE_HOLDOUT",
        "pressure_measurement":"PROXY_SACK_OR_QB_HIT_NOT_FULL_CHARTED_PRESSURE",
        "redzone_sample_variance":"MATERIAL_CAUTION",
        "turnover_variance":"MATERIAL_CAUTION",
        "profitability_claim":"PROHIBITED_NO_AUTHENTICATED_PRICE_EVIDENCE",
        "wager_execution":"DISABLED"},
      "defense_red_team":{
        "correlated_features":"EPA_SUCCESS_EXPLOSIVENESS_AND_REDZONE_ARE_NOT_INDEPENDENT",
        "game_script":"team-game state contains legitimate historical score/game-state effects and may regress out of sample",
        "turnovers":"high variance; do not treat short-window turnover edge as stable skill without separate persistence proof",
        "pressure":"qb_hit+sack is a transparent nflverse proxy and can miss uncharted pressures",
        "redzone":"small-denominator volatility can create extreme trailing rates",
        "schedule_strength":"raw team efficiency is opponent-sensitive and may overlap existing schedule-strength/NET domains",
        "early_season":"within-season MIN_PRIOR=3 means weeks 1-3 are intentionally not evaluated by team metrics",
        "multiple_comparisons":"seven metrics plus convergence diagnostics are exploratory; no best-looking retrospective cutpoint is promoted",
        "decision":"NO_AUTOMATIC_PROMOTION"},
      "promotion":{"decision":promotion,"rationale":rationale,
                   "next_if_material":"freeze only a predeclared candidate relationship that is cross-season stable, then evaluate prospectively or on an untouched holdout; otherwise leave Winner DNA v1 unchanged"}
    }
    audit_cols=["game_id","season","game_type","week","gameday","away_team","home_team","away_score","home_score","winner","majority_vote","unanimous7","unanimous_pick",
                "team_factor_votes_available","team_factor_home_votes","team_factor_away_votes","team_factor_majority","team_factor_max_agreement","team_factor_unanimous"]
    for m in METRICS:
        audit_cols += [f"away_{m}",f"home_{m}",f"team_vote_{m}",f"home_margin_{m}"]
    g[audit_cols].to_csv(OUT/"NFL_WINNER_DNA_TEAM_CHAOS_GAME_AUDIT_2026-09-26.csv",index=False)
    history.to_csv(OUT/"NFL_TEAM_PREGAME_METRIC_HISTORY_2021_2025.csv",index=False)
    (OUT/"NFL_WINNER_DNA_TEAM_CHAOS_GATE_2026-09-26.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    md=["# ALPHANFL WINNER DNA — TEAM CHAOS-SEPARATION GATE","",f"Status: **{report['status']}**","","## Control",
        f"Reconstruction: {recon['status']}","Seven-domain frozen reference and rejected QB challenger were not mutated.","",
        "## Independent metrics"]
    for m,v in metrics.items():
        o=v["overall"]; md.append(f"- {v['label']}: N={o['n']} wins={o['wins']} accuracy={o['accuracy']}; cross-season stable={v['stability']['survives_across_seasons']}")
    md += ["","## Multi-factor convergence",json.dumps(conv,indent=2),"","## Winner DNA unanimous chaos separation",json.dumps(ud,indent=2),
           "","## Cross-season stable individual metrics",json.dumps(stable_individual),"","## Cross-season stable unanimous separators",json.dumps(stable_sep),
           "","## CCA15",json.dumps(report["cca15"],indent=2),"","## Defense Red Team",json.dumps(report["defense_red_team"],indent=2),
           "","## Promotion",json.dumps(report["promotion"],indent=2)]
    (OUT/"NFL_WINNER_DNA_TEAM_CHAOS_GATE_2026-09-26.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print("TEAM_CHAOS_REPORT_BEGIN"); print(json.dumps(report,indent=2,default=str)); print("TEAM_CHAOS_REPORT_END")

if __name__=="__main__":
    main()
