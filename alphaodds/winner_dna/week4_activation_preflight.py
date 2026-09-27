#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.request, hashlib
from pathlib import Path
import pandas as pd

FREEZE_ID="ALPHANFL-WINNER-DNA-TWO-TIER-2026-09-26T193120-0500"
OUT=Path("alphaodds/winner_dna/outputs/week4_activation")
OUT.mkdir(parents=True,exist_ok=True)

def main():
    p=Path("week4_activation_games.csv")
    u="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    q=urllib.request.Request(u,headers={"User-Agent":"AlphaNFL-Week4Activation/1.0"})
    with urllib.request.urlopen(q,timeout=240) as r,p.open("wb") as w:
        while True:
            b=r.read(1<<20)
            if not b: break
            w.write(b)
    d=pd.read_csv(p,low_memory=False)
    d=d[(d.season==2026)&(d.game_type.astype(str).str.upper()=="REG")].copy()
    for c in ["week","home_score","away_score"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    w3=d[d.week==3].copy(); w4=d[d.week==4].copy()
    w3_final=w3.home_score.notna()&w3.away_score.notna()
    teams=set(w4.home_team.dropna())|set(w4.away_team.dropna())
    counts={}
    for t in sorted(teams):
        prior=d[(d.week<4)&((d.home_team==t)|(d.away_team==t))&(d.home_score.notna())&(d.away_score.notna())]
        counts[t]=int(len(prior))
    eligible=all(v>=3 for v in counts.values()) and len(w4)>0
    report={
      "gate":"ALPHANFL WINNER DNA — WEEK 4 FIRST-ELIGIBLE PROSPECTIVE ACTIVATION",
      "freeze_id":FREEZE_ID,
      "status":"ACTIVATE" if eligible else "HOLD_WAIT_FOR_WEEK3_FINALS",
      "schedule_receipt":{"url":u,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()},
      "week3":{"games":int(len(w3)),"final_games":int(w3_final.sum()),"remaining":int((~w3_final).sum())},
      "week4":{"games":int(len(w4)),"teams_with_three_completed_prior_games":int(sum(v>=3 for v in counts.values())),"teams_total":int(len(counts))},
      "team_prior_game_counts":counts,
      "controls":{"tier1_rule_mutation":"NONE","tier2_rule_mutation":"NONE","min_prior":3,"backfill":"PROHIBITED","activation_before_eligibility":"PROHIBITED"}
    }
    (OUT/"WEEK4_ACTIVATION_PREFLIGHT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__": main()
