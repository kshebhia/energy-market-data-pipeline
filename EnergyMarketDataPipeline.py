"""
Energy Market Data Pipeline - German generation and day-ahead prices
Source: Energy-Charts API by Fraunhofer ISE (https://api.energy-charts.info), CC BY 4.0.
No API key needed.

What it does:
  1. Pulls one month of public net generation by technology for Germany (/public_power).
  2. Pulls day-ahead prices for the DE-LU bidding zone (/price).
  3. Checks both for gaps (missing timestamps) and outliers.
  4. Saves clean CSV files, a short data-quality report and two charts.

Run:  pip install requests pandas matplotlib
      python energy_data_pipeline.py --start 2026-10-01 --end 2026-10-31
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import requests

BASE = "https://api.energy-charts.info"
OUT = Path("output")


def get_json(endpoint: str, params: dict) -> dict:
    """Make one API request and return the JSON body."""
    r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def load_generation(start: str, end: str) -> pd.DataFrame:
    data = get_json("public_power", {"country": "de", "start": start, "end": end})
    idx = pd.to_datetime(data["unix_seconds"], unit="s", utc=True)
    cols = {p["name"]: p["data"] for p in data["production_types"]}
    return pd.DataFrame(cols, index=idx)  # values in MW


def load_prices(start: str, end: str) -> pd.DataFrame:
    data = get_json("price", {"bzn": "DE-LU", "start": start, "end": end})
    idx = pd.to_datetime(data["unix_seconds"], unit="s", utc=True)
    return pd.DataFrame({"price_eur_mwh": data["price"]}, index=idx)


def quality_report(df: pd.DataFrame, name: str) -> dict:
    """Count missing timestamps, missing values and outliers (outside 1st-99th percentile x3 range)."""
    step = df.index.to_series().diff().mode().iloc[0]
    expected = pd.date_range(df.index.min(), df.index.max(), freq=step)
    missing_ts = len(expected.difference(df.index))
    missing_vals = int(df.isna().sum().sum())
    outliers = 0
    for col in df.select_dtypes("number"):
        s = df[col].dropna()
        if s.empty:
            continue
        lo, hi = s.quantile(0.01), s.quantile(0.99)
        span = hi - lo
        outliers += int(((s < lo - 3 * span) | (s > hi + 3 * span)).sum())
    return {
        "dataset": name,
        "rows": len(df),
        "time_step": str(step),
        "missing_timestamps": missing_ts,
        "missing_values": missing_vals,
        "outliers": outliers,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-10-01")
    ap.add_argument("--end", default="2026-10-31")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    gen = load_generation(a.start, a.end)
    price = load_prices(a.start, a.end)

    report = [quality_report(gen, "generation"), quality_report(price, "price")]

    # Simple facts for the CV line (real numbers from your run)
    # Pumped storage only shifts energy, so it counts as neither renewable nor generation here
    skip = ("load", "residual load", "renewable share of generation", "renewable share of load",
            "cross border electricity trading")
    total_cols = [c for c in gen.columns if c.lower() not in skip and "pumped storage" not in c.lower()]
    renew_cols = [c for c in total_cols if any(k in c.lower() for k in
                  ["solar", "wind", "hydro", "biomass", "geothermal"])]
    G = gen[total_cols].clip(lower=0).sum(axis=1)          # total generation per 15-min interval
    R = gen[renew_cols].clip(lower=0).sum(axis=1)          # renewable generation per interval
    renew_share = R.sum() / G.sum()                         # energy-weighted share

    # --- Reconcile my share with the source's own "Renewable share of generation" column ---
    src = gen["Renewable share of generation"]
    waste = gen["Waste"].clip(lower=0) if "Waste" in gen.columns else 0
    reconcile = {
        "source_share_simple_mean_pct": round(src.mean(), 1),
        "source_share_energy_weighted_pct": round((src * G).sum() / G.sum(), 1),
        "my_share_energy_weighted_pct": round(100 * renew_share, 1),
        "my_share_with_50pct_waste_as_renewable_pct": round(100 * (R + 0.5 * waste).sum() / G.sum(), 1),
    }

    # --- Daily values on local (Berlin) days: does wind push prices down? ---
    local_gen = gen.tz_convert("Europe/Berlin")
    local_price = price.tz_convert("Europe/Berlin")
    wind_cols = [c for c in gen.columns if "wind" in c.lower()]
    daily = pd.DataFrame({
        "wind_mw": local_gen[wind_cols].sum(axis=1).resample("D").mean(),
        "price_eur_mwh": local_price["price_eur_mwh"].resample("D").mean(),
    })
    wind_price = {
        "daily_wind_vs_price_correlation": round(daily["wind_mw"].corr(daily["price_eur_mwh"]), 2),
        "lowest_daily_price": {"date": str(daily["price_eur_mwh"].idxmin().date()),
                               "price_eur_mwh": round(daily["price_eur_mwh"].min()),
                               "wind_mw": round(daily.loc[daily["price_eur_mwh"].idxmin(), "wind_mw"])},
        "highest_daily_price": {"date": str(daily["price_eur_mwh"].idxmax().date()),
                                "price_eur_mwh": round(daily["price_eur_mwh"].max()),
                                "wind_mw": round(daily.loc[daily["price_eur_mwh"].idxmax(), "wind_mw"])},
    }

    summary = {
        "period": f"{a.start} to {a.end}",
        "renewable_share_of_generation_pct": round(100 * renew_share, 1),
        "avg_day_ahead_price_eur_mwh": round(price["price_eur_mwh"].mean(), 2),
        "negative_price_15min_slots": int((price["price_eur_mwh"] < 0).sum()),
        "zero_or_negative_price_15min_slots": int((price["price_eur_mwh"] <= 0).sum()),
        "share_reconciliation": reconcile,
        "wind_vs_price": wind_price,
        "quality": report,
    }

    gen.to_csv(OUT / "generation_de.csv")
    price.to_csv(OUT / "price_de_lu.csv")
    daily.to_csv(OUT / "daily_wind_price.csv")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))

    gen[renew_cols].resample("D").mean().plot(figsize=(10, 4), title="Daily mean renewable generation, DE (MW)")
    plt.tight_layout(); plt.savefig(OUT / "renewables_daily.png", dpi=150); plt.close()
    price.resample("D").mean().plot(figsize=(10, 4), title="Daily mean day-ahead price, DE-LU (EUR/MWh)", legend=False)
    plt.tight_layout(); plt.savefig(OUT / "price_daily.png", dpi=150); plt.close()

    print(json.dumps(summary, indent=2))
    print("\nData: Energy-Charts (Fraunhofer ISE), CC BY 4.0")


if __name__ == "__main__":
    main()