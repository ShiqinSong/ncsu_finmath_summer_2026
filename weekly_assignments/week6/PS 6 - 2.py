#!/usr/bin/env python
# coding: utf-8

# In[4]:


import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# SVI Surface and Static Arbitrage Checks

# 1. Raw SVI total-variance parameterization w(k)
# 2. Analytic first and second derivatives
# 3. Butterfly-arbitrage diagnostic g(k)
# 4. Raw-SVI parameter checks
# 5. Lee wing-slope condition
# 6. Positivity of total variance
# 7. Calendar-spread checks across maturities
# 8. Detailed reporting of which constraints fail and where
#
# Raw SVI:
#
#   w(k) = a + b * [rho * (k - m)
#                   + sqrt((k - m)^2 + sigma^2)]
#
# where k is log-forward-moneyness.


def svi_total_variance(k, a, b, rho, m, sigma):
    """
    Raw SVI total implied variance:
        w(k) = a + b * [rho * (k - m) + sqrt((k - m)^2 + sigma^2)]
    """
    x = k - m
    return a + b * (rho * x + np.sqrt(x**2 + sigma**2))


def svi_first_derivative(k, b, rho, m, sigma):
    """First derivative w'(k)."""
    x = k - m
    return b * (rho + x / np.sqrt(x**2 + sigma**2))


def svi_second_derivative(k, b, m, sigma):
    """Second derivative w''(k)."""
    x = k - m
    return b * sigma**2 / (x**2 + sigma**2) ** 1.5


# Butterfly-arbitrage diagnostic

def butterfly_g_function(k, a, b, rho, m, sigma):
    """
    Gatheral butterfly-arbitrage diagnostic.

    A standard local no-butterfly-arbitrage condition is:
        g(k) >= 0
    for all k, together with suitable tail behavior.
    """
    w = svi_total_variance(k, a, b, rho, m, sigma)
    wp = svi_first_derivative(k, b, rho, m, sigma)
    wpp = svi_second_derivative(k, b, m, sigma)

    with np.errstate(divide="ignore", invalid="ignore"):
        g = (
            (1.0 - k * wp / (2.0 * w)) ** 2
            - (wp**2 / 4.0) * (1.0 / w + 0.25)
            + wpp / 2.0
        )

    return g



# Parameter-level checks

def check_svi_parameters(params):
    """
    Check basic raw-SVI parameter restrictions.

    Conditions checked:
      1. b >= 0
      2. sigma > 0
      3. |rho| < 1
      4. Minimum total variance is nonnegative
      5. Lee wing-slope condition:
             b * (1 + |rho|) <= 2

    The raw-SVI minimum is:
        a + b * sigma * sqrt(1 - rho^2)
    when |rho| < 1.
    """
    a = params["a"]
    b = params["b"]
    rho = params["rho"]
    m = params["m"]
    sigma = params["sigma"]

    del m  

    rho_valid = abs(rho) < 1.0

    if rho_valid and sigma > 0 and b >= 0:
        min_total_variance = a + b * sigma * np.sqrt(1.0 - rho**2)
    else:
        min_total_variance = np.nan

    wing_slope = b * (1.0 + abs(rho))

    checks = {
        "b_nonnegative": b >= 0,
        "sigma_positive": sigma > 0,
        "rho_in_range": rho_valid,
        "min_variance_nonnegative": (
            np.isfinite(min_total_variance) and min_total_variance >= 0
        ),
        "wing_condition_b(1+|rho|)<=2": wing_slope <= 2.0,
    }

    values = {
        "min_total_variance_value": (
            float(min_total_variance) if np.isfinite(min_total_variance) else np.nan
        ),
        "wing_slope_value": float(wing_slope),
    }

    return checks, values


# Violation-range reporting

def summarize_violation_ranges(k, mask):
    """
    Convert a boolean violation mask into contiguous intervals of
    k-values.

    Example output:
        [(-1.0, -0.42), (0.65, 1.0)]
    """
    ranges = []
    in_run = False
    start_idx = None

    for i, flag in enumerate(mask):
        if flag and not in_run:
            in_run = True
            start_idx = i
        elif not flag and in_run:
            in_run = False
            ranges.append((round(float(k[start_idx]), 4), round(float(k[i - 1]), 4)))

    if in_run:
        ranges.append((round(float(k[start_idx]), 4), round(float(k[-1]), 4)))

    return ranges



# Main single-slice SVI analysis

def analyze_svi(
    params,
    maturity=1.0,
    k_min=-1.0,
    k_max=1.0,
    n_points=501,
    name="SVI"
):
    """
    Generate an SVI smile and perform:
      - parameter-level checks
      - total-variance positivity checks
      - pointwise butterfly checks
      - violation-range reporting
    """
    if maturity <= 0:
        raise ValueError("maturity must be positive.")

    if n_points < 3:
        raise ValueError("n_points must be at least 3.")

    k = np.linspace(k_min, k_max, n_points)

    w = svi_total_variance(
        k, params["a"], params["b"], params["rho"], params["m"], params["sigma"]
    )

    implied_volatility = np.full_like(w, np.nan, dtype=float)
    positive_variance_mask = w > 0
    implied_volatility[positive_variance_mask] = np.sqrt(
        w[positive_variance_mask] / maturity
    )

    g = butterfly_g_function(
        k, params["a"], params["b"], params["rho"], params["m"], params["sigma"]
    )

    basic_checks, basic_values = check_svi_parameters(params)

    variance_violation_mask = ~np.isfinite(w) | (w <= 0)
    butterfly_violation_mask = ~np.isfinite(g) | (g < 0)

    variance_violations = int(np.sum(variance_violation_mask))
    butterfly_violations = int(np.sum(butterfly_violation_mask))

    variance_violation_ranges = summarize_violation_ranges(k, variance_violation_mask)
    butterfly_violation_ranges = summarize_violation_ranges(k, butterfly_violation_mask)

    results = pd.DataFrame({
        "k": k,
        "total_variance": w,
        "implied_volatility": implied_volatility,
        "g_function": g,
        "variance_positive": np.isfinite(w) & (w > 0),
        "butterfly_safe": np.isfinite(g) & (g >= 0),
    })

    failing_constraints = []

    for check_name, passed in basic_checks.items():
        if not passed:
            failing_constraints.append("parameter check failed: " + check_name)

    if variance_violations > 0:
        failing_constraints.append(
            "total variance w(k) <= 0 or non-finite on k-ranges: "
            f"{variance_violation_ranges}"
        )

    if butterfly_violations > 0:
        failing_constraints.append(
            "butterfly condition g(k) < 0 or non-finite on k-ranges: "
            f"{butterfly_violation_ranges}"
        )

    finite_w = w[np.isfinite(w)]
    finite_g = g[np.isfinite(g)]

    minimum_total_variance = (
        float(np.min(finite_w)) if finite_w.size > 0 else np.nan
    )
    minimum_g = float(np.min(finite_g)) if finite_g.size > 0 else np.nan

    summary = {
        "name": name,
        "basic_checks": basic_checks,
        "basic_values": basic_values,
        "variance_violations": variance_violations,
        "butterfly_violations": butterfly_violations,
        "variance_violation_ranges": variance_violation_ranges,
        "butterfly_violation_ranges": butterfly_violation_ranges,
        "minimum_total_variance": minimum_total_variance,
        "minimum_g": minimum_g,
        "failing_constraints": failing_constraints,
        "is_arbitrage_free": len(failing_constraints) == 0,
    }

    return results, summary



# Calendar-spread check

def check_calendar_spread(
    param_sets_by_maturity,
    k_min=-1.0,
    k_max=1.0,
    n_points=501
):
    """
    Check calendar-spread no-arbitrage:
        w(k, T2) >= w(k, T1)
    whenever T2 > T1.

    Input format:
        {0.5: params_short, 1.0: params_long}
    """
    maturities = sorted(param_sets_by_maturity.keys())

    if len(maturities) < 2:
        return {
            "checked": False,
            "note": (
                "Calendar-spread check skipped: only one maturity supplied."
            ),
        }

    if any(T <= 0 for T in maturities):
        raise ValueError("All maturities must be positive.")

    k = np.linspace(k_min, k_max, n_points)
    violations = {}

    for T1, T2 in zip(maturities[:-1], maturities[1:]):
        p1 = param_sets_by_maturity[T1]
        p2 = param_sets_by_maturity[T2]

        w1 = svi_total_variance(k, p1["a"], p1["b"], p1["rho"], p1["m"], p1["sigma"])
        w2 = svi_total_variance(k, p2["a"], p2["b"], p2["rho"], p2["m"], p2["sigma"])

        mask = ~np.isfinite(w1) | ~np.isfinite(w2) | (w2 < w1)

        if np.any(mask):
            violations[(T1, T2)] = summarize_violation_ranges(k, mask)

    return {
        "checked": True,
        "violations": violations,
        "is_arbitrage_free": len(violations) == 0,
    }



# Output summary

def print_summary(summary):
    print("\n" + "=" * 72)
    print(summary["name"])
    print("=" * 72)

    for check_name, passed in summary["basic_checks"].items():
        status = "PASS" if passed else "FAIL"
        print(f"{check_name:40s}: {status}")

    min_var_value = summary["basic_values"]["min_total_variance_value"]
    wing_value = summary["basic_values"]["wing_slope_value"]

    print(
        f"{'min_total_variance_value':40s}: {min_var_value:.6f}"
        if np.isfinite(min_var_value)
        else f"{'min_total_variance_value':40s}: NaN"
    )

    print(f"{'wing slope b(1+|rho|)':40s}: {wing_value:.6f} (must be <= 2)")

    print("-" * 72)
    print("Total variance violations :", summary["variance_violations"])
    if summary["variance_violation_ranges"]:
        print("  -> k-ranges:", summary["variance_violation_ranges"])

    print("Butterfly violations      :", summary["butterfly_violations"])
    if summary["butterfly_violation_ranges"]:
        print("  -> k-ranges:", summary["butterfly_violation_ranges"])

    print(
        "Minimum total variance    :",
        f"{summary['minimum_total_variance']:.6f}"
        if np.isfinite(summary["minimum_total_variance"])
        else "NaN"
    )

    print(
        "Minimum g(k)              :",
        f"{summary['minimum_g']:.6f}"
        if np.isfinite(summary["minimum_g"])
        else "NaN"
    )

    print("-" * 72)

    if summary["is_arbitrage_free"]:
        print("RESULT: No static parameter-level or butterfly arbitrage detected.")
    else:
        print("RESULT: ARBITRAGE DETECTED.")
        print("Failing constraints:")
        for item in summary["failing_constraints"]:
            print("   -", item)



# Plotting 

def plot_comparison(valid_results, broken_results):
    # Total variance
    plt.figure(figsize=(10, 5))
    plt.plot(valid_results["k"], valid_results["total_variance"], label="Valid SVI")
    plt.plot(broken_results["k"], broken_results["total_variance"], label="Broken SVI")
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xlabel("Log-moneyness k")
    plt.ylabel("Total variance w(k)")
    plt.title("SVI Total Implied Variance")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Implied volatility
    plt.figure(figsize=(10, 5))
    plt.plot(valid_results["k"], valid_results["implied_volatility"], label="Valid SVI")
    plt.plot(broken_results["k"], broken_results["implied_volatility"], label="Broken SVI")
    plt.xlabel("Log-moneyness k")
    plt.ylabel("Implied volatility")
    plt.title("SVI Implied Volatility Smile")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Butterfly diagnostic
    plt.figure(figsize=(10, 5))
    plt.plot(valid_results["k"], valid_results["g_function"], label="Valid SVI")
    plt.plot(broken_results["k"], broken_results["g_function"], label="Broken SVI")
    plt.axhline(0, linestyle="--", linewidth=1, label="No-arbitrage boundary")
    plt.xlabel("Log-moneyness k")
    plt.ylabel("g(k)")
    plt.title("Butterfly Arbitrage Diagnostic")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()



# Main execution

if __name__ == "__main__":

    valid_params = {
        "a": 0.04,
        "b": 0.20,
        "rho": -0.40,
        "m": 0.00,
        "sigma": 0.30,
    }

    # Deliberately broken:
    # - negative a pushes total variance down
    # - aggressive b and rho violate the wing bound
    # - butterfly violations may also appear
    broken_params = {
        "a": -0.02,
        "b": 1.50,
        "rho": -0.95,
        "m": 0.00,
        "sigma": 0.05,
    }

    valid_results, valid_summary = analyze_svi(
        valid_params, maturity=1.0, name="Valid SVI Parameter Set"
    )

    broken_results, broken_summary = analyze_svi(
        broken_params, maturity=1.0, name="Broken SVI Parameter Set"
    )

    print_summary(valid_summary)
    print_summary(broken_summary)

    # Single maturity: calendar check will be skipped.
    calendar_check = check_calendar_spread({1.0: valid_params})

    print("\n" + "=" * 72)
    print("Calendar-spread check")
    print("=" * 72)

    if not calendar_check["checked"]:
        print(calendar_check["note"])
    else:
        print(calendar_check)

    plot_comparison(valid_results, broken_results)


# In[ ]:




