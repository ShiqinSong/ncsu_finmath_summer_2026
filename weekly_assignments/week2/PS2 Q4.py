#!/usr/bin/env python
# coding: utf-8

# In[4]:


# PS2 Q4 — Glosten-Milgrom Simulation on Real Coincall BTC-USD Data
# Replaces simulated order flow from PS1 Q4 with real trade records.
# Data: btcusd_trades_20260614_22.parquet (1 hour, 3352 trades)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


df = pd.read_parquet("btcusd_trades_20260614_22.parquet")

# trade_side: 1 = buy, 2 = sell
df["order"] = df["trade_side"].map({1: "buy", 2: "sell"})

# Use price mid-point of first trade as proxy for prior true value
# (in GM framework we set VH / VL around the observed price range)
p_mid   = df["price"].mean()
p_range = df["price"].std() * 2          # ±2σ band

VH = p_mid + p_range   # "high" fundamental value
VL = p_mid - p_range   # "low" fundamental value

print(f"VH = {VH:.2f},  VL = {VL:.2f},  mid = {p_mid:.2f}")

# ── 2. GM model parameters ─────────────────────────────────────────────────
mu = 0.05          # informed-trader probability (same as PS1)
pi = 0.50          # prior P(V = VH)

# ── 3. Bayesian update (identical to PS1 Q4) ───────────────────────────────
def bayesian_update(pi, order, mu):
    if order == "buy":
        p_VH = mu + 0.5 * (1 - mu)
        p_VL = 0.5 * (1 - mu)
    else:
        p_VH = 0.5 * (1 - mu)
        p_VL = mu + 0.5 * (1 - mu)
    denom = pi * p_VH + (1 - pi) * p_VL
    return pi * p_VH / denom

# ── 4. Run GM over real order sequence ─────────────────────────────────────
beliefs = [pi]
asks    = []
bids    = []
orders  = df["order"].tolist()

for order in orders:
    pi_if_buy  = bayesian_update(pi, "buy",  mu)
    pi_if_sell = bayesian_update(pi, "sell", mu)

    ask = VH * pi_if_buy  + VL * (1 - pi_if_buy)
    bid = VH * pi_if_sell + VL * (1 - pi_if_sell)
    asks.append(ask)
    bids.append(bid)

    pi = bayesian_update(pi, order, mu)
    beliefs.append(pi)

# ── 5. Output CSV (as required by PS2) ─────────────────────────────────────
out = pd.DataFrame({
    "trade_index": range(len(orders)),
    "order":       orders,
    "belief_VH":   beliefs[1:],
    "ask":         asks,
    "bid":         bids,
    "real_price":  df["price"].values,
})
out.to_csv("gm_belief_convergence_real.csv", index=False)
print("CSV saved: gm_belief_convergence_real.csv")

# ── 6. Plots ────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(12, 8))

# Plot 1: Belief convergence
axes[0].plot(beliefs, label="Posterior P(V = VH)", color="steelblue")
axes[0].axhline(0.5, linestyle="--", color="gray", label="Prior = 0.5")
axes[0].set_xlabel("Trade Number")
axes[0].set_ylabel("Belief P(V = VH)")
axes[0].set_title("Glosten-Milgrom: Public Belief on Real BTC-USD Trades (22:00–23:00)")
axes[0].legend()
axes[0].grid(True)

# Plot 2: Model bid/ask vs real trade price
axes[1].plot(asks,               label="GM Ask Quote",    color="blue",   alpha=0.7)
axes[1].plot(bids,               label="GM Bid Quote",    color="orange", alpha=0.7)
axes[1].plot(df["price"].values, label="Real Trade Price",color="green",  alpha=0.5, linewidth=0.8)
axes[1].set_xlabel("Trade Number")
axes[1].set_ylabel("Price ($)")
axes[1].set_title("GM Model Quotes vs Real BTC-USD Trade Prices")
axes[1].legend()
axes[1].grid(True)

plt.tight_layout()
plt.savefig("ps2_q4_gm_real_data.png", dpi=150)
plt.show()

# ── 7. Summary stats ───────────────────────────────────────────────────────
print(f"\nFinal belief P(V = VH): {beliefs[-1]:.4f}")
print(f"Buy orders:  {orders.count('buy')}")
print(f"Sell orders: {orders.count('sell')}")
print(f"Final GM ask: {asks[-1]:.2f},  Final GM bid: {bids[-1]:.2f}")
print(f"Real price range: {df['price'].min():.2f} – {df['price'].max():.2f}")


# In[ ]:


# mu = 0.05: reflects realistic informed-trader fraction in liquid crypto markets.
# With mu = 0.30 (PS1), belief collapsed within 200 trades.
# With mu = 0.05, belief gradually drifts toward VL over ~1500 trades,
# tracking the net sell pressure (1717 sells vs 1635 buys) in this hour.
# GM quotes closely follow real BTC-USD prices in the first half,
# then diverge as the static model converges — a known limitation
# of the one-shot GM framework applied to continuous markets.

