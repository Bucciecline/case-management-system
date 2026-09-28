# ALPHACREATIVE MATCHUP-CONDITIONED STAKE ROUTING GATE — 2026-09-27

## Status
**HOLD — ROUTING ECONOMICS NOT IDENTIFIED FROM CURRENT PRICE ARCHIVE**

Research only. No wager execution.

## Frozen inputs
- T7 / T8 / T10 thresholds remain unchanged.
- Matchup alignment definition remains unchanged.
- Matchup routes remain GROUND / WRTE_REC / RB_REC.
- Slot A / Slot B / Dynamic Slot C remain unchanged.
- No target-game input is used for pregame classification.

## AlphaCreative finding
The data reject a naive rule that automatically shifts more stake toward whichever route is labeled the matchup route.

Historical lane support is asymmetric:
- Slot A improves when the matchup route is GROUND.
- Slot B does not improve merely because the matchup route is WRTE_REC.
- Dynamic Slot C does not improve simply because its receiving lane matches the generic route label.

Therefore the useful signal is **selective**, not symmetrical.

## T8 + style-aligned historical diagnostic
T8 aligned games: 76
- Favorite first TD: 80.26%
- A+B+C first-TD hit: 35.53%

### T8 aligned — GROUND route
18 games
- Favorite first TD: 83.33%
- A+B+C hit: 44.44%
- Slot A hit: 27.78% → raw fair price about +260
- Slot B hit: 5.56% → raw fair price about +1700
- Slot C hit: 11.11% → raw fair price about +800

### T8 aligned — WRTE_REC route
58 games
- Favorite first TD: 79.31%
- A+B+C hit: 32.76%
- Slot A hit: 17.24% → raw fair price about +480
- Slot B hit: 6.90% → raw fair price about +1350
- Slot C hit: 8.62% → raw fair price about +1060

These fair prices are retrospective break-even references only, before vig and uncertainty. They are not validated live thresholds.

## Authenticated price archive limitation
The strict late-2024 price archive has seven complete A/B/C games:
- four style-aligned;
- three style-conflict;
- six WRTE_REC route;
- one GROUND route.

The only GROUND price-complete game was style-conflict and lost.
All four style-aligned priced games were WRTE_REC.

Therefore there is **no authenticated historical price sample capable of comparing aligned GROUND stake routing against aligned WRTE stake routing**.

Any claim that one route-specific stake allocation is economically superior would be overfit.

## Existing price diagnostic
On the same seven complete-price games:
- 45/45/10: -86.43% ROI
- 35/35/30: -59.29% ROI
- 25/25/50: -32.14% ROI
- matchup 2x tilt: -45.71% ROI

On the four style-aligned games only:
- 25/25/50: +18.75% ROI

This four-game result is too small for promotion.

## AlphaCreative structural conclusion
The next highest-information layer is **price gating**, not another fixed stake percentage.

Reason:
1. Matchup context improves team/route diagnosis.
2. Slot hit probabilities vary materially by matchup route.
3. Real first-TD prices vary even more.
4. Without requiring a price to clear a route-specific break-even hurdle, stake routing can simply concentrate money on an overpriced ticket.

## Next falsifiable experiment
**ALPHACREATIVE MATCHUP-CONDITIONED PRICE-HURDLE GATE**

Prospectively shadow:
- T7 baseline;
- T8 aligned challenger;
- T10 aligned challenger.

For each frozen A/B/C ticket:
1. identify the frozen matchup route;
2. record actual timestamped first-TD price;
3. compare price to the predeclared route/threshold hurdle;
4. mark PRICE PASS / PRICE FAIL before kickoff;
5. keep a no-price / missing-price state rather than imputing;
6. shadow-grade any stake architecture separately.

No route-specific hurdle may be promoted from retrospective performance alone.

## Disposition
- Fixed matchup stake routing: HOLD.
- Ground support for Slot A: promising challenger.
- Receiver-route automatic stake boost: REJECT as unsupported.
- Style-alignment participation filter: continue prospectively.
- Price-hurdle layer: NEXT TEST.
- Profitability claim: HOLD.
- Wager execution: DISABLED.
