# ALPHAPROFIT MATCHUP-CONDITIONED PROSPECTIVE FREEZE — v1.0

## Mission
Prospectively test whether matchup alignment and injury/role redistribution improve the AlphaProfit first-touchdown architecture without changing frozen team/player selectors after outcomes.

## Frozen execution order
1. **Team Gate** — only games with an authenticated pre-kickoff favorite of at least 7 points qualify.
2. **Matchup Gate** — compare the favorite's prior-eight offensive TD route profile with the opponent's prior-eight TD routes allowed.
3. **Injury / Role Redistribution Audit** — use only information authenticated before kickoff. Identify material absences or role changes that could redistribute red-zone/goal-line opportunity. This layer may flag uncertainty or identify which already-defined lane is stressed; it may not invent a new scorer rule after outcomes.
4. **Player DNA** — freeze Slot A, Slot B, and Dynamic Slot C exactly under the existing selector definitions.
5. **Price Freeze** — record timestamped first-TD prices before kickoff. Missing prices are missing; never impute.
6. **Shadow Stake Grade** — record both:
   - Baseline: 45 / 45 / 10
   - Challenger: 25 / 25 / 50
7. **Outcome Grade** — populate results only after kickoff/outcome.
8. **No-Bet Rule** — if Team Gate fails, official research status is NO QUALIFIER. Do not override because the matchup "looks good."

## Rams live-diagnostic quarantine — 2026-09-27
- Los Angeles Rams at Denver Broncos was already in progress when inspected.
- Pregame market evidence showed the Rams around -1.5, therefore this game was outside the frozen 7+ Team Gate.
- Puka Nacua was known pregame to be unavailable.
- Tyler Higbee scored the first TD live; contemporaneous public pregame sources listed Higbee around +1600 to +2000 first TD.
- Kyren Williams showed meaningful live rushing and receiving involvement.
- These are **challenger observations only**. They may motivate a prospective injury/role-redistribution feature, but may not change any frozen selector or threshold retrospectively.

## Prospective checkpoint — Philadelphia at Chicago, 2026-09-28
- Current public market range observed on 2026-09-27: Philadelphia approximately -3.5 to -5 depending on source/book.
- Result: **TEAM GATE FAIL — NO QUALIFIER** because the favorite is below 7 points.
- Significant pregame absences include Chicago QB Caleb Williams (out) and Philadelphia TE Dallas Goedert / WR Marquise Brown (out).
- Injuries do not override the Team Gate.
- No A/B/C player freeze is authorized for this game under the official prospective lane.
- If maintained as an exploratory side study, it must be labeled CHALLENGER ONLY and segregated from the official prospective ledger.

## Promotion standard
No matchup, injury, price, or stake rule may be promoted from a single game. Promotion requires a prospective sample and must preserve:
- no hindsight;
- source timestamps;
- board completeness;
- exact miss taxonomy;
- worst-case-loss accounting;
- no profitability claim without authenticated prices.

## External action
Research only. No wager placement or sportsbook transmission.


## Spread-Threshold Shadow Lanes — added 2026-09-27 before future grading

The retrospective Spread-Threshold Robustness Gate tested every 0.5-point threshold from 0.5 through 14.0 across 2021-2024 regular-season games.

No historical result is permitted to retroactively replace the original 7+ baseline.

Three prospective lanes are frozen:

### Lane T7 — Baseline
- Qualification: favorite by at least 7.0 points.
- Historical reference only: 296 games, 65.20% favorite-first TD.
- Purpose: preserve continuity with the original architecture.

### Lane T8 — Stability Challenger
- Qualification: favorite by at least 8.0 points.
- Historical reference only: 195 games, 71.28% favorite-first TD.
- Historical season floor: 68.57%, the strongest minimum-season rate among tested thresholds with at least 100 games.
- Purpose: test whether a modestly stricter favorite threshold improves reliability without collapsing sample size.

### Lane T10 — High-Conviction Challenger
- Qualification: favorite by at least 10.0 points.
- Historical reference only: 134 games, 73.88% favorite-first TD.
- Historical 95% Wilson lower bound: 65.85%, the strongest among tested thresholds with at least 100 games.
- Purpose: test whether very strong favorites create a meaningfully better first-TD environment despite lower frequency.

### Prospective adjudication
- T7, T8, and T10 are graded simultaneously whenever applicable.
- A game may qualify for multiple nested lanes.
- Outcomes may not alter the lane definitions.
- The 8+ or 10+ lanes may only replace the baseline after a prospectively defined checkpoint with sufficient sample.
- Matchup, injury, A/B/C, price, and stake controls remain identical across lanes.
- No profitability claim is permitted from historical threshold differences alone.


## Matchup-Conditioned Price Hurdles — frozen 2026-09-27

These hurdles are retrospective reference points only and are frozen for prospective shadow classification. They do not establish profitability.

### Classification
- **CORE_PASS** — actual timestamped pre-kickoff odds are at or above the conservative 95% Wilson hurdle, and the historical cell has at least 20 reference games.
- **RAW_PASS_ONLY** — actual odds clear the raw break-even hurdle but not the conservative hurdle; shadow only.
- **PRICE_FAIL** — actual odds are below the raw break-even hurdle.
- **NO_REFERENCE** — fewer than 20 reference games, zero historical hits, or no usable route cell.
- **NO_PRICE** — missing authenticated pre-kickoff price; never impute.

### Moderate-support reference cells

#### T7 BASE — GROUND
- Slot A: raw +345; conservative +668; n=49.
- Slot B: raw +1533; conservative +4653; n=49.
- Slot C: raw +1533; conservative +4653; n=49.

#### T7 BASE — WRTE_REC
- Slot A: raw +500; conservative +772; n=144.
- Slot B: raw +1957; conservative +4112; n=144.
- Slot C: raw +1500; conservative +2910; n=144.

#### T8 ALIGNED — WRTE_REC
- Slot A: raw +480; conservative +937; n=58.
- Slot B: raw +1350; conservative +3584; n=58.
- Slot C: raw +1060; conservative +2575; n=58.

### Shadow-only / no automatic CORE_PASS
- T8 ALIGNED — GROUND: n=18, sparse.
- T10 ALIGNED — GROUND: n=11, sparse.
- T10 ALIGNED — WRTE_REC: n=38, thin.
- RB_REC matchup-route cells: no usable historical reference in the current taxonomy.

### Prospective rule
For every future qualifier:
1. determine T7/T8/T10 membership;
2. determine matchup alignment and matchup route;
3. freeze A/B/Dynamic-C;
4. record authenticated pre-kickoff prices;
5. classify each ticket CORE_PASS / RAW_PASS_ONLY / PRICE_FAIL / NO_REFERENCE / NO_PRICE before kickoff;
6. shadow-grade all classifications after the outcome;
7. do not alter hurdles until a predeclared prospective checkpoint.

The price gate may remove or downgrade a ticket, but it may not increase the $100 research-unit cap or create a fourth ticket.
