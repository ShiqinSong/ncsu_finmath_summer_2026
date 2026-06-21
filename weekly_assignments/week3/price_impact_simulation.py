"""Vectorized price-impact extension for PS3 Problem 5.

The simulator keeps the Avellaneda--Stoikov policy from Problem 3, but lets
the quoted mid react permanently to the market maker's own fills.  A bid fill
(the maker buys) moves the mid down by ``impact_per_fill``; an ask fill (the
maker sells) moves it up.  This is adverse selection from the maker's point
of view and deliberately violates the independent-mid assumption.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from helpers_futures.models.avellaneda_stoikov import ASParams, optimal_half_spread


@dataclass(frozen=True)
class ImpactResult:
    """Terminal and diagnostic results for one impact level."""

    impact_per_fill: float
    terminal_pnl: np.ndarray
    terminal_inventory: np.ndarray
    fill_count: np.ndarray
    impact_cost: np.ndarray


def simulate_with_impact(
    params: ASParams,
    *,
    impact_per_fill: float,
    n_sims: int = 1_000,
    s0: float = 100.0,
    dt: float = 1.0,
    seed: int = 99,
) -> ImpactResult:
    """Run vectorized A--S simulations with permanent adverse fill impact.

    Simulations are vectorized across paths and iterated through time.  The
    event order at each tick is: exogenous Brownian move, quote, fills,
    permanent price impact, then mark-to-market.  Separate calls with the same
    seed use common Brownian shocks and fill uniforms, making comparisons
    across impact levels paired rather than noisy.
    """

    if impact_per_fill < 0:
        raise ValueError("impact_per_fill must be non-negative")
    if n_sims < 1 or dt <= 0:
        raise ValueError("n_sims and dt must be positive")

    n_steps = int(params.T / dt)
    if n_steps < 1:
        raise ValueError("params.T / dt must contain at least one step")

    rng = np.random.default_rng(seed)
    mid = np.full(n_sims, s0, dtype=float)
    cash = np.zeros(n_sims, dtype=float)
    inventory = np.zeros(n_sims, dtype=np.int32)
    fill_count = np.zeros(n_sims, dtype=np.int32)
    impact_cost = np.zeros(n_sims, dtype=float)

    half_spread = optimal_half_spread(0.0, params)
    flow_term = np.log1p(params.gamma / params.kappa) / params.gamma

    for step in range(n_steps):
        mid += rng.normal(0.0, params.sigma * np.sqrt(dt), size=n_sims)

        if params.tau_risk is None:
            tau = params.T - step * dt
            half_spread = params.gamma * params.sigma**2 * tau / 2.0 + flow_term
        else:
            tau = params.tau_risk

        reservation = mid - inventory * (
            params.gamma * params.sigma**2 + params.funding_rate_per_s
        ) * tau
        bid = reservation - half_spread
        ask = reservation + half_spread

        bid_distance = mid - bid
        ask_distance = ask - mid
        p_bid = np.minimum(1.0, params.A * np.exp(-params.kappa * bid_distance) * dt)
        p_ask = np.minimum(1.0, params.A * np.exp(-params.kappa * ask_distance) * dt)
        p_bid = np.where(inventory < params.q_max, p_bid, 0.0)
        p_ask = np.where(inventory > params.q_min, p_ask, 0.0)

        bid_fill = rng.random(n_sims) < p_bid
        ask_fill = rng.random(n_sims) < p_ask

        cash -= bid * bid_fill
        cash += ask * ask_fill
        inventory += bid_fill.astype(np.int32) - ask_fill.astype(np.int32)
        fills_this_step = bid_fill.astype(np.int32) + ask_fill.astype(np.int32)
        fill_count += fills_this_step

        # A bid fill is followed by a down move; an ask fill by an up move.
        signed_impact = impact_per_fill * (
            ask_fill.astype(float) - bid_fill.astype(float)
        )
        mid += signed_impact

        # Immediate mark-to-market loss is eta for each one-unit fill.
        impact_cost += impact_per_fill * fills_this_step

        if params.funding_rate_per_s:
            cash -= inventory * params.funding_rate_per_s * dt

    terminal_pnl = cash + inventory * mid
    return ImpactResult(
        impact_per_fill=impact_per_fill,
        terminal_pnl=terminal_pnl,
        terminal_inventory=inventory,
        fill_count=fill_count,
        impact_cost=impact_cost,
    )


def summarize_impact_results(results: list[ImpactResult]) -> pd.DataFrame:
    """Create the Problem 5 comparison table, paired to zero impact."""

    if not results:
        raise ValueError("results cannot be empty")
    baseline = next((r for r in results if r.impact_per_fill == 0.0), None)
    if baseline is None:
        raise ValueError("results must include impact_per_fill=0")

    rows: list[dict[str, float]] = []
    for result in results:
        pnl = result.terminal_pnl
        paired_loss = baseline.terminal_pnl - pnl
        rows.append(
            {
                "impact_usd_per_fill": result.impact_per_fill,
                "mean_pnl": float(pnl.mean()),
                "std_pnl": float(pnl.std(ddof=1)),
                "p05_pnl": float(np.percentile(pnl, 5)),
                "median_pnl": float(np.median(pnl)),
                "p95_pnl": float(np.percentile(pnl, 95)),
                "mean_paired_degradation": float(paired_loss.mean()),
                "degradation_pct_of_zero_impact_pnl": float(
                    100.0 * paired_loss.mean() / baseline.terminal_pnl.mean()
                ),
                "mean_fills": float(result.fill_count.mean()),
                "mean_terminal_inventory": float(result.terminal_inventory.mean()),
                "std_terminal_inventory": float(result.terminal_inventory.std(ddof=1)),
            }
        )
    return pd.DataFrame(rows)
