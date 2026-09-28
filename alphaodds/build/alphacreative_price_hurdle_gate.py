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
matchup = load_module("matchup_gate", "alphaprofit_matchup_style_gate.py")

ROUTES = tuple(matchup.ROUTES)
HISTORY = 8
MIN_REFERENCE_GAMES = 20

def wilson_lower(hits, n, z=1.96):
    if n <= 0:
        return None
    p = hits / n
    denom = 1.0 + z*z/n
    center = p + z*z/(2*n)
    adj = z * math.sqrt((p*(1-p) + z*z/(4*n))/n)
    return (center - adj) / denom

def decimal_to_american(d):
    if d is None or not math.isfinite(d) or d <= 1:
        return None
    if d >= 2:
        return (d - 1.0) * 100.0
    return -100.0 / (d - 1.0)

def fair_from_prob(p):
    if p is None or p <= 0 or p >= 1:
        return {"decimal": None, "american": None}
    d = 1.0 / p
    return {"decimal": d, "american": decimal_to_american(d)}

def ref_cell(df, hit_col):
    n = int(len(df))
    hits = int(df[hit_col].sum()) if n else 0
    p = hits/n if n else None
    lo = wilson_lower(hits, n) if n else None
    raw = fair_from_prob(p)
    conservative = fair_from_prob(lo)
    if n < MIN_REFERENCE_GAMES:
        quality = "SPARSE"
    elif n < 40:
        quality = "THIN"
    else:
        quality = "MODERATE"
    if hits == 0:
        quality = "NO_HITS"
    return {
        "games": n,
        "hits": hits,
        "hit_rate": p,
        "wilson_95_lower": lo,
        "raw_break_even_decimal": raw["decimal"],
        "raw_break_even_american": raw["american"],
        "conservative_break_even_decimal": conservative["decimal"],
        "conservative_break_even_american": conservative["american"],
        "reference_quality": quality,
    }

def main():
    root = Path(os.environ.get("ALPHAPROFIT_PRICE_HURDLE_OUT", "alphaprofit_price_hurdle_runtime"))
    raw, out = root/"raw", root/"out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = dyn.materialize(raw)
    pbp, roster, schedule = dyn.load_inputs(raw)
    roster_idx = dyn.build_roster_index(roster)
    first_td = dyn.first_td_by_game(pbp)
    usage = dyn.game_usage(pbp)
    route_counts = matchup.build_game_route_counts(pbp, roster_idx)

    schedule = schedule.sort_values(["gameday","gametime","game_id"], kind="mergesort").reset_index(drop=True)
    history = defaultdict(list)
    rows = []

    for g in schedule.itertuples(index=False):
        gid, season, week = str(g.game_id), int(g.season), int(g.week)
        home, away = str(g.home_team), str(g.away_team)
        spread = float(g.spread_line) if pd.notna(g.spread_line) else math.nan

        target = (
            season in dyn.TARGET_SEASONS
            and str(g.game_type).upper() == "REG"
            and math.isfinite(spread)
            and abs(spread) >= 7.0
        )
        if target:
            favorite = home if spread > 0 else away
            opponent = away if favorite == home else home
            fh = history[favorite][-HISTORY:]
            oh = history[opponent][-HISTORY:]

            active = roster_idx.get((season, week, favorite), {})
            team_tot, players = dyn.aggregate_history(fh, favorite, usage)
            A, B, diag = dyn.pick_anchors(active, team_tot, players) if len(fh) >= dyn.MIN_HISTORY_GAMES else (None,None,{})

            if len(fh) >= dyn.MIN_DISLOCATION_HISTORY_GAMES:
                recent_ids = fh[-4:]
                previous_ids = fh[-8:-4]
                recent_tot, recent_players = dyn.aggregate_history(recent_ids, favorite, usage)
                previous_tot, previous_players = dyn.aggregate_history(previous_ids, favorite, usage)
                Cw, Cwd = dyn.pick_receiving_dislocation(
                    active, previous_tot, previous_players, recent_tot, recent_players,
                    team_tot, players, dyn.PASS_LANE, {B}, "WRTE_SECONDARY"
                )
                Cr, Crd = dyn.pick_receiving_dislocation(
                    active, previous_tot, previous_players, recent_tot, recent_players,
                    team_tot, players, {"RB"}, {A}, "RB_RECEIVING"
                )
                C, Cd = dyn.choose_dynamic_slot_c((Cw,Cwd),(Cr,Crd))
            else:
                C, Cd = None, {}

            style_alignment = None
            matchup_route = None
            if len(fh) >= HISTORY and len(oh) >= HISTORY:
                off_counts = matchup.aggregate_route_counts(fh, favorite, route_counts)
                opp_allowed = defaultdict(int)
                for pgid in oh:
                    sg = schedule[schedule["game_id"].astype(str).eq(str(pgid))]
                    if sg.empty:
                        continue
                    pg = sg.iloc[0]
                    ph, pa = str(pg["home_team"]), str(pg["away_team"])
                    prior_off = pa if opponent == ph else ph
                    for route, n in route_counts.get((str(pgid), prior_off), {}).items():
                        opp_allowed[route] += int(n)
                off = matchup.smooth_shares(off_counts)
                deff = matchup.smooth_shares(opp_allowed)
                offense_top = max(ROUTES, key=lambda r:(off[r],r))
                defense_top = max(ROUTES, key=lambda r:(deff[r],r))
                style_alignment = offense_top == defense_top
                compat = {r:off[r]*deff[r] for r in ROUTES}
                matchup_route = max(ROUTES, key=lambda r:(compat[r],r))

            actual = first_td.get(gid,{})
            actual_team = actual.get("team")
            actual_player = actual.get("player_id")
            fav_first = actual_team == favorite
            triple_eligible = bool(A and B and C)

            rows.append({
                "game_id":gid,
                "season":season,
                "week":week,
                "abs_spread":abs(spread),
                "style_alignment":style_alignment,
                "matchup_route":matchup_route,
                "slot_c_lane":Cd.get("lane") if C else None,
                "triple_eligible":triple_eligible,
                "favorite_first_td":bool(fav_first),
                "slot_a_hit":bool(triple_eligible and fav_first and actual_player==A),
                "slot_b_hit":bool(triple_eligible and fav_first and actual_player==B),
                "slot_c_hit":bool(triple_eligible and fav_first and actual_player==C),
            })

        history[home].append(gid)
        history[away].append(gid)

    df = pd.DataFrame(rows)
    full = df[df["triple_eligible"] & df["matchup_route"].notna()].copy()

    lane_defs = {
        "T7_BASE": full[full["abs_spread"].ge(7.0)].copy(),
        "T8_ALIGNED": full[full["abs_spread"].ge(8.0) & full["style_alignment"].eq(True)].copy(),
        "T10_ALIGNED": full[full["abs_spread"].ge(10.0) & full["style_alignment"].eq(True)].copy(),
    }

    table = {}
    long_rows = []
    for lane, ldf in lane_defs.items():
        table[lane] = {}
        for route in ROUTES:
            rdf = ldf[ldf["matchup_route"].eq(route)].copy()
            table[lane][route] = {}
            for slot, col in [("A","slot_a_hit"),("B","slot_b_hit"),("C","slot_c_hit")]:
                cell = ref_cell(rdf, col)
                table[lane][route][slot] = cell
                long_rows.append({"lane":lane,"matchup_route":route,"slot":slot,**cell})

    report = {
        "gate":"ALPHACREATIVE MATCHUP-CONDITIONED PRICE-HURDLE GATE",
        "status":"RETROSPECTIVE_REFERENCE_FREEZE_FOR_PROSPECTIVE_SHADOW_ONLY",
        "price_classification_rule":{
            "CORE_PASS":"actual pre-kickoff American odds >= conservative 95% Wilson break-even hurdle AND reference games >= 20",
            "RAW_PASS_ONLY":"actual odds >= raw break-even but below conservative hurdle; shadow only",
            "PRICE_FAIL":"actual odds below raw break-even",
            "NO_REFERENCE":"fewer than 20 historical reference games or zero historical hits; no automatic price pass",
            "missing_price":"NO_PRICE; never impute",
        },
        "lane_definitions":{
            "T7_BASE":"spread >=7; matchup route available; alignment not required",
            "T8_ALIGNED":"spread >=8 and offense/defense top route aligned",
            "T10_ALIGNED":"spread >=10 and offense/defense top route aligned",
        },
        "reference_table":table,
        "controls":{
            "hurdles_derived_after_historical_exposure":"YES_CHALLENGER_REFERENCE_ONLY",
            "prospective_outcomes_may_change_hurdles":"NO_UNTIL_PREDECLARED_CHECKPOINT",
            "player_selectors_changed":"NO",
            "matchup_definition_changed":"NO",
            "spread_lanes_changed":"NO",
            "2025_access":"PROHIBITED_NOT_READ",
            "profitability_claim":"PROHIBITED",
        },
        "alphacreative_innovation_memo":{
            "what_passed":"price must be evaluated relative to slot-specific matchup context, not absolute longshot size",
            "what_failed":"generic receiver-route stake boost",
            "largest_uncertainty":"small route-specific cells, especially RB_REC and T10",
            "best_next_falsifiable_experiment":"prospectively timestamp actual A/B/C first-TD prices and classify them before kickoff using this frozen table",
            "worst_case_loss_effect":"price gate can only remove or shadow tickets; it does not increase the $100 research-unit cap",
            "status":"TEST_PROSPECTIVELY",
        },
        "wager_execution":"DISABLED",
    }

    pd.DataFrame(long_rows).to_csv(out/"price_hurdle_reference_rows.csv", index=False)
    df.to_csv(out/"price_hurdle_game_rows.csv", index=False)
    (out/"PRICE_HURDLE_GATE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"PRICE_HURDLE_GATE.md").write_text(
        "# ALPHACREATIVE MATCHUP-CONDITIONED PRICE-HURDLE GATE\n\n"
        "Historical hurdle table is frozen for prospective shadow testing only.\n\n"
        + "\n".join(
            f"- {r['lane']} / {r['matchup_route']} / {r['slot']}: n={r['games']}, hits={r['hits']}, "
            f"raw={r['raw_break_even_american']}, conservative={r['conservative_break_even_american']}, "
            f"quality={r['reference_quality']}"
            for r in long_rows
        )
        + "\n\nNo profitability or wager-execution claim.\n",
        encoding="utf-8",
    )
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")

    print("ALPHACREATIVE_PRICE_HURDLE_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHACREATIVE_PRICE_HURDLE_END")

if __name__ == "__main__":
    main()
