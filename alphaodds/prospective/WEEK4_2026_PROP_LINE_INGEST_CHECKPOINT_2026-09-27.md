# ALPHABREADTH WEEK 4/5 PROP LINE-INGEST, EDGE & CORRELATION GATE — CHECKPOINT 2026-09-27

## Status
**SOURCE_HOLD — TARGET-GAME PLAYER-PROP ATTRIBUTION NOT YET CLEAN**

Research only. No wager placement or sportsbook transmission.

## Frozen projection source
- AP-RB1 model specification unchanged.
- Current Week 4 projection board: GitHub Actions run 36370438373.
- Valid active/recent-participant artifact SHA-256:
  27c6361f2f0959101156f1b304b9ddf2b3a828fca090929f9cd9a69274eeef7c
- Pre-market watchlist commit:
  94f193d271ca640c88894eb72e9c3d4e942e9013
- Projections were frozen before target-game prop lines were accepted.

## Target games currently prioritized
- Pittsburgh at Cleveland — 2026-10-01
- Tennessee at Baltimore — 2026-10-04
- Miami at Minnesota — 2026-10-04

## Current line-source audit

### GameDay Analytics / Hard Rock Bet feed
The public Prop Finder currently shows book lines captured 2026-09-27 at 2:30 PM CT, including:
- Deshaun Watson passing yards 188.5, O/U -115
- Lamar Jackson passing yards 242.5, O/U -115
- Aaron Rodgers passing yards 223.5, O/U -115
- Kyler Murray passing yards 215.5, O/U -115
- Malik Willis passing yards 176.5, O/U -115

These are **NOT ingested into the Week 4/target-game economic gate** because the page does not expose sufficient event-level attribution proving that each cached line belongs to the target Oct. 1/4 game rather than the player's Sep. 27 game/just-closed market.

Disposition: QUARANTINE_SOURCE_ATTRIBUTION.

### RotoWire PIT-CLE page
- Game page is correctly attributed to 2026-10-01.
- It exposes lineups/injury context.
- Player-prop module currently renders as "Loading Possible Bets" / dynamic content in the accessible source, without auditable numeric target-game prop lines.

Disposition: SOURCE_HOLD_FOR_PLAYER_LINES.

### DraftKings public page
- PIT-CLE game-level spread/total/moneyline is visible for the future game.
- Publicly indexed player-prop content remains dominated by Sep. 27 games/promotional markets; no auditable Oct. 1 yardage/reception board was recovered.

Disposition: SOURCE_HOLD_FOR_AP-RB1_MARKETS.

## Current game-level market checkpoint
Game-level prices may be used for SIDE/TOTAL research, not for PROP economics.
- PIT at CLE: market roughly PIT -2.5 to -3, total roughly 37.5 to 40.5 depending source/time.
- TEN at BAL: BAL roughly -8.5, total about 47.5.
- MIA at MIN: sources disagree materially, including MIN -7.5 and MIN -10.5 snapshots; final threshold lane must be rechecked before freeze.

## Player injury / role controls
- Any player with a current injury/questionable designation is INJURY_HOLD until role/status is authenticated closer to kickoff.
- A posted prop line does not override an injury/role hold.
- Lines for players absent from the frozen active-participant board are ignored unless the projection gate is explicitly rerun before outcome exposure.

## Edge classification once target-game lines are authenticated
For each player/market:
1. Match exact target game, player, market, book, line, price and timestamp.
2. Confirm timestamp is before kickoff.
3. Confirm injury/role status.
4. Compute projection - line.
5. Standardize the gap by the frozen AP-RB1 2024 validation MAE for that market.
6. Classify:
   - QUALIFIED_CHALLENGER: |gap| >= 0.50 MAE and price/source/role pass.
   - STRONG_SHADOW: |gap| >= 0.35 MAE but < 0.50 MAE.
   - NO_EDGE: |gap| < 0.35 MAE.
   - PRICE_HOLD / SOURCE_HOLD / INJURY_HOLD when any required input is unresolved.
7. Never change a frozen projection after seeing the sportsbook line.

## Frozen AP-RB1 validation MAE references
- QB passing yards: 69.8893
- RB rushing yards: 20.7004
- WR receiving yards: 21.6908
- WR receptions: 1.4537
- TE receiving yards: 16.1601
- TE receptions: 1.3316

### Corresponding 0.50-MAE challenger gaps
- QB passing yards: 34.94 yards
- RB rushing yards: 10.35 yards
- WR receiving yards: 10.85 yards
- WR receptions: 0.73 receptions
- TE receiving yards: 8.08 yards
- TE receptions: 0.67 receptions

These are research-screening hurdles, not proven profitability thresholds.

## Correlation clusters
Candidates are not counted as independent merely because they are different tickets.

### PASSING_SCRIPT_{TEAM}
Examples:
- QB passing OVER
- WR/TE receiving OVER
- WR/TE receptions OVER
Positive same-offense overs share volume/game-script risk.

### RUN_SCRIPT_{TEAM}
Examples:
- RB rushing OVER
- favorite spread / moneyline
- opposing QB passing attempts/yardage may correlate through trailing script.

### NEGATIVE_PASSING_SCRIPT_{TEAM}
QB passing UNDER plus multiple receiver UNDERs share the same failure mode.

### SCORER_{PLAYER}
First-TD + anytime-TD for the same player are one scorer-risk cluster.

### GAME_TOTAL_{GAME}
Multiple player overs/unders that depend on the same high/low scoring environment require a shared game-total tag.

### SIDE_{TEAM}
Moneyline + spread on the same team are one side-risk cluster.

## Independent opportunity accounting
Weekly opportunity count is the number of surviving risk clusters after:
- source;
- price;
- injury;
- projection-gap;
- matchup;
- and correlation controls.

Raw prop count is never used as the mission score.

## AlphaCreative Innovation Memo
- What passed: projection-before-market freeze and active-participant filtering.
- What failed: treating any web-visible line as a valid target-game prop without event attribution.
- Largest unresolved dependency: target-game-specific AP-RB1 market lines and prices.
- New useful information: the public market has opened game-level Week 4 sides/totals while many player yardage/reception props remain unavailable or unattributed.
- Best next falsifiable experiment: ingest the first event-attributed PIT-CLE lines, apply fixed MAE-normalized edge hurdles, and compare candidates with external injury/matchup context.
- Anti-loop: do not lower edge thresholds merely to increase weekly opportunity count.
- Status: SOURCE_RECOVERY / PRICE_HOLD.

## External action
Research only. No wager execution.
