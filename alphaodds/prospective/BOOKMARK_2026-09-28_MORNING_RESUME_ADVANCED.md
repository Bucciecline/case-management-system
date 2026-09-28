# ALPHAPROFIT MORNING RESUME CHECKPOINT — 2026-09-28

## Resumed from
BOOKMARK_2026-09-27_MORNING_RETURN_POINT.md

## Date-label correction
The October 1-4, 2026 NFL slate is Week 4 in the current schedule feed.
Older repository files using "Week 5" remain unchanged for audit continuity, but new analysis uses Week 4.

## SIDE/TOTAL MATCHUP UPGRADE GATE

GitHub Actions run: 36424802011
Artifact SHA-256:
2c56dac2ec30f7fc29c494f37144378073595cc2470c6dd2fc7b7ad0052f340a

Design:
- Train: 2021-2022
- Calibration: 2023 only
- Validation: 2024 untouched
- Current projection: 2026 Week 4
- Features: rolling 3/5/8 scoring, EPA, success, explosive plays, red-zone TD, pressure/sack, pass rate, play volume, opponent interactions, rest, market context.
- Weather/injuries kept outside core model as source-safe overlays.

### SIDE
2023 chosen confidence threshold: 0.03
2024 validation:
- n = 246
- wins = 120
- hit rate = 48.78%
- Wilson 95% lower = 42.60%

Disposition: REJECT.

### TOTAL
2023 chosen confidence threshold: 0.20
2024 validation:
- n = 132
- wins = 59
- hit rate = 44.70%
- Wilson 95% lower = 36.48%

Disposition: REJECT.

## AlphaCreative anti-loop decision
This is the second generic SIDE/TOTAL architecture that failed to demonstrate a credible validation edge.
Do not:
- lower confidence thresholds;
- tune on 2024;
- cherry-pick current Week 4 model flags;
- market the 13 SIDE / 5 TOTAL current challenger labels as betting opportunities.

Move one layer away from this structural failure.

## Current-market source notes
- Covers currently shows MIA at MIN around MIN -10.5 / total 43.5 in the matchup/picks surface.
- Covers currently shows TEN at BAL around BAL -11.5 in its consensus surface, demonstrating line movement from the earlier -10.5 checkpoint.
- PIT at CLE is currently surfaced around PIT -2.5 in Covers consensus.
All threshold lanes must be rechecked before any final freeze.

## Player-prop / TD priority
The Week 4 player-prop projection board remains frozen before market ingestion.
Current public event pages correctly attribute:
- PIT at CLE — Oct 1, 2026
- TEN at BAL — Oct 4, 2026
- MIA at MIN — Oct 4, 2026

However, accessible RotoWire event pages currently render the player-prop module as "Loading Possible Bets" rather than exposing auditable numeric yardage/reception lines in the static source.

Therefore:
- PROP remains SOURCE_HOLD for exact target-game lines/prices.
- Do not reuse unattributed cached prop numbers.
- Injury/role context may be updated independently, but projections remain frozen.

## Current useful injury/role context
- PIT-CLE event page identifies Jaylen Warren as questionable and shows current expected lineups.
- TEN-BAL event page identifies active current offensive lineups and recent role evidence; Mark Andrews had a hand issue in Week 3 but returned, Zay Flowers returned from hamstring issue and produced 84 receiving yards plus a 20-yard rush, Derrick Henry handled 26 carries.
These are context overlays only, not model retuning inputs.

## Agent status
- Agent 24 AlphaCreative: ACTIVE
- Agent 25 AlphaBreadth: ACTIVE
- First-TD lane: ACTIVE / selective
- PROP lane: ACTIVE / SOURCE_HOLD
- TD lane: ACTIVE / PRICE-SOURCE recovery
- SIDE lane: REJECTED generic architecture
- TOTAL lane: REJECTED generic architecture
- Profitability claim: HOLD
- Wager execution: DISABLED

## EXACT NEXT RECOMMENDED COMMAND

**ALPHABREADTH WEEK-4 EVENT-ATTRIBUTED PROP / TD SOURCE-RECOVERY GATE**

Preserve all frozen AP-RB1 projections, FT selectors, T7/T8/T10 controls, AlphaCreative anti-loop controls, and correlation clusters. Recover only target-game-specific player-prop and TD markets that expose exact game, player, market, line/odds, book/source and pre-kickoff timestamp. Prioritize PIT-CLE because it is the first kickoff, then TEN-BAL and MIA-MIN. Apply the frozen 0.50-MAE / 0.35-MAE prop gap classifications and existing first-TD price hurdles only after exact source attribution; update injury/role overlays without changing frozen projections; count independent risk clusters rather than tickets; do not place or transmit wagers.

## Morning resume status
Execution has advanced beyond the prior bookmark. Resume from the PROP / TD source-recovery gate above.
