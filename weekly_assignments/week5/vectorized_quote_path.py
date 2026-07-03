"""PS5 Question 1: vectorized Avellaneda--Stoikov quote path in PyTorch.

The task is to compute bid/ask quotes over an inventory grid without a Python
loop and report latency distribution statistics.  The closed-form asymptotic
Avellaneda--Stoikov quotes are

    reservation(q) = S - q * gamma * sigma^2 * tau
    half_spread    = log(1 + gamma / kappa) / gamma
                     + 0.5 * gamma * sigma^2 * tau

    bid(q) = reservation(q) - half_spread
    ask(q) = reservation(q) + half_spread

Because every inventory point uses the same formula, the whole grid is a
natural PyTorch tensor operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

import torch
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class QuoteBenchmarkParams:
    """Parameters for the quote-grid computation and latency benchmark."""

    mid_price: float = 100.0
    gamma: float = 0.1
    sigma: float = 2.0
    kappa: float = 1.5
    tau: float = 1.0
    q_min: int = -100
    q_max: int = 100
    warmup_runs: int = 200
    benchmark_runs: int = 5000
    dtype: torch.dtype = torch.float64
    device: str = "cpu"
    num_threads: int = 1

    def validate(self) -> None:
        if self.gamma <= 0 or self.sigma <= 0 or self.kappa <= 0:
            raise ValueError("gamma, sigma, and kappa must be positive")
        if self.tau < 0:
            raise ValueError("tau must be non-negative")
        if self.q_max < self.q_min:
            raise ValueError("q_max must be greater than or equal to q_min")
        if self.warmup_runs < 0 or self.benchmark_runs <= 0:
            raise ValueError("benchmark run counts are invalid")


def inventory_grid(params: QuoteBenchmarkParams) -> torch.Tensor:
    """Create the inventory grid as a PyTorch tensor."""

    params.validate()
    return torch.arange(params.q_min, params.q_max + 1, dtype=params.dtype, device=params.device)


def vectorized_as_quotes(
    mid_price: float | torch.Tensor,
    inventory: torch.Tensor,
    gamma: float,
    sigma: float,
    kappa: float,
    tau: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Vectorized Avellaneda--Stoikov bid/ask quotes over an inventory tensor."""

    mid = torch.as_tensor(mid_price, dtype=inventory.dtype, device=inventory.device)
    gamma_t = inventory.new_tensor(gamma)
    sigma_t = inventory.new_tensor(sigma)
    kappa_t = inventory.new_tensor(kappa)
    tau_t = inventory.new_tensor(tau)

    reservation = mid - inventory * gamma_t * sigma_t.square() * tau_t
    half_spread = torch.log1p(gamma_t / kappa_t) / gamma_t + 0.5 * gamma_t * sigma_t.square() * tau_t
    return reservation - half_spread, reservation + half_spread


def scalar_loop_as_quotes(
    mid_price: float,
    inventory_values: list[float] | np.ndarray,
    gamma: float,
    sigma: float,
    kappa: float,
    tau: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Python-loop reference implementation used for correctness checks."""

    half_spread = np.log1p(gamma / kappa) / gamma + 0.5 * gamma * sigma**2 * tau
    bids, asks = [], []
    for q in inventory_values:
        reservation = mid_price - q * gamma * sigma**2 * tau
        bids.append(reservation - half_spread)
        asks.append(reservation + half_spread)
    return np.asarray(bids), np.asarray(asks)


def quote_grid_dataframe(params: QuoteBenchmarkParams) -> pd.DataFrame:
    """Return the vectorized quote grid as a tidy DataFrame."""

    q = inventory_grid(params)
    bid, ask = vectorized_as_quotes(
        params.mid_price, q, params.gamma, params.sigma, params.kappa, params.tau
    )
    return pd.DataFrame(
        {
            "inventory": q.detach().cpu().numpy(),
            "bid": bid.detach().cpu().numpy(),
            "ask": ask.detach().cpu().numpy(),
            "spread": (ask - bid).detach().cpu().numpy(),
            "mid_price": params.mid_price,
        }
    )


def benchmark_vectorized_quotes(params: QuoteBenchmarkParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Benchmark vectorized quote computation and summarize latency in microseconds."""

    params.validate()
    old_threads = torch.get_num_threads()
    if params.num_threads > 0:
        torch.set_num_threads(params.num_threads)

    q = inventory_grid(params)
    try:
        with torch.no_grad():
            for _ in range(params.warmup_runs):
                vectorized_as_quotes(
                    params.mid_price, q, params.gamma, params.sigma, params.kappa, params.tau
                )
            if q.device.type == "cuda":
                torch.cuda.synchronize(q.device)

            latencies_us = np.empty(params.benchmark_runs, dtype=float)
            for i in range(params.benchmark_runs):
                start = perf_counter_ns()
                bid, ask = vectorized_as_quotes(
                    params.mid_price, q, params.gamma, params.sigma, params.kappa, params.tau
                )
                # Touch one value so the result cannot be optimized away.
                _ = float((bid[0] + ask[-1]).detach().cpu())
                if q.device.type == "cuda":
                    torch.cuda.synchronize(q.device)
                end = perf_counter_ns()
                latencies_us[i] = (end - start) / 1000.0
    finally:
        torch.set_num_threads(old_threads)

    latency = pd.DataFrame({"run": np.arange(params.benchmark_runs), "latency_us": latencies_us})
    summary = pd.DataFrame(
        [
            {
                "device": params.device,
                "dtype": str(params.dtype).replace("torch.", ""),
                "num_threads": params.num_threads,
                "inventory_points": params.q_max - params.q_min + 1,
                "runs": params.benchmark_runs,
                "mean_us": latency["latency_us"].mean(),
                "median_us": latency["latency_us"].median(),
                "p95_us": latency["latency_us"].quantile(0.95),
                "p99_us": latency["latency_us"].quantile(0.99),
                "min_us": latency["latency_us"].min(),
                "max_us": latency["latency_us"].max(),
            }
        ]
    )
    return latency, summary


def run_ps5_q1(
    params: QuoteBenchmarkParams | None = None,
    output_dir: str | Path = "output",
    figure_dir: str | Path = "figures",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the full PS5 Q1 deliverable and save CSV/figure artifacts."""

    params = params or QuoteBenchmarkParams()
    output_dir = Path(output_dir)
    figure_dir = Path(figure_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    quote_grid = quote_grid_dataframe(params)
    latency, summary = benchmark_vectorized_quotes(params)

    quote_grid.to_csv(output_dir / "ps5_q1_vectorized_quote_grid.csv", index=False)
    latency.to_csv(output_dir / "ps5_q1_latency_runs.csv", index=False)
    summary.to_csv(output_dir / "ps5_q1_latency_summary.csv", index=False)
    _save_latency_figure(latency, figure_dir / "ps5_q1_latency_distribution.svg")
    return quote_grid, latency, summary


def _save_latency_figure(latency: pd.DataFrame, path: Path) -> None:
    """Save a lightweight SVG latency histogram without importing matplotlib.

    On some Windows/Anaconda setups, importing matplotlib after torch can load a
    second OpenMP runtime.  A simple hand-written SVG is enough for this report
    and keeps the benchmark path focused on the PyTorch quote computation.
    """

    values = latency["latency_us"].to_numpy()
    counts, edges = np.histogram(values, bins=50)
    width, height = 900, 500
    margin_left, margin_right, margin_top, margin_bottom = 80, 30, 60, 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    max_count = max(int(counts.max()), 1)
    x_min, x_max = float(edges[0]), float(edges[-1])
    median = float(np.median(values))
    p95 = float(np.quantile(values, 0.95))

    def x_pos(x: float) -> float:
        return margin_left + (x - x_min) / max(x_max - x_min, 1e-12) * plot_w

    bars = []
    for count, left, right in zip(counts, edges[:-1], edges[1:]):
        bar_x = x_pos(float(left))
        bar_w = max(x_pos(float(right)) - bar_x - 1.0, 1.0)
        bar_h = count / max_count * plot_h
        bar_y = margin_top + plot_h - bar_h
        bars.append(
            f'<rect x="{bar_x:.2f}" y="{bar_y:.2f}" width="{bar_w:.2f}" '
            f'height="{bar_h:.2f}" fill="#CC0000" opacity="0.75" />'
        )

    median_x = x_pos(median)
    p95_x = x_pos(p95)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white" />
  <text x="{width / 2:.0f}" y="32" text-anchor="middle" font-family="Arial" font-size="22">PS5 Q1: Vectorized quote-path latency</text>
  <line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="black" />
  <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="black" />
  {''.join(bars)}
  <line x1="{median_x:.2f}" y1="{margin_top}" x2="{median_x:.2f}" y2="{margin_top + plot_h}" stroke="black" stroke-dasharray="6,5" />
  <line x1="{p95_x:.2f}" y1="{margin_top}" x2="{p95_x:.2f}" y2="{margin_top + plot_h}" stroke="#666" stroke-dasharray="2,5" />
  <text x="{median_x + 6:.2f}" y="{margin_top + 18}" font-family="Arial" font-size="13">median {median:.1f} us</text>
  <text x="{p95_x + 6:.2f}" y="{margin_top + 38}" font-family="Arial" font-size="13">p95 {p95:.1f} us</text>
  <text x="{width / 2:.0f}" y="{height - 22}" text-anchor="middle" font-family="Arial" font-size="15">Latency per quote-grid computation (microseconds)</text>
  <text x="22" y="{height / 2:.0f}" text-anchor="middle" font-family="Arial" font-size="15" transform="rotate(-90 22 {height / 2:.0f})">Run count</text>
  <text x="{margin_left}" y="{height - 48}" font-family="Arial" font-size="12">{x_min:.1f}</text>
  <text x="{margin_left + plot_w}" y="{height - 48}" text-anchor="end" font-family="Arial" font-size="12">{x_max:.1f}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    quotes, _, latency_summary = run_ps5_q1()
    row = latency_summary.iloc[0]
    print("PS5 Q1: vectorized quote path over inventory grid")
    print(f"inventory points: {int(row['inventory_points'])}")
    print(
        "latency: "
        f"mean={row['mean_us']:.2f}us, "
        f"median={row['median_us']:.2f}us, "
        f"p95={row['p95_us']:.2f}us, "
        f"p99={row['p99_us']:.2f}us"
    )
    print("\nQuote grid preview:")
    print(quotes.head().to_string(index=False))
