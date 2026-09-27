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
MIN_DISLOCATION_HISTORY_GAMES = 8
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
            "rec_td": 0, "explosive_rec_td": 0,
        })
        for r in rush.itertuples(index=False):
            pid = str(r.rusher_player_id); players[pid]["rush"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 10: players[pid]["i10_rush"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 5: players[pid]["i5_rush"] += 1
        for r in targ.itertuples(index=False):
            pid = str(r.receiver_player_id); players[pid]["targets"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 20: players[pid]["rz_targets"] += 1
            if pd.notna(r.yardline_100) and float(r.yardline_100) <= 10: players[pid]["i10_targets"] += 1
            if pd.to_numeric(getattr(r, "touchdown", 0), errors="coerce") == 1:
                players[pid]["rec_td"] += 1
                if pd.notna(r.yardline_100) and float(r.yardline_100) > 20:
                    players[pid]["explosive_rec_td"] += 1
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



def dislocation_sort_key(pid, metrics):
    return (
        metrics["delta_rz_target_share"],
        metrics["recent_i10_target_share"],
        metrics["recent_i10_targets"],
        metrics["recent_rz_target_share"],
        metrics["recent_rz_targets"],
        metrics["explosive_rec_td_8g"],
        metrics["recent_target_share"],
        metrics["recent_targets"],
        pid,
    )


def pick_receiving_dislocation(active, previous_tot, previous_players, recent_tot, recent_players,
                                full_tot, full_players, allowed_positions, exclude_ids, lane_name):
    candidates = []
    exclude_ids = {x for x in exclude_ids if x}
    for pid, pos in active.items():
        if pid in exclude_ids or pos not in allowed_positions:
            continue
        prev = previous_players.get(pid, {})
        rec = recent_players.get(pid, {})
        full = full_players.get(pid, {})
        prev_rz_share = share(int(prev.get("rz_targets", 0)), previous_tot.get("rz_targets", 0))
        recent_rz_share = share(int(rec.get("rz_targets", 0)), recent_tot.get("rz_targets", 0))
        recent_i10_share = share(int(rec.get("i10_targets", 0)), recent_tot.get("i10_targets", 0))
        recent_target_share = share(int(rec.get("targets", 0)), recent_tot.get("targets", 0))
        delta_rz_share = recent_rz_share - prev_rz_share
        explosive = int(full.get("explosive_rec_td", 0))
        recent_rz = int(rec.get("rz_targets", 0))
        recent_i10 = int(rec.get("i10_targets", 0))
        recent_targets = int(rec.get("targets", 0))
        qualifies = recent_targets > 0 and (delta_rz_share > 0 or recent_i10 > 0 or explosive > 0)
        if not qualifies:
            continue
        metrics = {
            "lane": lane_name,
            "position": pos,
            "delta_rz_target_share": delta_rz_share,
            "recent_rz_target_share": recent_rz_share,
            "recent_i10_target_share": recent_i10_share,
            "recent_rz_targets": recent_rz,
            "recent_i10_targets": recent_i10,
            "explosive_rec_td_8g": explosive,
            "recent_target_share": recent_target_share,
            "recent_targets": recent_targets,
            "full_targets": int(full.get("targets", 0)),
        }
        candidates.append((pid, metrics))
    candidates.sort(key=lambda z: dislocation_sort_key(z[0], z[1]), reverse=True)
    return (candidates[0][0], candidates[0][1]) if candidates else (None, {})


def choose_dynamic_slot_c(wrte_candidate, rb_candidate):
    candidates = [x for x in [wrte_candidate, rb_candidate] if x[0]]
    if not candidates:
        return None, {}
    candidates.sort(key=lambda z: dislocation_sort_key(z[0], z[1]), reverse=True)
    return candidates[0]


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
    p = rows[rows["pair_eligible"]].copy()
    t = rows[rows["triple_eligible"]].copy()
    tff = t[t["favorite_first_td"]]
    th = t[t["triple_hit"]]
    c_only = t[t["slot_c_hit"] & ~t["pair_hit"]]
    wrte_only = t[t["slot_c_wrte_hit"] & ~t["pair_hit"]]
    rb_only = t[t["slot_c_rb_hit"] & ~t["pair_hit"]]
    wrte_residual = t[t["favorite_first_td"] & ~t["pair_hit"] & t["actual_first_td_position"].isin(["WR", "TE"])]
    rb_recv_residual = t[
        t["favorite_first_td"] & ~t["pair_hit"]
        & t["actual_first_td_position"].eq("RB")
        & t["actual_first_td_play_type"].astype(str).str.lower().eq("pass")
    ]
    dynamic_wrte_recovery = wrte_residual[wrte_residual["slot_c_hit"]]
    dynamic_rb_recovery = rb_recv_residual[rb_recv_residual["slot_c_hit"]]
    lane_counts = t["slot_c_lane"].value_counts(dropna=False).to_dict()
    p_inc = float(len(c_only) / len(t)) if len(t) else None
    fair_decimal = (1.0 / p_inc) if p_inc and p_inc > 0 else None
    fair_american = ((fair_decimal - 1.0) * 100.0) if fair_decimal and fair_decimal >= 2.0 else None
    return {
        "pair_eligible_games": int(len(p)),
        "dynamic_c_eligible_games": int(len(t)),
        "favorite_first_td_games_dynamic_population": int(len(tff)),
        "pair_hits_same_population": int(t["pair_hit"].sum()) if len(t) else 0,
        "dynamic_triple_hits": int(len(th)),
        "pair_hit_rate_same_population": None if len(t) == 0 else float(t["pair_hit"].sum() / len(t)),
        "dynamic_triple_hit_rate": None if len(t) == 0 else float(len(th) / len(t)),
        "conditional_pair_capture_given_favorite_first": None if len(tff) == 0 else float(t["pair_hit"].sum() / len(tff)),
        "conditional_dynamic_capture_given_favorite_first": None if len(tff) == 0 else float(len(th) / len(tff)),
        "dynamic_c_incremental_hits": int(len(c_only)),
        "dynamic_c_incremental_hit_rate": p_inc,
        "dynamic_c_standalone_break_even_decimal": fair_decimal,
        "dynamic_c_standalone_break_even_american": fair_american,
        "wrte_candidate_incremental_hits_if_always_used": int(len(wrte_only)),
        "rb_candidate_incremental_hits_if_always_used": int(len(rb_only)),
        "dynamic_route_choice_counts": {str(k): int(v) for k, v in lane_counts.items()},
        "wrte_pair_misses": int(len(wrte_residual)),
        "dynamic_wrte_recoveries": int(len(dynamic_wrte_recovery)),
        "wrte_recovery_rate": None if len(wrte_residual) == 0 else float(len(dynamic_wrte_recovery) / len(wrte_residual)),
        "rb_receiving_pair_misses": int(len(rb_recv_residual)),
        "dynamic_rb_receiving_recoveries": int(len(dynamic_rb_recovery)),
        "rb_receiving_recovery_rate": None if len(rb_recv_residual) == 0 else float(len(dynamic_rb_recovery) / len(rb_recv_residual)),
    }


def main():
    root = Path(os.environ.get("ALPHAPROFIT_DYNAMIC_C_OUT", "alphaprofit_dynamic_c_runtime"))
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
            if len(hist) >= MIN_DISLOCATION_HISTORY_GAMES:
                recent_ids = hist[-4:]
                previous_ids = hist[-8:-4]
                recent_tot, recent_players = aggregate_history(recent_ids, favorite, usage)
                previous_tot, previous_players = aggregate_history(previous_ids, favorite, usage)
                C_wrte, cdiag_wrte = pick_receiving_dislocation(
                    active, previous_tot, previous_players, recent_tot, recent_players,
                    team_tot, players, PASS_LANE, {B}, "WRTE_SECONDARY"
                )
                C_rb, cdiag_rb = pick_receiving_dislocation(
                    active, previous_tot, previous_players, recent_tot, recent_players,
                    team_tot, players, {"RB"}, {A}, "RB_RECEIVING"
                )
                C, cdiag = choose_dynamic_slot_c((C_wrte, cdiag_wrte), (C_rb, cdiag_rb))
            else:
                C_wrte, cdiag_wrte, C_rb, cdiag_rb, C, cdiag = None, {}, None, {}, None, {}
            actual = first_td.get(game_id, {})
            actual_team, actual_player = actual.get("team"), actual.get("player_id")
            actual_position = active.get(actual_player) if actual_player else None
            pair_eligible = bool(A and B)
            triple_eligible = bool(A and B and C)
            favorite_first = bool(actual_team == favorite)
            a_hit = bool(pair_eligible and favorite_first and actual_player == A)
            b_hit = bool(pair_eligible and favorite_first and actual_player == B)
            c_hit = bool(triple_eligible and favorite_first and actual_player == C)
            wrte_c_hit = bool(pair_eligible and C_wrte and favorite_first and actual_player == C_wrte)
            rb_c_hit = bool(pair_eligible and C_rb and favorite_first and actual_player == C_rb)
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
                "slot_c_wrte_player_id": C_wrte, "slot_c_rb_player_id": C_rb,
                "slot_c_wrte_hit": wrte_c_hit, "slot_c_rb_hit": rb_c_hit,
                "slot_c_player_id": C, "slot_c_lane": cdiag.get("lane") if C else None,
                "slot_c_position": cdiag.get("position") if C else None,
                "slot_c_delta_rz_target_share": cdiag.get("delta_rz_target_share") if C else None,
                "slot_c_recent_rz_target_share": cdiag.get("recent_rz_target_share") if C else None,
                "slot_c_recent_i10_target_share": cdiag.get("recent_i10_target_share") if C else None,
                "slot_c_explosive_rec_td_8g": cdiag.get("explosive_rec_td_8g") if C else None,
                "actual_first_td_team": actual_team, "actual_first_td_player_id": actual_player,
                "actual_first_td_player_name": actual.get("player_name"), "actual_first_td_position": actual_position,
                "actual_first_td_play_type": actual.get("play_type"),
                "favorite_first_td": favorite_first, "slot_a_hit": a_hit, "slot_b_hit": b_hit, "slot_c_hit": c_hit,
                "pair_hit": bool(a_hit or b_hit), "triple_eligible": triple_eligible, "triple_hit": bool(a_hit or b_hit or c_hit),
            })
        # Critical no-hindsight control: target game enters history only after its selection is fixed.
        team_history[home].append(game_id)
        team_history[away].append(game_id)

    result = pd.DataFrame(rows)
    result.to_csv(out / "dynamic_slot_c_rows.csv", index=False)
    overall = summarize(result)
    by_season = {str(s): summarize(result[result["season"].eq(s)]) for s in TARGET_SEASONS}
    by_spread = {
        "7_to_9_5": summarize(result[result["spread_line"].abs().between(7, 9.5)]),
        "10_plus": summarize(result[result["spread_line"].abs().ge(10)]),
    }
    report = {
        "gate": "ALPHAPROFIT DYNAMIC SLOT-C ROUTE SELECTION GATE",
        "status": "RETROSPECTIVE_DIAGNOSTIC_ONLY",
        "selector_frozen_before_grade": {
            "history": "favorite team's previous 8 games; target game excluded",
            "minimum_history_games_ab": MIN_HISTORY_GAMES,
            "minimum_history_games_dynamic_c": MIN_DISLOCATION_HISTORY_GAMES,
            "team_gate": "regular-season favorite with abs(nflverse spread_line) >= 7",
            "slot_a": "active QB/RB ranked lexicographically by inside-5 rush share, inside-5 rushes, inside-10 rush share, inside-10 rushes, carry share, carries",
            "slot_b": "UNCHANGED active WR/TE primary red-zone anchor",
            "slot_c_wrte_candidate": "remaining active WR/TE with recent-four vs prior-four red-zone-share acceleration; same fixed tie-breaks",
            "slot_c_rb_candidate": "active RB other than Slot A with the identical receiving-dislocation scale and tie-breaks",
            "dynamic_slot_c_choice": "choose exactly one of the WR/TE or RB receiving candidates by the identical pregame dislocation ranking tuple; no fourth ticket",
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
    (out / "dynamic_slot_c_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "DYNAMIC_SLOT_C_GATE.md").write_text(
        "# ALPHAPROFIT DYNAMIC SLOT-C ROUTE SELECTION GATE\n\n"
        f"Status: {report['status']}\n"
        f"Dynamic-C eligible games: {overall['dynamic_c_eligible_games']}\n"
        f"Pair hit rate on same population: {overall['pair_hit_rate_same_population']}\n"
        f"Dynamic triple hit rate: {overall['dynamic_triple_hit_rate']}\n"
        f"Dynamic C incremental hits: {overall['dynamic_c_incremental_hits']}\n"
        f"Dynamic C incremental hit rate: {overall['dynamic_c_incremental_hit_rate']}\n"
        f"Standalone break-even decimal: {overall['dynamic_c_standalone_break_even_decimal']}\n"
        f"Standalone break-even American: {overall['dynamic_c_standalone_break_even_american']}\n"
        f"WR/TE misses recovered: {overall['dynamic_wrte_recoveries']} / {overall['wrte_pair_misses']}\n"
        f"RB receiving misses recovered: {overall['dynamic_rb_receiving_recoveries']} / {overall['rb_receiving_pair_misses']}\n"
        f"Route choices: {overall['dynamic_route_choice_counts']}\n\n"
        "No profitability, EV, ROI, or wager-execution claim is authorized by this gate.\n",
        encoding="utf-8",
    )
    print("ALPHAPROFIT_DYNAMIC_SLOT_C_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("ALPHAPROFIT_DYNAMIC_SLOT_C_REPORT_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
