"""
Week 6 — Raw SVI parameterization and calibration in PyTorch.

Raw SVI models the total implied variance w(k) = sigma^2 * T as a function of
log-moneyness k = ln(K / F):

    w(k) = a + b * ( rho * (k - m) + sqrt( (k - m)^2 + s^2 ) )

We calibrate (a, b, rho, m, s) to a (synthetic) smile by least squares using
autograd, and check the butterfly no-arbitrage condition g(k) >= 0 (a negative
g implies a negative risk-neutral density).

    python svi.py
"""
from __future__ import annotations

import torch


def svi_total_variance(k, a, b, rho, m, s):
    """Raw SVI total variance w(k)."""
    return a + b * (rho * (k - m) + torch.sqrt((k - m) ** 2 + s ** 2))


def butterfly_g(k, params):
    """Gatheral's g(k); g(k) >= 0 everywhere is the no-butterfly-arbitrage test."""
    a, b, rho, m, s = params
    k = k.clone().requires_grad_(True)
    w = svi_total_variance(k, a, b, rho, m, s)
    (wp,) = torch.autograd.grad(w.sum(), k, create_graph=True)
    (wpp,) = torch.autograd.grad(wp.sum(), k, create_graph=True)
    term = (1 - k * wp / (2 * w)) ** 2 - (wp ** 2) / 4 * (1 / w + 0.25) + wpp / 2
    return term.detach()


def calibrate(k, w_market, steps=4000, lr=1e-2, init=None):
    """Fit raw-SVI parameters to observed total variances by autograd LSQ.

    ``init`` optionally supplies a starting ``(a, b, rho, m, s)`` tuple (e.g.
    the previous day's fitted params, for warm-starting a rolling daily
    calibration); defaults to a fixed generic starting point.
    """
    a0, b0, rho0, m0, s0 = init if init is not None else (0.04, 0.2, -0.3, 0.0, 0.2)
    a = torch.tensor(float(a0), requires_grad=True)
    b = torch.tensor(float(b0), requires_grad=True)
    rho = torch.tensor(float(rho0), requires_grad=True)
    m = torch.tensor(float(m0), requires_grad=True)
    s = torch.tensor(float(s0), requires_grad=True)
    opt = torch.optim.Adam([a, b, rho, m, s], lr=lr)
    for _ in range(steps):
        w = svi_total_variance(k, a, b, rho.clamp(-0.999, 0.999), m, s.clamp(min=1e-3))
        loss = ((w - w_market) ** 2).mean()
        opt.zero_grad(); loss.backward(); opt.step()
    params = (a.detach(), b.detach(), rho.detach().clamp(-0.999, 0.999),
              m.detach(), s.detach().clamp(min=1e-3))
    return params, float(loss.detach())


if __name__ == "__main__":
    # synthetic "market" smile from known SVI params + noise
    k = torch.linspace(-0.5, 0.5, 21)
    true = (0.04, 0.20, -0.30, 0.00, 0.15)
    w_true = svi_total_variance(k, *(torch.tensor(x) for x in true))
    w_market = w_true + 1e-4 * torch.randn(k.shape, generator=torch.Generator().manual_seed(0))

    params, loss = calibrate(k, w_market)
    names = ["a", "b", "rho", "m", "s"]
    print("fitted SVI parameters:")
    for n, p in zip(names, params):
        print(f"  {n:3s} = {float(p): .4f}")
    rms_iv = float((((svi_total_variance(k, *params) / 1.0).clamp(min=1e-8).sqrt()
                     - (w_market).clamp(min=1e-8).sqrt()) ** 2).mean().sqrt())
    print(f"calibration MSE (total var): {loss:.3e}")
    g = butterfly_g(k, params)
    print(f"butterfly g(k) min: {float(g.min()):.4f}  "
          f"({'no-arb OK' if g.min() >= 0 else 'ARBITRAGE: g<0'})")
