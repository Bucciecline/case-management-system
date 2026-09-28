# ALPHABREADTH WEEKLY MULTI-MARKET RESEARCH PROTOCOL — v1.0

## Objective
Increase the number of weekly NFL research opportunities without weakening the first-touchdown system or treating correlated tickets as independent edges.

## Independent lanes

### FT — First Touchdown
- Existing T7/T8/T10 + matchup + injury/role + A/B/Dynamic-C + price hurdles.
- Selective by design.

### SIDE — Spread / Moneyline
- Every NFL game may enter the research universe.
- Require pregame model edge versus market spread/moneyline.
- ATS and ML are separate economic expressions of the same team-side thesis and belong to one risk cluster unless proven orthogonal.

### TOTAL — Full-game Over / Under
- Every game with an authenticated total may enter.
- Pregame inputs: prior scoring/allowance, pace/opportunity when source-safe, explosive scoring, red-zone efficiency, matchup style and weather/injury when timestamped.
- OVER and UNDER are mutually exclusive directions within one game-total risk cluster.

### PROP — Player statistical props
Frozen AP-RB1 target families:
- QB passing yards
- RB rushing yards
- WR receiving yards
- WR receptions
- TE receiving yards
- TE receptions
A player prop becomes a candidate only after line + price are authenticated before kickoff.

### TD — Anytime / First-TD
- Anytime TD and First-TD are different markets.
- Player DNA may be shared as a feature source, but price and settlement audits remain separate.

## Opportunity accounting
Do not count raw tickets. Count **independent risk clusters**.

Examples:
- Team ML + team spread = one SIDE cluster unless their terminal-state economics are explicitly separated.
- QB pass over + WR receiving over from the same passing-script thesis are correlated and tagged to one PASSING cluster.
- RB rush over + team under may share game-script dependence and require correlation notation.
- First-TD player + anytime-TD same player are one SCORER cluster for portfolio exposure purposes.

## Weekly breadth dashboard
For every game:
- SIDE status
- TOTAL status
- FT status
- PROP candidates
- TD candidates
- source/price status
- correlation cluster ID
- independent opportunity count
- worst-case cluster loss

## Lane statuses
- QUALIFIED
- SHADOW
- PRICE_HOLD
- SOURCE_HOLD
- MODEL_HOLD
- NO_EDGE
- NO_MARKET

## Research order
1. Build historical SIDE and TOTAL baselines with no-hindsight features.
2. Use the already-frozen AlphaProps baseline for PROP opportunity generation.
3. Keep FT lane unchanged.
4. Add actual pregame market lines/prices.
5. Measure per-lane opportunity frequency by week.
6. Measure per-lane calibration and economics separately.
7. Build portfolio only after lane validation.

## AlphaCreative oversight
After every weekly audit, Agent 24 must ask:
- Which lane produced independent information?
- Which candidates are merely correlated copies?
- Which market best expresses the underlying signal?
- Did a NO-EDGE game become attractive in another market family?
- Did price, not prediction, cause rejection?
- Are we adding opportunity or just adding exposure?

## Promotion rules
- More weekly candidates is useful only if quality controls survive.
- No lane may lower its threshold because another lane is quiet.
- No aggregate profitability claim may combine unvalidated lanes.
- A lane may be useful even when another lane rejects the same game.

## External action
Research only. No wager placement or sportsbook transmission.
