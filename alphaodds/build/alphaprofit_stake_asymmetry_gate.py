#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent

def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

dyn = load_module("dynamic_c", "alphaprofit_dynamic_slot_c_gate.py")
price = load_module("price_gate", "alphaprofit_first_td_price_gate.py")
matchup = load_module("matchup_gate", "alphaprofit_matchup_style_gate.py")

FIXED_ALLOCATIONS = {
    "BASE_45_45_10": {"A":45.0,"B":45.0,"C":10.0},
    "C_HEAVY_35_35_30": {"A":35.0,"B":35.0,"C":30.0},
    "C_MAX_25_25_50": {"A":25.0,"B":25.0,"C":50.0},
}
TOTAL = 100.0


def stake_pnl(row, stakes, price_prefix="best"):
    hit = "A" if row["A_hit"] else ("B" if row["B_hit"] else ("C" if row["C_hit"] else None))
    if hit is None:
        return -TOTAL
    p = row[f"{hit}_{price_prefix}_price"]
    if pd.isna(p):
        return np.nan
    gross = stakes[hit] * price.american_to_decimal(float(p))
    return gross - TOTAL


def equalized_gross_stakes(row, price_prefix="best"):
    ds = {s: price.american_to_decimal(float(row[f"{s}_{price_prefix}_price"])) for s in ["A","B","C"]}
    inv = sum(1.0/d for d in ds.values())
    gross_target = TOTAL / inv
    stakes = {s:gross_target/d for s,d in ds.items()}
    return stakes


def maximin_grid_stakes(row, price_prefix="best"):
    ds = {s: price.american_to_decimal(float(row[f"{s}_{price_prefix}_price"])) for s in ["A","B","C"]}
    best = None
    # Predeclared 5-unit grid, minimum 10 per slot, total 100.
    for a in range(10, 85, 5):
        for b in range(10, 85, 5):
            c = 100 - a - b
            if c < 10 or c > 80 or c % 5:
                continue
            stakes = {"A":float(a),"B":float(b),"C":float(c)}
            hit_nets = {s:stakes[s]*ds[s]-TOTAL for s in ["A","B","C"]}
            score = min(hit_nets.values())
            tie = -max(stakes.values())
            cand = (score, tie, stakes, hit_nets)
            if best is None or cand[:2] > best[:2]:
                best = cand
    return best[2], best[3]


def matchup_tilt_stakes(row):
    slot_route = {
        "A":"GROUND",
        "B":"WRTE_REC",
        "C":"RB_REC" if row["C_lane"] == "RB_RECEIVING" else "WRTE_REC",
    }
    top = row["matchup_route"]
    weights = {s:(2.0 if r == top else 1.0) for s,r in slot_route.items()}
    denom = sum(weights.values())
    return {s:TOTAL*weights[s]/denom for s in weights}


def summarize_strategy(df, name, stake_builder, prefix="best"):
    rows = []
    for _, r in df.iterrows():
        stakes = stake_builder(r)
        pnl = stake_pnl(r, stakes, prefix)
        rows.append({
            "game_id":r["game_id"],"strategy":name,"pnl":float(pnl),
            "stake_A":stakes["A"],"stake_B":stakes["B"],"stake_C":stakes["C"],
            "hit":bool(r["any_hit"]),
        })
    x = pd.DataFrame(rows)
    return x, {
        "games":int(len(x)),
        "net_pnl":float(x["pnl"].sum()),
        "roi":float(x["pnl"].sum()/(len(x)*TOTAL)) if len(x) else None,
        "hits":int(x["hit"].sum()),
        "mean_pnl_per_game":float(x["pnl"].mean()) if len(x) else None,
        "worst_game_pnl":float(x["pnl"].min()) if len(x) else None,
        "best_game_pnl":float(x["pnl"].max()) if len(x) else None,
    }


def main():
    root = Path(os.environ.get("ALPHAPROFIT_STAKE_OUT","alphaprofit_stake_runtime"))
    raw, out = root/"raw", root/"out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = dyn.materialize(raw)
    selections = price.reconstruct_2024(raw)

    pbp, roster, schedule = dyn.load_inputs(raw)
    roster_idx = dyn.build_roster_index(roster)
    route_counts = matchup.build_game_route_counts(pbp, roster_idx)
    schedule = schedule.sort_values(["gameday","gametime","game_id"], kind="mergesort").reset_index(drop=True)

    # Build strictly pregame matchup context for all games in chronological order.
    history = defaultdict(list)
    matchup_context = {}
    for g in schedule.itertuples(index=False):
        gid, season = str(g.game_id), int(g.season)
        home, away = str(g.home_team), str(g.away_team)
        if season == 2024:
            # Context will only be used for already-frozen 7+ favorite selections.
            sel = selections[selections["game_id"].eq(gid)]
            if not sel.empty:
                fav = str(sel.iloc[0]["favorite"])
                opp = away if fav == home else home
                fh = history[fav][-8:]
                oh = history[opp][-8:]
                if len(fh) >= 8 and len(oh) >= 8:
                    off_counts = matchup.aggregate_route_counts(fh, fav, route_counts)
                    opp_allowed = defaultdict(int)
                    for pgid in oh:
                        sg = schedule[schedule["game_id"].astype(str).eq(str(pgid))]
                        if sg.empty: continue
                        pg = sg.iloc[0]
                        ph, pa = str(pg["home_team"]), str(pg["away_team"])
                        prior_off = pa if opp == ph else ph
                        for route,n in route_counts.get((str(pgid),prior_off),{}).items():
                            opp_allowed[route] += int(n)
                    off = matchup.smooth_shares(off_counts)
                    deff = matchup.smooth_shares(opp_allowed)
                    compat = {r:off[r]*deff[r] for r in matchup.ROUTES}
                    top = max(matchup.ROUTES, key=lambda r:(compat[r],r))
                    matchup_context[gid] = {
                        "matchup_route":top,
                        "style_alignment":max(matchup.ROUTES,key=lambda r:(off[r],r)) == max(matchup.ROUTES,key=lambda r:(deff[r],r)),
                        "compat_ground":compat["GROUND"],
                        "compat_wrte_rec":compat["WRTE_REC"],
                        "compat_rb_rec":compat["RB_REC"],
                    }
        history[home].append(gid); history[away].append(gid)

    # Recover prices exactly as prior price gate.
    candidates = selections[selections["gameday"].isin(price.ARCHIVE_DATES)].copy()
    rows = []
    for r in candidates.itertuples(index=False):
        board, rec = price.fetch_board(r.gameday, r.home_team, r.away_team)
        if board is None or not rec.get("commit_pre_kickoff"):
            continue
        base = r._asdict()
        complete = True
        for slot in ["A","B","C"]:
            prices = price.extract_prices(board, base[f"{slot}_name"]) if base.get(f"{slot}_name") else []
            if not prices:
                complete = False; break
            base[f"{slot}_best_price"] = prices[0]["price"]
            dk = next((x for x in prices if x["book"]=="draftkings"),None)
            base[f"{slot}_dk_price"] = dk["price"] if dk else np.nan
        if not complete:
            continue
        base.update(matchup_context.get(base["game_id"], {"matchup_route":None,"style_alignment":None}))
        rows.append(base)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No complete matched-price rows")

    strategy_rows = []
    summaries = {}

    for name, stakes in FIXED_ALLOCATIONS.items():
        x,s = summarize_strategy(df,name,lambda r,st=stakes:dict(st),"best")
        strategy_rows.append(x); summaries[name]=s

    x,s = summarize_strategy(df,"EQUALIZED_GROSS",lambda r:equalized_gross_stakes(r,"best"),"best")
    strategy_rows.append(x); summaries["EQUALIZED_GROSS"]=s

    x,s = summarize_strategy(df,"MAXIMIN_PRICE_DUTCH",lambda r:maximin_grid_stakes(r,"best")[0],"best")
    strategy_rows.append(x); summaries["MAXIMIN_PRICE_DUTCH"]=s

    # Matchup tilt only where full matchup context exists; otherwise equal thirds.
    def mt(r):
        if not r.get("matchup_route"):
            return {"A":100/3,"B":100/3,"C":100/3}
        return matchup_tilt_stakes(r)
    x,s = summarize_strategy(df,"MATCHUP_TILT_2X",mt,"best")
    strategy_rows.append(x); summaries["MATCHUP_TILT_2X"]=s

    strategies = pd.concat(strategy_rows, ignore_index=True)
    strategies.to_csv(out/"stake_strategy_game_rows.csv", index=False)
    df.to_csv(out/"stake_gate_matched_inputs.csv", index=False)

    # Same strategies on style-aligned vs conflict games for diagnostic only.
    subgroup = {}
    if "style_alignment" in df.columns:
        for label,mask in [("aligned",df["style_alignment"].eq(True)),("conflict",df["style_alignment"].eq(False))]:
            sub = df[mask].copy()
            subgroup[label] = {"games":int(len(sub))}
            if len(sub):
                for name, stakes in FIXED_ALLOCATIONS.items():
                    _,ss = summarize_strategy(sub,name,lambda r,st=stakes:dict(st),"best")
                    subgroup[label][name]=ss
                _,ss = summarize_strategy(sub,"MATCHUP_TILT_2X",mt,"best")
                subgroup[label]["MATCHUP_TILT_2X"]=ss

    report = {
        "gate":"ALPHAPROFIT STAKE-ASYMMETRY / PAYOFF-EFFICIENCY GATE",
        "status":"PARTIAL_LATE_2024_DIAGNOSTIC_ONLY",
        "predeclared_strategies":{
            "BASE_45_45_10":"45/45/10 frozen prior architecture",
            "C_HEAVY_35_35_30":"fixed 35/35/30",
            "C_MAX_25_25_50":"fixed 25/25/50",
            "EQUALIZED_GROSS":"price-only dutch; stakes inversely proportional to decimal odds so any single hit grosses the same amount",
            "MAXIMIN_PRICE_DUTCH":"5-unit grid, min 10 each, maximize worst net payoff if any one of A/B/C wins",
            "MATCHUP_TILT_2X":"double pregame stake-weight of each slot whose route matches the frozen matchup route, then normalize to 100",
        },
        "matched_games":int(len(df)),
        "strategy_results_best_available_prices":summaries,
        "matchup_subgroup_diagnostic":subgroup,
        "controls":{
            "player_selectors_changed":"NO",
            "price_source_changed":"NO",
            "outcome_based_stake_tuning":"NO",
            "same_game_matchup_inputs":"PROHIBITED",
            "full_season_profitability_claim":"PROHIBITED",
            "sample":"same strict late-2024 complete-price games only",
        },
        "interpretation_rule":"No strategy may be promoted from this tiny sample; use only to identify which stake architecture merits prospective testing.",
        "wager_execution":"DISABLED",
    }
    (out/"STAKE_ASYMMETRY_GATE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"STAKE_ASYMMETRY_GATE.md").write_text(
        "# ALPHAPROFIT STAKE-ASYMMETRY / PAYOFF-EFFICIENCY GATE\n\n"
        + "\n".join(f"- {k}: ROI {v.get('roi')}, net P/L {v.get('net_pnl')}" for k,v in summaries.items())
        + "\n\nDiagnostic only. No profitability or wager-execution claim.\n",
        encoding="utf-8",
    )
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")

    print("ALPHAPROFIT_STAKE_GATE_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHAPROFIT_STAKE_GATE_END")


if __name__ == "__main__":
    main()
