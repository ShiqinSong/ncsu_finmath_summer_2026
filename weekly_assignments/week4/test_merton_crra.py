import numpy as np

from merton_crra import (
    MertonCRRAParams,
    analytic_optimal_share,
    run_crra_experiment,
    solve_coefficient_backward_ode,
)


def test_backward_ode_matches_closed_form_at_time_zero():
    params = MertonCRRAParams(ode_steps=5000)
    ode = solve_coefficient_backward_ode(params)

    numerical = float(ode.loc[0, "coefficient"])
    exact = float(ode.loc[0, "exact_coefficient"])

    assert abs(numerical - exact) < 1e-6


def test_implied_crra_share_is_constant_in_wealth(tmp_path):
    params = MertonCRRAParams(w_points=600)
    share_check, summary = run_crra_experiment(params, tmp_path / "output", tmp_path / "figures")

    target = analytic_optimal_share(params.mu, params.r, params.sigma, params.gamma)

    assert np.isclose(summary.loc[0, "analytic_optimal_share"], target)
    assert summary.loc[0, "max_abs_error"] < 2e-3
    assert share_check["implied_optimal_share"].std() < 5e-4


def test_more_risk_aversion_lowers_the_risky_share(tmp_path):
    low_gamma = MertonCRRAParams(gamma=2.0)
    high_gamma = MertonCRRAParams(gamma=5.0)

    _, low_summary = run_crra_experiment(low_gamma, tmp_path / "low_output", tmp_path / "low_figures")
    _, high_summary = run_crra_experiment(high_gamma, tmp_path / "high_output", tmp_path / "high_figures")

    assert high_summary.loc[0, "analytic_optimal_share"] < low_summary.loc[0, "analytic_optimal_share"]
