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
    "log_close",
    "candle_range",
    "body",
    "upper_wick",
    "lower_wick",
    "body_norm",
    "wick_upper_norm",
    "wick_lower_norm",
    "volume_log",
    "quote_volume_log",
    "taker_buy_ratio",
]


def make_s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def list_symbol_klines_days(
    symbol: str,
    settings: Settings,
    s3_client,
) -> list[str]:
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
    except Exception as exc:  # boto3 raises generated exceptions here
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def read_symbol_klines_day(
    symbol: str,
    day: str,
    settings: Settings,
    s3_client,
) -> pd.DataFrame:
    key = raw_klines_key(symbol=symbol, day=day, settings=settings)
    obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))

    required_columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base",
    ]
    missing_columns = sorted(set(required_columns) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing required klines columns: {missing_columns}")

    if df.empty:
        return pd.DataFrame(columns=required_columns)

    cleaned = df[required_columns].copy()
    cleaned["open_time"] = pd.to_numeric(cleaned["open_time"], errors="coerce").astype("Int64")

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base",
    ]
    for column in numeric_columns:
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
    result = np.divide(
        numerator.astype("float64"),
        denominator.astype("float64"),
        out=np.zeros(len(numerator), dtype="float64"),
        where=denominator.astype("float64").to_numpy() != 0,
    )
    return pd.Series(result, index=numerator.index)


def build_features_for_day(
    symbol: str,
    day: str,
    settings: Settings,
    s3_client,
) -> pd.DataFrame:
    df = read_symbol_klines_day(
        symbol=symbol,
        day=day,
        settings=settings,
        s3_client=s3_client,
    )

    if df.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    candle_range = df["high"] - df["low"]
    body = df["close"] - df["open"]
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]

    feature_df = pd.DataFrame(
        {
            "open_time": df["open_time"].astype("int64"),
            "log_close": np.log(df["close"]),
            "candle_range": candle_range,
            "body": body,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "body_norm": safe_divide(body, candle_range),
            "wick_upper_norm": safe_divide(upper_wick, candle_range),
            "wick_lower_norm": safe_divide(lower_wick, candle_range),
            "volume_log": np.log1p(df["volume"]),
            "quote_volume_log": np.log1p(df["quote_volume"]),
            "taker_buy_ratio": safe_divide(df["taker_buy_base"], df["volume"]),
        }
    )

    feature_df = feature_df.replace([np.inf, -np.inf], np.nan).fillna(0)
    return feature_df[FEATURE_COLUMNS].reset_index(drop=True)


def select_dates(
    available_dates: list[str],
    start_date: date | None,
    end_date: date | None,
) -> list[str]:
    selected_dates = []
    for day in available_dates:
        parsed_day = pd.Timestamp(day).date()
        if start_date and parsed_day < start_date:
            continue
        if end_date and parsed_day > end_date:
            continue
        selected_dates.append(day)
    return selected_dates


def write_features_for_symbol_to_s3(
    symbol: str,
    settings: Settings,
    s3_client,
) -> pd.DataFrame:
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

        feature_df = build_features_for_day(
            symbol=symbol,
            day=day,
            settings=settings,
            s3_client=s3_client,
        )

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = load_settings()
    LOGGER.info("Starting feature aggregation with settings=%s", safe_settings_for_logs(settings))

    s3_client = make_s3_client(settings)
    results = write_features_for_symbol_to_s3(
        symbol=settings.symbol,
        settings=settings,
        s3_client=s3_client,
    )

    status_counts = results["status"].value_counts(dropna=False).to_dict()
    uploaded_rows = int(results.loc[results["status"] == "uploaded", "rows"].fillna(0).sum())
    LOGGER.info(
        "Finished feature aggregation: processed_days=%s status_counts=%s uploaded_rows=%s",
        len(results),
        status_counts,
        uploaded_rows,
    )


if __name__ == "__main__":
    main()
