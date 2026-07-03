import numpy as np
import torch

from vectorized_quote_path import (
    QuoteBenchmarkParams,
    benchmark_vectorized_quotes,
    inventory_grid,
    scalar_loop_as_quotes,
    vectorized_as_quotes,
)


def test_vectorized_quotes_match_scalar_loop_reference():
    params = QuoteBenchmarkParams(q_min=-5, q_max=5, benchmark_runs=5, warmup_runs=0)
    q = inventory_grid(params)

    bid_t, ask_t = vectorized_as_quotes(
        params.mid_price, q, params.gamma, params.sigma, params.kappa, params.tau
    )
    bid_np, ask_np = scalar_loop_as_quotes(
        params.mid_price,
        q.cpu().numpy(),
        params.gamma,
        params.sigma,
        params.kappa,
        params.tau,
    )

    np.testing.assert_allclose(bid_t.cpu().numpy(), bid_np, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(ask_t.cpu().numpy(), ask_np, rtol=1e-12, atol=1e-12)


def test_quotes_move_down_as_inventory_increases():
    params = QuoteBenchmarkParams(q_min=-10, q_max=10)
    q = inventory_grid(params)
    bid, ask = vectorized_as_quotes(
        params.mid_price, q, params.gamma, params.sigma, params.kappa, params.tau
    )

    assert torch.all(torch.diff(bid) < 0)
    assert torch.all(torch.diff(ask) < 0)
    assert torch.all(ask > bid)


def test_benchmark_returns_required_latency_distribution_columns():
    params = QuoteBenchmarkParams(q_min=-10, q_max=10, warmup_runs=2, benchmark_runs=20)
    latency, summary = benchmark_vectorized_quotes(params)

    required = {"mean_us", "median_us", "p95_us", "p99_us"}

    assert len(latency) == params.benchmark_runs
    assert required.issubset(summary.columns)
    assert summary.loc[0, "inventory_points"] == 21
    assert summary.loc[0, "mean_us"] > 0
    assert summary.loc[0, "p99_us"] >= summary.loc[0, "median_us"]
