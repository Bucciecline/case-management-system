#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error

FREEZE_ID = "ALPHAPROPS-AP-RB1-2026-09-23"
MODEL_PATH = Path("alphaodds/build/alpha_props_gate.py")
MANIFEST_PATH = Path("alphaodds/freezes/ALPHAPROPS_AP-RB1_2026-09-23_FREEZE_MANIFEST.json")
EXPECTED_MODEL_BLOB_SHA1 = "a2052512b20fa25ebba439ce463d097926c47459"
EXPECTED_MANIFEST_BLOB_SHA1 = "956be9fb0becd6b7dfc56ab8cc86a253a418b5c8"
DEV_SEASONS = (2021, 2022, 2023)
VALIDATION_SEASON = 2024
HOLDOUT_SEASON = 2025
HISTORY_SEASONS = (2021, 2022, 2023, 2024, 2025)
POSITIONS = ("QB", "RB", "WR", "TE")

PREEXISTING_EXPOSURE_CAVEAT = (
    "PREEXISTING 2025 REPOSITORY-EXPOSURE CAVEAT: before AP-RB1 was frozen, "
    "the connected Drive source-import workbook already contained a tab titled "
    "'2025 Holdout - OPENED ONCE'. Therefore 2025 is not described as historically "
    "pristine. This run is the first authorized post-freeze AlphaProps outcome evaluation "
    "under AP-RB1, and the caveat is preserved rather than erased."
)

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
HOLDOUT_LOCK = {
    "weekly_player_stats": (
        BASE + "/stats_player/stats_player_week_2025.csv",
        "stats_player_week_2025.csv", 8656387,
        "e5e0615b3d96a3eaebfaee91e55afb4a4e7fe0caf057454177bcd7d6ad4bcfc2",
    ),
    "play_by_play": (
        BASE + "/pbp/play_by_play_2025.csv",
        "play_by_play_2025.csv", 97951481,
        "8ce0001826f0f7b895b7a1068e4db7f43696c699db7064ccb1201855768fd06c",
    ),
    "weekly_rosters": (
        BASE + "/weekly_rosters/roster_weekly_2025.csv",
        "roster_weekly_2025.csv", 15385661,
        "c2f7a1ffebe06058400af1989d1cd2900cc5c9659f084623708a06d4e28de35b",
    ),
    "snap_counts": (
        BASE + "/snap_counts/snap_counts_2025.csv",
        "snap_counts_2025.csv", 2401193,
        "80b02a6e511aa20283551cae622b29ba4d0a6f006c489a2d91591fcad33792e7",
    ),
    "depth_charts": (
        BASE + "/depth_charts/depth_charts_2025.rds",
        "depth_charts_2025.rds", 7970199,
        "6a147ed7edb1325e9e3cf242927c888368ef238ad23eb305f69adf5f812bce7a",
    ),
    "injuries": (
        BASE + "/injuries/injuries_2025.csv",
        "injuries_2025.csv", 696006,
        "873ca1606dd575bd01152508a243ef6b3a0f8f97b90b707217e62ee8c7ceb735",
    ),
}


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    h = hashlib.sha1()
    h.update(f"blob {len(data)}\0".encode("utf-8"))
    h.update(data)
    return h.hexdigest()


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
    req = urllib.request.Request(url, headers={"User-Agent": "AlphaProps-AP-RB1-OneShot/1.0"})
    with urllib.request.urlopen(req, timeout=240) as r, dest.open("wb") as w:
        while True:
            b = r.read(1024 * 1024)
            if not b:
                break
            w.write(b)


def load_frozen_module():
    model_blob = git_blob_sha1(MODEL_PATH)
    manifest_blob = git_blob_sha1(MANIFEST_PATH)
    if model_blob != EXPECTED_MODEL_BLOB_SHA1:
        raise RuntimeError(f"Frozen model blob mismatch: {model_blob}")
    if manifest_blob != EXPECTED_MANIFEST_BLOB_SHA1:
        raise RuntimeError(f"Freeze manifest blob mismatch: {manifest_blob}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("freeze_id") != FREEZE_ID:
        raise RuntimeError("Freeze ID mismatch")
    if manifest.get("status") != "FROZEN_RESEARCH_BASELINE_NOT_BETTING_EDGE":
        raise RuntimeError("Freeze manifest is not a frozen research baseline")

    spec = importlib.util.spec_from_file_location("alphaprops_frozen", MODEL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load frozen model module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    expected_targets = {
        "QB": ["passing_yards"],
        "RB": ["rushing_yards"],
        "WR": ["receiving_yards", "receptions"],
        "TE": ["receiving_yards", "receptions"],
    }
    checks = {
        "dev_seasons": tuple(mod.DEV_SEASONS) == DEV_SEASONS,
        "validation_season": int(mod.VALIDATION_SEASON) == VALIDATION_SEASON,
        "holdout_season": int(mod.HOLDOUT_SEASON) == HOLDOUT_SEASON,
        "roll_windows": tuple(mod.ROLL_WINDOWS) == (3, 5, 8),
        "targets": mod.TARGETS == expected_targets,
        "stability_threshold": float(mod.STABILITY_MAX_FOLD_MAE_RATIO) == 1.75,
        "coverage_min": float(mod.INTERVAL_COVERAGE_MIN) == 0.65,
        "coverage_max": float(mod.INTERVAL_COVERAGE_MAX) == 0.95,
        "min_dev_n": int(mod.MIN_DEV_N) == 100,
        "min_val_n": int(mod.MIN_VAL_N) == 40,
        "min_fold_n": int(mod.MIN_FOLD_N) == 20,
    }
    probe_yards = mod.make_model("passing_yards").get_params()
    probe_rec = mod.make_model("receptions").get_params()
    checks.update({
        "model_class": type(mod.make_model("passing_yards")).__name__ == "HistGradientBoostingRegressor",
        "learning_rate": float(probe_yards["learning_rate"]) == 0.05,
        "max_iter": int(probe_yards["max_iter"]) == 250,
        "max_leaf_nodes": int(probe_yards["max_leaf_nodes"]) == 15,
        "min_samples_leaf": int(probe_yards["min_samples_leaf"]) == 20,
        "l2_regularization": float(probe_yards["l2_regularization"]) == 1.0,
        "random_state": int(probe_yards["random_state"]) == 190022,
        "yardage_loss": probe_yards["loss"] == "squared_error",
        "receptions_loss": probe_rec["loss"] == "poisson",
    })
    if not all(checks.values()):
        raise RuntimeError(f"Frozen specification assertion failed: {checks}")
    return mod, manifest, checks, model_blob, manifest_blob


def materialize_holdout(raw: Path) -> list[dict]:
    receipts = []
    for family, (url, name, expected_size, expected_sha) in HOLDOUT_LOCK.items():
        dest = raw / name
        print(f"MATERIALIZE HOLDOUT {family} {name}", flush=True)
        download(url, dest)
        actual_size = dest.stat().st_size
        actual_sha = sha256_file(dest)
        rec = {
            "family": family,
            "season": HOLDOUT_SEASON,
            "name": name,
            "url": url,
            "expected_size": expected_size,
            "actual_size": actual_size,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "size_ok": actual_size == expected_size,
            "sha_ok": actual_sha == expected_sha,
        }
        rec["status"] = "PASS" if rec["size_ok"] and rec["sha_ok"] else "FAIL"
        receipts.append(rec)
        if rec["status"] != "PASS":
            raise RuntimeError(f"2025 source receipt failed: {rec}")
    return receipts


def load_stats_2021_2025(raw: Path) -> pd.DataFrame:
    frames = []
    for season in HISTORY_SEASONS:
        p = raw / f"stats_player_week_{season}.csv"
        d = pd.read_csv(p, low_memory=False)
        if "season" not in d.columns:
            d["season"] = season
        frames.append(d)
    out = pd.concat(frames, ignore_index=True, sort=False)
    if "season_type" in out.columns:
        out = out[out["season_type"].astype(str).str.upper().eq("REG")].copy()
    out["season"] = pd.to_numeric(out["season"], errors="coerce")
    out["week"] = pd.to_numeric(out["week"], errors="coerce")
    return out


def exact_frozen_snap_attach(mod, base: pd.DataFrame, raw: Path):
    original_seasons = mod.SEASONS
    try:
        mod.SEASONS = HISTORY_SEASONS
        out, status = mod.attach_snap_state(base, raw)
    finally:
        mod.SEASONS = original_seasons
    return out, status


def fit_one_shot_target(mod, frame: pd.DataFrame, features: list[str], target: str, pos: str) -> dict:
    d = frame[frame["position"].astype(str).str.upper().eq(pos)].copy()
    d[target] = pd.to_numeric(d[target], errors="coerce")
    d = d[d[target].notna() & (d["prior_games"] >= 3)].copy()
    dev = d[d["season"].isin(DEV_SEASONS)].copy()
    hold = d[d["season"].eq(HOLDOUT_SEASON)].copy()

    if len(dev) < mod.MIN_DEV_N or len(hold) < mod.MIN_VAL_N:
        return {
            "status": "HOLD_SAMPLE", "position": pos, "target": target,
            "dev_n": int(len(dev)), "holdout_n": int(len(hold)), "gate_pass": False,
        }

    blocked = []
    residuals = []
    for train_seasons, test_season in [((2021,), 2022), ((2021, 2022), 2023)]:
        tr = dev[dev["season"].isin(train_seasons)].copy()
        te = dev[dev["season"].eq(test_season)].copy()
        if len(tr) < 50 or len(te) < mod.MIN_FOLD_N:
            blocked.append({
                "train_seasons": list(train_seasons), "test_season": test_season,
                "status": "HOLD_SAMPLE", "train_n": int(len(tr)), "test_n": int(len(te)),
            })
            continue
        med = tr[features].apply(pd.to_numeric, errors="coerce").median()
        xtr = tr[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
        xte = te[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
        model = mod.make_model(target)
        model.fit(xtr, tr[target].to_numpy(float))
        pred = model.predict(xte)
        if target == "receptions":
            pred = np.clip(pred, 0, None)
        y = te[target].to_numpy(float)
        residuals.extend((y - pred).tolist())
        blocked.append({
            "train_seasons": list(train_seasons), "test_season": test_season, "status": "PASS",
            "train_n": int(len(tr)), "test_n": int(len(te)),
            "mae": float(mean_absolute_error(y, pred)),
            "rmse": float(math.sqrt(mean_squared_error(y, pred))),
            "median_ae": float(median_absolute_error(y, pred)),
        })

    med = dev[features].apply(pd.to_numeric, errors="coerce").median()
    xdev = dev[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
    xhold = hold[features].apply(pd.to_numeric, errors="coerce").fillna(med).fillna(0.0)
    model = mod.make_model(target)
    model.fit(xdev, dev[target].to_numpy(float))
    pred = model.predict(xhold)
    if target == "receptions":
        pred = np.clip(pred, 0, None)
    y = hold[target].to_numpy(float)

    hold_mae = float(mean_absolute_error(y, pred))
    hold_rmse = float(math.sqrt(mean_squared_error(y, pred)))
    hold_median_ae = float(median_absolute_error(y, pred))

    if residuals:
        lo_r, hi_r = np.quantile(np.asarray(residuals), [0.10, 0.90])
        lo, hi = pred + lo_r, pred + hi_r
        if target == "receptions":
            lo = np.clip(lo, 0, None)
        coverage = float(np.mean((y >= lo) & (y <= hi)))
    else:
        coverage = float("nan")

    abs_err = np.abs(y - pred)
    rng = np.random.default_rng(1500)
    boot = [float(np.mean(rng.choice(abs_err, size=len(abs_err), replace=True))) for _ in range(500)]
    mae_ci = [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]

    dev_fold_maes = [x["mae"] for x in blocked if x.get("status") == "PASS"]
    all_maes = dev_fold_maes + [hold_mae]
    stability_ratio = max(all_maes) / min(all_maes) if len(dev_fold_maes) == 2 and min(all_maes) > 0 else None
    stability_pass = bool(stability_ratio is not None and stability_ratio <= float(mod.STABILITY_MAX_FOLD_MAE_RATIO))
    coverage_pass = bool(
        np.isfinite(coverage)
        and float(mod.INTERVAL_COVERAGE_MIN) <= coverage <= float(mod.INTERVAL_COVERAGE_MAX)
    )
    sample_pass = len(hold) >= int(mod.MIN_VAL_N)
    lag_snap = "lag1__offense_snaps"
    lag_snap_rate = (
        float(pd.to_numeric(hold[lag_snap], errors="coerce").notna().mean())
        if lag_snap in hold.columns else None
    )
    gate_pass = bool(stability_pass and coverage_pass and sample_pass)
    return {
        "status": "2025_ONE_SHOT_EVALUATED", "position": pos, "target": target,
        "dev_n": int(len(dev)), "holdout_n": int(len(hold)), "features_n": int(len(features)),
        "mae": hold_mae, "rmse": hold_rmse, "median_ae": hold_median_ae,
        "mae_bootstrap_95pct": mae_ci,
        "holdout_80pct_interval_coverage": coverage,
        "blocked_development_folds": blocked,
        "holdout_plus_dev_fold_mae_ratio": stability_ratio,
        "stability_threshold_max_ratio": float(mod.STABILITY_MAX_FOLD_MAE_RATIO),
        "sample_stability_pass": stability_pass,
        "coverage_gate_range": [float(mod.INTERVAL_COVERAGE_MIN), float(mod.INTERVAL_COVERAGE_MAX)],
        "coverage_pass": coverage_pass, "sample_pass": sample_pass,
        "lag1_offense_snaps_nonmissing_rate": lag_snap_rate,
        "gate_pass": gate_pass,
        "profitability_claim": "PROHIBITED_NO_AUTHENTICATED_HISTORICAL_PROP_PRICE_EVIDENCE",
    }


def main() -> int:
    root = Path("alphaodds_holdout_runtime")
    raw = root / "raw"
    out = root / "out"
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    print(PREEXISTING_EXPOSURE_CAVEAT, flush=True)
    print(
        "ONE-SHOT GATE RULE: no tuning, repair, threshold change, target change, feature-family change, "
        "or data-split change is authorized after 2025 outcome metrics are observed.",
        flush=True,
    )

    mod, manifest, spec_checks, model_blob, manifest_blob = load_frozen_module()
    print(f"FROZEN MODEL VERIFIED {model_blob}", flush=True)
    print(f"FREEZE MANIFEST VERIFIED {manifest_blob}", flush=True)

    pre_receipts = mod.materialize(raw)
    if any(r.get("status") != "PASS" for r in pre_receipts):
        raise RuntimeError("Pre-holdout source receipt gate failed")

    holdout_receipts = materialize_holdout(raw)

    stats = load_stats_2021_2025(raw)
    stats = mod.add_team_shares(stats)
    stats = mod.add_efficiency_state(stats)
    stats, snap_status = exact_frozen_snap_attach(mod, stats, raw)
    feat, all_features = mod.build_features(stats)
    leakage = mod.leakage_audit(all_features)
    if leakage.get("status") != "PASS":
        raise RuntimeError(f"Frozen leakage audit failed: {leakage}")

    results = []
    for pos in POSITIONS:
        fcols = mod.features_for(pos, all_features)
        for target in mod.TARGETS[pos]:
            results.append(fit_one_shot_target(mod, feat, fcols, target, pos))

    all_target_pass = all(r.get("gate_pass") is True for r in results)
    source_pass = all(r.get("status") == "PASS" for r in pre_receipts + holdout_receipts)
    overall_pass = bool(source_pass and leakage.get("status") == "PASS" and all_target_pass)
    decision = "PASS_2025_ONE_SHOT_RESEARCH_HOLDOUT" if overall_pass else "HOLD_2025_ONE_SHOT_NO_RETROACTIVE_REPAIR"

    report = {
        "gate": "ALPHAPROPS POST-FREEZE 2025 ONE-SHOT HOLDOUT",
        "freeze_id": FREEZE_ID,
        "decision": decision,
        "one_shot": True,
        "preexisting_2025_repository_exposure_caveat": PREEXISTING_EXPOSURE_CAVEAT,
        "pristine_holdout_claim": "PROHIBITED",
        "frozen_integrity": {
            "model_blob_sha1": model_blob,
            "expected_model_blob_sha1": EXPECTED_MODEL_BLOB_SHA1,
            "freeze_manifest_blob_sha1": manifest_blob,
            "expected_freeze_manifest_blob_sha1": EXPECTED_MANIFEST_BLOB_SHA1,
            "specification_assertions": spec_checks,
            "model_specification_changes": "NONE",
            "threshold_changes": "NONE",
            "data_split_changes": "NONE",
        },
        "data_split": {
            "development": list(DEV_SEASONS),
            "validation_history_not_re_evaluated": [VALIDATION_SEASON],
            "holdout": [HOLDOUT_SEASON],
            "2024_use_in_this_run": "RAW PRIOR-GAME HISTORY ONLY FOR LAGGED 2025 FEATURES; NO 2024 METRICS RECOMPUTED",
        },
        "source_receipts": {
            "pre_holdout_2021_2024": {
                "count": len(pre_receipts),
                "pass_count": sum(r.get("status") == "PASS" for r in pre_receipts),
            },
            "holdout_2025": holdout_receipts,
            "status": "PASS" if source_pass else "FAIL",
        },
        "snap_state_exact_frozen_join": snap_status,
        "same_week_leakage": leakage,
        "targets": results,
        "cca15": {
            "freeze_fingerprint": "PASS",
            "preexisting_2025_exposure_disclosed_before_download": "PASS",
            "2025_source_receipts": "PASS" if all(r.get("status") == "PASS" for r in holdout_receipts) else "FAIL",
            "2024_metric_reread_or_recompute": "NONE",
            "same_week_leakage": "PASS" if leakage.get("status") == "PASS" else "FAIL",
            "post_holdout_tuning": "PROHIBITED_NONE_PERFORMED",
            "historical_prop_price_evidence": "BLOCKED_FOR_PROFITABILITY_CLAIMS",
            "decision": "PASS" if overall_pass else "HOLD",
        },
        "defense_red_team": {
            "holdout_pristine_status": "NOT_PRISTINE_PREEXISTING_REPOSITORY_EXPOSURE_CAVEAT",
            "frozen_model_reuse": "PASS_EXACT_BLOB_VERIFIED",
            "2024_as_feature_history": "PASS_PRIOR_STATE_ONLY_NOT_TRAINING_AND_NOT_RE_EVALUATED",
            "sequential_2025_feature_rule": "PASS_SHIFT1_FROZEN_FEATURE_CODE",
            "new_thresholds_after_results": "NONE",
            "retroactive_model_repair": "PROHIBITED_NONE_PERFORMED",
            "all_target_stability_and_coverage_gates": "PASS" if all_target_pass else "HOLD",
            "profitability_inference": "PROHIBITED_NO_HISTORICAL_PRICE_ARCHIVE",
            "decision": "PASS" if overall_pass else "HOLD",
        },
        "freeze_effect": (
            "AP_RB1_SURVIVES_2025_ONE_SHOT_AS_RESEARCH_BASELINE_NO_BETTING_EDGE_CLAIM"
            if overall_pass
            else "AP_RB1_REMAINS_FROZEN_HISTORICAL_ARTIFACT_BUT_HOLDOUT_PROMOTION_IS_HELD_NO_REPAIR"
        ),
        "profitability": "NOT_TESTED_NO_AUTHENTICATED_HISTORICAL_PROP_PRICE_ARCHIVE",
        "wager_execution": "DISABLED",
    }

    (out / "AP_RB1_2025_ONE_SHOT_HOLDOUT_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = [
        "# ALPHAPROPS AP-RB1 — 2025 ONE-SHOT HOLDOUT", "",
        f"Decision: {decision}", "", PREEXISTING_EXPOSURE_CAVEAT, "",
        "No 2024 metrics were reread or recomputed. 2024 raw outcomes were used only as prior-game history for lagged 2025 features.",
        "No tuning, model repair, threshold change, profitability claim, or wager execution occurred.", "",
        "## Target results",
    ]
    for r in results:
        md.append(
            f"- {r['position']} {r['target']}: N={r.get('holdout_n')} MAE={r.get('mae')} "
            f"RMSE={r.get('rmse')} MedianAE={r.get('median_ae')} "
            f"coverage={r.get('holdout_80pct_interval_coverage')} "
            f"stability_ratio={r.get('holdout_plus_dev_fold_mae_ratio')} gate_pass={r.get('gate_pass')}"
        )
    md += ["", "## CCA15", json.dumps(report["cca15"], indent=2), "", "## Defense Red Team", json.dumps(report["defense_red_team"], indent=2)]
    (out / "AP_RB1_2025_ONE_SHOT_HOLDOUT_RESULT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("ALPHAPROPS_2025_HOLDOUT_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("ALPHAPROPS_2025_HOLDOUT_REPORT_END")
    return 0 if overall_pass else 3


if __name__ == "__main__":
    raise SystemExit(main())
