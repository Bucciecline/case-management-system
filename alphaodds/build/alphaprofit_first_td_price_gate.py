#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DYN_PATH = ROOT / "alphaprofit_dynamic_slot_c_gate.py"
spec = importlib.util.spec_from_file_location("dynamic_c", DYN_PATH)
dyn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dyn)

TARGET_SEASON = 2024
STAKES = {"A": 45.0, "B": 45.0, "C": 10.0}
TOTAL_STAKE = sum(STAKES.values())
PRICE_REPO = "ldinan-git/sports-betting-ops"
PRICE_BASE = "https://raw.githubusercontent.com/ldinan-git/sports-betting-ops"
PRICE_DIR = "bet-ops/odds_api_responses/player_props/output/americanfootball_nfl/player_props"

# Source recovery audit froze these commits before matched-price grading.
# 2024-11-28 and 2024-12-01 are intentionally omitted because their latest
# commits occurred after the target games and therefore fail strict pre-kickoff provenance.
ARCHIVE_DATES = {
    "20241208": {"commit": "3fba8ff58436beef74dd4c496a99b65d68811d0d", "commit_time": "2024-12-08T15:37:00Z"},
    "20241209": {"commit": "0ab5f0862c51c048de400b40f543d3152a99832f", "commit_time": "2024-12-09T15:19:54Z"},
    "20241212": {"commit": "639b6f0638dbc94aa0d81a8f9e83932645da5c20", "commit_time": "2024-12-12T14:06:03Z"},
    "20241214": {"commit": "abcba26d34349a50d677b3d3ba5607b342e0d4c7", "commit_time": "2024-12-14T17:44:21Z"},
    "20241216": {"commit": "aa8ed17b83ad330858d2c7750cb3413ef2ac6e80", "commit_time": "2024-12-16T14:09:18Z"},
    "20241219": {"commit": "68dda88ce65ddb86b7b7ba665a86005d27eeab8d", "commit_time": "2024-12-19T14:37:00Z"},
    "20241221": {"commit": "bf08766b81306786bb36bddc04f9be371234e138", "commit_time": "2024-12-21T13:47:01Z"},
    "20241222": {"commit": "3e1b50134b37bb6803955541e6ff07a0084be575", "commit_time": "2024-12-22T14:27:54Z"},
    "20241223": {"commit": "407a58750024a1150e2fdf66085ae88cd1a4c6c1", "commit_time": "2024-12-23T14:32:24Z"},
    "20241225": {"commit": "a426e838d57ccea15fbf56f94d8163adb756a7c1", "commit_time": "2024-12-24T17:35:03Z"},
}

TEAM_FULL = {
    "ARI":"Arizona Cardinals","ATL":"Atlanta Falcons","BAL":"Baltimore Ravens","BUF":"Buffalo Bills",
    "CAR":"Carolina Panthers","CHI":"Chicago Bears","CIN":"Cincinnati Bengals","CLE":"Cleveland Browns",
    "DAL":"Dallas Cowboys","DEN":"Denver Broncos","DET":"Detroit Lions","GB":"Green Bay Packers",
    "HOU":"Houston Texans","IND":"Indianapolis Colts","JAX":"Jacksonville Jaguars","KC":"Kansas City Chiefs",
    "LA":"Los Angeles Rams","LAC":"Los Angeles Chargers","LV":"Las Vegas Raiders","MIA":"Miami Dolphins",
    "MIN":"Minnesota Vikings","NE":"New England Patriots","NO":"New Orleans Saints","NYG":"New York Giants",
    "NYJ":"New York Jets","PHI":"Philadelphia Eagles","PIT":"Pittsburgh Steelers","SEA":"Seattle Seahawks",
    "SF":"San Francisco 49ers","TB":"Tampa Bay Buccaneers","TEN":"Tennessee Titans","WAS":"Washington Commanders",
}


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def norm_name(s):
    s = "" if s is None else str(s)
    s = re.sub(r"[^A-Za-z0-9 ]+", "", s).lower().strip()
    parts = [p for p in s.split() if p not in {"jr", "sr", "ii", "iii", "iv"}]
    return "".join(parts)


def american_to_decimal(price):
    p = float(price)
    if p > 0:
        return 1.0 + p / 100.0
    return 1.0 + 100.0 / abs(p)


def download_json(url):
    req = urllib.request.Request(url, headers={"User-Agent":"AlphaProfit-Price-Gate/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def roster_name_map(raw: Path):
    frames = []
    for season in dyn.SOURCE_SEASONS:
        p = raw / f"roster_weekly_{season}.csv"
        cols = pd.read_csv(p, nrows=0).columns.tolist()
        keep = [c for c in ["gsis_id","full_name","player_name","position"] if c in cols]
        d = pd.read_csv(p, usecols=keep, low_memory=False)
        frames.append(d)
    r = pd.concat(frames, ignore_index=True, sort=False)
    name_col = "full_name" if "full_name" in r.columns else "player_name"
    r = r[r["gsis_id"].notna() & r[name_col].notna()].copy()
    return r.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")[name_col].astype(str).to_dict()


def reconstruct_2024(raw: Path):
    pbp, roster, schedule = dyn.load_inputs(raw)
    roster_idx = dyn.build_roster_index(roster)
    names = roster_name_map(raw)
    first_td = dyn.first_td_by_game(pbp)
    usage = dyn.game_usage(pbp)
    schedule = schedule.sort_values(["gameday","gametime","game_id"], kind="mergesort").reset_index(drop=True)

    history = defaultdict(list)
    rows = []
    for g in schedule.itertuples(index=False):
        gid, season, week = str(g.game_id), int(g.season), int(g.week)
        home, away = str(g.home_team), str(g.away_team)
        spread = float(g.spread_line) if pd.notna(g.spread_line) else math.nan
        target = season == TARGET_SEASON and str(g.game_type).upper() == "REG" and math.isfinite(spread) and abs(spread) >= dyn.SPREAD_MIN
        if target:
            favorite = home if spread > 0 else away
            hist = history[favorite][-dyn.HISTORY_GAMES:]
            active = roster_idx.get((season, week, favorite), {})
            team_tot, players = dyn.aggregate_history(hist, favorite, usage)
            A, B, diag = dyn.pick_anchors(active, team_tot, players) if len(hist) >= dyn.MIN_HISTORY_GAMES else (None,None,{})
            if len(hist) >= dyn.MIN_DISLOCATION_HISTORY_GAMES:
                recent_ids = hist[-4:]
                previous_ids = hist[-8:-4]
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
            actual = first_td.get(gid,{})
            actual_player = actual.get("player_id")
            rows.append({
                "game_id":gid,"season":season,"week":week,
                "gameday":pd.Timestamp(g.gameday).strftime("%Y%m%d"),
                "away_team":away,"home_team":home,"spread_line":spread,"favorite":favorite,
                "A_id":A,"A_name":names.get(A),"B_id":B,"B_name":names.get(B),
                "C_id":C,"C_name":names.get(C),"C_lane":Cd.get("lane") if C else None,
                "actual_first_td_player_id":actual_player,
                "A_hit":bool(A and actual_player == A),
                "B_hit":bool(B and actual_player == B),
                "C_hit":bool(C and actual_player == C),
                "any_hit":bool(actual_player in {x for x in [A,B,C] if x}),
            })
        history[home].append(gid)
        history[away].append(gid)
    return pd.DataFrame(rows)


def price_path(date, home_abbr, away_abbr):
    home = TEAM_FULL[home_abbr]
    away = TEAM_FULL[away_abbr]
    fname = f"americanfootball_nfl_player_props_{home}_{away}_{date}.json"
    return f"{PRICE_DIR}/{fname}"


def fetch_board(date, home, away):
    meta = ARCHIVE_DATES.get(date)
    if not meta:
        return None, {"status":"NO_ARCHIVE_DATE"}
    path = price_path(date, home, away)
    quoted = urllib.parse.quote(path, safe="/")
    url = f"{PRICE_BASE}/{meta['commit']}/{quoted}"
    try:
        data = download_json(url)
    except Exception as exc:
        return None, {"status":"BOARD_NOT_FOUND","error":str(exc),"path":path,"url":url}
    commence = parse_iso(data.get("commence_time"))
    commit_time = parse_iso(meta["commit_time"])
    commit_pre = bool(commence and commit_time and commit_time < commence)
    return data, {
        "status":"FOUND",
        "path":path,"commit":meta["commit"],"commit_time":meta["commit_time"],
        "commence_time":data.get("commence_time"),"commit_pre_kickoff":commit_pre,
        "event_id":data.get("id"),
    }


def extract_prices(board, player_name):
    commence = parse_iso(board.get("commence_time"))
    wanted = norm_name(player_name)
    found = []
    for book in board.get("bookmakers",[]):
        for market in book.get("markets",[]):
            if market.get("key") not in {"player_1st_td","player_first_td"}:
                continue
            upd = parse_iso(market.get("last_update") or book.get("last_update"))
            if not commence or not upd or upd >= commence:
                continue
            for out in market.get("outcomes",[]):
                if str(out.get("name","")).lower() != "yes":
                    continue
                desc = out.get("description")
                if norm_name(desc) != wanted:
                    continue
                found.append({
                    "book":book.get("key"),"book_title":book.get("title"),
                    "price":float(out.get("price")),
                    "market_last_update":market.get("last_update") or book.get("last_update"),
                    "minutes_to_kickoff":(commence-upd).total_seconds()/60.0,
                    "description":desc,
                })
    found.sort(key=lambda x:x["price"], reverse=True)
    return found


def pnl_for_row(row, mode):
    hit_slot = "A" if row["A_hit"] else ("B" if row["B_hit"] else ("C" if row["C_hit"] else None))
    if hit_slot is None:
        return -TOTAL_STAKE
    price = row[f"{hit_slot}_{mode}_price"]
    if pd.isna(price):
        return np.nan
    gross = STAKES[hit_slot] * american_to_decimal(price)
    return gross - TOTAL_STAKE


def summarize_econ(df, mode):
    complete_col = f"{mode}_complete"
    d = df[df[complete_col]].copy()
    if d.empty:
        return {"games":0}
    d["pnl"] = d.apply(lambda r:pnl_for_row(r,mode), axis=1)
    return {
        "games":int(len(d)),
        "total_stake":float(len(d)*TOTAL_STAKE),
        "gross_return":float((d["pnl"]+TOTAL_STAKE).sum()),
        "net_pnl":float(d["pnl"].sum()),
        "roi":float(d["pnl"].sum()/(len(d)*TOTAL_STAKE)),
        "portfolio_hits":int(d["any_hit"].sum()),
        "portfolio_hit_rate":float(d["any_hit"].mean()),
        "A_hits":int(d["A_hit"].sum()),"B_hits":int(d["B_hit"].sum()),"C_hits":int(d["C_hit"].sum()),
    }


def main():
    root = Path(os.environ.get("ALPHAPROFIT_PRICE_OUT","alphaprofit_price_runtime"))
    raw, out = root/"raw", root/"out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = dyn.materialize(raw)
    selections = reconstruct_2024(raw)
    target_total = int(len(selections))
    candidates = selections[selections["gameday"].isin(ARCHIVE_DATES)].copy()

    rows = []
    price_receipts = []
    for r in candidates.itertuples(index=False):
        board, rec = fetch_board(r.gameday, r.home_team, r.away_team)
        rec.update({"game_id":r.game_id,"date":r.gameday})
        price_receipts.append(rec)
        base = r._asdict()
        if board is None or not rec.get("commit_pre_kickoff"):
            base.update({"board_status":rec["status"],"commit_pre_kickoff":False})
            rows.append(base); continue

        base["board_status"] = "PREKICKOFF_ARCHIVE_PASS"
        base["commit_pre_kickoff"] = True
        commence = parse_iso(board.get("commence_time"))
        for slot in ["A","B","C"]:
            pname = base[f"{slot}_name"]
            prices = extract_prices(board, pname) if pname else []
            base[f"{slot}_price_count"] = len(prices)
            if prices:
                best = prices[0]
                base[f"{slot}_best_price"] = best["price"]
                base[f"{slot}_best_book"] = best["book"]
                base[f"{slot}_best_minutes_to_kickoff"] = best["minutes_to_kickoff"]
                dk = next((x for x in prices if x["book"]=="draftkings"), None)
                if dk:
                    base[f"{slot}_dk_price"] = dk["price"]
                    base[f"{slot}_dk_minutes_to_kickoff"] = dk["minutes_to_kickoff"]
            else:
                base[f"{slot}_best_price"] = np.nan
                base[f"{slot}_dk_price"] = np.nan

        base["best_complete"] = all(pd.notna(base.get(f"{s}_best_price")) for s in ["A","B","C"])
        base["dk_complete"] = all(pd.notna(base.get(f"{s}_dk_price")) for s in ["A","B","C"])
        rows.append(base)

    result = pd.DataFrame(rows)
    if not result.empty:
        for col in ["best_complete","dk_complete"]:
            if col not in result: result[col] = False
            result[col] = result[col].fillna(False).astype(bool)

    best = summarize_econ(result,"best") if not result.empty else {"games":0}
    dk = summarize_econ(result,"dk") if not result.empty else {"games":0}

    c_best = result[result.get("best_complete",pd.Series(dtype=bool))].copy() if not result.empty else pd.DataFrame()
    if not c_best.empty:
        c_prices = pd.to_numeric(c_best["C_best_price"], errors="coerce")
        c_standalone_pnl = np.where(c_best["C_hit"], STAKES["C"]*c_prices.map(american_to_decimal)-STAKES["C"], -STAKES["C"])
        c_diag = {
            "games":int(len(c_best)),
            "C_hits":int(c_best["C_hit"].sum()),
            "C_hit_rate":float(c_best["C_hit"].mean()),
            "median_best_price":float(c_prices.median()),
            "mean_best_price":float(c_prices.mean()),
            "C_net_pnl_at_10_per_game":float(np.sum(c_standalone_pnl)),
            "C_roi_at_10_per_game":float(np.sum(c_standalone_pnl)/(len(c_best)*STAKES["C"])),
        }
    else:
        c_diag = {"games":0}

    report = {
        "gate":"ALPHAPROFIT HISTORICAL FIRST-TD PRICE SOURCE-RECOVERY & DYNAMIC-C ECONOMIC GATE",
        "status":"PARTIAL_LATE_2024_SOURCE_COVERAGE_ONLY",
        "frozen_economic_rule":{
            "research_unit":100.0,"slot_A":45.0,"slot_B":45.0,"dynamic_slot_C":10.0,
            "best_price_rule":"maximum simultaneously captured pre-kickoff American price among archived bookmakers",
            "draftkings_rule":"DraftKings-only pre-kickoff price",
            "missing_price_rule":"exclude game from that economic view; never impute",
        },
        "source_recovery":{
            "full_2024_qualifying_games":target_total,
            "qualifying_games_on_strict_archive_dates":int(len(candidates)),
            "board_files_found":int(sum(x.get("status")=="FOUND" for x in price_receipts)),
            "boards_passing_commit_pre_kickoff":int(sum(x.get("status")=="FOUND" and x.get("commit_pre_kickoff") for x in price_receipts)),
            "best_price_complete_games":int(result["best_complete"].sum()) if not result.empty else 0,
            "draftkings_complete_games":int(result["dk_complete"].sum()) if not result.empty else 0,
            "archive_window":"2024-12-08 through 2024-12-25 strict pre-kickoff commits; post-kickoff 2024-11-28 and 2024-12-01 files quarantined",
            "upstream_archive":"ldinan-git/sports-betting-ops; raw The Odds API player-prop responses committed to GitHub",
        },
        "best_available_economics":best,
        "draftkings_economics":dk,
        "dynamic_C_best_price_diagnostic":c_diag,
        "cca15":{
            "selector_changed_for_price_test":"NO",
            "stake_rule_changed_after_prices":"NO",
            "post_kickoff_archive_files":"QUARANTINED",
            "missing_prices":"EXCLUDED_NOT_IMPUTED",
            "full_season_profitability_claim":"PROHIBITED_PARTIAL_SOURCE_COVERAGE",
            "price_source_identity":"PASS_RAW_JSON_WITH_EVENT_COMMENCE_AND_MARKET_LAST_UPDATE",
        },
        "defense_red_team":{
            "sample_size":"SMALL_LATE_SEASON_SUBSET",
            "book_selection":"BEST_PRICE_AND_FIXED_DRAFTKINGS_REPORTED_SEPARATELY",
            "account_limits_and_availability":"NOT_MODELED",
            "market_board_survivorship":"POSSIBLE_PUBLIC_ARCHIVE_COVERAGE_LIMITATION",
            "promotion_effect":"NO_BETTING_EDGE_PROMOTION_ALLOWED",
        },
        "profitability_claim":"HOLD_FULL_SEASON_PRICE_ARCHIVE_REQUIRED",
        "wager_execution":"DISABLED",
    }

    result.to_csv(out/"late_2024_matched_price_rows.csv", index=False)
    (out/"price_source_receipts.json").write_text(json.dumps(price_receipts,indent=2),encoding="utf-8")
    (out/"PRICE_ECONOMIC_GATE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"PRICE_ECONOMIC_GATE.md").write_text(
        "# ALPHAPROFIT HISTORICAL FIRST-TD PRICE SOURCE-RECOVERY & DYNAMIC-C ECONOMIC GATE\n\n"
        f"Status: {report['status']}\n"
        f"Full 2024 qualifying games: {target_total}\n"
        f"Qualifying games on strict archive dates: {len(candidates)}\n"
        f"Best-price complete games: {report['source_recovery']['best_price_complete_games']}\n"
        f"DraftKings complete games: {report['source_recovery']['draftkings_complete_games']}\n"
        f"Best-price net P/L: {best.get('net_pnl')}\n"
        f"Best-price ROI: {best.get('roi')}\n"
        f"DraftKings net P/L: {dk.get('net_pnl')}\n"
        f"DraftKings ROI: {dk.get('roi')}\n\n"
        "This is a partial late-2024 historical economic diagnostic, not a profitability validation.\n",
        encoding="utf-8",
    )
    (out/"source_receipts.json").write_text(json.dumps(receipts,indent=2),encoding="utf-8")
    print("ALPHAPROFIT_PRICE_GATE_BEGIN")
    print(json.dumps(report,indent=2))
    print("ALPHAPROFIT_PRICE_GATE_END")


if __name__ == "__main__":
    main()
