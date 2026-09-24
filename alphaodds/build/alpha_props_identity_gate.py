#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

SEASONS = (2021, 2022, 2023, 2024)
HOLDOUT_SEASON = 2025
POSITIONS = ("QB", "RB", "WR", "TE")
COVERAGE_THRESHOLD = 0.90

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
FILES = {
    "weekly_rosters": {
        2021: ("roster_weekly_2021.csv", 15242660, "88adfe0fba5cbedd260d7928ad373476d4fb168d0213cb52ef1163ed5d3056b7"),
        2022: ("roster_weekly_2022.csv", 14790824, "bd6a50de334473c10f8058afa948fd0c6adc8a8b081da41c500cc0aa069c5312"),
        2023: ("roster_weekly_2023.csv", 14612235, "1433f1f239784dde7fcb35349d211a9b83abfc0156337b72ec4f923abf715bd3"),
        2024: ("roster_weekly_2024.csv", 14926918, "074ecaeb9325de943c11f7bbc941425626985090ef8386f90cd837fa5cb5d4b3"),
    },
    "snap_counts": {
        2021: ("snap_counts_2021.csv", 2388493, "8e4dae054a4749cf2d4919508d9161a6068fd67509979aefa385bfb3803d0ee5"),
        2022: ("snap_counts_2022.csv", 2379719, "0018a4833fbf0f825286c1c27450c6254391b548d6c55bcde728e93e4816815a"),
        2023: ("snap_counts_2023.csv", 2394875, "303b61aa5c33ffda863f93a750fc14483f397f9187ad502b1ce71e9b516a64c0"),
        2024: ("snap_counts_2024.csv", 2402841, "a2aa58efe093f8aa0ad5aadf09f81d8ec690a1183bd2dde68d20e7f109a9c335"),
    },
}
URLS = {
    "weekly_rosters": BASE + "/weekly_rosters/roster_weekly_{season}.csv",
    "snap_counts": BASE + "/snap_counts/snap_counts_{season}.csv",
}

# Independent team-alias authority pinned to a concrete nflverse/nfldata commit.
TEAM_MAP_COMMIT = "08adcd384baab25063ce3761fc994e931ce1ebc7"
TEAM_MAP_BLOB = "8c3683d118fa2362a7bcf61cbf95806639ae2d82"
TEAM_MAP_URL = (
    "https://raw.githubusercontent.com/nflverse/nfldata/"
    + TEAM_MAP_COMMIT
    + "/data/teams.csv"
)

# Deterministic hierarchy frozen before this gate executes.
HIERARCHY = (
    "H1_EXACT_PFR_RAW_TEAM_WEEK",
    "H2_EXACT_PFR_CANON_TEAM_WEEK",
    "H3_UNIQUE_PFR_WEEK",
    "H4_UNIQUE_PFR_SEASON",
    "H5_UNIQUE_EXACT_NAME_CANON_TEAM_WEEK",
    "H6_UNIQUE_EXACT_NAME_POSITION_SEASON",
)


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
        raise RuntimeError("2025 access blocked by identity-gate policy")
    req = urllib.request.Request(url, headers={"User-Agent": "AlphaProps-Identity-Gate/0.1"})
    with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as w:
        while True:
            b = r.read(1024 * 1024)
            if not b:
                break
            w.write(b)


def norm_text(x) -> str | None:
    if pd.isna(x):
        return None
    s = unicodedata.normalize("NFKD", str(x))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s or None


def materialize(raw: Path) -> list[dict]:
    raw.mkdir(parents=True, exist_ok=True)
    receipts = []
    for family in ("weekly_rosters", "snap_counts"):
        for season in SEASONS:
            name, expected_size, expected_sha = FILES[family][season]
            url = URLS[family].format(season=season)
            dest = raw / name
            print(f"MATERIALIZE {family} {season} {name}", flush=True)
            download(url, dest)
            actual_size = dest.stat().st_size
            actual_sha = sha256_file(dest)
            rec = {
                "family": family,
                "season": season,
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
                raise RuntimeError(f"locked source receipt failed: {rec}")

    team_path = raw / "nflverse_nfldata_teams.csv"
    download(TEAM_MAP_URL, team_path)
    receipts.append({
        "family": "team_alias_authority",
        "season": None,
        "name": team_path.name,
        "url": TEAM_MAP_URL,
        "pinned_commit": TEAM_MAP_COMMIT,
        "github_blob_sha1": TEAM_MAP_BLOB,
        "actual_size": team_path.stat().st_size,
        "actual_sha256": sha256_file(team_path),
        "status": "PASS_COMMIT_PINNED",
    })
    return receipts


def build_team_aliases(team_path: Path) -> tuple[dict[tuple[int, str], str], dict]:
    t = pd.read_csv(team_path, low_memory=False)
    t["season"] = pd.to_numeric(t["season"], errors="coerce")
    t = t[t["season"].isin(SEASONS)].copy()
    alt_cols = [c for c in ["team", "nfl", "espn", "pfr", "pfflabel", "fo"] if c in t.columns]

    rows = []
    conflicts = []
    for _, r in t.iterrows():
        season = int(r["season"])
        canon = norm_text(r["team"])
        if not canon:
            continue
        for col in alt_cols:
            alt = norm_text(r[col])
            if alt:
                rows.append((season, alt, canon, col))

    x = pd.DataFrame(rows, columns=["season", "alias", "canonical", "source_column"])
    grouped = x.groupby(["season", "alias"])["canonical"].agg(lambda s: sorted(set(s))).reset_index()
    for _, r in grouped.iterrows():
        if len(r["canonical"]) > 1:
            conflicts.append({
                "season": int(r["season"]),
                "alias": r["alias"],
                "canonical_candidates": r["canonical"],
            })

    conflict_keys = {(c["season"], c["alias"]) for c in conflicts}
    mapping = {}
    for _, r in grouped.iterrows():
        k = (int(r["season"]), r["alias"])
        if k not in conflict_keys and len(r["canonical"]) == 1:
            mapping[k] = r["canonical"][0]

    return mapping, {
        "source": TEAM_MAP_URL,
        "pinned_commit": TEAM_MAP_COMMIT,
        "blob_sha1": TEAM_MAP_BLOB,
        "alternate_columns": alt_cols,
        "unambiguous_alias_count": len(mapping),
        "conflicts": conflicts,
        "status": "PASS" if not conflicts else "PASS_CONFLICTS_EXCLUDED",
    }


def canon_team(season, team, mapping):
    try:
        s = int(season)
    except Exception:
        return norm_text(team)
    a = norm_text(team)
    return mapping.get((s, a), a) if a else None


def unique_lookup(df: pd.DataFrame, keys: list[str], value: str) -> tuple[dict, int]:
    d = df.dropna(subset=keys + [value]).copy()
    g = d.groupby(keys, dropna=False)[value].agg(lambda s: sorted(set(str(v) for v in s if pd.notna(v)))).reset_index()
    unique = {}
    ambiguous = 0
    for _, r in g.iterrows():
        vals = r[value]
        key = tuple(r[k] for k in keys)
        if len(vals) == 1:
            unique[key] = vals[0]
        elif len(vals) > 1:
            ambiguous += 1
    return unique, ambiguous


def main():
    root = Path("alphaodds_identity_runtime")
    raw = root / "raw"
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)

    receipts = materialize(raw)
    (out / "identity_source_receipts.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")

    team_map, team_audit = build_team_aliases(raw / "nflverse_nfldata_teams.csv")
    (out / "team_alias_audit.json").write_text(json.dumps(team_audit, indent=2), encoding="utf-8")

    snaps = pd.concat(
        [pd.read_csv(raw / f"snap_counts_{s}.csv", low_memory=False) for s in SEASONS],
        ignore_index=True,
        sort=False,
    )
    rosters = pd.concat(
        [pd.read_csv(raw / f"roster_weekly_{s}.csv", low_memory=False) for s in SEASONS],
        ignore_index=True,
        sort=False,
    )

    if HOLDOUT_SEASON in set(pd.to_numeric(snaps["season"], errors="coerce").dropna().astype(int)):
        raise RuntimeError("2025 snap rows detected")
    if HOLDOUT_SEASON in set(pd.to_numeric(rosters["season"], errors="coerce").dropna().astype(int)):
        raise RuntimeError("2025 roster rows detected")

    for d in (snaps, rosters):
        d["season"] = pd.to_numeric(d["season"], errors="coerce")
        d["week"] = pd.to_numeric(d["week"], errors="coerce")

    # Identity gate population only: regular-season QB/RB/WR/TE snap-history rows.
    snaps["position_norm"] = snaps["position"].map(norm_text)
    snaps["game_type_norm"] = snaps["game_type"].map(norm_text) if "game_type" in snaps.columns else "REG"
    pop = snaps[
        snaps["season"].isin(SEASONS)
        & snaps["position_norm"].isin(POSITIONS)
        & snaps["game_type_norm"].eq("REG")
    ].copy().reset_index(drop=True)
    pop["identity_row_id"] = range(len(pop))
    pop["pfr_id_norm"] = pop["pfr_player_id"].map(norm_text)
    pop["team_raw_norm"] = pop["team"].map(norm_text)
    pop["team_canon"] = [canon_team(s, t, team_map) for s, t in zip(pop["season"], pop["team"])]
    pop["name_norm"] = pop["player"].map(norm_text)

    rosters["pfr_id_norm"] = rosters["pfr_id"].map(norm_text)
    rosters["gsis_id_norm"] = rosters["gsis_id"].map(norm_text)
    rosters["team_raw_norm"] = rosters["team"].map(norm_text)
    rosters["team_canon"] = [canon_team(s, t, team_map) for s, t in zip(rosters["season"], rosters["team"])]
    rosters["name_norm"] = rosters["full_name"].map(norm_text)
    rosters["position_norm"] = rosters["position"].map(norm_text)
    if "game_type" in rosters.columns:
        rosters["game_type_norm"] = rosters["game_type"].map(norm_text)
        rosters = rosters[rosters["game_type_norm"].eq("REG")].copy()
    rosters = rosters[rosters["season"].isin(SEASONS)].copy()

    # Required exact roster PFR->GSIS source integrity.
    roster_id = rosters.dropna(subset=["pfr_id_norm", "gsis_id_norm"]).copy()
    pfr_to_gsis_global, pfr_global_ambiguous = unique_lookup(roster_id, ["pfr_id_norm"], "gsis_id_norm")

    # Fixed lookup layers.
    h1, h1_amb = unique_lookup(
        roster_id, ["season", "week", "pfr_id_norm", "team_raw_norm"], "gsis_id_norm"
    )
    h2, h2_amb = unique_lookup(
        roster_id, ["season", "week", "pfr_id_norm", "team_canon"], "gsis_id_norm"
    )
    h3, h3_amb = unique_lookup(
        roster_id, ["season", "week", "pfr_id_norm"], "gsis_id_norm"
    )
    h4, h4_amb = unique_lookup(
        roster_id, ["season", "pfr_id_norm"], "gsis_id_norm"
    )

    roster_named = rosters.dropna(subset=["name_norm", "gsis_id_norm"]).copy()
    h5, h5_amb = unique_lookup(
        roster_named,
        ["season", "week", "name_norm", "team_canon", "position_norm"],
        "gsis_id_norm",
    )
    h6, h6_amb = unique_lookup(
        roster_named,
        ["season", "name_norm", "position_norm"],
        "gsis_id_norm",
    )

    mapped_id = []
    mapped_layer = []
    team_changed = []
    for _, r in pop.iterrows():
        result = None
        layer = None
        pfr = r["pfr_id_norm"]

        if pfr:
            key = (r["season"], r["week"], pfr, r["team_raw_norm"])
            result = h1.get(key)
            if result:
                layer = "H1_EXACT_PFR_RAW_TEAM_WEEK"

        if not result and pfr:
            key = (r["season"], r["week"], pfr, r["team_canon"])
            result = h2.get(key)
            if result:
                layer = "H2_EXACT_PFR_CANON_TEAM_WEEK"

        if not result and pfr:
            key = (r["season"], r["week"], pfr)
            result = h3.get(key)
            if result:
                layer = "H3_UNIQUE_PFR_WEEK"

        if not result and pfr:
            key = (r["season"], pfr)
            result = h4.get(key)
            if result:
                layer = "H4_UNIQUE_PFR_SEASON"

        if not result and r["name_norm"]:
            key = (
                r["season"],
                r["week"],
                r["name_norm"],
                r["team_canon"],
                r["position_norm"],
            )
            result = h5.get(key)
            if result:
                layer = "H5_UNIQUE_EXACT_NAME_CANON_TEAM_WEEK"

        if not result and r["name_norm"]:
            key = (r["season"], r["name_norm"], r["position_norm"])
            result = h6.get(key)
            if result:
                layer = "H6_UNIQUE_EXACT_NAME_POSITION_SEASON"

        mapped_id.append(result)
        mapped_layer.append(layer)
        team_changed.append(
            bool(r["team_raw_norm"] and r["team_canon"] and r["team_raw_norm"] != r["team_canon"])
        )

    pop["gsis_id"] = mapped_id
    pop["identity_layer"] = mapped_layer
    pop["team_alias_changed"] = team_changed
    pop["mapped"] = pop["gsis_id"].notna()

    # CCA15: PFR source consistency. If a PFR identifier ever maps to a different GSIS
    # elsewhere in the locked roster family, any name-fallback result that conflicts is rejected.
    conflicts = []
    for i, r in pop[pop["mapped"] & pop["pfr_id_norm"].notna()].iterrows():
        unique_global = pfr_to_gsis_global.get(r["pfr_id_norm"])
        if unique_global and unique_global != r["gsis_id"]:
            conflicts.append({
                "identity_row_id": int(r["identity_row_id"]),
                "pfr_id": r["pfr_id_norm"],
                "mapped_gsis": r["gsis_id"],
                "global_unique_gsis": unique_global,
                "layer": r["identity_layer"],
            })
    if conflicts:
        bad = {c["identity_row_id"] for c in conflicts}
        pop.loc[pop["identity_row_id"].isin(bad), ["gsis_id", "identity_layer"]] = [None, None]
        pop["mapped"] = pop["gsis_id"].notna()

    total = int(len(pop))
    mapped = int(pop["mapped"].sum())
    coverage = float(mapped / total) if total else 0.0

    layer_counts = (
        pop["identity_layer"]
        .fillna("UNMATCHED")
        .value_counts(dropna=False)
        .rename_axis("layer")
        .reset_index(name="rows")
    )
    layer_counts["share"] = layer_counts["rows"] / total if total else 0.0

    season_position = (
        pop.groupby(["season", "position_norm"], dropna=False)["mapped"]
        .agg(["count", "sum"])
        .reset_index()
        .rename(columns={"count": "rows", "sum": "mapped_rows"})
    )
    season_position["coverage"] = season_position["mapped_rows"] / season_position["rows"]

    per_position = (
        pop.groupby(["position_norm"], dropna=False)["mapped"]
        .agg(["count", "sum"])
        .reset_index()
        .rename(columns={"count": "rows", "sum": "mapped_rows"})
    )
    per_position["coverage"] = per_position["mapped_rows"] / per_position["rows"]

    per_season = (
        pop.groupby(["season"], dropna=False)["mapped"]
        .agg(["count", "sum"])
        .reset_index()
        .rename(columns={"count": "rows", "sum": "mapped_rows"})
    )
    per_season["coverage"] = per_season["mapped_rows"] / per_season["rows"]

    unmatched = pop[~pop["mapped"]].copy()
    residue = {
        "unmatched_rows": int(len(unmatched)),
        "missing_pfr_id": int(unmatched["pfr_id_norm"].isna().sum()),
        "missing_name": int(unmatched["name_norm"].isna().sum()),
        "team_alias_changed_rows_total": int(pop["team_alias_changed"].sum()),
        "unmatched_by_position": unmatched["position_norm"].value_counts().to_dict(),
        "unmatched_by_season": {str(k): int(v) for k, v in unmatched["season"].value_counts().sort_index().items()},
        "top_unmatched_teams": unmatched["team_raw_norm"].value_counts().head(20).to_dict(),
    }

    ambiguity = {
        "H1_ambiguous_keys_excluded": h1_amb,
        "H2_ambiguous_keys_excluded": h2_amb,
        "H3_ambiguous_keys_excluded": h3_amb,
        "H4_ambiguous_keys_excluded": h4_amb,
        "H5_ambiguous_keys_excluded": h5_amb,
        "H6_ambiguous_keys_excluded": h6_amb,
        "global_pfr_ambiguous_keys": pfr_global_ambiguous,
        "cca15_cross_source_conflicts_rejected": len(conflicts),
    }

    gate_pass = bool(coverage >= COVERAGE_THRESHOLD and len(conflicts) == 0)
    status = "PASS_IDENTITY_COVERAGE_CLOSED" if gate_pass else "HOLD_IDENTITY_COVERAGE"

    cca15 = {
        "source_receipts": "PASS" if all(r["status"].startswith("PASS") for r in receipts) else "FAIL",
        "population_scope": "PASS_REGULAR_SEASON_QB_RB_WR_TE_ONLY",
        "team_alias_authority": team_audit["status"],
        "fallback_uniqueness": "PASS_AMBIGUITIES_EXCLUDED",
        "cross_source_identity_conflicts": "PASS_NONE_REMAINING" if len(conflicts) == 0 else "FAIL",
        "2025_access": "PASS_NOT_READ",
        "model_outcome_evaluation": "NOT_RUN",
        "threshold_mutation": "NONE_90_PERCENT_UNCHANGED",
        "status": "PASS" if gate_pass else "HOLD",
    }

    low_strata = []
    for _, r in per_position.iterrows():
        if float(r["coverage"]) < COVERAGE_THRESHOLD:
            low_strata.append({
                "position": r["position_norm"],
                "coverage": float(r["coverage"]),
                "rows": int(r["rows"]),
            })

    defense = {
        "circular_mapping": "PASS_NO_MODEL_OUTCOMES_OR_PROP_PRICES_USED",
        "team_alias_normalization": "PASS_SEASON_SPECIFIC_NFLVERSE_NFLDATA_COMMIT_PINNED",
        "fuzzy_name_matching": "PROHIBITED_NOT_USED",
        "ambiguous_fallbacks": "EXCLUDED",
        "trade_team_risk": "CONTROLLED_PFR_ID_UNIQUENESS_BEFORE_NAME_FALLBACK",
        "population_denominator": "QB_RB_WR_TE_REGULAR_SEASON_SNAP_ROWS_ONLY",
        "position_strata_below_90pct": low_strata,
        "posthoc_threshold_change": "NONE",
        "2024_projection_metrics": "NOT_READ_OR_RECOMPUTED",
        "status": "PASS" if gate_pass else "HOLD",
    }

    report = {
        "gate": "ALPHAPROPS SNAP IDENTITY COVERAGE CLOSURE",
        "seasons": list(SEASONS),
        "holdout_not_read": HOLDOUT_SEASON,
        "coverage_threshold": COVERAGE_THRESHOLD,
        "identity_hierarchy": list(HIERARCHY),
        "team_alias_audit": team_audit,
        "population": {
            "rows": total,
            "mapped_rows": mapped,
            "coverage": coverage,
            "status": status,
        },
        "layer_counts": layer_counts.to_dict(orient="records"),
        "per_position": per_position.to_dict(orient="records"),
        "per_season": per_season.to_dict(orient="records"),
        "season_position": season_position.to_dict(orient="records"),
        "ambiguity_controls": ambiguity,
        "unmatched_residue": residue,
        "cca15": cca15,
        "defense_red_team": defense,
        "freeze_effect": (
            "ROLE_HISTORY_GATE_CLOSED_ELIGIBLE_FOR_EXISTING_FREEZE_DECISION_PATH"
            if gate_pass
            else "ROLE_HISTORY_GATE_REMAINS_OPEN_MODEL_NOT_FROZEN"
        ),
        "model_specification_changes": "NONE",
        "historical_prop_profitability": "NOT_TESTED_NO_AUTHENTICATED_PRICE_ARCHIVE",
        "wager_execution": "DISABLED",
    }

    (out / "identity_coverage_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    layer_counts.to_csv(out / "identity_layer_counts.csv", index=False)
    season_position.to_csv(out / "identity_coverage_by_season_position.csv", index=False)
    unmatched[
        [
            c for c in [
                "season", "week", "position", "player", "pfr_player_id", "team",
                "team_raw_norm", "team_canon", "offense_snaps", "offense_pct",
            ] if c in unmatched.columns
        ]
    ].to_csv(out / "unmatched_identity_rows.csv", index=False)

    md = [
        "# ALPHAPROPS SNAP IDENTITY COVERAGE CLOSURE GATE",
        "",
        f"Status: {status}",
        f"Population: {total:,} regular-season QB/RB/WR/TE snap-history rows",
        f"Mapped: {mapped:,}",
        f"Coverage: {coverage:.4%}",
        f"Frozen threshold: {COVERAGE_THRESHOLD:.0%}",
        "",
        "No 2024 projection metrics were read or recomputed.",
        "2025 was not downloaded, opened, or read.",
        "No profitability claim was tested and wager execution remained disabled.",
        "",
        "## Identity hierarchy",
    ] + [f"- {x}" for x in HIERARCHY]
    md += ["", "## CCA15", json.dumps(cca15, indent=2), "", "## Defense Red Team", json.dumps(defense, indent=2)]
    (out / "IDENTITY_GATE_RESULT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("ALPHAPROPS_IDENTITY_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("ALPHAPROPS_IDENTITY_REPORT_END")
    return 0 if gate_pass else 3


if __name__ == "__main__":
    raise SystemExit(main())
