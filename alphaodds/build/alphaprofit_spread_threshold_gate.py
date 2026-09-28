#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DYN_PATH = ROOT / "alphaprofit_dynamic_slot_c_gate.py"
spec = importlib.util.spec_from_file_location("dynamic_c", DYN_PATH)
dyn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dyn)

SEASONS = (2021, 2022, 2023, 2024)
THRESHOLDS = tuple(round(x * 0.5, 1) for x in range(1, 29))  # 0.5 through 14.0
BANDS = (
    (0.5, 2.5, "0.5_to_2.5"),
    (3.0, 4.5, "3_to_4.5"),
    (5.0, 6.5, "5_to_6.5"),
    (7.0, 9.5, "7_to_9.5"),
    (10.0, 13.5, "10_to_13.5"),
    (14.0, 99.0, "14_plus"),
)

def wilson_lower(hits, n, z=1.96):
    if n <= 0:
        return None
    p = hits / n
    denom = 1 + z*z/n
    center = p + z*z/(2*n)
    adj = z * math.sqrt((p*(1-p) + z*z/(4*n))/n)
    return (center - adj) / denom

def summarize(df):
    n = len(df)
    hits = int(df["favorite_first_td"].sum())
    no_td = int(df["no_td"].sum())
    td_games = n - no_td
    td_hits = hits
    season_rates = {}
    for s in SEASONS:
        d = df[df["season"].eq(s)]
        season_rates[str(s)] = None if len(d)==0 else float(d["favorite_first_td"].mean())
    valid_season_rates = [x for x in season_rates.values() if x is not None]
    return {
        "games": int(n),
        "favorite_first_td_hits": hits,
        "no_td_games": no_td,
        "all_game_hit_rate": None if n==0 else float(hits/n),
        "td_game_hit_rate": None if td_games==0 else float(td_hits/td_games),
        "wilson_95_lower": wilson_lower(hits, n),
        "season_rates": season_rates,
        "min_season_rate": None if not valid_season_rates else float(min(valid_season_rates)),
        "max_season_rate": None if not valid_season_rates else float(max(valid_season_rates)),
        "season_range": None if not valid_season_rates else float(max(valid_season_rates)-min(valid_season_rates)),
    }

def main():
    root = Path(os.environ.get("ALPHAPROFIT_SPREAD_OUT", "alphaprofit_spread_runtime"))
    raw, out = root/"raw", root/"out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = dyn.materialize(raw)
    pbp, roster, schedule = dyn.load_inputs(raw)
    first_td = dyn.first_td_by_game(pbp)

    sched = schedule[
        schedule["season"].isin(SEASONS)
        & schedule["game_type"].astype(str).str.upper().eq("REG")
        & schedule["spread_line"].notna()
        & schedule["spread_line"].ne(0)
    ].copy()

    rows = []
    for g in sched.itertuples(index=False):
        spread = float(g.spread_line)
        favorite = str(g.home_team) if spread > 0 else str(g.away_team)
        actual = first_td.get(str(g.game_id), {})
        td_team = actual.get("team")
        rows.append({
            "game_id": str(g.game_id),
            "season": int(g.season),
            "week": int(g.week),
            "abs_spread": abs(spread),
            "favorite": favorite,
            "first_td_team": td_team,
            "favorite_first_td": bool(td_team == favorite),
            "no_td": td_team is None,
        })
    df = pd.DataFrame(rows)

    threshold_report = {}
    threshold_rows = []
    for t in THRESHOLDS:
        d = df[df["abs_spread"].ge(t)].copy()
        s = summarize(d)
        threshold_report[f"{t:.1f}_plus"] = s
        threshold_rows.append({"threshold":t, **{k:v for k,v in s.items() if k!="season_rates"}})

    band_report = {}
    for lo, hi, name in BANDS:
        if hi >= 99:
            d = df[df["abs_spread"].ge(lo)]
        else:
            d = df[df["abs_spread"].between(lo, hi)]
        band_report[name] = summarize(d)

    # Predeclared robustness views, not optimization:
    # - highest Wilson lower bound among thresholds with >=100 games
    # - highest minimum-season rate among thresholds with >=100 games
    eligible = [r for r in threshold_rows if r["games"] >= 100]
    best_wilson = max(eligible, key=lambda r:(r["wilson_95_lower"], -r["threshold"])) if eligible else None
    best_floor = max(eligible, key=lambda r:(r["min_season_rate"], -r["threshold"])) if eligible else None

    report = {
        "gate":"ALPHAPROFIT SPREAD-THRESHOLD ROBUSTNESS GATE",
        "status":"RETROSPECTIVE_HYPOTHESIS_GENERATION_ONLY",
        "baseline_7_plus":"PRESERVED_NOT_RETROACTIVELY_CHANGED",
        "tested_thresholds":"0.5-point increments from 0.5 through 14.0",
        "seasons":list(SEASONS),
        "thresholds":threshold_report,
        "bands":band_report,
        "robustness_views_min_100_games":{
            "highest_wilson_lower_bound":best_wilson,
            "highest_minimum_single_season_rate":best_floor,
        },
        "controls":{
            "2025_access":"PROHIBITED_NOT_READ",
            "threshold_promotion_from_this_test":"PROHIBITED",
            "all_thresholds_reported":"YES_NO_CHERRY_PICKING",
            "spread_source":"nflverse schedule source already source-locked",
            "first_td_source":"source-locked nflverse PBP",
        },
        "next_action":"If a threshold plateau/challenger appears, freeze it prospectively alongside the original 7+ baseline rather than replacing 7+ retrospectively.",
        "wager_execution":"DISABLED",
    }

    pd.DataFrame(threshold_rows).to_csv(out/"spread_threshold_rows.csv", index=False)
    df.to_csv(out/"spread_threshold_game_rows.csv", index=False)
    (out/"SPREAD_THRESHOLD_GATE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"SPREAD_THRESHOLD_GATE.md").write_text(
        "# ALPHAPROFIT SPREAD-THRESHOLD ROBUSTNESS GATE\n\n"
        f"Baseline 7+: {threshold_report['7.0_plus']}\n\n"
        f"Highest Wilson lower bound (>=100 games): {best_wilson}\n\n"
        f"Highest season-floor (>=100 games): {best_floor}\n\n"
        "Retrospective hypothesis generation only. No threshold promotion from this gate.\n",
        encoding="utf-8"
    )
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")

    print("ALPHAPROFIT_SPREAD_THRESHOLD_GATE_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHAPROFIT_SPREAD_THRESHOLD_GATE_END")

if __name__ == "__main__":
    main()
