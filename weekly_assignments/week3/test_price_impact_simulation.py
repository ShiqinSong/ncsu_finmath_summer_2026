import numpy as np

from helpers_futures.models.avellaneda_stoikov import ASParams
from price_impact_simulation import simulate_with_impact, summarize_impact_results


def _params() -> ASParams:
    return ASParams(
        gamma=0.1,
        sigma=2.0,
        kappa=1.5,
        A=0.07,
        T=300.0,
        tau_risk=1.0,
    )


def test_reproducible_at_zero_impact() -> None:
    first = simulate_with_impact(_params(), impact_per_fill=0.0, n_sims=32, seed=7)
    second = simulate_with_impact(_params(), impact_per_fill=0.0, n_sims=32, seed=7)
    np.testing.assert_array_equal(first.terminal_pnl, second.terminal_pnl)
    np.testing.assert_array_equal(first.fill_count, second.fill_count)


def test_common_random_numbers_preserve_fill_paths() -> None:
    zero = simulate_with_impact(_params(), impact_per_fill=0.0, n_sims=64, seed=11)
    high = simulate_with_impact(_params(), impact_per_fill=0.10, n_sims=64, seed=11)
    np.testing.assert_array_equal(zero.fill_count, high.fill_count)
    np.testing.assert_array_equal(zero.terminal_inventory, high.terminal_inventory)


def test_impact_degrades_mean_pnl() -> None:
    zero = simulate_with_impact(_params(), impact_per_fill=0.0, n_sims=256, seed=13)
    low = simulate_with_impact(_params(), impact_per_fill=0.05, n_sims=256, seed=13)
    high = simulate_with_impact(_params(), impact_per_fill=0.10, n_sims=256, seed=13)
    summary = summarize_impact_results([zero, low, high])
    assert summary["mean_pnl"].is_monotonic_decreasing
    assert summary["mean_paired_degradation"].is_monotonic_increasing
