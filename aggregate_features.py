from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict
from datetime import date

import boto3
import numpy as np
import pandas as pd

from config_loader import Settings, load_settings


LOGGER = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "open_time",
    "VWAP",
    "PI_buy",
    "PI_sell",
    "PI_total",
    "F_eff",
    "F_PI",
    "F_asymmetry",
    "VWAP_pos",
]

FLOAT_FEATURE_COLUMNS = FEATURE_COLUMNS[1:]


def make_s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def list_symbol_klines_days(symbol: str, settings: Settings, s3_client) -> list[str]:
    source_prefix = (
        f"{settings.raw_prefix.strip('/')}/klines/"
        f"symbol={symbol}/interval={settings.interval}/"
    )
    pattern = re.compile(r"/date=(\d{4}-\d{2}-\d{2})/data\.parquet$")

    dates = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=source_prefix):
        for obj in page.get("Contents", []):
            match = pattern.search(f"/{obj['Key']}")
            if match:
                dates.add(match.group(1))

    return sorted(dates)


def raw_klines_key(symbol: str, day: str, settings: Settings) -> str:
    return (
        f"{settings.raw_prefix.strip('/')}/klines/"
        f"symbol={symbol}/interval={settings.interval}/date={day}/data.parquet"
    )


def raw_agg_trades_key(symbol: str, day: str, settings: Settings) -> str:
    return (
        f"{settings.raw_prefix.strip('/')}/aggTrades/"
        f"symbol={symbol}/date={day}/data.parquet"
    )


def feature_dataset_key(symbol: str, day: str, settings: Settings) -> str:
    return (
        f"{settings.features_prefix.strip('/')}/{settings.feature_dataset_name}/"
        f"symbol={symbol}/interval={settings.interval}/date={day}/data.parquet"
    )


def s3_key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # boto3 raises generated exceptions here
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def read_symbol_klines_day(symbol: str, day: str, settings: Settings, s3_client) -> pd.DataFrame:
    key = raw_klines_key(symbol=symbol, day=day, settings=settings)
    obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))

    required_columns = ["open_time", "high", "low", "close"]
    missing_columns = sorted(set(required_columns) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing required klines columns: {missing_columns}")

    if df.empty:
        return pd.DataFrame(columns=required_columns)

    cleaned = df[required_columns].copy()
    cleaned["open_time"] = pd.to_numeric(cleaned["open_time"], errors="coerce").astype("Int64")
    for column in ["high", "low", "close"]:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned = (
        cleaned.dropna(subset=["open_time"])
        .drop_duplicates(subset=["open_time"])
        .sort_values("open_time")
        .reset_index(drop=True)
    )

    open_time_utc = pd.to_datetime(cleaned["open_time"].astype("int64"), unit="ms", utc=True)
    if not open_time_utc.dt.second.eq(0).all() or not open_time_utc.dt.microsecond.eq(0).all():
        raise ValueError("open_time must be minute-aligned UTC")

    return cleaned


def read_symbol_agg_trades_day(
    symbol: str,
    day: str,
    settings: Settings,
    s3_client,
) -> pd.DataFrame:
    key = raw_agg_trades_key(symbol=symbol, day=day, settings=settings)
    obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))

    required_columns = ["transact_time", "price", "quantity", "is_buyer_maker"]
    missing_columns = sorted(set(required_columns) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing required aggTrades columns: {missing_columns}")

    if df.empty:
        return pd.DataFrame(columns=required_columns + ["minute_bucket"])

    cleaned = df[required_columns].copy()
    cleaned["transact_time"] = pd.to_numeric(cleaned["transact_time"], errors="coerce").astype("Int64")
    cleaned["price"] = pd.to_numeric(cleaned["price"], errors="coerce")
    cleaned["quantity"] = pd.to_numeric(cleaned["quantity"], errors="coerce")
    cleaned["is_buyer_maker"] = cleaned["is_buyer_maker"].astype("boolean")
    cleaned = cleaned.dropna(subset=["transact_time", "price", "quantity", "is_buyer_maker"])

    if cleaned.empty:
        return pd.DataFrame(columns=required_columns + ["minute_bucket"])

    transact_time_utc = pd.to_datetime(cleaned["transact_time"].astype("int64"), unit="ms", utc=True)
    cleaned["minute_bucket"] = transact_time_utc.dt.floor("min").astype("int64") // 10**6

    return cleaned.sort_values(["minute_bucket", "transact_time"], kind="stable").reset_index(drop=True)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator_values = numerator.astype("float64").to_numpy()
    denominator_values = denominator.astype("float64").to_numpy()
    result = np.divide(
        numerator_values,
        denominator_values,
        out=np.zeros(len(numerator), dtype="float64"),
        where=denominator_values != 0,
    )
    return pd.Series(result, index=numerator.index)


def build_trade_features(agg_trades: pd.DataFrame) -> pd.DataFrame:
    if agg_trades.empty:
        return pd.DataFrame(
            columns=[
                "open_time",
                "VWAP",
                "PI_buy",
                "PI_sell",
                "PI_total",
                "F_PI",
            ]
        )

    trades = agg_trades.copy()
    trades["quote_qty"] = trades["price"] * trades["quantity"]
    trades["is_buy"] = ~trades["is_buyer_maker"]
    trades["sign"] = np.where(trades["is_buy"], 1.0, -1.0)

    grouped = trades.groupby("minute_bucket", sort=True)
    minute_totals = grouped.agg(
        total_quantity=("quantity", "sum"),
        quote_qty_sum=("quote_qty", "sum"),
    )
    minute_totals["VWAP"] = safe_divide(minute_totals["quote_qty_sum"], minute_totals["total_quantity"])

    trades = trades.join(minute_totals["VWAP"], on="minute_bucket")
    trades["delta_p"] = trades["price"] - trades["VWAP"]
    trades["PI_i"] = trades["sign"] * trades["quantity"] * trades["delta_p"]
    trades["price_diff_sq"] = grouped["price"].diff().pow(2).fillna(0.0)

    impact = trades.groupby(["minute_bucket", "is_buy"], sort=True)["PI_i"].sum().unstack(fill_value=0.0)
    pi_buy = impact[True] if True in impact.columns else pd.Series(0.0, index=impact.index)
    pi_sell = impact[False] if False in impact.columns else pd.Series(0.0, index=impact.index)

    rv = trades.groupby("minute_bucket", sort=True)["price_diff_sq"].sum()

    features = pd.DataFrame(index=minute_totals.index)
    features["open_time"] = features.index.astype("int64")
    features["VWAP"] = minute_totals["VWAP"]
    features["PI_buy"] = pi_buy.reindex(features.index, fill_value=0.0)
    features["PI_sell"] = pi_sell.reindex(features.index, fill_value=0.0)
    features["PI_total"] = features["PI_buy"] + features["PI_sell"]
    features["F_PI"] = safe_divide(features["PI_total"], rv * minute_totals["total_quantity"])

    return features.reset_index(drop=True)


def build_features_for_day(symbol: str, day: str, settings: Settings, s3_client) -> pd.DataFrame:
    backbone = read_symbol_klines_day(symbol=symbol, day=day, settings=settings, s3_client=s3_client)
    if backbone.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    agg_trades = read_symbol_agg_trades_day(symbol=symbol, day=day, settings=settings, s3_client=s3_client)
    trade_features = build_trade_features(agg_trades)

    feature_df = backbone.merge(trade_features, on="open_time", how="left")
    trade_value_columns = ["VWAP", "PI_buy", "PI_sell", "PI_total", "F_PI"]
    feature_df[trade_value_columns] = feature_df[trade_value_columns].fillna(0.0)

    buy_volume = (
        agg_trades.loc[~agg_trades["is_buyer_maker"]]
        .groupby("minute_bucket", sort=True)["quantity"]
        .sum()
    )
    sell_volume = (
        agg_trades.loc[agg_trades["is_buyer_maker"]]
        .groupby("minute_bucket", sort=True)["quantity"]
        .sum()
    )
    feature_df["V_buy_base"] = feature_df["open_time"].map(buy_volume).fillna(0.0)
    feature_df["V_sell_base"] = feature_df["open_time"].map(sell_volume).fillna(0.0)

    volume_imbalance_abs = (feature_df["V_buy_base"] - feature_df["V_sell_base"]).abs()
    feature_df["F_eff"] = safe_divide(feature_df["close"] - feature_df["VWAP"], volume_imbalance_abs)
    asymmetry_denominator = feature_df["PI_buy"] + feature_df["PI_sell"].abs()
    feature_df["F_asymmetry"] = safe_divide(
        feature_df["PI_buy"] - feature_df["PI_sell"].abs(),
        asymmetry_denominator,
    )
    feature_df["VWAP_pos"] = safe_divide(feature_df["close"] - feature_df["VWAP"], feature_df["high"] - feature_df["low"])

    no_trade_mask = feature_df["V_buy_base"].eq(0) & feature_df["V_sell_base"].eq(0)
    feature_df.loc[no_trade_mask, FLOAT_FEATURE_COLUMNS] = 0.0

    feature_df = feature_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    feature_df = feature_df.sort_values("open_time").reset_index(drop=True)
    feature_df["open_time"] = feature_df["open_time"].astype("int64")
    for column in FLOAT_FEATURE_COLUMNS:
        feature_df[column] = feature_df[column].astype("float32")

    return feature_df[FEATURE_COLUMNS]


def select_dates(available_dates: list[str], start_date: date | None, end_date: date | None) -> list[str]:
    selected_dates = []
    for day in available_dates:
        parsed_day = pd.Timestamp(day).date()
        if start_date and parsed_day < start_date:
            continue
        if end_date and parsed_day > end_date:
            continue
        selected_dates.append(day)
    return selected_dates


def write_features_for_symbol_to_s3(symbol: str, settings: Settings, s3_client) -> pd.DataFrame:
    available_dates = list_symbol_klines_days(symbol=symbol, settings=settings, s3_client=s3_client)
    selected_dates = select_dates(
        available_dates=available_dates,
        start_date=settings.start_date,
        end_date=settings.end_date,
    )

    if not selected_dates:
        raise FileNotFoundError(
            f"No klines days found for symbol={symbol}, interval={settings.interval}, "
            f"start_date={settings.start_date}, end_date={settings.end_date}"
        )

    rows = []
    for day in selected_dates:
        key = feature_dataset_key(symbol=symbol, day=day, settings=settings)

        if settings.skip_existing and s3_key_exists(s3_client, settings.s3_bucket, key):
            LOGGER.info("Skip exists: s3://%s/%s", settings.s3_bucket, key)
            rows.append({"symbol": symbol, "date": day, "rows": None, "key": key, "status": "skipped"})
            continue

        feature_df = build_features_for_day(symbol=symbol, day=day, settings=settings, s3_client=s3_client)
        buffer = io.BytesIO()
        feature_df.to_parquet(buffer, index=False, engine="pyarrow", compression="zstd")
        s3_client.put_object(Bucket=settings.s3_bucket, Key=key, Body=buffer.getvalue())

        LOGGER.info("Uploaded: s3://%s/%s rows=%s", settings.s3_bucket, key, len(feature_df))
        rows.append({"symbol": symbol, "date": day, "rows": len(feature_df), "key": key, "status": "uploaded"})

    return pd.DataFrame(rows)


def safe_settings_for_logs(settings: Settings) -> dict[str, object]:
    values = asdict(settings)
    values["aws_access_key_id"] = "***"
    values["aws_secret_access_key"] = "***"
    return values


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    LOGGER.info("Starting price-pressure feature aggregation with settings=%s", safe_settings_for_logs(settings))

    s3_client = make_s3_client(settings)
    results = write_features_for_symbol_to_s3(symbol=settings.symbol, settings=settings, s3_client=s3_client)

    status_counts = results["status"].value_counts(dropna=False).to_dict()
    uploaded_rows = int(results.loc[results["status"] == "uploaded", "rows"].fillna(0).sum())
    LOGGER.info(
        "Finished price-pressure feature aggregation: processed_days=%s status_counts=%s uploaded_rows=%s",
        len(results),
        status_counts,
        uploaded_rows,
    )


if __name__ == "__main__":
    main()
