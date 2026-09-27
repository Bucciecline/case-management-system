#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HISTORY_GAMES = 8
MIN_HISTORY_GAMES = 3
TARGET_SEASONS = (2022, 2023, 2024)
SOURCE_SEASONS = (2021, 2022, 2023, 2024)
SPREAD_MIN = 7.0
POSITIONS = {"QB", "RB", "WR", "TE"}
RUSH_LANE = {"QB", "RB"}
PASS_LANE = {"WR", "TE"}
HOLDOUT_SEASON = 2025

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
PBP_LOCK = {
    2021: ("play_by_play_2021.csv", 99167760, "35f5d0b49905daa7d63ace9710346c48c7eb32ce0b8686629491954308013354"),
    2022: ("play_by_play_2022.csv", 99104593, "8aeb0e505d43950e09fec35a241a4e62720422454cdd3ac8f98c95650d54ab54"),
    2023: ("play_by_play_2023.csv", 99720211, "4aeca98ebe6357c5f1a13165533007964605d1f17bd54561937769b952c67613"),
    2024: ("play_by_play_2024.csv", 99483794, "6ae564c2c49378ec531303292966caee596982278b9fcdad9c9dd0a0dc16bfa7"),
}
ROSTER_LOCK = {
    2021: ("roster_weekly_2021.csv", 15242660, "88adfe0fba5cbedd260d7928ad373476d4fb168d0213cb52ef1163ed5d3056b7"),
    2022: ("roster_weekly_2022.csv", 14790824, "bd6a50de334473c10f8058afa948fd0c6adc8a8b081da41c500cc0aa069c5312"),
    2023: ("roster_weekly_2023.csv", 14612235, "1433f1f239784dde7fcb35349d211a9b83abfc0156337b72ec4f923abf715bd3"),
    2024: ("roster_weekly_2024.csv", 14926918, "074ecaeb9325de943c11f7bbc941425626985090ef8386f90cd837fa5cb5d4b3"),
}
SCHEDULE_COMMIT = "bd805a6c643e2b4a3b8ba0918434e3a5a5bcccd5"
SCHEDULE_BLOB_SHA1 = "5d1405c2f7e365af6bcc431eacf29f1665957e82"
SCHEDULE_URL = f"https://raw.githubusercontent.com/nflverse/nfldata/{SCHEDULE_COMMIT}/data/games.csv"


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    if "2025" in url or "2025" in dest.name:
        raise RuntimeError("2025 access prohibited in this gate")
    req = urllib.request.Request(url, headers={"User-Agent": "AlphaProfit-GoalLine-Gate/0.1"})
    with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as w:
        while True:
            block = r.read(1024 * 1024)
            if not block:
                break
            w.write(block)


def materialize(raw: Path) -> list[dict]:
    raw.mkdir(parents=True, exist_ok=True)
    receipts = []
    for family, locks, pattern in [
        ("play_by_play", PBP_LOCK, BASE + "/pbp/play_by_play_{season}.csv"),
        ("weekly_rosters", ROSTER_LOCK, BASE + "/weekly_rosters/roster_weekly_{season}.csv"),
    ]:
        for season in SOURCE_SEASONS:
            name, expected_size, expected_sha = locks[season]
            url = pattern.format(season=season)
            dest = raw / name
            print(f"MATERIALIZE {family} {season} {name}", flush=True)
            download(url, dest)
            actual_size = dest.stat().st_size
            actual_sha = sha256_file(dest)
            rec = {
                "family": family, "season": season, "name": name, "url": url,
                "expected_size": expected_size, "actual_size": actual_size,
                "expected_sha256": expected_sha, "actual_sha256": actual_sha,
                "size_ok": actual_size == expected_size, "sha_ok": actual_sha == expected_sha,
            }
            rec["status"] = "PASS" if rec["size_ok"] and rec["sha_ok"] else "FAIL"
            receipts.append(rec)
            if rec["status"] != "PASS":
                raise RuntimeError(f"Source receipt failure: {rec}")
    sched = raw / "games.csv"
    print(f"MATERIALIZE schedule commit {SCHEDULE_COMMIT}", flush=True)
    download(SCHEDULE_URL, sched)
    receipts.append({
        "family": "schedule", "name": "games.csv", "url": SCHEDULE_URL,
        "pinned_commit": SCHEDULE_COMMIT, "pinned_blob_sha1": SCHEDULE_BLOB_SHA1,
        "actual_size": sched.stat().st_size, "actual_sha256": sha256_file(sched),
        "status": "PASS_PINNED_COMMIT_BLOB",
    })
    return receipts


def load_inputs(raw: Path):
    use_pbp = [
        "game_id", "season", "season_type", "week", "play_id", "posteam", "yardline_100",
        "play_type", "touchdown", "td_team", "td_player_id", "td_player_name",
        "rusher_player_id", "rusher_player_name", "receiver_player_id", "receiver_player_name",
        "qb_kneel", "qb_spike",
    ]
    pbps = []
    for season in SOURCE_SEASONS:
        p = raw / f"play_by_play_{season}.csv"
        header = pd.read_csv(p, nrows=0).columns.tolist()
        cols = [c for c in use_pbp if c in header]
        d = pd.read_csv(p, usecols=cols, low_memory=False)
        if "season" not in d.columns:
            d["season"] = season
        pbps.append(d)
    pbp = pd.concat(pbps, ignore_index=True, sort=False)
    if "season_type" in pbp.columns:
        pbp = pbp[pbp["season_type"].astype(str).str.upper().isin(["REG", "POST"])].copy()
    if HOLDOUT_SEASON in set(pd.to_numeric(pbp["season"], errors="coerce").dropna().astype(int)):
        raise RuntimeError("2025 PBP detected")

    rosters = []
    for season in SOURCE_SEASONS:
        p = raw / f"roster_weekly_{season}.csv"
        header = pd.read_csv(p, nrows=0).columns.tolist()
        keep = [c for c in ["season", "week", "team", "gsis_id", "full_name", "position"] if c in header]
        d = pd.read_csv(p, usecols=keep, low_memory=False)
        if "season" not in d.columns:
            d["season"] = season
        rosters.append(d)
    roster = pd.concat(rosters, ignore_index=True, sort=False)

    schedule = pd.read_csv(raw / "games.csv", low_memory=False)
    schedule = schedule[
        schedule["season"].isin(SOURCE_SEASONS)
        & schedule["game_type"].astype(str).str.upper().isin(["REG", "POST"])
    ].copy()
    schedule["spread_line"] = pd.to_numeric(schedule["spread_line"], errors="coerce")
    schedule["gameday"] = pd.to_datetime(schedule["gameday"], errors="coerce")
    return pbp, roster, schedule


def build_roster_index(roster: pd.DataFrame):
    r = roster.copy()
    r["season"] = pd.to_numeric(r["season"], errors="coerce").astype("Int64")
    r["week"] = pd.to_numeric(r["week"], errors="coerce").astype("Int64")
    r["position"] = r["position"].astype(str).str.upper()
    r = r[r["position"].isin(POSITIONS) & r["gsis_id"].notna()].copy()
    out = {}
    for (season, week, team), g in r.groupby(["season", "week", "team"], dropna=True):
        out[(int(season), int(week), str(team))] = {
            str(row.gsis_id): str(row.position)
            for row in g[["gsis_id", "position"]].drop_duplicates("gsis_id").itertuples(index=False)
        }
    return out


def first_td_by_game(pbp: pd.DataFrame):
    t = pbp[pd.to_numeric(pbp.get("touchdown"), errors="coerce").fillna(0).eq(1)].copy()
    t["play_id"] = pd.to_numeric(t["play_id"], errors="coerce")
    t = t.sort_values(["game_id", "play_id"], kind="mergesort").drop_duplicates("game_id", keep="first")
    out = {}
    for r in t.itertuples(index=False):
        out[str(r.game_id)] = {
            "team": None if pd.isna(getattr(r, "td_team", np.nan)) else str(getattr(r, "td_team")),
            "player_id": None if pd.isna(getattr(r, "td_player_id", np.nan)) else str(getattr(r, "td_player_id")),
            "player_name": None if pd.isna(getattr(r, "td_player_name", np.nan)) else str(getattr(r, "td_player_name")),
            "play_type": None if pd.isna(getattr(r, "play_type", np.nan)) else str(getattr(r, "play_type")),
        }
    return out


def game_usage(pbp: pd.DataFrame):
    p = pbp.copy()
    p["yardline_100"] = pd.to_numeric(p["yardline_100"], errors="coerce")
    p["qb_kneel"] = pd.to_numeric(p.get("qb_kneel", 0), errors="coerce").fillna(0)
    p["qb_spike"] = pd.to_numeric(p.get("qb_spike", 0), errors="coerce").fillna(0)
    out = {}
    for (game_id, team), g in p[p["posteam"].notna()].groupby(["game_id", "posteam"], sort=False):
        team, game_id = str(team), str(game_id)
        rush = g[g["rusher_player_id"].notna() & ~g["qb_kneel"].eq(1)].copy()
        targ = g[g["receiver_player_id"].notna() & ~g["qb_spike"].eq(1)].copy()
        team_tot = {
            "rush": int(len(rush)), "i10_rush": int((rush["yardline_100"] <= 10).sum()),
            "i5_rush": int((rush["yardline_100"] <= 5).sum()), "targets": int(len(targ)),
            "rz_targets": int((targ["yardline_100"] <= 20).sum()),
            "i10_targets": int((targ["yardline_100"] <= 10).sum()),
        }
        players = defaultdict(lambda: {
            "rush": 0, "i10_rush": 0, "i5_rush": 0,
            "targets": 0, "rz_targets": 0, "i10_targets": 0,
        })
        for r in rush.itertuples(index=False):
            pid = str(r.rusher_player_id); players[pid]["rush"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 10: players[pid]["i10_rush"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 5: players[pid]["i5_rush"] += 1
        for r in targ.itertuples(index=False):
            pid = str(r.receiver_player_id); players[pid]["targets"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 20: players[pid]["rz_targets"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 10: players[pid]["i10_targets"] += 1
        out[(game_id, team)] = {"team": team_tot, "players": dict(players)}
    return out


def aggregate_history(game_ids, team, usage):
    team_total = defaultdict(int)
    players = defaultdict(lambda: defaultdict(int))
    for gid in game_ids:
        x = usage.get((gid, team))
        if not x: continue
        for k, v in x["team"].items(): team_total[k] += int(v)
        for pid, d in x["players"].items():
            for k, v in d.items(): players[pid][k] += int(v)
    return dict(team_total), {pid: dict(d) for pid, d in players.items()}


def share(n, d):
    return float(n / d) if d else 0.0


def pick_anchors(active, team_tot, players):
    rush_candidates, pass_candidates, diagnostics = [], [], {}
    for pid, pos in active.items():
        d = players.get(pid, {})
        met = {
            "position": pos, "i5_rush": int(d.get("i5_rush", 0)),
            "i10_rush": int(d.get("i10_rush", 0)), "rush": int(d.get("rush", 0)),
            "rz_targets": int(d.get("rz_targets", 0)), "i10_targets": int(d.get("i10_targets", 0)),
            "targets": int(d.get("targets", 0)),
        }
        met.update({
            "i5_rush_share": share(met["i5_rush"], team_tot.get("i5_rush", 0)),
            "i10_rush_share": share(met["i10_rush"], team_tot.get("i10_rush", 0)),
            "carry_share": share(met["rush"], team_tot.get("rush", 0)),
            "rz_target_share": share(met["rz_targets"], team_tot.get("rz_targets", 0)),
            "i10_target_share": share(met["i10_targets"], team_tot.get("i10_targets", 0)),
            "target_share": share(met["targets"], team_tot.get("targets", 0)),
        })
        diagnostics[pid] = met
        if pos in RUSH_LANE and (met["i5_rush"] > 0 or met["i10_rush"] > 0 or met["rush"] > 0):
            rush_candidates.append((pid, met))
        if pos in PASS_LANE and (met["rz_targets"] > 0 or met["targets"] > 0):
            pass_candidates.append((pid, met))
    rush_candidates.sort(key=lambda z: (
        z[1]["i5_rush_share"], z[1]["i5_rush"], z[1]["i10_rush_share"],
        z[1]["i10_rush"], z[1]["carry_share"], z[1]["rush"], z[0]
    ), reverse=True)
    pass_candidates.sort(key=lambda z: (
        z[1]["rz_target_share"], z[1]["rz_targets"], z[1]["i10_target_share"],
        z[1]["i10_targets"], z[1]["target_share"], z[1]["targets"], z[0]
    ), reverse=True)
    return (
        rush_candidates[0][0] if rush_candidates else None,
        pass_candidates[0][0] if pass_candidates else None,
        diagnostics,
    )


def summarize(rows: pd.DataFrame):
    e = rows[rows["pair_eligible"]].copy()
    ff = e[e["favorite_first_td"]]
    hits = e[e["pair_hit"]]
    return {
        "eligible_games": int(len(e)),
        "favorite_first_td_games": int(len(ff)),
        "pair_hits": int(len(hits)),
        "overall_hit_rate": None if len(e) == 0 else float(len(hits) / len(e)),
        "favorite_first_td_rate": None if len(e) == 0 else float(len(ff) / len(e)),
        "conditional_capture_given_favorite_first": None if len(ff) == 0 else float(len(hits) / len(ff)),
        "slot_a_hits": int(e["slot_a_hit"].sum()),
        "slot_b_hits": int(e["slot_b_hit"].sum()),
    }


def main():
    root = Path(os.environ.get("ALPHAPROFIT_GL_OUT", "alphaprofit_goal_line_runtime"))
    raw, out = root / "raw", root / "out"
    out.mkdir(parents=True, exist_ok=True)
    receipts = materialize(raw)
    (out / "source_receipts.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")

    pbp, roster, schedule = load_inputs(raw)
    roster_idx = build_roster_index(roster)
    first_td = first_td_by_game(pbp)
    usage = game_usage(pbp)
    schedule = schedule.sort_values(["gameday", "gametime", "game_id"], kind="mergesort").reset_index(drop=True)

    team_history = defaultdict(list)
    rows = []
    for g in schedule.itertuples(index=False):
        game_id, season, week = str(g.game_id), int(g.season), int(g.week)
        home, away = str(g.home_team), str(g.away_team)
        spread = float(g.spread_line) if pd.notna(g.spread_line) else math.nan
        target = season in TARGET_SEASONS and str(g.game_type).upper() == "REG" and math.isfinite(spread) and abs(spread) >= SPREAD_MIN
        if target:
            favorite = home if spread > 0 else away
            hist = team_history[favorite][-HISTORY_GAMES:]
            active = roster_idx.get((season, week, favorite), {})
            team_tot, players = aggregate_history(hist, favorite, usage)
            A, B, diag = pick_anchors(active, team_tot, players) if len(hist) >= MIN_HISTORY_GAMES else (None, None, {})
            actual = first_td.get(game_id, {})
            actual_team, actual_player = actual.get("team"), actual.get("player_id")
            pair_eligible = bool(A and B)
            favorite_first = bool(actual_team == favorite)
            a_hit = bool(pair_eligible and favorite_first and actual_player == A)
            b_hit = bool(pair_eligible and favorite_first and actual_player == B)
            rows.append({
                "game_id": game_id, "season": season, "week": week, "away_team": away, "home_team": home,
                "spread_line": spread, "favorite": favorite, "history_games": len(hist), "pair_eligible": pair_eligible,
                "slot_a_player_id": A, "slot_a_position": diag.get(A, {}).get("position") if A else None,
                "slot_a_i5_rush_share": diag.get(A, {}).get("i5_rush_share") if A else None,
                "slot_a_i5_rush": diag.get(A, {}).get("i5_rush") if A else None,
                "slot_a_i10_rush_share": diag.get(A, {}).get("i10_rush_share") if A else None,
                "slot_a_carry_share": diag.get(A, {}).get("carry_share") if A else None,
                "slot_b_player_id": B, "slot_b_position": diag.get(B, {}).get("position") if B else None,
                "slot_b_rz_target_share": diag.get(B, {}).get("rz_target_share") if B else None,
                "slot_b_rz_targets": diag.get(B, {}).get("rz_targets") if B else None,
                "slot_b_i10_target_share": diag.get(B, {}).get("i10_target_share") if B else None,
                "slot_b_target_share": diag.get(B, {}).get("target_share") if B else None,
                "actual_first_td_team": actual_team, "actual_first_td_player_id": actual_player,
                "actual_first_td_player_name": actual.get("player_name"), "actual_first_td_play_type": actual.get("play_type"),
                "favorite_first_td": favorite_first, "slot_a_hit": a_hit, "slot_b_hit": b_hit, "pair_hit": bool(a_hit or b_hit),
            })
        # Critical no-hindsight control: target game enters history only after its selection is fixed.
        team_history[home].append(game_id)
        team_history[away].append(game_id)

    result = pd.DataFrame(rows)
    result.to_csv(out / "goal_line_player_dna_rows.csv", index=False)
    overall = summarize(result)
    by_season = {str(s): summarize(result[result["season"].eq(s)]) for s in TARGET_SEASONS}
    by_spread = {
        "7_to_9_5": summarize(result[result["spread_line"].abs().between(7, 9.5)]),
        "10_plus": summarize(result[result["spread_line"].abs().ge(10)]),
    }
    report = {
        "gate": "ALPHAPROFIT GOAL-LINE / RED-ZONE PLAYER DNA GATE",
        "status": "RETROSPECTIVE_DIAGNOSTIC_ONLY",
        "selector_frozen_before_grade": {
            "history": "favorite team's previous 8 games; target game excluded",
            "minimum_history_games": MIN_HISTORY_GAMES,
            "team_gate": "regular-season favorite with abs(nflverse spread_line) >= 7",
            "slot_a": "active QB/RB ranked lexicographically by inside-5 rush share, inside-5 rushes, inside-10 rush share, inside-10 rushes, carry share, carries",
            "slot_b": "active WR/TE ranked lexicographically by red-zone target share, red-zone targets, inside-10 target share, inside-10 targets, overall target share, targets",
            "current_game_inputs": "PROHIBITED_FOR_SELECTION",
        },
        "overall": overall, "by_season": by_season, "by_spread_bucket": by_spread,
        "cca15": {
            "source_receipts": "PASS" if all(r["status"].startswith("PASS") for r in receipts) else "FAIL",
            "same_game_leakage": "PASS_BY_CONSTRUCTION_HISTORY_UPDATED_AFTER_SELECTION",
            "2025_access": "PROHIBITED_NOT_READ",
            "2024_pristine_claim": "PROHIBITED_PRIOR_EXPOSURE_EXISTS",
            "historical_price_evidence": "BLOCKED_FOR_PROFITABILITY_CLAIMS",
        },
        "defense_red_team": {
            "role_identity": "WEEKLY_ROSTER_GSIS_ACTIVE_POOL",
            "goal_line_sample_sparsity": "TRACKED_DO_NOT_BACKFILL_WITH_TARGET_GAME",
            "defensive_or_special_teams_first_td": "COUNTED_AS_PAIR_MISS",
            "no_td_game": "COUNTED_AS_PAIR_MISS",
            "posthoc_threshold_tuning": "NONE_IN_THIS_GATE",
        },
        "profitability": "NOT_TESTED_NO_AUTHENTICATED_HISTORICAL_FIRST_TD_PRICE_ARCHIVE",
        "wager_execution": "DISABLED",
    }
    (out / "goal_line_player_dna_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "GOAL_LINE_GATE.md").write_text(
        "# ALPHAPROFIT GOAL-LINE / RED-ZONE PLAYER DNA GATE\n\n"
        f"Status: {report['status']}\n"
        f"Pair eligible games: {overall['eligible_games']}\n"
        f"Pair hits: {overall['pair_hits']}\n"
        f"Overall hit rate: {overall['overall_hit_rate']}\n"
        f"Favorite-first rate: {overall['favorite_first_td_rate']}\n"
        f"Conditional player capture given favorite scored first: {overall['conditional_capture_given_favorite_first']}\n"
        f"Slot A hits: {overall['slot_a_hits']}\n"
        f"Slot B hits: {overall['slot_b_hits']}\n\n"
        "No profitability, EV, ROI, or wager-execution claim is authorized by this gate.\n",
        encoding="utf-8",
    )
    print("ALPHAPROFIT_GOAL_LINE_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("ALPHAPROFIT_GOAL_LINE_REPORT_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
