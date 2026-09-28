# ALPHABREADTH WEEK 5 PRE-MARKET PROP WATCHLIST — 2026-09-27

## Status
PRICE_HOLD / PROJECTIONS FROZEN BEFORE MARKET

## Source run
GitHub Actions run 36370438373
Artifact SHA-256: 27c6361f2f0959101156f1b304b9ddf2b3a828fca090929f9cd9a69274eeef7c

## Frozen AP-RB1 projection universe
- Games: 16
- Active/recent-participant projection rows: 483
- QB passing-yards projections: 37
- RB rushing-yards projections: 82
- WR receiving-yards projections: 118
- WR receptions projections: 118
- TE receiving-yards projections: 64
- TE receptions projections: 64
- Latest published weekly roster used: Week 3
- Target week: Week 4
- Players removed for insufficient recent offensive participation: 200

## Pre-market watchlist compression
For monitoring only, before sportsbook lines:
- 1 highest-projected QB passing-yards candidate per team where available;
- up to 2 highest-projected RB rushing-yards candidates per team;
- up to 3 highest-projected WR/TE receiving-yards candidates per team.

This produces 192 watchlist rows across 32 teams.

This is a **market-monitor list**, not 192 wagers and not 192 independent opportunities.

## Correlation control
AlphaCreative / AlphaBreadth must collapse candidates into risk clusters after lines appear.

Examples:
- QB passing OVER + WR receiving OVER from the same offense -> PASSING-SCRIPT cluster.
- Two receiving OVERs on the same team -> shared passing-volume cluster.
- RB rushing OVER + opposing passing OVER can share a favorable-lead game script and require explicit correlation review.
- First-TD + anytime-TD on the same player -> SCORER cluster.
- Spread + moneyline on the same side -> SIDE cluster.

## Representative frozen projections to watch

### Baltimore vs Tennessee
BAL:
- Lamar Jackson passing yards: 165.05
- Derrick Henry rushing yards: 70.97
- Zay Flowers receiving yards: 62.14
- Mark Andrews receiving yards: 43.87
TEN:
- Cam Ward passing yards: 175.59
- Tony Pollard rushing yards: 56.85
- Carnell Tate receiving yards: 66.24
- Wan'Dale Robinson receiving yards: 56.68

### Miami vs Minnesota
MIA:
- Malik Willis passing yards: 155.58
- De'Von Achane rushing yards: 37.32
- Ollie Gordon II rushing yards: 34.17
MIN:
- Kyler Murray passing yards: 169.58
- Aaron Jones rushing yards: 64.83
- Justin Jefferson receiving yards: 60.06
- T.J. Hockenson receiving yards: 35.80

### Pittsburgh vs Cleveland
PIT:
- Aaron Rodgers passing yards: 196.52
- Jaylen Warren rushing yards: 59.90
- DK Metcalf receiving yards: 52.05
- Pat Freiermuth receiving yards: 28.35
CLE:
- Deshaun Watson passing yards: 234.01
- Quinshon Judkins rushing yards: 51.97
- Denzel Boston receiving yards: 49.64
- KC Concepcion receiving yards: 44.48

## Market gate when lines appear
For each watchlist row:
1. authenticate book / line / price / timestamp;
2. verify player availability and expected role;
3. calculate projection-minus-line gap;
4. compare gap to the model's historical validation error for that market;
5. classify QUALIFIED / SHADOW / PRICE_HOLD / INJURY_HOLD / NO_EDGE;
6. assign correlation cluster;
7. count independent opportunities, not tickets.

## Integrity note
An earlier raw roster projection pass produced 990 rows and was quarantined.
A second workflow falsely appeared successful because a Python error was piped through tee without pipefail; that run was also quarantined.
The workflow was corrected to fail on Python pipeline errors, and the active-participant gate produced the successful 483-row board above.

## External action
Research only. No wager placement or sportsbook transmission.
