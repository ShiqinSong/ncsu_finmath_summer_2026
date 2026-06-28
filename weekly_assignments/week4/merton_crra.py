"""PS4 Problem 1: Merton portfolio problem with CRRA utility.

The finite-horizon Merton problem is

    dW_t = (r W_t + pi_t (mu - r)) dt + pi_t sigma dB_t,
    U(W_T) = W_T ** (1 - gamma) / (1 - gamma),

where ``pi_t`` is the dollar amount invested in the risky asset.  It is more
natural under CRRA to write the control as a risky *share*

    phi_t = pi_t / W_t.

The HJB implies

    phi* = (mu - r) / (gamma sigma^2),

which is independent of wealth.  This module discretizes the resulting
backward ODE for the CRRA value-function coefficient and then recovers the
share numerically from finite-difference derivatives of the value function.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MertonCRRAParams:
    """Model parameters for the CRRA Merton problem."""

    mu: float = 0.08
    r: float = 0.02
    sigma: float = 0.20
    gamma: float = 3.0
    T: float = 1.0
    ode_steps: int = 2000
    w_min: float = 1.0
    w_max: float = 10.0
    w_points: int = 500

    def validate(self) -> None:
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if self.gamma <= 0 or np.isclose(self.gamma, 1.0):
            raise ValueError("gamma must be positive and different from 1 for CRRA power utility")
        if self.T <= 0 or self.ode_steps <= 0:
            raise ValueError("T and ode_steps must be positive")
        if self.w_min <= 0 or self.w_max <= self.w_min or self.w_points < 5:
            raise ValueError("wealth grid must be positive and contain at least five points")


def crra_utility(wealth: np.ndarray, gamma: float) -> np.ndarray:
    """CRRA terminal utility for ``gamma != 1``."""

    wealth = np.asarray(wealth, dtype=float)
    if np.any(wealth <= 0):
        raise ValueError("CRRA utility requires positive wealth")
    if np.isclose(gamma, 1.0):
        raise ValueError("gamma=1 corresponds to log utility, not power CRRA utility")
    return wealth ** (1.0 - gamma) / (1.0 - gamma)


def analytic_optimal_share(mu: float, r: float, sigma: float, gamma: float) -> float:
    """Closed-form optimal risky portfolio share."""

    return (mu - r) / (gamma * sigma**2)


def hjb_growth_rate(mu: float, r: float, sigma: float, gamma: float) -> float:
    """Rate in the scalar CRRA value-function ODE.

    With ``V(t,w) = a(t) U(w)``, the HJB gives

        a'(t) = -rate * a(t),    a(T)=1.

    Thus ``a(t) = exp(rate * (T - t))``.
    """

    sharpe_excess = mu - r
    return (1.0 - gamma) * (r + sharpe_excess**2 / (2.0 * gamma * sigma**2))


def solve_coefficient_backward_ode(params: MertonCRRAParams) -> pd.DataFrame:
    """Discretize the backward ODE for the CRRA value-function coefficient."""

    params.validate()
    dt = params.T / params.ode_steps
    rate = hjb_growth_rate(params.mu, params.r, params.sigma, params.gamma)

    times = np.linspace(0.0, params.T, params.ode_steps + 1)
    coeff = np.empty_like(times)
    coeff[-1] = 1.0

    # March backward from terminal time.  Since the scalar ODE is smooth, this
    # simple first-order discretization is enough for the problem's numerical
    # verification.
    for i in range(params.ode_steps - 1, -1, -1):
        coeff[i] = coeff[i + 1] * (1.0 + rate * dt)

    exact = np.exp(rate * (params.T - times))
    return pd.DataFrame({"time": times, "coefficient": coeff, "exact_coefficient": exact})


def value_function_at_time_zero(params: MertonCRRAParams) -> tuple[np.ndarray, np.ndarray, float]:
    """Return wealth grid, numerical value at t=0, and the ODE coefficient."""

    ode = solve_coefficient_backward_ode(params)
    coefficient_0 = float(ode.loc[0, "coefficient"])
    wealth = np.linspace(params.w_min, params.w_max, params.w_points)
    value = coefficient_0 * crra_utility(wealth, params.gamma)
    return wealth, value, coefficient_0


def implied_share_from_value_derivatives(
    wealth: np.ndarray, value: np.ndarray, mu: float, sigma: float
) -> np.ndarray:
    """Recover the HJB optimizer from finite-difference value derivatives."""

    dV = np.gradient(value, wealth, edge_order=2)
    d2V = np.gradient(dV, wealth, edge_order=2)
    return -mu * dV / (sigma**2 * wealth * d2V)


def run_crra_experiment(
    params: MertonCRRAParams | None = None,
    output_dir: str | Path = "output",
    figure_dir: str | Path = "figures",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run PS4 Problem 1 and save the numerical verification artifacts."""

    params = params or MertonCRRAParams()
    params.validate()
    output_dir = Path(output_dir)
    figure_dir = Path(figure_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    ode = solve_coefficient_backward_ode(params)
    wealth, value, _ = value_function_at_time_zero(params)

    excess_return = params.mu - params.r
    implied_share = implied_share_from_value_derivatives(wealth, value, excess_return, params.sigma)
    analytic_share = analytic_optimal_share(params.mu, params.r, params.sigma, params.gamma)

    # Drop a few boundary points where finite differences are least accurate.
    interior = slice(3, -3)
    share_check = pd.DataFrame(
        {
            "wealth": wealth[interior],
            "value_t0": value[interior],
            "implied_optimal_share": implied_share[interior],
            "analytic_optimal_share": analytic_share,
            "abs_error": np.abs(implied_share[interior] - analytic_share),
        }
    )

    summary = pd.DataFrame(
        [
            {
                "mu": params.mu,
                "r": params.r,
                "sigma": params.sigma,
                "gamma": params.gamma,
                "T": params.T,
                "analytic_optimal_share": analytic_share,
                "mean_implied_share": share_check["implied_optimal_share"].mean(),
                "std_implied_share": share_check["implied_optimal_share"].std(),
                "max_abs_error": share_check["abs_error"].max(),
                "coefficient_t0": float(ode.loc[0, "coefficient"]),
                "coefficient_t0_exact": float(ode.loc[0, "exact_coefficient"]),
                "coefficient_abs_error": abs(
                    float(ode.loc[0, "coefficient"]) - float(ode.loc[0, "exact_coefficient"])
                ),
            }
        ]
    )

    share_check.to_csv(output_dir / "ps4_p1_crra_share_by_wealth.csv", index=False)
    summary.to_csv(output_dir / "ps4_p1_crra_summary.csv", index=False)
    ode.to_csv(output_dir / "ps4_p1_crra_ode_coefficients.csv", index=False)

    _save_share_figure(share_check, analytic_share, figure_dir / "ps4_p1_crra_constant_share.png")
    return share_check, summary


def _save_share_figure(share_check: pd.DataFrame, analytic_share: float, path: Path) -> None:
    """Save the constant-share diagnostic figure."""

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(share_check["wealth"], share_check["implied_optimal_share"], label="Numerical HJB share")
    ax.axhline(analytic_share, color="black", linestyle="--", label="Analytic share")
    ax.set_title("Merton CRRA: optimal risky share is constant in wealth")
    ax.set_xlabel("Wealth")
    ax.set_ylabel("Risky portfolio share")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    checks, summary_table = run_crra_experiment()
    row = summary_table.iloc[0]
    print("PS4 Problem 1: Merton CRRA")
    print(f"analytic optimal risky share: {row['analytic_optimal_share']:.6f}")
    print(f"mean numerical implied share: {row['mean_implied_share']:.6f}")
    print(f"max absolute error: {row['max_abs_error']:.3e}")
