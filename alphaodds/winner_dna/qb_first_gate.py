#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math, re, urllib.request
from collections import defaultdict, deque
from pathlib import Path
import numpy as np
import pandas as pd

OUTDIR=Path("alphaodds/winner_dna/outputs")
RAW=Path("winner_dna_qb_runtime/raw")
OUTDIR.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
TARGET=tuple(range(2021,2026)); WARMUP=(2019,2020); ROLL=6; MIN_PRIOR=3; K=20.0; CARRY=.67
STAT_SHA={
2021:"41915fb49238902ad1f129ebf0405b11a1e710454ae0fe8f7b3e4f9145875f48",
2022:"ad426c3fe5bf1cc30c3f137fdfe96d054e19d400879ee4413129da49fa7b54be",
2023:"f19cb71a5de0dce7fd09376026237c9ee9d5a93fe13815a2ea3ec2d37204cb17",
2024:"3ddc45a84f759aa348ce465ae001752c530575455717657cdfe1f8abfcdb4759",
2025:"e5e0615b3d96a3eaebfaee91e55afb4a4e7fe0caf057454177bcd7d6ad4bcfc2"}
REF={"decided_games":1420,
"domain_accuracy":{"elo":.636,"net":.624,"offense":.616,"prior_win_pct":.596,"prior_point_diff":.589,"defense":.565,"schedule_strength":.505,"majority":.632},
"unanimous":{"n":176,"wins":134,"accuracy":134/176},
"unanimous_by_season":{"2021":{"n":42,"wins":31},"2022":{"n":30,"wins":20},"2023":{"n":35,"wins":28},"2024":{"n":32,"wins":27},"2025":{"n":37,"wins":28}}}
URL={"schedules":"https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
"qbr":"https://raw.githubusercontent.com/nflverse/espnscrapeR-data/master/data/qbr-nfl-weekly.csv"}
for y in TARGET: URL[f"stats_{y}"]=f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv"
ALIASES={"LAR":"LA","STL":"LA","WSH":"WAS","OAK":"LV","SD":"LAC","JAC":"JAX"}

def ct(x):
    if pd.isna(x): return None
    s=str(x).strip().upper(); return ALIASES.get(s,s)
def nn(x):
    if pd.isna(x): return None
    s=re.sub(r"\b(jr|sr|ii|iii|iv)\b","",str(x).lower())
    return re.sub(r"[^a-z0-9]","",s)
def dl(url,p):
    req=urllib.request.Request(url,headers={"User-Agent":"AlphaOdds-WinnerDNA-QBFirst/1.0"})
    with urllib.request.urlopen(req,timeout=240) as r,p.open("wb") as w:
        while True:
            b=r.read(1<<20)
            if not b: break
            w.write(b)
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()
def materialize():
    out=[]
    for k,u in URL.items():
        name="schedules.csv" if k=="schedules" else ("qbr-nfl-weekly.csv" if k=="qbr" else f"stats_player_week_{k.split('_')[1]}.csv")
        p=RAW/name; print("DOWNLOAD",k,u,flush=True); dl(u,p)
        r={"family":k,"url":u,"path":str(p),"size":p.stat().st_size,"sha256":sha(p),"status":"PASS"}
        if k.startswith("stats_"):
            y=int(k.split("_")[1]); r["expected_sha256"]=STAT_SHA[y]; r["sha_match"]=r["sha256"]==STAT_SHA[y]
            if not r["sha_match"]: r["status"]="FAIL_SHA_MISMATCH"
        out.append(r)
    if any(r["status"]!="PASS" for r in out if r["family"].startswith("stats_")): raise RuntimeError("weekly stats receipt failure")
    return out
def schedules():
    d=pd.read_csv(RAW/"schedules.csv",low_memory=False)
    d=d[d.season.isin(range(min(WARMUP),max(TARGET)+1))].copy()
    d=d[d.game_type.astype(str).str.upper().isin(["REG","WC","DIV","CON","SB","POST"])].copy()
    d["gameday"]=pd.to_datetime(d.gameday,errors="coerce")
    d["home_team"]=d.home_team.map(ct); d["away_team"]=d.away_team.map(ct)
    for c in ["home_score","away_score","week"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    return d[d.home_score.notna()&d.away_score.notna()].sort_values(["gameday","game_id"],kind="mergesort").reset_index(drop=True)
def prior_table(s):
    out={}; reg=s[s.game_type.astype(str).str.upper().eq("REG")]
    for season,df in reg.groupby("season"):
        a=defaultdict(lambda:{"gp":0,"w":0.,"pd":0.})
        for r in df.itertuples(index=False):
            for t,pf,pa in [(r.home_team,r.home_score,r.away_score),(r.away_team,r.away_score,r.home_score)]:
                x=a[t]; x["gp"]+=1; x["pd"]+=pf-pa; x["w"]+=1 if pf>pa else .5 if pf==pa else 0
        for t,x in a.items(): out[(int(season),t)]={"win_pct":x["w"]/x["gp"],"pd_per_game":x["pd"]/x["gp"]}
    return out
def control(s):
    prior=prior_table(s); elo=defaultdict(lambda:1500.); hist=defaultdict(lambda:deque(maxlen=ROLL)); cs=None; rows=[]
    for r in s.itertuples(index=False):
        y=int(r.season)
        if cs is None: cs=y
        if y!=cs:
            for t in list(elo): elo[t]=1500.+CARRY*(elo[t]-1500.)
            hist=defaultdict(lambda:deque(maxlen=ROLL)); cs=y
        h,a=r.home_team,r.away_team; he,ae=float(elo[h]),float(elo[a]); v={"elo":h if he>ae else a if ae>he else None}
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
        avail=[x for x in v.values() if x is not None]; hc,ac=avail.count(h),avail.count(a); maj=h if hc>ac else a if ac>hc else None
        un=len(avail)==7 and len(set(avail))==1; win=h if r.home_score>r.away_score else a if r.away_score>r.home_score else None
        row={"game_id":r.game_id,"season":y,"game_type":r.game_type,"week":int(r.week),"gameday":str(r.gameday.date()),"away_team":a,"home_team":h,
        "away_score":r.away_score,"home_score":r.home_score,"winner":win,"away_qb_id":getattr(r,"away_qb_id",None),"home_qb_id":getattr(r,"home_qb_id",None),
        "away_qb_name":getattr(r,"away_qb_name",None),"home_qb_name":getattr(r,"home_qb_name",None),"majority_vote":maj,"unanimous7":un,"unanimous_pick":avail[0] if un else None,"votes_available":len(avail)}
        for k,x in v.items(): row[f"vote_{k}"]=x
        rows.append(row)
        hist[h].append({"pf":r.home_score,"pa":r.away_score,"opp_elo":ae}); hist[a].append({"pf":r.away_score,"pa":r.home_score,"opp_elo":he})
        res=1. if r.home_score>r.away_score else .5 if r.home_score==r.away_score else 0.; exp=1/(1+10**(-(he-ae)/400)); mult=1.
        if res!=.5:
            mov=abs(float(r.home_score-r.away_score)); adv=(he-ae)*(1 if res==1 else -1); mult=math.log(mov+1)*2.2/(adv*.001+2.2)
        d=K*mult*(res-exp); elo[h]+=d; elo[a]-=d
    return pd.DataFrame(rows)
def qb_stats():
    fs=[]
    for y in TARGET:
        d=pd.read_csv(RAW/f"stats_player_week_{y}.csv",low_memory=False)
        if "season" not in d.columns:d["season"]=y
        d=d[d.position.astype(str).str.upper().eq("QB")].copy()
        if "season_type" in d.columns:d=d[d.season_type.astype(str).str.upper().isin(["REG","POST"])].copy()
        tc="recent_team" if "recent_team" in d.columns else "team"; d["team"]=d[tc].map(ct)
        d["season"]=pd.to_numeric(d.season,errors="coerce"); d["week"]=pd.to_numeric(d.week,errors="coerce")
        for c in ["attempts","sacks","passing_epa","passing_yards","completions","interceptions"]:
            if c not in d.columns:d[c]=np.nan
            d[c]=pd.to_numeric(d[c],errors="coerce")
        if d.passing_epa.notna().sum()==0:raise RuntimeError(f"passing_epa missing {y}")
        db=d.attempts.fillna(0)+d.sacks.fillna(0); d["epa_per_db"]=np.where(db>0,d.passing_epa/db,np.nan)
        d["completion_rate"]=np.where(d.attempts>0,d.completions/d.attempts,np.nan); d["ypa"]=np.where(d.attempts>0,d.passing_yards/d.attempts,np.nan)
        d["int_rate"]=np.where(d.attempts>0,d.interceptions/d.attempts,np.nan)
        fs.append(d[["season","week","player_id","player_display_name","team","epa_per_db","completion_rate","ypa","int_rate"]])
    q=pd.concat(fs,ignore_index=True); q["player_id"]=q.player_id.astype("string"); q["name_norm"]=q.player_display_name.map(nn)
    q=q.sort_values(["player_id","season","week"],kind="mergesort").reset_index(drop=True)
    for m in ["epa_per_db","completion_rate","ypa","int_rate"]:
        lag=q.groupby(["player_id","season"],sort=False)[m].shift(1)
        q[f"roll6_{m}"]=lag.groupby([q.player_id,q.season],sort=False).transform(lambda x:x.rolling(ROLL,min_periods=MIN_PRIOR).mean())
    q["prior_qb_games"]=q.groupby(["player_id","season"],sort=False).cumcount()
    return q
def qbr_stats():
    q=pd.read_csv(RAW/"qbr-nfl-weekly.csv",low_memory=False); q["season"]=pd.to_numeric(q.season,errors="coerce")
    wc="week_num" if "week_num" in q.columns else ("game_week" if "game_week" in q.columns else ("week" if "week" in q.columns else None))
    if wc is None:raise RuntimeError("QBR week column missing")
    q["week_num"]=pd.to_numeric(q[wc],errors="coerce"); q=q[q.season.isin(TARGET)].copy(); q["team"]=q.team_abb.map(ct); q["qbr_total"]=pd.to_numeric(q.qbr_total,errors="coerce")
    q["name_norm"]=q.name_display.map(nn); q=q.sort_values(["player_id","season","week_num"],kind="mergesort")
    lag=q.groupby(["player_id","season"],sort=False).qbr_total.shift(1)
    q["roll6_qbr"]=lag.groupby([q.player_id,q.season],sort=False).transform(lambda x:x.rolling(ROLL,min_periods=MIN_PRIOR).mean())
    q["prior_qbr_games"]=q.groupby(["player_id","season"],sort=False).cumcount()
    return q[["season","week_num","team","name_norm","roll6_qbr","prior_qbr_games"]].rename(columns={"week_num":"week"})
def continuity(g):
    h=defaultdict(list); out=[]
    for r in g.sort_values(["season","gameday","game_id"]).itertuples(index=False):
        z={"game_id":r.game_id}
        for side in ["away","home"]:
            team=getattr(r,f"{side}_team"); qid=getattr(r,f"{side}_qb_id"); qn=getattr(r,f"{side}_qb_name"); ident=str(qid) if pd.notna(qid) and str(qid).strip() not in {"","nan","None"} else nn(qn)
            a=h[(int(r.season),team)]; recent=a[-ROLL:]
            if ident and len(recent)>=MIN_PRIOR:
                share=sum(x==ident for x in recent)/len(recent); streak=0
                for x in reversed(a):
                    if x==ident:streak+=1
                    else:break
            else:share=streak=np.nan
            z[f"{side}_qb_start_share6"]=share; z[f"{side}_qb_start_streak"]=streak
        out.append(z)
        for side in ["away","home"]:
            team=getattr(r,f"{side}_team"); qid=getattr(r,f"{side}_qb_id"); qn=getattr(r,f"{side}_qb_name"); ident=str(qid) if pd.notna(qid) and str(qid).strip() not in {"","nan","None"} else nn(qn)
            h[(int(r.season),team)].append(ident)
    return pd.DataFrame(out)
def sv(r,a,h,high=True):
    av,hv=r.get(a),r.get(h)
    if not(pd.notna(av) and pd.notna(hv)) or float(av)==float(hv):return None
    return r.home_team if (float(hv)>float(av) if high else float(hv)<float(av)) else r.away_team
def attach(c,qs,qbr):
    t=c[c.season.isin(TARGET)].copy(); cols=["season","week","player_id","name_norm","team","roll6_epa_per_db","roll6_completion_rate","roll6_ypa","roll6_int_rate","prior_qb_games"]
    x=qs[cols].copy(); x["player_id"]=x.player_id.astype("string"); byi=x.drop_duplicates(["season","week","player_id"],keep="last"); byn=x.drop_duplicates(["season","week","team","name_norm"],keep="last")
    qbri=qbr.drop_duplicates(["season","week","team","name_norm"],keep="last")
    for side in ["away","home"]:
        t[f"{side}_qb_id_str"]=t[f"{side}_qb_id"].astype("string"); t[f"{side}_qb_name_norm"]=t[f"{side}_qb_name"].map(nn)
        m=t[["game_id","season","week",f"{side}_team",f"{side}_qb_id_str",f"{side}_qb_name_norm"]].merge(byi,left_on=["season","week",f"{side}_qb_id_str"],right_on=["season","week","player_id"],how="left")
        miss=m.roll6_epa_per_db.isna()
        if miss.any():
            fb=t.loc[miss.values,["game_id","season","week",f"{side}_team",f"{side}_qb_name_norm"]].merge(byn,left_on=["season","week",f"{side}_team",f"{side}_qb_name_norm"],right_on=["season","week","team","name_norm"],how="left")
            for k in ["roll6_epa_per_db","roll6_completion_rate","roll6_ypa","roll6_int_rate","prior_qb_games"]:m.loc[miss,k]=fb[k].to_numpy()
        for k in ["roll6_epa_per_db","roll6_completion_rate","roll6_ypa","roll6_int_rate","prior_qb_games"]:t[f"{side}_{k}"]=m[k].to_numpy()
        m=t[["game_id","season","week",f"{side}_team",f"{side}_qb_name_norm"]].merge(qbri,left_on=["season","week",f"{side}_team",f"{side}_qb_name_norm"],right_on=["season","week","team","name_norm"],how="left")
        t[f"{side}_roll6_qbr"]=m.roll6_qbr.to_numpy()
    t=t.merge(continuity(t),on="game_id",how="left",validate="1:1"); z=[]
    for _,r in t.iterrows():
        e=sv(r,"away_roll6_epa_per_db","home_roll6_epa_per_db"); q=sv(r,"away_roll6_qbr","home_roll6_qbr"); cv=sv(r,"away_qb_start_share6","home_qb_start_share6")
        if cv is None and pd.notna(r.away_qb_start_streak) and pd.notna(r.home_qb_start_streak) and r.away_qb_start_streak!=r.home_qb_start_streak:cv=r.home_team if r.home_qb_start_streak>r.away_qb_start_streak else r.away_team
        a=[x for x in [e,q,cv] if x is not None]; comp=None
        if len(a)>=2:
            hc,ac=a.count(r.home_team),a.count(r.away_team); comp=r.home_team if hc>ac else r.away_team if ac>hc else None
        z.append((e,q,cv,comp,len(a)))
    return pd.concat([t,pd.DataFrame(z,columns=["qb_vote_epa","qb_vote_qbr","qb_vote_continuity","qb_composite_vote","qb_votes_available"],index=t.index)],axis=1)
def ac(d,col):
    x=d[d.winner.notna()&d[col].notna()]; return {"n":int(len(x)),"wins":int((x[col]==x.winner).sum()),"accuracy":float((x[col]==x.winner).mean()) if len(x) else None}
def control_summary(c):
    t=c[c.season.isin(TARGET)&c.winner.notna()].copy(); m={"decided_games":int(len(t))}
    for k in ["elo","offense","defense","net","schedule_strength","prior_win_pct","prior_point_diff"]:m[k]=ac(t,f"vote_{k}")
    m["majority"]=ac(t,"majority_vote"); u=t[t.unanimous7]; m["unanimous"]={"n":int(len(u)),"wins":int((u.unanimous_pick==u.winner).sum()),"accuracy":float((u.unanimous_pick==u.winner).mean()) if len(u) else None}
    m["unanimous_by_season"]={str(int(s)):{"n":int(len(d)),"wins":int((d.unanimous_pick==d.winner).sum()),"accuracy":float((d.unanimous_pick==d.winner).mean())} for s,d in u.groupby("season")}
    return m
def recon(m):
    d={"decided_games":m["decided_games"]-REF["decided_games"],"unanimous_n":m["unanimous"]["n"]-REF["unanimous"]["n"],"unanimous_wins":m["unanimous"]["wins"]-REF["unanimous"]["wins"]}
    for k,v in REF["domain_accuracy"].items():d[k]=m[k]["accuracy"]-v
    shape=abs(d["decided_games"])<=2 and abs(d["unanimous_n"])<=10 and abs(d["unanimous_wins"])<=10; accok=all(abs(d[k])<=.02 for k in REF["domain_accuracy"])
    return {"status":"PASS_RECONSTRUCTION_CLOSE" if shape and accok else "HOLD_RECONSTRUCTION_NOT_EXACT","differences":d,"shape_pass":shape,"accuracy_pass":accok}
def qb_summary(g):
    d=g[g.winner.notna()].copy(); out={"standalone":{c:ac(d,c) for c in ["qb_vote_epa","qb_vote_qbr","qb_vote_continuity","qb_composite_vote"]},"by_season":{}}
    for s,x in d.groupby("season"):out["by_season"][str(int(s))]={c:ac(x,c) for c in ["qb_vote_epa","qb_vote_qbr","qb_vote_continuity","qb_composite_vote"]}
    u=d[d.unanimous7].copy(); u["rel"]=np.where(u.qb_composite_vote.isna(),"NEUTRAL",np.where(u.qb_composite_vote==u.unanimous_pick,"CONFIRM","WARNING"))
    out["unanimous_relation"]={r:{"n":int(len(x)),"control_wins":int((x.unanimous_pick==x.winner).sum()),"control_accuracy":float((x.unanimous_pick==x.winner).mean())} for r,x in u.groupby("rel")}
    loss=u[u.unanimous_pick!=u.winner]; win=u[u.unanimous_pick==u.winner]
    out["false_confidence_separation"]={"unanimous_losses_n":int(len(loss)),"losses_with_qb_warning":int((loss.qb_composite_vote.notna()&(loss.qb_composite_vote!=loss.unanimous_pick)).sum()),
    "loss_warning_capture_rate":float((loss.qb_composite_vote.notna()&(loss.qb_composite_vote!=loss.unanimous_pick)).mean()) if len(loss) else None,
    "unanimous_wins_n":int(len(win)),"wins_with_false_qb_warning":int((win.qb_composite_vote.notna()&(win.qb_composite_vote!=win.unanimous_pick)).sum()),
    "win_false_warning_rate":float((win.qb_composite_vote.notna()&(win.qb_composite_vote!=win.unanimous_pick)).mean()) if len(win) else None}
    for base in ["vote_elo","majority_vote"]:
        x=d[d.qb_composite_vote.notna()&d[base].notna()&(d.qb_composite_vote!=d[base])]; miss=d[d[base].notna()&(d[base]!=d.winner)]
        out[f"qb_opposes_{base}"]={"n":int(len(x)),"qb_side_wins":int((x.qb_composite_vote==x.winner).sum()),"qb_side_accuracy":float((x.qb_composite_vote==x.winner).mean()) if len(x) else None,
        "base_misses_n":int(len(miss)),"base_misses_with_qb_opposition":int((miss.qb_composite_vote.notna()&(miss.qb_composite_vote!=miss[base])).sum()),
        "miss_capture_rate":float((miss.qb_composite_vote.notna()&(miss.qb_composite_vote!=miss[base])).mean()) if len(miss) else None}
    u["conservative_pick"]=np.where(u.qb_composite_vote.notna()&(u.qb_composite_vote!=u.unanimous_pick),None,u.unanimous_pick)
    out["unanimous_with_qb_warning_pass"]=ac(u,"conservative_pick"); out["unanimous_with_qb_warning_pass"]["retained_share"]=float(u.conservative_pick.notna().mean()) if len(u) else None
    return out
def main():
    receipts=materialize(); s=schedules(); c=control(s); cm=control_summary(c); rc=recon(cm); qs=qb_stats(); qbr=qbr_stats(); g=attach(c,qs,qbr); qbs=qb_summary(g); qyears=sorted(int(x) for x in qbr.season.dropna().unique())
    report={"gate":"ALPHANFL WINNER DNA — QB-FIRST ADVANCED ENRICHMENT & CHAOS-SEPARATION","as_of":"2026-09-26 America/Chicago",
    "status":"PASS_DIAGNOSTIC_QB_LAYER_NO_PROMOTION" if rc["status"].startswith("PASS") else "PARTIAL_HOLD_CONTROL_RECONSTRUCTION_NOT_EXACT",
    "frozen_control_reference":REF,"reconstructed_control":cm,"reconstruction_check":rc,
    "qb_method":{"rolling_window":ROLL,"minimum_prior_games":MIN_PRIOR,"same_week_leakage":"PROHIBITED_ALL_QB_PERFORMANCE_FEATURES_SHIFTED_BEFORE_ROLLING",
    "epa_metric":"passing_epa / (attempts + sacks), trailing-six mean by starting QB within season","qbr_metric":"ESPN QBR trailing-six mean by named starting QB; partial source coverage disclosed",
    "continuity":"current starter share of prior six team starts within season; current start streak breaks share ties","composite":"at least two available votes; 2/2 agreement or 2-of-3 majority","qbr_source_years_present":qyears},
    "qb_results":qbs,"source_receipts":receipts,"cca15":{"frozen_seven_domain_control_changed":"NO","post_outcome_threshold_tuning":"NONE","same_week_leakage":"PASS_BY_SHIFT1_CONSTRUCTION",
    "qbr_2024_2025_gap":"DISCLOSED_PARTIAL_COVERAGE" if max(qyears,default=0)<2025 else "NONE","profitability_claim":"PROHIBITED","wager_execution":"DISABLED"},"promotion":"NO_WINNER_DNA_V2_PROMOTION_FROM_THIS_GATE"}
    keep=[x for x in g.columns if x.startswith("vote_") or x.startswith("qb_") or x in ["game_id","season","game_type","week","gameday","away_team","home_team","away_score","home_score","winner","away_qb_id","home_qb_id","away_qb_name","home_qb_name","majority_vote","unanimous7","unanimous_pick","votes_available"] or x.startswith("away_roll6") or x.startswith("home_roll6") or x.startswith("away_qb_start") or x.startswith("home_qb_start")]
    g[keep].to_csv(OUTDIR/"NFL_WINNER_DNA_QB_FIRST_GAME_AUDIT_2026-09-26.csv",index=False)
    (OUTDIR/"NFL_WINNER_DNA_QB_FIRST_GATE_2026-09-26.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    md=["# ALPHANFL WINNER DNA — QB-FIRST ADVANCED ENRICHMENT & CHAOS-SEPARATION","",f"Status: **{report['status']}**","","## Frozen control","Original seven-domain control remains unchanged.",f"Reconstruction: {rc['status']}","","## QB layer",
    f"EPA: {qbs['standalone']['qb_vote_epa']}",f"QBR: {qbs['standalone']['qb_vote_qbr']}",f"Continuity: {qbs['standalone']['qb_vote_continuity']}",f"Composite: {qbs['standalone']['qb_composite_vote']}","",
    "## Unanimous-control separation",json.dumps(qbs["unanimous_relation"],indent=2),"",json.dumps(qbs["false_confidence_separation"],indent=2),"","## CCA15",json.dumps(report["cca15"],indent=2),"","No profitability claim. No wager placed or transmitted."]
    (OUTDIR/"NFL_WINNER_DNA_QB_FIRST_GATE_2026-09-26.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print("WINNER_DNA_QB_FIRST_REPORT_BEGIN"); print(json.dumps(report,indent=2,default=str)); print("WINNER_DNA_QB_FIRST_REPORT_END")
if __name__=="__main__": main()
