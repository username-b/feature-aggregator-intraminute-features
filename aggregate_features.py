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
MAX_HORIZON_MINUTES = 120

TARGET_COLUMNS = ["open_time"] + [f"return_{minute}m" for minute in range(1, MAX_HORIZON_MINUTES + 1)]
FLOAT_TARGET_COLUMNS = TARGET_COLUMNS[1:]


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


def target_dataset_key(symbol: str, day: str, settings: Settings) -> str:
    return (
        f"{settings.targets_prefix.strip('/')}/{settings.target_dataset_name}/"
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


def read_symbol_klines_day(symbol: str, day: str, settings: Settings, s3_client) -> pd.DataFrame:
    key = raw_klines_key(symbol=symbol, day=day, settings=settings)
    obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
    required_columns = ["open_time", "close"]
    missing_columns = sorted(set(required_columns) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing required klines columns: {missing_columns}")
    if df.empty:
        return pd.DataFrame(columns=required_columns)

    cleaned = df[required_columns].copy()
    cleaned["open_time"] = pd.to_numeric(cleaned["open_time"], errors="coerce").astype("Int64")
    cleaned["close"] = pd.to_numeric(cleaned["close"], errors="coerce")
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


def next_day(day: str) -> str:
    return (pd.Timestamp(day).date() + timedelta(days=1)).isoformat()


def read_forward_klines_context(symbol: str, day: str, settings: Settings, s3_client) -> pd.DataFrame:
    frames = [read_symbol_klines_day(symbol=symbol, day=day, settings=settings, s3_client=s3_client)]
    rows_after_current_day = 0
    candidate_day = day

    while rows_after_current_day < MAX_HORIZON_MINUTES:
        candidate_day = next_day(candidate_day)
        key = raw_klines_key(symbol=symbol, day=candidate_day, settings=settings)
        if not s3_key_exists(s3_client, settings.s3_bucket, key):
            break
        future_df = read_symbol_klines_day(
            symbol=symbol,
            day=candidate_day,
            settings=settings,
            s3_client=s3_client,
        )
        frames.append(future_df)
        rows_after_current_day += len(future_df)

    return pd.concat(frames, ignore_index=True).sort_values("open_time").reset_index(drop=True)


def safe_future_return(current_close: pd.Series, future_close: pd.Series) -> pd.Series:
    current_values = current_close.astype("float64").to_numpy()
    future_values = future_close.astype("float64").to_numpy()
    result = np.divide(
        future_values - current_values,
        current_values,
        out=np.zeros(len(current_close), dtype="float64"),
        where=(current_values != 0) & ~np.isnan(future_values),
    )
    return pd.Series(result, index=current_close.index)


def build_targets_for_day(symbol: str, day: str, settings: Settings, s3_client) -> pd.DataFrame:
    current_day = read_symbol_klines_day(symbol=symbol, day=day, settings=settings, s3_client=s3_client)
    if current_day.empty:
        return pd.DataFrame(columns=TARGET_COLUMNS)

    context = read_forward_klines_context(symbol=symbol, day=day, settings=settings, s3_client=s3_client)
    close_by_time = context.set_index("open_time")["close"]

    target_df = current_day[["open_time", "close"]].copy()
    return_columns = {}
    for horizon in range(1, MAX_HORIZON_MINUTES + 1):
        future_times = target_df["open_time"] + horizon * 60_000
        future_close = future_times.map(close_by_time)
        return_columns[f"return_{horizon}m"] = safe_future_return(target_df["close"], future_close)

    target_df = pd.concat([target_df.drop(columns=["close"]), pd.DataFrame(return_columns)], axis=1)
    target_df = target_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    target_df = target_df.sort_values("open_time").reset_index(drop=True)
    target_df["open_time"] = target_df["open_time"].astype("int64")
    for column in FLOAT_TARGET_COLUMNS:
        target_df[column] = target_df[column].astype("float32")
    return target_df[TARGET_COLUMNS]


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


def write_targets_for_symbol_to_s3(symbol: str, settings: Settings, s3_client) -> pd.DataFrame:
    available_dates = list_symbol_klines_days(symbol=symbol, settings=settings, s3_client=s3_client)
    selected_dates = select_dates(available_dates, settings.start_date, settings.end_date)
    if not selected_dates:
        raise FileNotFoundError(
            f"No klines days found for symbol={symbol}, interval={settings.interval}, "
            f"start_date={settings.start_date}, end_date={settings.end_date}"
        )

    rows = []
    for day in selected_dates:
        key = target_dataset_key(symbol=symbol, day=day, settings=settings)
        if settings.skip_existing and s3_key_exists(s3_client, settings.s3_bucket, key):
            LOGGER.info("Skip exists: s3://%s/%s", settings.s3_bucket, key)
            rows.append({"symbol": symbol, "date": day, "rows": None, "key": key, "status": "skipped"})
            continue
        target_df = build_targets_for_day(symbol=symbol, day=day, settings=settings, s3_client=s3_client)
        buffer = io.BytesIO()
        target_df.to_parquet(buffer, index=False, engine="pyarrow", compression="zstd")
        s3_client.put_object(Bucket=settings.s3_bucket, Key=key, Body=buffer.getvalue())
        LOGGER.info("Uploaded: s3://%s/%s rows=%s", settings.s3_bucket, key, len(target_df))
        rows.append({"symbol": symbol, "date": day, "rows": len(target_df), "key": key, "status": "uploaded"})
    return pd.DataFrame(rows)


def safe_settings_for_logs(settings: Settings) -> dict[str, object]:
    values = asdict(settings)
    values["aws_access_key_id"] = "***"
    values["aws_secret_access_key"] = "***"
    return values


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    LOGGER.info("Starting future-return target generation with settings=%s", safe_settings_for_logs(settings))
    s3_client = make_s3_client(settings)
    results = write_targets_for_symbol_to_s3(symbol=settings.symbol, settings=settings, s3_client=s3_client)
    status_counts = results["status"].value_counts(dropna=False).to_dict()
    uploaded_rows = int(results.loc[results["status"] == "uploaded", "rows"].fillna(0).sum())
    LOGGER.info(
        "Finished future-return target generation: processed_days=%s status_counts=%s uploaded_rows=%s",
        len(results),
        status_counts,
        uploaded_rows,
    )


if __name__ == "__main__":
    main()
