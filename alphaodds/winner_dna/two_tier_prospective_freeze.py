#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib.util, json, math, urllib.request
from collections import defaultdict, deque
from pathlib import Path
import numpy as np
import pandas as pd

FREEZE_ID="ALPHANFL-WINNER-DNA-TWO-TIER-2026-09-26T193120-0500"
FREEZE_LOCAL="2026-09-26T19:31:20-05:00"
CONTROL_BLOB="8c6bec29b3d4ae2031beefee84a1002d762656f7"
MIN_CORE_BLOB="0ad416093fc58cd9a9485469ab3e3eea29f754e5"
TIER1=("elo","offense","defense","net","schedule_strength","prior_win_pct","prior_point_diff")
TIER2=("elo","offense","defense","net")
TARGET_DATES={"2026-09-27","2026-09-28"}
ROLL=6; MIN_PRIOR=3; K=20.0; CARRY=.67
OUT=Path("alphaodds/winner_dna/outputs/two_tier_freeze")
OUT.mkdir(parents=True,exist_ok=True)

def loadmod():
    p=Path("alphaodds/winner_dna/qb_first_gate.py")
    s=importlib.util.spec_from_file_location("wdna",p)
    if s is None or s.loader is None: raise RuntimeError("cannot load Winner DNA control")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def blob_sha1(path):
    data=Path(path).read_bytes()
    h=hashlib.sha1(); h.update(f"blob {len(data)}\0".encode()); h.update(data); return h.hexdigest()

def download_schedule(mod):
    p=Path("winner_dna_two_tier_games.csv")
    u="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    q=urllib.request.Request(u,headers={"User-Agent":"AlphaNFL-TwoTierFreeze/1.0"})
    with urllib.request.urlopen(q,timeout=240) as r,p.open("wb") as w:
        while True:
            b=r.read(1<<20)
            if not b: break
            w.write(b)
    d=pd.read_csv(p,low_memory=False)
    d=d[d.season.isin(range(2019,2027))].copy()
    d=d[d.game_type.astype(str).str.upper().isin(["REG","WC","DIV","CON","SB","POST"])].copy()
    d["gameday"]=pd.to_datetime(d.gameday,errors="coerce")
    d["home_team"]=d.home_team.map(mod.ct); d["away_team"]=d.away_team.map(mod.ct)
    for c in ["home_score","away_score","week"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d.sort_values(["gameday","game_id"],kind="mergesort").reset_index(drop=True)
    return d,{"url":u,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}

def prior_table(scored):
    out={}
    reg=scored[scored.game_type.astype(str).str.upper().eq("REG")]
    for season,df in reg.groupby("season"):
        a=defaultdict(lambda:{"gp":0,"w":0.,"pd":0.})
        for r in df.itertuples(index=False):
            for t,pf,pa in [(r.home_team,r.home_score,r.away_score),(r.away_team,r.away_score,r.home_score)]:
                x=a[t]; x["gp"]+=1; x["pd"]+=float(pf-pa); x["w"]+=1 if pf>pa else .5 if pf==pa else 0
        for t,x in a.items():
            out[(int(season),t)]={"win_pct":x["w"]/x["gp"],"pd_per_game":x["pd"]/x["gp"]}
    return out

def compute_votes(schedule):
    scored=schedule[schedule.home_score.notna()&schedule.away_score.notna()].copy()
    prior=prior_table(scored)
    elo=defaultdict(lambda:1500.); hist=defaultdict(lambda:deque(maxlen=ROLL)); current_season=None
    rows=[]
    for r in schedule.itertuples(index=False):
        season=int(r.season)
        if current_season is None: current_season=season
        if season!=current_season:
            for t in list(elo): elo[t]=1500.+CARRY*(elo[t]-1500.)
            hist=defaultdict(lambda:deque(maxlen=ROLL)); current_season=season
        h,a=r.home_team,r.away_team
        he,ae=float(elo[h]),float(elo[a])
        v={"elo":h if he>ae else a if ae>he else None}
        def rv(team,key):
            z=list(hist[team])
            if len(z)<MIN_PRIOR:return np.nan
            if key=="offense":return float(np.mean([x["pf"] for x in z]))
            if key=="defense":return float(np.mean([x["pa"] for x in z]))
            if key=="net":return float(np.mean([x["pf"]-x["pa"] for x in z]))
            return float(np.mean([x["opp_elo"] for x in z]))
        for key in ["offense","defense","net","schedule_strength"]:
            hv,av=rv(h,key),rv(a,key)
            v[key]=None if not np.isfinite(hv) or not np.isfinite(av) or hv==av else (h if (hv<av if key=="defense" else hv>av) else a)
        hp,ap=prior.get((season-1,h)),prior.get((season-1,a))
        for key,field in [("prior_win_pct","win_pct"),("prior_point_diff","pd_per_game")]:
            hv=hp.get(field) if hp else np.nan; av=ap.get(field) if ap else np.nan
            v[key]=None if not np.isfinite(hv) or not np.isfinite(av) or hv==av else (h if hv>av else a)
        if season==2026 and str(r.gameday.date()) in TARGET_DATES and pd.isna(r.home_score) and pd.isna(r.away_score):
            def tier(domains):
                vals=[v[x] for x in domains]
                ready=all(x is not None for x in vals)
                pick=vals[0] if ready and len(set(vals))==1 else None
                return ready,pick
            t1_ready,t1=tier(TIER1); t2_ready,t2=tier(TIER2)
            rows.append({
              "freeze_id":FREEZE_ID,"freeze_local":FREEZE_LOCAL,
              "game_id":r.game_id,"season":season,"week":int(r.week),"gameday":str(r.gameday.date()),
              "away_team":a,"home_team":h,
              **{f"vote_{k}":v[k] for k in TIER1},
              "tier1_elite_ready":t1_ready,"tier1_elite_pick":t1,
              "tier2_core_ready":t2_ready,"tier2_core_pick":t2,
              "tier_relation":"AGREE" if t1 and t2 and t1==t2 else ("TIER1_ONLY" if t1 and not t2 else ("TIER2_ONLY" if t2 and not t1 else ("DISAGREE" if t1 and t2 and t1!=t2 else "NO_SIGNAL"))),
              "graded":False,"actual_winner":None
            })
        if pd.notna(r.home_score) and pd.notna(r.away_score):
            hist[h].append({"pf":float(r.home_score),"pa":float(r.away_score),"opp_elo":ae})
            hist[a].append({"pf":float(r.away_score),"pa":float(r.home_score),"opp_elo":he})
            res=1. if r.home_score>r.away_score else .5 if r.home_score==r.away_score else 0.
            exp=1/(1+10**(-(he-ae)/400)); mult=1.
            if res!=.5:
                mov=abs(float(r.home_score-r.away_score)); adv=(he-ae)*(1 if res==1 else -1)
                mult=math.log(mov+1)*2.2/(adv*.001+2.2)
            delta=K*mult*(res-exp); elo[h]+=delta; elo[a]-=delta
    return rows

def main():
    mod=loadmod()
    actual_control=blob_sha1("alphaodds/winner_dna/qb_first_gate.py")
    actual_core=blob_sha1("alphaodds/winner_dna/minimum_core_gate.py")
    if actual_control!=CONTROL_BLOB: raise RuntimeError(f"control blob mismatch {actual_control}")
    if actual_core!=MIN_CORE_BLOB: raise RuntimeError(f"minimum-core blob mismatch {actual_core}")
    sched,receipt=download_schedule(mod)
    rows=compute_votes(sched)
    if len(rows)!=15: raise RuntimeError(f"expected 15 unplayed Week 3 Sun/Mon games, got {len(rows)}")
    elite=[x for x in rows if x["tier1_elite_pick"]]
    core=[x for x in rows if x["tier2_core_pick"]]
    manifest={
      "freeze_id":FREEZE_ID,
      "frozen_at_local":FREEZE_LOCAL,
      "status":"FROZEN_PROSPECTIVE_RESEARCH_BASELINE",
      "source_fingerprints":{"winner_dna_control_git_blob_sha1":actual_control,"minimum_core_gate_git_blob_sha1":actual_core,"schedule_receipt":receipt},
      "tiers":{
        "tier1_elite":{"domains":list(TIER1),"rule":"all seven present and unanimous","historical_authority":"frozen reference 134-42, 76.1%; not recomputed/promoted here"},
        "tier2_core":{"domains":list(TIER2),"rule":"Elo + offense + defense + NET all present and unanimous","historical_research_reference":"371-159, 70.0% in retrospective minimum-core audit; hypothesis only, not promised prospective accuracy"}
      },
      "prospective_protocol":{
        "cohort":"2026 Week 3 Sunday 2026-09-27 and Monday 2026-09-28 games unplayed at freeze",
        "rows":len(rows),"elite_signals":len(elite),"core_signals":len(core),
        "after_freeze":"append final winner and grade frozen pick only; never alter domain votes, pick, rule, or tier assignment",
        "metrics":"straight-up accuracy by tier, overlap cohort, year-to-date sample size; no profitability or EV claims without authenticated prices",
        "no_tuning_until":"predeclared review after at least 50 Tier 2 signals or end of 2026 regular season, whichever comes later",
        "wager_execution":"DISABLED"
      },
      "cca15":{"known_outcomes_in_seed_cohort":"NONE","thursday_ATL_GB_excluded":"YES_ALREADY_FINAL","post_freeze_pick_changes":"PROHIBITED","backfill":"PROHIBITED","profitability_claim":"PROHIBITED"}
    }
    (OUT/"TWO_TIER_FREEZE_MANIFEST.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (OUT/"WEEK3_PROSPECTIVE_LEDGER.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    lines=["# ALPHANFL Winner DNA - Two-Tier Prospective Freeze","",
           "Freeze ID: "+FREEZE_ID,"Freeze time: "+FREEZE_LOCAL,"",
           "## Tier 1 - Elite","All seven original domains must be present and unanimous. Frozen historical authority remains 134-42 (76.1%).","",
           "## Tier 2 - Core","Elo + Offense + Defense + NET must be present and unanimous. Retrospective research reference 371-159 (70.0%); prospective performance is unknown.","",
           "## Seed cohort",f"15 unplayed Week 3 Sunday/Monday games. Elite signals: {len(elite)}. Core signals: {len(core)}.","",
           "| Game | Elite | Core | Relation |","|---|---|---|---|"]
    for x in rows:
        lines.append(f"| {x['away_team']} @ {x['home_team']} | {x['tier1_elite_pick'] or 'PASS'} | {x['tier2_core_pick'] or 'PASS'} | {x['tier_relation']} |")
    lines += ["","## Controls","No pick may be edited after freeze. Final outcomes may only be appended for grading. No wagering or profitability claim is part of this protocol."]
    (OUT/"TWO_TIER_FREEZE_README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("TWO_TIER_FREEZE_BEGIN"); print(json.dumps(manifest,indent=2)); print("SEED_LEDGER_BEGIN"); print(json.dumps(rows,indent=2)); print("SEED_LEDGER_END")

if __name__=="__main__":
    main()
