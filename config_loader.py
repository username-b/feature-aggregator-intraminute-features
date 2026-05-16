from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    s3_endpoint_url: str
    s3_bucket: str
    raw_prefix: str
    features_prefix: str
    symbol: str
    interval: str
    feature_dataset_name: str
    skip_existing: bool
    start_date: date | None
    end_date: date | None


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _parse_optional_date(name: str) -> date | None:
    raw_value = os.getenv(name)
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be in YYYY-MM-DD format") from exc


def load_settings() -> Settings:
    load_dotenv()

    start_date = _parse_optional_date("START_DATE")
    end_date = _parse_optional_date("END_DATE")
    if start_date and end_date and start_date > end_date:
        raise ValueError("START_DATE must be less than or equal to END_DATE")

    return Settings(
        aws_access_key_id=_required("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_required("AWS_SECRET_ACCESS_KEY"),
        aws_region=_required("AWS_DEFAULT_REGION"),
        s3_endpoint_url=_required("S3_ENDPOINT_URL"),
        s3_bucket=_required("S3_BUCKET"),
        raw_prefix=_required("RAW_PREFIX"),
        features_prefix=_required("FEATURES_PREFIX"),
        symbol=_required("SYMBOL"),
        interval=os.getenv("INTERVAL", "1m"),
        feature_dataset_name=os.getenv("FEATURE_DATASET_NAME", "intraminute_features"),
        skip_existing=_parse_bool(os.getenv("SKIP_EXISTING", "true")),
        start_date=start_date,
        end_date=end_date,
    )
