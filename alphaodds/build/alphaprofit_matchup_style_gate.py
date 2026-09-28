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
DYN_PATH = ROOT / "alphaprofit_dynamic_slot_c_gate.py"
spec = importlib.util.spec_from_file_location("dynamic_c", DYN_PATH)
dyn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dyn)

ROUTES = ("GROUND", "WRTE_REC", "RB_REC")
MATCHUP_CLEAR_THRESHOLD = 0.45
HISTORY_GAMES = 8
MIN_MATCHUP_HISTORY_GAMES = 8


def smooth_shares(counts):
    total = sum(int(counts.get(r, 0)) for r in ROUTES)
    denom = total + len(ROUTES)
    return {r: (int(counts.get(r, 0)) + 1) / denom for r in ROUTES}


def route_from_td_row(row, roster_idx):
    posteam = None if pd.isna(getattr(row, "posteam", np.nan)) else str(getattr(row, "posteam"))
    td_team = None if pd.isna(getattr(row, "td_team", np.nan)) else str(getattr(row, "td_team"))
    if not posteam or not td_team or posteam != td_team:
        return "OTHER"

    season = int(getattr(row, "season"))
    week = int(getattr(row, "week"))
    active = roster_idx.get((season, week, posteam), {})

    rid = getattr(row, "rusher_player_id", np.nan)
    if pd.notna(rid):
        pos = active.get(str(rid))
        return "GROUND" if pos in {"QB", "RB"} else "OTHER"

    recid = getattr(row, "receiver_player_id", np.nan)
    if pd.notna(recid):
        pos = active.get(str(recid))
        if pos in {"WR", "TE"}:
            return "WRTE_REC"
        if pos == "RB":
            return "RB_REC"
        return "OTHER"

    return "OTHER"


def build_game_route_counts(pbp, roster_idx):
    p = pbp[pd.to_numeric(pbp.get("touchdown"), errors="coerce").fillna(0).eq(1)].copy()
    out = defaultdict(lambda: defaultdict(int))
    for row in p.itertuples(index=False):
        posteam = None if pd.isna(getattr(row, "posteam", np.nan)) else str(getattr(row, "posteam"))
        if not posteam:
            continue
        route = route_from_td_row(row, roster_idx)
        if route in ROUTES:
            out[(str(row.game_id), posteam)][route] += 1
    return {k: dict(v) for k, v in out.items()}


def aggregate_route_counts(game_ids, team, route_counts):
    d = defaultdict(int)
    for gid in game_ids:
        for route, n in route_counts.get((gid, team), {}).items():
            d[route] += int(n)
    return dict(d)


def summarize_group(df):
    if len(df) == 0:
        return {"games": 0}
    fav = df[df["favorite_first_td"]]
    return {
        "games": int(len(df)),
        "favorite_first_td_games": int(df["favorite_first_td"].sum()),
        "favorite_first_td_rate": float(df["favorite_first_td"].mean()),
        "portfolio_hits": int(df["triple_hit"].sum()),
        "portfolio_hit_rate": float(df["triple_hit"].mean()),
        "conditional_portfolio_capture": None if len(fav) == 0 else float(fav["triple_hit"].mean()),
        "matchup_route_correct_games": int(df["matchup_route_correct"].sum()),
        "matchup_route_accuracy_all_games": float(df["matchup_route_correct"].mean()),
        "matchup_route_accuracy_given_favorite_first": None if len(fav) == 0 else float(fav["matchup_route_correct"].mean()),
        "slot_a_hits": int(df["slot_a_hit"].sum()),
        "slot_b_hits": int(df["slot_b_hit"].sum()),
        "slot_c_hits": int(df["slot_c_hit"].sum()),
    }


def main():
    root = Path(os.environ.get("ALPHAPROFIT_MATCHUP_OUT", "alphaprofit_matchup_runtime"))
    raw, out = root / "raw", root / "out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = dyn.materialize(raw)
    pbp, roster, schedule = dyn.load_inputs(raw)
    roster_idx = dyn.build_roster_index(roster)
    first_td = dyn.first_td_by_game(pbp)
    usage = dyn.game_usage(pbp)
    route_counts = build_game_route_counts(pbp, roster_idx)

    schedule = schedule.sort_values(["gameday", "gametime", "game_id"], kind="mergesort").reset_index(drop=True)

    team_history = defaultdict(list)
    rows = []

    for g in schedule.itertuples(index=False):
        gid, season, week = str(g.game_id), int(g.season), int(g.week)
        home, away = str(g.home_team), str(g.away_team)
        spread = float(g.spread_line) if pd.notna(g.spread_line) else math.nan

        target = (
            season in dyn.TARGET_SEASONS
            and str(g.game_type).upper() == "REG"
            and math.isfinite(spread)
            and abs(spread) >= dyn.SPREAD_MIN
        )

        if target:
            favorite = home if spread > 0 else away
            opponent = away if favorite == home else home
            fav_hist = team_history[favorite][-HISTORY_GAMES:]
            opp_hist = team_history[opponent][-HISTORY_GAMES:]

            active = roster_idx.get((season, week, favorite), {})
            team_tot, players = dyn.aggregate_history(fav_hist, favorite, usage)
            A, B, diag = dyn.pick_anchors(active, team_tot, players) if len(fav_hist) >= dyn.MIN_HISTORY_GAMES else (None, None, {})

            if len(fav_hist) >= dyn.MIN_DISLOCATION_HISTORY_GAMES:
                recent_ids = fav_hist[-4:]
                previous_ids = fav_hist[-8:-4]
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
                C, Cd = dyn.choose_dynamic_slot_c((Cw, Cwd), (Cr, Crd))
            else:
                C, Cd = None, {}

            # Defensive allowance history is reconstructed from the opposing offenses faced.
            opp_allowed_counts = defaultdict(int)
            for prior_gid in opp_hist:
                sg = schedule[schedule["game_id"].astype(str).eq(str(prior_gid))]
                if sg.empty:
                    continue
                pg = sg.iloc[0]
                phome, paway = str(pg["home_team"]), str(pg["away_team"])
                prior_offense = paway if opponent == phome else phome
                for route, n in route_counts.get((str(prior_gid), prior_offense), {}).items():
                    opp_allowed_counts[route] += int(n)

            offense_counts = aggregate_route_counts(fav_hist, favorite, route_counts)
            offense_shares = smooth_shares(offense_counts)
            defense_shares = smooth_shares(opp_allowed_counts)
            compatibility = {r: offense_shares[r] * defense_shares[r] for r in ROUTES}
            compat_total = sum(compatibility.values())
            matchup_route = max(ROUTES, key=lambda r: (compatibility[r], r))
            matchup_share = compatibility[matchup_route] / compat_total if compat_total else 0.0
            offense_top = max(ROUTES, key=lambda r: (offense_shares[r], r))
            defense_top = max(ROUTES, key=lambda r: (defense_shares[r], r))
            style_alignment = offense_top == defense_top

            actual = first_td.get(gid, {})
            actual_team = actual.get("team")
            actual_player = actual.get("player_id")
            actual_route = None
            tdrows = pbp[
                pbp["game_id"].astype(str).eq(gid)
                & pd.to_numeric(pbp.get("touchdown"), errors="coerce").fillna(0).eq(1)
            ].copy()
            if not tdrows.empty:
                tdrows["play_id"] = pd.to_numeric(tdrows["play_id"], errors="coerce")
                firstrow = tdrows.sort_values("play_id").iloc[0]
                actual_route = route_from_td_row(firstrow, roster_idx)

            pair_eligible = bool(A and B)
            triple_eligible = bool(A and B and C)
            favorite_first = actual_team == favorite
            a_hit = bool(pair_eligible and favorite_first and actual_player == A)
            b_hit = bool(pair_eligible and favorite_first and actual_player == B)
            c_hit = bool(triple_eligible and favorite_first and actual_player == C)

            slot_routes = {
                "A": "GROUND",
                "B": "WRTE_REC",
                "C": ("RB_REC" if Cd.get("lane") == "RB_RECEIVING" else "WRTE_REC") if C else None,
            }
            matchup_supported_slots = [s for s, route in slot_routes.items() if route == matchup_route]
            matchup_supported_hit = (
                ("A" in matchup_supported_slots and a_hit)
                or ("B" in matchup_supported_slots and b_hit)
                or ("C" in matchup_supported_slots and c_hit)
            )

            rows.append({
                "game_id": gid, "season": season, "week": week, "favorite": favorite, "opponent": opponent,
                "spread_line": spread, "history_favorite": len(fav_hist), "history_opponent": len(opp_hist),
                "pair_eligible": pair_eligible, "triple_eligible": triple_eligible,
                "slot_c_lane": Cd.get("lane") if C else None,
                "favorite_first_td": bool(favorite_first),
                "slot_a_hit": a_hit, "slot_b_hit": b_hit, "slot_c_hit": c_hit,
                "triple_hit": bool(a_hit or b_hit or c_hit),
                "actual_first_td_route": actual_route,
                "offense_top_route": offense_top,
                "defense_funnel_top_route": defense_top,
                "style_alignment": style_alignment,
                "matchup_route": matchup_route,
                "matchup_route_share": matchup_share,
                "clear_matchup": matchup_share >= MATCHUP_CLEAR_THRESHOLD,
                "matchup_route_correct": bool(favorite_first and actual_route == matchup_route),
                "matchup_supported_slots": "|".join(matchup_supported_slots),
                "matchup_supported_hit": bool(matchup_supported_hit),
                **{f"offense_{r.lower()}_share": offense_shares[r] for r in ROUTES},
                **{f"defense_{r.lower()}_share": defense_shares[r] for r in ROUTES},
                **{f"compat_{r.lower()}": compatibility[r] for r in ROUTES},
            })

        team_history[home].append(gid)
        team_history[away].append(gid)

    df = pd.DataFrame(rows)
    full = df[df["triple_eligible"] & df["history_opponent"].ge(MIN_MATCHUP_HISTORY_GAMES)].copy()

    by_route = {route: summarize_group(full[full["matchup_route"].eq(route)]) for route in ROUTES}
    by_alignment = {
        "offense_and_defense_same_top_route": summarize_group(full[full["style_alignment"]]),
        "offense_and_defense_different_top_route": summarize_group(full[~full["style_alignment"]]),
    }
    by_clear = {
        "clear_matchup": summarize_group(full[full["clear_matchup"]]),
        "nonclear_matchup": summarize_group(full[~full["clear_matchup"]]),
    }

    # Does a slot perform better when matchup says its lane is the best route?
    slot_support = {}
    for slot, hit_col, route_rule in [
        ("A", "slot_a_hit", lambda x: x["matchup_route"].eq("GROUND")),
        ("B", "slot_b_hit", lambda x: x["matchup_route"].eq("WRTE_REC")),
    ]:
        supported = full[route_rule(full)]
        nonsupported = full[~route_rule(full)]
        slot_support[slot] = {
            "supported_games": int(len(supported)),
            "supported_hit_rate": None if len(supported) == 0 else float(supported[hit_col].mean()),
            "nonsupported_games": int(len(nonsupported)),
            "nonsupported_hit_rate": None if len(nonsupported) == 0 else float(nonsupported[hit_col].mean()),
        }

    c_supported = full[
        ((full["slot_c_lane"].eq("RB_RECEIVING")) & full["matchup_route"].eq("RB_REC"))
        | ((full["slot_c_lane"].eq("WRTE_SECONDARY")) & full["matchup_route"].eq("WRTE_REC"))
    ]
    c_nonsupported = full.drop(c_supported.index)
    slot_support["C"] = {
        "supported_games": int(len(c_supported)),
        "supported_hit_rate": None if len(c_supported) == 0 else float(c_supported["slot_c_hit"].mean()),
        "nonsupported_games": int(len(c_nonsupported)),
        "nonsupported_hit_rate": None if len(c_nonsupported) == 0 else float(c_nonsupported["slot_c_hit"].mean()),
    }

    report = {
        "gate": "ALPHAPROFIT MATCHUP-STYLE INTERACTION GATE",
        "status": "RETROSPECTIVE_DIAGNOSTIC_ONLY",
        "hypothesis_frozen_before_grade": {
            "offense_style": "favorite prior-8 offensive TD route shares with Laplace +1 smoothing",
            "defense_funnel": "opponent prior-8 offensive TD routes allowed with identical smoothing",
            "routes": list(ROUTES),
            "compatibility": "offense route share multiplied by defense allowed route share",
            "matchup_route": "highest compatibility route",
            "clear_matchup_threshold": MATCHUP_CLEAR_THRESHOLD,
            "player_selectors": "A/B/Dynamic-C unchanged from prior frozen gate",
            "minimum_matchup_history": MIN_MATCHUP_HISTORY_GAMES,
            "target_game_inputs": "PROHIBITED",
        },
        "overall": summarize_group(full),
        "by_matchup_route": by_route,
        "by_style_alignment": by_alignment,
        "by_matchup_clarity": by_clear,
        "slot_hit_rate_when_matchup_supports_lane": slot_support,
        "cca15": {
            "source_receipts": "PASS" if all(r["status"].startswith("PASS") for r in receipts) else "FAIL",
            "same_game_leakage": "PASS_HISTORY_UPDATED_AFTER_TARGET_SELECTION",
            "player_selectors_changed": "NO",
            "2025_access": "PROHIBITED_NOT_READ",
            "historical_price_claim": "NOT_PART_OF_THIS_GATE",
        },
        "defense_red_team": {
            "posthoc_threshold_tuning": "NONE",
            "route_taxonomy": "ONLY_OFFENSIVE_GROUND_WRTE_RECEIVING_RB_RECEIVING; DEF_ST_OTHER_EXCLUDED_FROM_ROUTE_MATCH",
            "sample_exposure": "2022-2024 previously exposed; diagnostic only",
            "promotion_standard": "must improve in prospective 2026 or independent future sample before live use",
        },
        "wager_execution": "DISABLED",
    }

    df.to_csv(out / "matchup_style_rows.csv", index=False)
    (out / "MATCHUP_STYLE_GATE_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "MATCHUP_STYLE_GATE.md").write_text(
        "# ALPHAPROFIT MATCHUP-STYLE INTERACTION GATE\n\n"
        f"Eligible full-history games: {report['overall']['games']}\n"
        f"Portfolio hit rate: {report['overall']['portfolio_hit_rate']}\n"
        f"Favorite-first rate: {report['overall']['favorite_first_td_rate']}\n"
        f"Matchup-route accuracy given favorite first: {report['overall']['matchup_route_accuracy_given_favorite_first']}\n\n"
        "Diagnostic only; no live promotion or wager execution.\n",
        encoding="utf-8",
    )
    (out / "source_receipts.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")

    print("ALPHAPROFIT_MATCHUP_GATE_BEGIN")
    print(json.dumps(report, indent=2))
    print("ALPHAPROFIT_MATCHUP_GATE_END")


if __name__ == "__main__":
    main()
