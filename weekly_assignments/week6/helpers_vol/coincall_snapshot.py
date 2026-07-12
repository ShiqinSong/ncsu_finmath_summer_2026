"""
Week 6 — Build one BTC option-chain snapshot from recorded Coincall order-book
captures, and invert it to an implied-vol smile per expiry.

Data layout (see CLAUDE.md): hourly folders of per-symbol parquet files under
``options_ob_ws/<YYYYMMDD_HHMM>/``, one row per book update
(``symbol, recv_ts_ms, server_ts, bid1_px, bid1_sz, ask1_px, ask1_sz, n_bids,
n_asks``), plus a top-of-book BTC futures L2 stream under
``futures_ws/btcusd_<YYYYMMDD>_<HH>.parquet`` used as the forward-price proxy.

A "snapshot" is not a single recorded row — each symbol updates asynchronously
— so we pick one instant in time and take, per symbol, the most recent update
at or before that instant. Options are priced with the undiscounted Black-76
formula (r=0, matching the r=0 default used elsewhere in this repo's Week 6
code): only the forward F enters, so no separate discount-rate assumption is
needed. We invert to IV using OTM options only (OTM puts for K<F, OTM calls
for K>=F) since those quotes carry the least bid-ask noise relative to price.

    python coincall_snapshot.py
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import brentq
from scipy.stats import norm

OB_BASE = "/Volumes/SEAGATE/Crypto/Coincall_OB/options_ob_ws"
FUT_BASE = "/Volumes/SEAGATE/Crypto/Coincall_OB/futures_ws"

SYMBOL_RE = re.compile(r"^BTCUSD-(\d{1,2}[A-Z]{3}\d{2})-(\d+)-([CP])$")
OPTION_EXPIRY_HOUR_UTC = 8  # Coincall BTC options expire 08:00 UTC


def _parse_symbol(symbol: str) -> pd.Series:
    m = SYMBOL_RE.match(symbol)
    expiry_str, strike, cp = m.groups()
    expiry = (pd.to_datetime(expiry_str, format="%d%b%y", utc=True)
              + pd.Timedelta(hours=OPTION_EXPIRY_HOUR_UTC))
    return pd.Series({"expiry": expiry, "strike": float(strike), "cp": cp})


_OB_BASE_COLS = ["symbol", "recv_ts_ms", "server_ts", "n_bids", "n_asks"]


def _normalize_ob_file(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the two ``options_ob_ws`` schema versions seen in this capture.

    Recordings through 2026-06-17 stored single top-of-book fields
    (``bid1_px``/``ask1_px``); from 2026-06-18 onward the capture switched to
    a 10-level L2 book (``bid_px_00``...``bid_px_09`` etc.) with no
    ``bid1_px`` column at all. We only need top-of-book, so normalize both to
    the same ``bid1_px``/``bid1_sz``/``ask1_px``/``ask1_sz`` names.
    """
    if "bid1_px" in df.columns:
        return df[_OB_BASE_COLS + ["bid1_px", "bid1_sz", "ask1_px", "ask1_sz"]].copy()
    rename = {"bid_px_00": "bid1_px", "bid_sz_00": "bid1_sz",
              "ask_px_00": "ask1_px", "ask_sz_00": "ask1_sz"}
    return df[_OB_BASE_COLS + list(rename.keys())].rename(columns=rename)


def load_chain_snapshot(hour: str, offset_min: float = 30.0) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Load one point-in-time BTC option chain snapshot.

    ``hour`` is an ``options_ob_ws`` folder name, e.g. ``"20260616_1200"``.
    The snapshot instant is ``offset_min`` minutes after the folder's first
    recorded update (folders span roughly one hour but are not calendar
    aligned to their own label).  Returns the valid two-sided-quote chain
    (with ``mid``, ``expiry``, ``strike``, ``cp``, ``T``) and the snapshot
    timestamp (UTC).
    """
    files = sorted(f for f in glob.glob(f"{OB_BASE}/{hour}/*.parquet")
                    if not Path(f).name.startswith("._"))
    if not files:
        raise FileNotFoundError(f"no parquet files under {OB_BASE}/{hour}")

    ob = pd.concat([_normalize_ob_file(pq.read_table(f).to_pandas()) for f in files],
                   ignore_index=True)
    for c in ["bid1_px", "bid1_sz", "ask1_px", "ask1_sz"]:
        ob[c] = pd.to_numeric(ob[c], errors="coerce")

    target_ts = ob["recv_ts_ms"].min() + int(offset_min * 60_000)
    target_dt = pd.to_datetime(target_ts, unit="ms", utc=True)

    pool = ob[ob["recv_ts_ms"] <= target_ts]
    latest_idx = pool.groupby("symbol")["recv_ts_ms"].idxmax()
    snap = ob.loc[latest_idx].reset_index(drop=True)

    valid = snap[(snap["n_bids"] > 0) & (snap["n_asks"] > 0)
                 & snap["bid1_px"].notna() & snap["ask1_px"].notna()].copy()
    valid["mid"] = (valid["bid1_px"] + valid["ask1_px"]) / 2
    valid = pd.concat([valid, valid["symbol"].apply(_parse_symbol)], axis=1)
    valid["T"] = (valid["expiry"] - target_dt).dt.total_seconds() / (365.25 * 24 * 3600)
    return valid, target_dt


def forward_price(target_dt: pd.Timestamp) -> float:
    """BTC forward proxy: top-of-book futures mid nearest ``target_dt``."""
    fut_file = f"{FUT_BASE}/btcusd_{target_dt.strftime('%Y%m%d_%H')}.parquet"
    fut = pq.read_table(fut_file, columns=["recv_ts_ms", "bid_px_00", "ask_px_00"]).to_pandas()
    target_ts = int(target_dt.timestamp() * 1000)
    row = fut.iloc[(fut["recv_ts_ms"] - target_ts).abs().argmin()]
    return float((row["bid_px_00"] + row["ask_px_00"]) / 2)


def black76_price(F: float, K: float, T: float, sigma: float, cp: str) -> float:
    """Undiscounted Black-76 price (r=0, consistent with the repo's Week 6 default)."""
    if sigma <= 0 or T <= 0:
        return max(F - K, 0.0) if cp == "C" else max(K - F, 0.0)
    d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if cp == "C":
        return F * norm.cdf(d1) - K * norm.cdf(d2)
    return K * norm.cdf(-d2) - F * norm.cdf(-d1)


def implied_vol(price: float, F: float, K: float, T: float, cp: str,
                 lo: float = 1e-4, hi: float = 5.0) -> float:
    """Invert ``black76_price`` for sigma by bisection; NaN if unbracketed/sub-intrinsic."""
    intrinsic = max(F - K, 0.0) if cp == "C" else max(K - F, 0.0)
    if price <= intrinsic + 1e-10:
        return np.nan
    f = lambda s: black76_price(F, K, T, s, cp) - price
    if f(lo) > 0 or f(hi) < 0:
        return np.nan
    return brentq(f, lo, hi, xtol=1e-8)


def parity_forwards(chain: pd.DataFrame, fallback_F: float) -> dict[pd.Timestamp, float]:
    """Per-expiry forward via put-call parity: ``F = median(K + C_mid - P_mid)``
    over strikes quoting both a call and a put for that expiry.

    Coincall's dated futures/options curve is in contango, so the forward
    implied by each expiry's own quotes runs meaningfully above a single
    near-term futures mid, and increasingly so for longer-dated expiries.
    Using one flat futures-based ``F`` for every expiry misplaces the
    OTM-put/OTM-call switch point away from the true at-the-money strike,
    which shows up as a sharp, spurious jump in the stitched smile exactly
    at ``k=0`` (worse the further out the expiry). Falls back to
    ``fallback_F`` for an expiry with no dual-quoted strike.
    """
    forwards = {}
    for expiry, g in chain.groupby("expiry"):
        piv = g.pivot_table(index="strike", columns="cp", values="mid", aggfunc="first")
        piv = piv.dropna(subset=[c for c in ("C", "P") if c in piv.columns])
        if {"C", "P"}.issubset(piv.columns) and not piv.empty:
            forwards[expiry] = float((piv.index + (piv["C"] - piv["P"])).median())
        else:
            forwards[expiry] = fallback_F
    return forwards


def build_otm_smiles(chain: pd.DataFrame, forwards: dict[pd.Timestamp, float]) -> dict[pd.Timestamp, pd.DataFrame]:
    """Invert the OTM leg of the chain to IV and return per-expiry smiles.

    ``forwards`` gives each expiry its own forward (see ``parity_forwards``);
    a single shared forward across expiries misplaces the OTM switch point
    and produces a spurious ATM discontinuity. Each smile carries
    log-moneyness ``k = ln(K/F)`` and total variance ``w = iv**2 * T``, the
    ``(k, w)`` pairs SVI is calibrated to.
    """
    chain = chain.copy()
    chain["F"] = chain["expiry"].map(forwards)
    otm_mask = np.where(chain["strike"] < chain["F"], chain["cp"] == "P", chain["cp"] == "C")
    otm = chain[otm_mask].copy()
    otm["iv"] = otm.apply(lambda r: implied_vol(r["mid"], r["F"], r["strike"], r["T"], r["cp"]), axis=1)
    otm["k"] = np.log(otm["strike"] / otm["F"])
    otm["w"] = otm["iv"] ** 2 * otm["T"]
    otm = otm.dropna(subset=["iv"]).sort_values("strike")

    return {expiry: g.reset_index(drop=True) for expiry, g in otm.groupby("expiry")}


if __name__ == "__main__":
    chain, target_dt = load_chain_snapshot("20260616_1200")
    F_fut = forward_price(target_dt)
    forwards = parity_forwards(chain, fallback_F=F_fut)
    smiles = build_otm_smiles(chain, forwards)

    print(f"snapshot instant: {target_dt}   futures F = {F_fut:.2f}")
    print(f"{len(chain)} symbols, {sum(len(g) for g in smiles.values())} OTM quotes "
          f"across {len(smiles)} expiries\n")
    for expiry, g in smiles.items():
        print(f"{expiry.date()}  T={g['T'].iloc[0]:.4f}y  n={len(g):2d}  "
              f"F_parity={forwards[expiry]:.1f} (+{forwards[expiry]-F_fut:.1f} vs futures)  "
              f"IV range [{g['iv'].min():.3f}, {g['iv'].max():.3f}]")
