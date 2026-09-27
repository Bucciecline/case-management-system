#!/usr/bin/env python3
"""
ALPHAPROFIT generic payoff-matrix optimizer.

Input JSON:
{
  "bankroll_cap": 1000,
  "bets": [
    {"name":"Ravens ML","max_stake":500},
    {"name":"Cowboys ML","max_stake":500},
    {"name":"Under 47.5","max_stake":500},
    {"name":"Over 47.5","max_stake":500}
  ],
  "states": [
    {"name":"BAL_UNDER","profit_per_dollar":[0.80,-1,0.91,-1]},
    {"name":"BAL_OVER","profit_per_dollar":[0.80,-1,-1,0.91]},
    {"name":"DAL_UNDER","profit_per_dollar":[-1,1.25,0.91,-1]},
    {"name":"DAL_OVER","profit_per_dollar":[-1,1.25,-1,0.91]}
  ]
}

profit_per_dollar is NET P/L per $1 staked in each terminal state:
- losing bet = -1
- +100 winner = +1.00
- -125 winner = +0.80
- push = 0
- void/stake returned = 0

The optimizer maximizes the minimum terminal-state net P/L.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
import numpy as np

try:
    from scipy.optimize import linprog
except Exception as exc:
    raise SystemExit(
        "scipy is required. Install with: python -m pip install scipy numpy"
    ) from exc


def solve(payload: dict[str, Any]) -> dict[str, Any]:
    bets = payload["bets"]
    states = payload["states"]
    n = len(bets)
    if n == 0 or len(states) == 0:
        raise ValueError("At least one bet and one terminal state are required.")

    bankroll = float(payload.get("bankroll_cap", 0))
    if bankroll <= 0:
        raise ValueError("bankroll_cap must be positive.")

    # Decision variables: stakes x_1..x_n, then z = minimum net P/L.
    # Maximize z <=> minimize -z.
    c = np.zeros(n + 1)
    c[-1] = -1.0

    A_ub = []
    b_ub = []

    # For each state: sum(p_i * x_i) >= z
    # => -sum(p_i * x_i) + z <= 0
    for state in states:
        p = np.asarray(state["profit_per_dollar"], dtype=float)
        if len(p) != n:
            raise ValueError(
                f"State {state.get('name')} has {len(p)} coefficients; expected {n}."
            )
        row = np.zeros(n + 1)
        row[:n] = -p
        row[-1] = 1.0
        A_ub.append(row)
        b_ub.append(0.0)

    # Total bankroll constraint.
    row = np.zeros(n + 1)
    row[:n] = 1.0
    A_ub.append(row)
    b_ub.append(bankroll)

    # Optional minimum total stake.
    min_total = float(payload.get("minimum_total_stake", 0) or 0)
    if min_total > 0:
        row = np.zeros(n + 1)
        row[:n] = -1.0
        A_ub.append(row)
        b_ub.append(-min_total)

    bounds = []
    for bet in bets:
        lo = float(bet.get("min_stake", 0) or 0)
        hi_raw = bet.get("max_stake")
        hi = float(hi_raw) if hi_raw is not None else bankroll
        bounds.append((lo, hi))
    bounds.append((None, None))  # z

    res = linprog(
        c,
        A_ub=np.asarray(A_ub),
        b_ub=np.asarray(b_ub),
        bounds=bounds,
        method="highs",
    )
    if not res.success:
        return {
            "status": "NO_FEASIBLE_STRUCTURE",
            "solver_message": res.message,
        }

    stakes = res.x[:n]
    pnl = []
    for state in states:
        p = np.asarray(state["profit_per_dollar"], dtype=float)
        pnl.append(float(np.dot(p, stakes)))

    total_stake = float(stakes.sum())
    min_pnl = float(min(pnl))
    max_pnl = float(max(pnl))
    eps = 1e-7

    if min_pnl > eps:
        classification = "TRUE_ARBITRAGE"
    elif abs(min_pnl) <= eps:
        classification = "BREAK_EVEN_FLOOR"
    else:
        classification = "HEDGE_OR_DEFINED_RISK"

    return {
        "status": "SOLVED",
        "classification": classification,
        "bankroll_cap": bankroll,
        "total_stake": total_stake,
        "minimum_net_pnl": min_pnl,
        "maximum_net_pnl": max_pnl,
        "minimum_roi_on_staked_capital": (min_pnl / total_stake) if total_stake else None,
        "stakes": [
            {"bet": bets[i]["name"], "stake": float(stakes[i])}
            for i in range(n)
        ],
        "terminal_states": [
            {
                "state": states[i]["name"],
                "net_pnl": pnl[i],
                "positive": pnl[i] > eps,
            }
            for i in range(len(states))
        ],
        "controls": {
            "guaranteed_profit_label_allowed": bool(min_pnl > eps),
            "all_states_positive": bool(all(x > eps for x in pnl)),
            "solver_objective": "maximize minimum terminal-state net P/L",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = solve(payload)
    text = json.dumps(result, indent=2)

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
