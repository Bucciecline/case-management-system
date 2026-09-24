# ALPHAODDS - ALPHAPROPS POST-HOLDOUT SHADOW-VALIDATION ARCHITECTURE v1.0

## Status

ACTIVE FOR PROSPECTIVE RESEARCH CAPTURE ONLY.
WAGER EXECUTION DISABLED.
AP-RB1 and the 2025 one-shot result remain unchanged.
No historical or prospective profitability claim is authorized until the promotion gate below is independently satisfied.

## 1. Frozen scope

Initial supported market families are limited to the AP-RB1 frozen outcomes:

- QB passing yards
- RB rushing yards
- WR receiving yards
- WR receptions
- TE receiving yards
- TE receptions

All other player markets are NEW/UNMAPPED and default PASS or EXPERIMENTAL until separately defined and validated.

## 2. Append-only record model

The shadow book uses three immutable record types:

1. QUOTE_SNAPSHOT - one observed book/source price at one timestamp.
2. PREKICK_DECISION - the frozen model output plus AlphaPrice decision tied to one authenticated quote.
3. POSTGAME_GRADE - official result and shadow settlement tied back to the pre-kickoff decision.

Never overwrite a quote or decision because a later price appears. Create a new record and link it.

## 3. Universe lock and anti-selection-bias rule

Before the primary pre-kickoff decision window, create a universe_snapshot_id containing every discovered AP-RB1-supported player market from the approved source set.

The shadow book must retain:

- attractive candidates;
- WATCH candidates;
- EXPERIMENTAL candidates;
- PASS candidates;
- source failures and unmapped settlement records.

Do not delete, hide, or omit losing or unattractive records after results are known.
A market family may not be evaluated from a hand-selected subset created after outcomes are visible.

## 4. Capture windows

EARLY - optional first-available snapshot more than 60 minutes before kickoff.
PRIMARY - required research decision snapshot, targeted 60 to 20 minutes before scheduled kickoff when the market is available.
CLOSE_PROXY - targeted 10 to 1 minute before kickoff when the market remains open.
MOVE_UPDATE - any later material line/price update, stored as a new quote record.

A quote captured after kickoff is invalid for pregame shadow validation and receives PASS_QUOTE_AFTER_KICKOFF.

## 5. Price authentication

Every quote used for price/ROI/CLV analysis must be AUTHENTICATED by a retained raw API payload, screenshot, saved page, or provider receipt.

Required evidence fields:

- source/book name;
- capture timestamp;
- event and player identity;
- exact market and settlement definition;
- line and American odds;
- market status;
- evidence reference;
- SHA-256 when the evidence object can be hashed.

Unverified quotes may remain in the repository for troubleshooting but are excluded from profitability, EV, and CLV claims.

## 6. Timestamp and freshness rules

All canonical timestamps are UTC.
Event kickoff is stored in UTC.
Store provider timestamp when available and local capture timestamp separately.

PRIMARY decision quote age must be no more than 120 seconds at decision lock.
If older, AlphaPrice returns PASS_QUOTE_STALE.

The model forecast_generated_at_utc must precede the AlphaPrice decision lock and must not depend on the quoted price.

## 7. Settlement lock

Each market needs:

- canonical market family;
- canonical statistic;
- side;
- exact numeric line;
- settlement_rule_id;
- human-readable settlement text.

Do not assume two books have identical settlement merely because the display name is similar.
Unknown or conflicting settlement rules default PASS_SETTLEMENT_UNMAPPED.

## 8. AP-RB1 model lock

Every PREKICK_DECISION must reference:

- freeze_id ALPHAPROPS-AP-RB1-2026-09-23;
- model blob SHA-1 a2052512b20fa25ebba439ce463d097926c47459;
- forecast timestamp;
- projection mean;
- probability/distribution method ID and status;
- role uncertainty;
- source status.

No 2025 tuning or retroactive AP-RB1 repair is permitted.

Important current limitation: AP-RB1 is frozen as a projection baseline, but a market-line fair-probability wrapper has not yet been separately frozen. Until that wrapper is frozen, probability_method_status is NOT_FROZEN or EXPERIMENTAL and final market decision is EXPERIMENTAL/PASS, never a promoted PICK.

## 9. AlphaPrice firewall

All value statements flow through AlphaPrice.

For every priced candidate AlphaPrice records:

- break-even probability from quoted American odds;
- no-vig probability when both required market sides are authenticated;
- ALPHA fair probability when a frozen probability method exists;
- raw edge;
- conservative probability;
- conservative edge;
- expected value per unit;
- fair odds;
- price boundary;
- quote age;
- decision;
- reason code(s).

Decision logic for prospective testing:

PICK - only after the market family and probability method are promoted, all source/model gates pass, and conservative probability is above the applicable break-even/no-vig boundary.
WATCH - point estimate clears the price boundary but the conservative probability does not, or the quote is near the frozen boundary.
EXPERIMENTAL - source/model/price math is recordable but the market family or probability method has not been promoted.
PASS - any mandatory source, identity, role, settlement, freshness, model, uncertainty, or price gate fails.

Execution status is always DISABLED_SHADOW_ONLY.

## 10. Price-shopping rule

Capture every authenticated quote used in a comparison.
The best price can be designated only among identical settlement conditions.
Do not compare different lines as though they were the same product.

If both over and under are available, calculate the no-vig market probability.
If only one side is available, break-even probability may be calculated but no-vig probability remains null.

## 11. Postgame grading

After official final statistics are available, create a POSTGAME_GRADE record.
Do not edit the pre-kickoff record.

Store:

- official stat source and reference;
- final statistic;
- WIN / LOSS / PUSH / VOID settlement;
- hypothetical shadow return in units at the recorded price;
- close_quote_id when available;
- same-line market-probability movement when comparable;
- line movement separately when the line changed.

A shadow return is not a real wager return and must not be described as actual profit.

## 12. CLV control

Do not compress price movement and line movement into one invented CLV number.

COMPARABLE_SAME_LINE - compare implied/no-vig probability at the same settlement line.
LINE_MOVED_NOT_DIRECTLY_COMPARABLE - record line_delta and price data separately.
CLOSE_QUOTE_UNAVAILABLE - no CLV claim.

## 13. Prospective promotion-review gate

These thresholds are frozen before the first Shadow v1 sample and apply prospectively only. They are not retrofitted to 2024 or the 2025 one-shot holdout.

A market family becomes PROMOTION_REVIEW_ELIGIBLE only when all are true:

- at least 200 authenticated, graded PREKICK_DECISION records in the family;
- observations span at least 6 distinct NFL weeks;
- observations include at least 20 distinct players;
- no single NFL week contributes more than 25 percent of the family sample;
- 100 percent of records used for ROI/EV claims have authenticated price evidence and mapped settlement rules;
- probability calibration expected calibration error is 0.05 or lower using predeclared bins with adequate bin counts;
- calibration slope is between 0.80 and 1.20 and absolute calibration intercept is 0.05 or lower;
- Brier score is no worse than the authenticated no-vig market-probability baseline on comparable records;
- the week-cluster bootstrap 95 percent confidence interval lower bound for mean shadow ROI under the frozen decision rule is above 0;
- at least 100 same-line close-comparable decisions exist and their closing-market movement is favorable on a prespecified aggregate measure;
- CCA15 and Defense Red Team return PASS;
- no post-result threshold, feature, or market-family definition change contaminated the sample.

Meeting these conditions does not automatically label the family VALIDATED. It authorizes a separate promotion review.

## 14. Claim-control ladder

Before promotion review:

Permitted: "prospective shadow capture," "research signal," "projection-supported," "authenticated quote captured," "shadow result."

Prohibited: "profitable," "proven edge," "validated betting system," "winning strategy," "ROI-generating," or equivalent performance language.

After a separate promotion review, claims remain limited to the exact market family, version, period, sample, source set, and measured result actually supported.

## 15. No-hindsight and versioning

Any change to:

- model version;
- probability method;
- price decision rule;
- reason-code mapping;
- stale-price rule;
- sample threshold;
- calibration threshold;
- promotion criteria;
- settlement mapping;

creates a new version and a new prospective sample boundary.
Never silently merge pre-change and post-change samples.

## 16. External-action control

No field in Shadow v1 authorizes execution.
The schema intentionally excludes stake, wager ID, transmission status, and sportsbook execution fields.
No wager is placed or transmitted by this architecture.
