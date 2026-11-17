# Energy Market Data Pipeline

A small Python tool that pulls German electricity generation and day-ahead price data from the public
[Energy-Charts API](https://api.energy-charts.info) (Fraunhofer ISE), checks the data quality, and turns it
into clean CSV files, a summary and charts.

## What it does

1. Requests 15-minute public net generation by technology for Germany (`/public_power`).
2. Requests 15-minute day-ahead prices for the DE-LU bidding zone (`/price`).
3. Checks both datasets for missing timestamps, missing values and outliers.
4. Calculates the renewable share of generation and compares it with the source's own figure.
5. Compares daily wind output with daily prices (local Berlin days).
6. Saves CSV files, `summary.json` and two charts to an `output/` folder. The results from my October 2026
   run are in the main folder of this repository.

## How to run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python EnergyMarketDataPipeline.py --start 2026-10-01 --end 2026-10-31
```

No API key is needed.

## Results for October 2026

**Data quality**
- 2,980 fifteen-minute intervals per dataset (31 days x 96, plus 4 for the clock change on 25 October).
- No missing timestamps, no missing values, no outliers.

**Renewable share: why my number differed from the source**

| Method | Renewable share |
|---|---|
| Source column, simple average of 15-minute shares | 57.6% |
| My calculation, energy-weighted | 59.8% |
| Source column, energy-weighted | 60.9% |
| My calculation, energy-weighted, 50% of waste counted as renewable | 60.9% |

The 2.2-point gap had two causes:
1. **Averaging method.** A simple average of 15-minute shares gives every interval the same weight. An
   energy-weighted share counts intervals with more generation more heavily.
2. **Waste.** The source counts part of waste incineration as renewable (its biogenic share). My first
   version counted none.

Once both are measured the same way, the figures match.

**Wind and price**
- Daily wind output and daily day-ahead price have a correlation of -0.82.
- Highest daily price: 315 EUR/MWh on 29 October, with about 4 GW of wind.
- Lowest daily price: 13 EUR/MWh on 25 October, with about 44 GW of wind.

## Output files

| File | Content |
|---|---|
| `generation_de.csv` | 15-minute generation by technology (MW) |
| `price_de_lu.csv` | 15-minute day-ahead price (EUR/MWh) |
| `daily_wind_price.csv` | Daily mean wind output and price |
| `summary.json` | Data-quality checks, reconciliation and key figures |
| `renewables_daily.png`, `price_daily.png` | Daily charts |

## Data source and licence

Data: Energy-Charts (Fraunhofer ISE), licensed under CC BY 4.0. Price data originally from Bundesnetzagentur
(SMARD.de).
