# ALPHAPROFIT MORNING RETURN POINT — 2026-09-27

## Bookmark status
FROZEN RETURN POINT

## Where we stopped
The Week-5 / Week-4 Player-Prop Line-Ingest, Edge & Correlation Gate is at:

**SOURCE_HOLD**

The AP-RB1 current-week projection board was frozen before sportsbook player-prop lines were accepted.

### Valid frozen projection source
- GitHub Actions run: 36370438373
- Artifact SHA-256:
  27c6361f2f0959101156f1b304b9ddf2b3a828fca090929f9cd9a69274eeef7c
- Pre-market watchlist commit:
  94f193d271ca640c88894eb72e9c3d4e942e9013

### Current prop-ingest checkpoint
- Commit:
  cc4942cfd3f7242e6a51227e8e3eafe7aa66a684
- Player-prop lines remain SOURCE_HOLD until exact target game, player, market, book, line, price and timestamp are authenticated.
- No projections may be changed after market lines appear.

## Frozen edge hurdles
QUALIFIED_CHALLENGER requires at least 0.50 of AP-RB1 2024 validation MAE plus source/price/injury/role pass.

Approximate 0.50-MAE gaps:
- QB passing yards: 34.94
- RB rushing yards: 10.35
- WR receiving yards: 10.85
- WR receptions: 0.73
- TE receiving yards: 8.08
- TE receptions: 0.67

0.35–0.50 MAE = STRONG_SHADOW only.

## Correlation controls
Count independent risk clusters, not raw tickets.
Examples:
- same-team QB passing OVER + receiver OVERs = PASSING_SCRIPT cluster
- spread + moneyline same team = SIDE cluster
- first-TD + anytime-TD same player = SCORER cluster
- multiple props driven by same high/low scoring environment = GAME_TOTAL cluster

## AlphaCreative / AlphaBreadth status
- Agent 24 AlphaCreative: ACTIVE
- Agent 25 AlphaBreadth: ACTIVE
- First-TD lane: preserved
- Side/Total lane: simple baseline rejected; deeper matchup version next
- Player-prop lane: projections frozen, awaiting clean target-game market lines
- Profitability claim: HOLD
- Wager execution: DISABLED

## Week 5 strong-favorite checkpoint
Early Covers checkpoint identified:
- Baltimore vs Tennessee: BAL approximately -10.5
- Minnesota vs Miami: MIN approximately -10.5
Lines must be rechecked before final threshold classification.

Prior matchup source pack:
- GitHub Actions run: 36369042841
- Artifact SHA-256:
  413c5871d65aa20a2b0100bd0d666f51ac4a21b6d686521aef52cf63b113d9ad

## EXACT NEXT RECOMMENDED COMMAND

**ALPHABREADTH WEEK-5 SIDE/TOTAL MATCHUP UPGRADE GATE**

Preserve the frozen T7/T8/T10, matchup, injury/role, AlphaCreative, AlphaBreadth and player-prop SOURCE_HOLD controls; use authenticated current game-level spreads and totals to build a deeper no-hindsight SIDE/TOTAL challenger using offense-vs-defense matchup DNA, red-zone/explosive scoring, pressure/QB interaction, pace/opportunity, injuries, home/away, rest/travel and weather where source-safe; validate without lowering thresholds merely to create action; continue monitoring target-game player-prop boards and ingest them only when exact game/player/market/book/line/price/timestamp attribution is available; count independent risk clusters rather than raw tickets; do not place or transmit any wager.

## Morning shorthand
User can say:

**"Chief, resume AlphaProfit from the morning bookmark."**

and resume directly from the SIDE/TOTAL MATCHUP UPGRADE GATE above.
