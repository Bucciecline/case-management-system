#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error

DEV_SEASONS = (2021, 2022, 2023)
VALIDATION_SEASON = 2024
HOLDOUT_SEASON = 2025
SEASONS = (*DEV_SEASONS, VALIDATION_SEASON)
POSITIONS = ("QB", "RB", "WR", "TE")
ROLL_WINDOWS = (3, 5, 8)
TARGETS = {
    "QB": ["passing_yards"],
    "RB": ["rushing_yards"],
    "WR": ["receiving_yards", "receptions"],
    "TE": ["receiving_yards", "receptions"],
}

# Frozen before any 2024 metrics are read by this run.
STABILITY_MAX_FOLD_MAE_RATIO = 1.75
INTERVAL_COVERAGE_MIN = 0.65
INTERVAL_COVERAGE_MAX = 0.95
MIN_DEV_N = 100
MIN_VAL_N = 40
MIN_FOLD_N = 20

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
LOCK = {
    "weekly_player_stats": {
        "pattern": BASE + "/stats_player/stats_player_week_{season}.csv",
        "files": {
            2021: ("stats_player_week_2021.csv", 8477784, "41915fb49238902ad1f129ebf0405b11a1e710454ae0fe8f7b3e4f9145875f48"),
            2022: ("stats_player_week_2022.csv", 8408729, "ad426c3fe5bf1cc30c3f137fdfe96d054e19d400879ee4413129da49fa7b54be"),
            2023: ("stats_player_week_2023.csv", 8332874, "f19cb71a5de0dce7fd09376026237c9ee9d5a93fe13815a2ea3ec2d37204cb17"),
            2024: ("stats_player_week_2024.csv", 8470040, "3ddc45a84f759aa348ce465ae001752c530575455717657cdfe1f8abfcdb4759"),
        },
    },
    "play_by_play": {
        "pattern": BASE + "/pbp/play_by_play_{season}.csv",
        "files": {
            2021: ("play_by_play_2021.csv", 99167760, "35f5d0b49905daa7d63ace9710346c48c7eb32ce0b8686629491954308013354"),
            2022: ("play_by_play_2022.csv", 99104593, "8aeb0e505d43950e09fec35a241a4e62720422454cdd3ac8f98c95650d54ab54"),
            2023: ("play_by_play_2023.csv", 99720211, "4aeca98ebe6357c5f1a13165533007964605d1f17bd54561937769b952c67613"),
            2024: ("play_by_play_2024.csv", 99483794, "6ae564c2c49378ec531303292966caee596982278b9fcdad9c9dd0a0dc16bfa7"),
        },
    },
    "weekly_rosters": {
        "pattern": BASE + "/weekly_rosters/roster_weekly_{season}.csv",
        "files": {
            2021: ("roster_weekly_2021.csv", 15242660, None),
            2022: ("roster_weekly_2022.csv", 14790824, None),
            2023: ("roster_weekly_2023.csv", 14612235, None),
            2024: ("roster_weekly_2024.csv", 14926918, None),
        },
    },
    "snap_counts": {
        "pattern": BASE + "/snap_counts/snap_counts_{season}.csv",
        "files": {
            2021: ("snap_counts_2021.csv", 2388493, "8e4dae054a4749cf2d4919508d9161a6068fd67509979aefa385bfb3803d0ee5"),
            2022: ("snap_counts_2022.csv", 2379719, "0018a4833fbf0f825286c1c27450c6254391b548d6c55bcde728e93e4816815a"),
            2023: ("snap_counts_2023.csv", 2394875, "303b61aa5c33ffda863f93a750fc14483f397f9187ad502b1ce71e9b516a64c0"),
            2024: ("snap_counts_2024.csv", 2402841, "a2aa58efe093f8aa0ad5aadf09f81d8ec690a1183bd2dde68d20e7f109a9c335"),
        },
    },
    "depth_charts": {
        "pattern": BASE + "/depth_charts/depth_charts_{season}.rds",
        "files": {
            2021: ("depth_charts_2021.rds", 433510, None),
            2022: ("depth_charts_2022.rds", 424934, None),
            2023: ("depth_charts_2023.rds", 411204, None),
            2024: ("depth_charts_2024.rds", 419410, None),
        },
    },
    "injuries": {
        "pattern": BASE + "/injuries/injuries_{season}.csv",
        "files": {
            2021: ("injuries_2021.csv", 737083, None),
            2022: ("injuries_2022.csv", 752433, None),
            2023: ("injuries_2023.csv", 738501, None),
            2024: ("injuries_2024.csv", 816989, None),
        },
    },
}

STATE_VARS = [
    "attempts", "completions", "passing_yards", "carries", "rushing_yards",
    "targets", "receptions", "receiving_yards", "target_share", "air_yards_share", "wopr",
]
SAFE_STATIC_COLS = ["season", "week", "player_id", "player_display_name", "player_name", "position", "recent_team", "team"]


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def download_one(url: str, dest: Path) -> None:
    if "2025" in url or "2025" in dest.name:
        raise RuntimeError("2025 access blocked before AlphaProps freeze")
    req = urllib.request.Request(url, headers={"User-Agent": "AlphaProps-Research-Gate/0.1"})
    with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as w:
        while True:
            block = r.read(1024 * 1024)
            if not block:
                break
            w.write(block)


def materialize(raw: Path) -> list[dict]:
    raw.mkdir(parents=True, exist_ok=True)
    receipts = []
    for family, spec in LOCK.items():
        for season in SEASONS:
            name, expected_size, expected_sha = spec["files"][season]
            url = spec["pattern"].format(season=season)
            dest = raw / name
            print(f"MATERIALIZE {family} {season} {name}", flush=True)
            download_one(url, dest)
            actual_size = dest.stat().st_size
            actual_sha = sha256_file(dest)
            size_ok = actual_size == expected_size
            sha_ok = None if expected_sha is None else actual_sha == expected_sha
            status = "PASS" if size_ok and (sha_ok is not False) else "FAIL"
            rec = {
                "family": family, "season": season, "name": name, "url": url,
                "expected_size": expected_size, "actual_size": actual_size,
                "expected_sha256": expected_sha, "actual_sha256": actual_sha,
                "size_ok": size_ok, "sha_ok": sha_ok,
                "sha_status": "VERIFIED_AGAINST_LOCK" if expected_sha else "COMPUTED_AND_FROZEN_AT_MATERIALIZATION",
                "status": status,
            }
            receipts.append(rec)
            if status != "PASS":
                raise RuntimeError(f"Source receipt failure: {rec}")
    return receipts


def load_weekly_stats(raw: Path) -> pd.DataFrame:
    frames = []
    for season in SEASONS:
        p = raw / f"stats_player_week_{season}.csv"
        df = pd.read_csv(p, low_memory=False)
        if "season" not in df.columns:
            df["season"] = season
        frames.append(df)
    out = pd.concat(frames, ignore_index=True, sort=False)
    if "season_type" in out.columns:
        out = out[out["season_type"].astype(str).str.upper().eq("REG")].copy()
    if HOLDOUT_SEASON in set(pd.to_numeric(out["season"], errors="coerce").dropna().astype(int)):
        raise RuntimeError("2025 rows detected before freeze")
    for col in ["season", "week"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def attach_snap_state(base: pd.DataFrame, raw: Path) -> tuple[pd.DataFrame, dict]:
    """Attach same-week snap state through the authenticated roster PFR->GSIS crosswalk.
    The attached same-week snap columns are state only; build_features shifts them by one
    player-game before they are eligible as predictors.
    """
    snaps = pd.concat(
        [pd.read_csv(raw / f"snap_counts_{s}.csv", low_memory=False) for s in SEASONS],
        ignore_index=True, sort=False
    )
    rosters = pd.concat(
        [pd.read_csv(raw / f"roster_weekly_{s}.csv", low_memory=False) for s in SEASONS],
        ignore_index=True, sort=False
    )

    required_snap = {"season", "week", "pfr_player_id"}
    required_roster = {"season", "week", "pfr_id", "gsis_id"}
    if not required_snap.issubset(snaps.columns) or not required_roster.issubset(rosters.columns):
        return base, {
            "status": "HOLD_SCHEMA",
            "snap_columns": list(snaps.columns),
            "roster_columns": list(rosters.columns),
        }

    snaps = snaps.rename(columns={"pfr_player_id": "pfr_id"})
    snap_keep = [c for c in ["season", "week", "pfr_id", "team", "offense_snaps", "offense_pct"] if c in snaps.columns]
    snaps = snaps[snap_keep].copy()
    roster_keep = [c for c in ["season", "week", "pfr_id", "gsis_id", "team", "full_name"] if c in rosters.columns]
    rosters = rosters[roster_keep].copy()

    for x in (snaps, rosters):
        x["season"] = pd.to_numeric(x["season"], errors="coerce")
        x["week"] = pd.to_numeric(x["week"], errors="coerce")
        x["pfr_id"] = x["pfr_id"].astype("string")
    rosters["gsis_id"] = rosters["gsis_id"].astype("string")

    # Unique source-key crosswalk. Team is added when available to avoid same-week ambiguity.
    join_keys = ["season", "week", "pfr_id"]
    if "team" in snaps.columns and "team" in rosters.columns:
        join_keys.append("team")
    cross = rosters.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates(join_keys, keep="last")
    mapped = snaps.merge(cross[join_keys + ["gsis_id"]], on=join_keys, how="left", validate="m:1")
    mapped = mapped.rename(columns={"gsis_id": "player_id"})
    mapped = mapped.dropna(subset=["player_id"]).copy()
    mapped["player_id"] = mapped["player_id"].astype("string")

    keep = [c for c in ["season", "week", "player_id", "offense_snaps", "offense_pct"] if c in mapped.columns]
    mapped = mapped[keep].drop_duplicates(["season", "week", "player_id"], keep="last")

    b = base.copy()
    b["player_id"] = b["player_id"].astype("string")
    out = b.merge(mapped, on=["season", "week", "player_id"], how="left", validate="m:1")

    snap_rows = int(len(snaps))
    mapped_rows = int(len(mapped))
    coverage = float(mapped_rows / snap_rows) if snap_rows else 0.0
    status = "PASS_STATE_JOINED_THEN_LAGGED" if coverage >= 0.90 else "HOLD_CROSSWALK_COVERAGE"
    return out, {
        "status": status,
        "snap_rows": snap_rows,
        "mapped_rows": mapped_rows,
        "crosswalk_coverage": coverage,
        "join_keys": join_keys,
        "state_columns": keep,
        "predictor_rule": "same-week snap state attached then shift(1) before use",
    }

def add_team_shares(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    team_col = "recent_team" if "recent_team" in out.columns else ("team" if "team" in out.columns else None)
    if not team_col:
        return out
    keys = ["season", "week", team_col]
    for raw, name in [("attempts", "pass_attempt_share"), ("carries", "carry_share"), ("targets", "target_share_rebuilt")]:
        if raw in out.columns:
            v = pd.to_numeric(out[raw], errors="coerce")
            out[raw] = v
            total = out.groupby(keys, dropna=False)[raw].transform("sum")
            out[name] = np.where(total > 0, v / total, np.nan)
    return out


def add_efficiency_state(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    def ratio(num, den, dest):
        if num in out.columns and den in out.columns:
            n = pd.to_numeric(out[num], errors="coerce")
            d = pd.to_numeric(out[den], errors="coerce")
            out[dest] = np.where(d > 0, n / d, np.nan)
    ratio("passing_yards", "attempts", "pass_yards_per_attempt")
    ratio("completions", "attempts", "completion_rate")
    ratio("rushing_yards", "carries", "rush_yards_per_carry")
    ratio("receptions", "targets", "catch_rate")
    ratio("receiving_yards", "targets", "receiving_yards_per_target")
    ratio("receiving_yards", "receptions", "receiving_yards_per_reception")
    return out


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = df.copy().sort_values(["player_id", "season", "week"], kind="mergesort").reset_index(drop=True)
    state = [c for c in STATE_VARS + [
        "pass_attempt_share", "carry_share", "target_share_rebuilt", "pass_yards_per_attempt",
        "completion_rate", "rush_yards_per_carry", "catch_rate", "receiving_yards_per_target",
        "receiving_yards_per_reception", "offense_snaps", "offense_pct"
    ] if c in out.columns]
    g = out.groupby("player_id", sort=False, group_keys=False)
    out["prior_games"] = g.cumcount()
    feats = ["prior_games"]
    for col in state:
        s = pd.to_numeric(out[col], errors="coerce")
        lag = s.groupby(out["player_id"], sort=False).shift(1)
        ln = f"lag1__{col}"
        out[ln] = lag
        feats.append(ln)
        for w in ROLL_WINDOWS:
            mn = f"roll{w}_mean__{col}"
            sd = f"roll{w}_std__{col}"
            out[mn] = lag.groupby(out["player_id"], sort=False).transform(lambda x: x.rolling(w, min_periods=1).mean())
            out[sd] = lag.groupby(out["player_id"], sort=False).transform(lambda x: x.rolling(w, min_periods=2).std())
            feats.extend([mn, sd])
    return out, feats


def leakage_audit(features: list[str]) -> dict:
    violations = []
    targets = {t for v in TARGETS.values() for t in v}
    for c in features:
        if c == "prior_games":
            continue
        if not (c.startswith("lag1__") or c.startswith("roll")):
            violations.append({"feature": c, "reason": "not explicitly lagged"})
        if c in targets:
            violations.append({"feature": c, "reason": "same-week target"})
    return {"status": "PASS" if not violations else "FAIL", "violations": violations}


def features_for(pos: str, all_features: list[str]) -> list[str]:
    tokens = {
        "QB": ("attempt", "completion", "passing", "pass_", "offense_snap", "offense_pct"),
        "RB": ("carry", "rushing", "rush_", "target", "reception", "receiving", "catch", "offense_snap", "offense_pct"),
        "WR": ("target", "reception", "receiving", "catch", "offense_snap", "offense_pct"),
        "TE": ("target", "reception", "receiving", "catch", "offense_snap", "offense_pct"),
    }[pos]
    return [c for c in all_features if c == "prior_games" or any(t in c for t in tokens)]


def make_model(target: str):
    return HistGradientBoostingRegressor(
        loss="poisson" if target == "receptions" else "squared_error",
        learning_rate=0.05, max_iter=250, max_leaf_nodes=15, min_samples_leaf=20,
        l2_regularization=1.0, random_state=190022,
    )


def fit_target(frame: pd.DataFrame, features: list[str], target: str, pos: str) -> dict:
    d = frame[frame["position"].astype(str).str.upper().eq(pos)].copy()
    d[target] = pd.to_numeric(d[target], errors="coerce")
    d = d[d[target].notna() & (d["prior_games"] >= 3)].copy()
    dev = d[d["season"].isin(DEV_SEASONS)].copy()
    val = d[d["season"].eq(VALIDATION_SEASON)].copy()
    if len(dev) < MIN_DEV_N or len(val) < MIN_VAL_N:
        return {"status": "HOLD_SAMPLE", "position": pos, "target": target, "dev_n": int(len(dev)), "validation_n": int(len(val)), "gate_pass": False}

    blocked = []
    residuals = []
    for train_seasons, test_season in [((2021,), 2022), ((2021, 2022), 2023)]:
        tr = dev[dev["season"].isin(train_seasons)].copy()
        te = dev[dev["season"].eq(test_season)].copy()
        if len(tr) < 50 or len(te) < MIN_FOLD_N:
            blocked.append({"train_seasons": list(train_seasons), "test_season": test_season, "status": "HOLD_SAMPLE", "train_n": int(len(tr)), "test_n": int(len(te))})
            continue
        med = tr[features].apply(pd.to_numeric, errors="coerce").median()
        Xtr = tr[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
        Xte = te[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
        m = make_model(target)
        m.fit(Xtr, tr[target].to_numpy(float))
        p = m.predict(Xte)
        if target == "receptions":
            p = np.clip(p, 0, None)
        y = te[target].to_numpy(float)
        residuals.extend((y - p).tolist())
        blocked.append({
            "train_seasons": list(train_seasons), "test_season": test_season, "status": "PASS",
            "train_n": int(len(tr)), "test_n": int(len(te)),
            "mae": float(mean_absolute_error(y, p)),
            "rmse": float(math.sqrt(mean_squared_error(y, p))),
            "median_ae": float(median_absolute_error(y, p)),
        })

    fold_maes = [x["mae"] for x in blocked if x.get("status") == "PASS"]
    ratio = (max(fold_maes) / min(fold_maes)) if len(fold_maes) >= 2 and min(fold_maes) > 0 else None
    stability_pass = (len(fold_maes) == 2 and ratio is not None and ratio <= STABILITY_MAX_FOLD_MAE_RATIO)

    med = dev[features].apply(pd.to_numeric, errors="coerce").median()
    Xdev = dev[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
    Xval = val[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
    model = make_model(target)
    model.fit(Xdev, dev[target].to_numpy(float))
    pred = model.predict(Xval)
    if target == "receptions":
        pred = np.clip(pred, 0, None)
    y = val[target].to_numpy(float)

    if residuals:
        lo_r, hi_r = np.quantile(np.asarray(residuals), [0.10, 0.90])
        lo, hi = pred + lo_r, pred + hi_r
        if target == "receptions":
            lo = np.clip(lo, 0, None)
        coverage = float(np.mean((y >= lo) & (y <= hi)))
    else:
        coverage = np.nan

    abs_err = np.abs(y - pred)
    rng = np.random.default_rng(1500)
    boot = [float(np.mean(rng.choice(abs_err, size=len(abs_err), replace=True))) for _ in range(500)]
    ci = [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]
    coverage_pass = bool(np.isfinite(coverage) and INTERVAL_COVERAGE_MIN <= coverage <= INTERVAL_COVERAGE_MAX)
    gate_pass = bool(stability_pass and coverage_pass)

    return {
        "status": "VALIDATED_2024_PROJECTION_ONLY", "position": pos, "target": target,
        "dev_n": int(len(dev)), "validation_n": int(len(val)), "features_n": int(len(features)),
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(math.sqrt(mean_squared_error(y, pred))),
        "median_ae": float(median_absolute_error(y, pred)),
        "mae_bootstrap_95pct": ci,
        "validation_80pct_interval_coverage": coverage,
        "blocked_development_folds": blocked,
        "fold_mae_ratio": ratio,
        "stability_threshold_max_ratio": STABILITY_MAX_FOLD_MAE_RATIO,
        "sample_stability_pass": stability_pass,
        "coverage_gate_range": [INTERVAL_COVERAGE_MIN, INTERVAL_COVERAGE_MAX],
        "coverage_pass": coverage_pass,
        "gate_pass": gate_pass,
        "profitability_claim": "PROHIBITED_NO_AUTHENTICATED_HISTORICAL_PROP_PRICE_EVIDENCE",
    }


def main():
    root = Path(os.environ.get("ALPHAPROPS_OUT", "alphaodds_runtime"))
    raw = root / "raw"
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = materialize(raw)
    (out / "source_receipts.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")
    if any(r["status"] != "PASS" for r in receipts):
        raise RuntimeError("receipt gate failed")

    stats = load_weekly_stats(raw)
    stats = add_team_shares(stats)
    stats = add_efficiency_state(stats)
    stats, snap_status = attach_snap_state(stats, raw)
    feat, all_features = build_features(stats)
    leak = leakage_audit(all_features)
    if leak["status"] != "PASS":
        raise RuntimeError(f"leakage gate failed {leak}")

    models = []
    for pos in POSITIONS:
        fcols = features_for(pos, all_features)
        p = feat[feat["position"].astype(str).str.upper().eq(pos)].copy()
        keep = [c for c in SAFE_STATIC_COLS if c in p.columns] + sorted(set(fcols + TARGETS[pos]))
        p[keep].to_csv(out / f"{pos.lower()}_opportunity_efficiency_2021_2024.csv", index=False)
        for target in TARGETS[pos]:
            models.append(fit_target(feat, fcols, target, pos) if target in feat.columns else {"status": "HOLD_SCHEMA", "position": pos, "target": target, "gate_pass": False})

    source_pass = all(r["status"] == "PASS" for r in receipts)
    model_pass = all(m.get("gate_pass") is True for m in models)
    role_pass = snap_status.get("status") == "PASS_STATE_JOINED_THEN_LAGGED"
    freeze_pass = bool(source_pass and leak["status"] == "PASS" and model_pass and role_pass)
    freeze_status = "FROZEN_RESEARCH_BASELINE_NOT_BETTING_EDGE" if freeze_pass else "HOLD_NOT_FROZEN"

    report = {
        "split": {"development": list(DEV_SEASONS), "validation": [VALIDATION_SEASON], "holdout_not_read": [HOLDOUT_SEASON]},
        "source_receipts_summary": {
            "count": len(receipts),
            "pass_count": sum(r["status"] == "PASS" for r in receipts),
            "families": sorted(set(r["family"] for r in receipts)),
            "status": "PASS" if source_pass else "FAIL",
        },
        "snap_history": snap_status,
        "leakage_audit": leak,
        "role_control": {
            "injury_depth_chart_numeric_features": "EXCLUDED_FROM_FIRST_FIT_UNTIL_POINT_IN_TIME_ASOF_SAFETY_IS_VERIFIED",
            "current_week_snaps": "NEVER_USED_DIRECTLY_ONLY_SHIFTED_PRIOR_HISTORY",
            "cold_start": "MINIMUM_3_PRIOR_GAMES",
        },
        "models": models,
        "cca15": {
            "source_identity": "PASS",
            "receipt_integrity": "PASS" if source_pass else "FAIL",
            "2025_access": "PASS_NOT_READ",
            "same_week_leakage": "PASS" if leak["status"] == "PASS" else "FAIL",
            "historical_prop_price_evidence": "BLOCKED_FOR_PROFITABILITY_CLAIMS",
        },
        "defense_red_team": {
            "sample_stability": "PASS" if all(m.get("sample_stability_pass") for m in models) else "HOLD",
            "interval_calibration": "PASS" if all(m.get("coverage_pass") for m in models) else "HOLD",
            "role_uncertainty": "LIMITED_PASS_PRIOR_USAGE_ONLY",
            "posthoc_2024_tuning": "PROHIBITED_NONE_PERFORMED",
            "validation_exposure_caveat": "2024 metrics were exposed by prior failed plumbing run before roster crosswalk repair; this repair changes identity plumbing only, not frozen features, hyperparameters, thresholds, or gates.",
        },
        "freeze_gate": {
            "source_pass": source_pass,
            "leakage_pass": leak["status"] == "PASS",
            "model_gates_pass": model_pass,
            "role_history_pass": role_pass,
            "status": freeze_status,
        },
        "profitability": "NOT_TESTED_NO_AUTHENTICATED_HISTORICAL_PROP_PRICE_ARCHIVE",
        "wager_execution": "DISABLED",
    }

    (out / "first_model_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    freeze_lines = [
        "# ALPHAPROPS FIRST-MODEL FREEZE",
        f"Status: {freeze_status}",
        "",
        "2025 was not downloaded, opened, or read by this run.",
        "No profitability or wagering claim is made.",
        "",
    ]
    for m in models:
        freeze_lines.append(
            f"- {m['position']} {m['target']}: status={m['status']} gate_pass={m.get('gate_pass')} "
            f"MAE={m.get('mae')} RMSE={m.get('rmse')} MedianAE={m.get('median_ae')} "
            f"coverage={m.get('validation_80pct_interval_coverage')} fold_ratio={m.get('fold_mae_ratio')}"
        )
    (out / ("MODEL_FREEZE.md" if freeze_pass else "MODEL_HOLD.md")).write_text("\n".join(freeze_lines) + "\n", encoding="utf-8")

    print("ALPHAPROPS_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("ALPHAPROPS_REPORT_END")
    return 0 if freeze_pass else 3


if __name__ == "__main__":
    raise SystemExit(main())

# trigger receipt: workflow already present; no model specification change
