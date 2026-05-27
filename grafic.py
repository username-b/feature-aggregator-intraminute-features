import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import time
import urllib3

# =========================================================
# DISABLE SSL WARNINGS
# =========================================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================================================
# SETTINGS
# =========================================================

START_DATE = "2020-02-01"
END_DATE = "2026-02-01"

OUTPUT_ALL = "coinmarketcap_historical_rankings.csv"
OUTPUT_ADA = "ada_only.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    )
}

# =========================================================
# GENERATE WEEKLY SNAPSHOT DATES
# =========================================================

start = datetime.strptime(START_DATE, "%Y-%m-%d")
end = datetime.strptime(END_DATE, "%Y-%m-%d")

dates = []

current = start

while current <= end:
    dates.append(current.strftime("%Y%m%d"))
    current += timedelta(days=7)

print(f"Total snapshots: {len(dates)}")

# =========================================================
# STORAGE
# =========================================================

all_rows = []

# =========================================================
# SCRAPER LOOP
# =========================================================

for snapshot_date in dates:

    url = f"https://coinmarketcap.com/historical/{snapshot_date}/"

    print()
    print("=" * 60)
    print(f"Downloading: {url}")

    try:

        # =================================================
        # DOWNLOAD PAGE
        # =================================================

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
            verify=False
        )

        if response.status_code != 200:

            print(f"HTTP ERROR: {response.status_code}")
            continue

        # =================================================
        # PARSE HTML
        # =================================================

        soup = BeautifulSoup(response.text, "html.parser")

        script_tag = soup.find("script", id="__NEXT_DATA__")

        if script_tag is None:

            print("NEXT_DATA not found")
            continue

        # =================================================
        # LOAD JSON
        # =================================================

        json_data = json.loads(script_tag.string)

        # =================================================
        # GET initialState
        # =================================================

        initial_state_raw = (
            json_data
            .get("props", {})
            .get("initialState", "")
        )

        if not initial_state_raw:

            print("initialState is empty")
            continue

        # =================================================
        # PARSE initialState JSON STRING
        # =================================================

        try:

            initial_state = json.loads(initial_state_raw)

        except Exception as e:

            print("Cannot parse initialState")
            print(e)
            continue

        # =================================================
        # EXTRACT HISTORICAL LISTINGS
        # =================================================

        try:

            cryptocurrencies = (
                initial_state
                ["cryptocurrency"]
                ["listingHistorical"]
                ["data"]
            )

        except Exception as e:

            print("Cannot extract listingHistorical")
            print(e)
            continue

        # =================================================
        # EXTRACT ROWS
        # =================================================

        collected = 0

        for coin in cryptocurrencies:

            try:

                usd_quote = coin["quote"]["USD"]

                row = {
                    "snapshot_date": snapshot_date,
                    "rank": coin.get("cmcRank"),
                    "name": coin.get("name"),
                    "symbol": coin.get("symbol"),
                    "market_cap": usd_quote.get("marketCap"),
                    "price": usd_quote.get("price"),
                    "volume24h": usd_quote.get("volume24h"),
                    "percent_change_24h": usd_quote.get("percentChange24h"),
                    "percent_change_7d": usd_quote.get("percentChange7d"),
                    "circulating_supply": coin.get("circulatingSupply"),
                }

                all_rows.append(row)

                collected += 1

            except Exception:
                pass

        print(f"Collected rows: {collected}")

        # polite delay
        time.sleep(2)

    except Exception as e:

        print("ERROR:")
        print(e)

# =========================================================
# CREATE DATAFRAME
# =========================================================

df = pd.DataFrame(all_rows)

print()
print("=" * 60)
print("FINAL RESULT")
print("=" * 60)

print(df.head())

print()
print(f"Total rows: {len(df)}")

# =========================================================
# SAVE FULL DATASET
# =========================================================

if len(df) == 0:

    print("WARNING: EMPTY DATAFRAME")

else:

    df.to_csv(OUTPUT_ALL, index=False)

    print(f"Saved full dataset: {OUTPUT_ALL}")

# =========================================================
# ADA SUBSET
# =========================================================

ada = df[df["symbol"] == "ADA"].copy()

if len(ada) > 0:

    ada.to_csv(OUTPUT_ADA, index=False)

    print(f"Saved ADA dataset: {OUTPUT_ADA}")

    print()
    print("=" * 60)
    print("ADA SUMMARY")
    print("=" * 60)

    print(f"Observations: {len(ada)}")
    print(f"Best rank: {ada['rank'].min()}")
    print(f"Worst rank: {ada['rank'].max()}")
    print(f"Median rank: {ada['rank'].median():.2f}")

    top10_share = (ada["rank"] <= 10).mean() * 100
    top20_share = (ada["rank"] <= 20).mean() * 100

    print(f"Weeks in TOP-10: {top10_share:.2f}%")
    print(f"Weeks in TOP-20: {top20_share:.2f}%")

else:

    print("ADA not found in dataset")