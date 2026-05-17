from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict
from datetime import date, timedelta

import boto3
import numpy as np
import pandas as pd

from config_loader import Settings, load_settings


LOGGER = logging.getLogger(__name__)
BTC_SYMBOL = "BTCUSDT"
ROLLING_WINDOW = 60

FEATURE_COLUMNS = [
    "open_time",
    "btc_log_return",
    "btc_volatility",
    "btc_volume_log",
    "btc_quote_volume_log",
    "btc_zscore",
    "btc_rolling_volatility",
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


def feature_dataset_key(symbol: str, day: str, settings: Settings) -> str:
    return (
        f"{settings.features_prefix.strip('/')}/{settings.feature_dataset_name}/"
        f"symbol={symbol}/interval={settings.interval}/date={day}/data.parquet"
    )


def s3_key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def read_symbol_klines_day(
    symbol: str,
    day: str,
    settings: Settings,
    s3_client,
    required_columns: list[str],
) -> pd.DataFrame:
    key = raw_klines_key(symbol=symbol, day=day, settings=settings)
    obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
    missing_columns = sorted(set(required_columns) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing required klines columns for {symbol}: {missing_columns}")
    if df.empty:
        return pd.DataFrame(columns=required_columns)

    cleaned = df[required_columns].copy()
    cleaned["open_time"] = pd.to_numeric(cleaned["open_time"], errors="coerce").astype("Int64")
    for column in [column for column in required_columns if column != "open_time"]:
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


def previous_day(day: str) -> str:
    return (pd.Timestamp(day).date() - timedelta(days=1)).isoformat()


def read_btc_history_for_day(day: str, settings: Settings, s3_client) -> pd.DataFrame:
    required_columns = ["open_time", "open", "high", "low", "close", "volume", "quote_volume"]
    frames = []
    previous = previous_day(day)
    previous_key = raw_klines_key(symbol=BTC_SYMBOL, day=previous, settings=settings)
    if s3_key_exists(s3_client, settings.s3_bucket, previous_key):
        frames.append(
            read_symbol_klines_day(
                symbol=BTC_SYMBOL,
                day=previous,
                settings=settings,
                s3_client=s3_client,
                required_columns=required_columns,
            ).tail(ROLLING_WINDOW)
        )

    current_key = raw_klines_key(symbol=BTC_SYMBOL, day=day, settings=settings)
    if not s3_key_exists(s3_client, settings.s3_bucket, current_key):
        return pd.DataFrame(columns=required_columns + ["is_current_day"])

    current = read_symbol_klines_day(
        symbol=BTC_SYMBOL,
        day=day,
        settings=settings,
        s3_client=s3_client,
        required_columns=required_columns,
    )
    frames.append(current)
    history = pd.concat(frames, ignore_index=True)
    history["is_current_day"] = history["open_time"].isin(current["open_time"])
    return history.sort_values("open_time").reset_index(drop=True)


def build_btc_features_for_day(day: str, settings: Settings, s3_client) -> pd.DataFrame:
    history = read_btc_history_for_day(day=day, settings=settings, s3_client=s3_client)
    if history.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    previous_close = history["close"].shift(1)
    ratio = safe_divide(history["close"], previous_close)
    history["btc_log_return"] = np.where(previous_close.eq(0) | previous_close.isna(), 0.0, np.log(ratio))
    history["btc_volatility"] = safe_divide(history["high"] - history["low"], history["close"])
    history["btc_volume_log"] = np.log1p(history["volume"])
    history["btc_quote_volume_log"] = np.log1p(history["quote_volume"])
    rolling_mean = history["btc_log_return"].rolling(window=ROLLING_WINDOW, min_periods=1).mean()
    rolling_std = history["btc_log_return"].rolling(window=ROLLING_WINDOW, min_periods=2).std()
    history["btc_zscore"] = safe_divide(history["btc_log_return"] - rolling_mean, rolling_std.fillna(0.0))
    history["btc_rolling_volatility"] = rolling_std.fillna(0.0)
    return history.loc[history["is_current_day"], FEATURE_COLUMNS].reset_index(drop=True)


def build_features_for_day(symbol: str, day: str, settings: Settings, s3_client) -> pd.DataFrame:
    backbone = read_symbol_klines_day(
        symbol=symbol,
        day=day,
        settings=settings,
        s3_client=s3_client,
        required_columns=["open_time"],
    )
    if backbone.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    btc_features = build_btc_features_for_day(day=day, settings=settings, s3_client=s3_client)
    feature_df = backbone.merge(btc_features, on="open_time", how="left")
    feature_df[FLOAT_FEATURE_COLUMNS] = feature_df[FLOAT_FEATURE_COLUMNS].fillna(0.0)
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
    selected_dates = select_dates(available_dates, settings.start_date, settings.end_date)
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
        feature_df = build_features_for_day(symbol, day, settings, s3_client)
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
    LOGGER.info("Starting BTC feature aggregation with settings=%s", safe_settings_for_logs(settings))
    s3_client = make_s3_client(settings)
    results = write_features_for_symbol_to_s3(settings.symbol, settings, s3_client)
    status_counts = results["status"].value_counts(dropna=False).to_dict()
    uploaded_rows = int(results.loc[results["status"] == "uploaded", "rows"].fillna(0).sum())
    LOGGER.info(
        "Finished BTC feature aggregation: processed_days=%s status_counts=%s uploaded_rows=%s",
        len(results),
        status_counts,
        uploaded_rows,
    )


if __name__ == "__main__":
    main()
