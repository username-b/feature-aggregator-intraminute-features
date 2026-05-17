# Price Pressure Features Aggregator

Самодостаточный Docker-проект для генерации minute-level датасета `price_pressure`.

Проект использует:

```text
raw/klines/symbol=<SYMBOL>/interval=<INTERVAL>/date=<YYYY-MM-DD>/data.parquet
raw/aggTrades/symbol=<SYMBOL>/date=<YYYY-MM-DD>/data.parquet
```

и записывает результат в:

```text
features/price_pressure/symbol=<SYMBOL>/interval=<INTERVAL>/date=<YYYY-MM-DD>/data.parquet
```

Minute backbone берется из raw `klines`: состав минут итогового parquet в точности повторяет `open_time` из свечей. Если для минуты нет сделок в `aggTrades`, строка все равно создается, а все числовые признаки равны `0`.

## Состав выходного parquet

- `open_time`
- `VWAP`
- `PI_buy`
- `PI_sell`
- `PI_total`
- `F_eff`
- `F_PI`
- `F_asymmetry`
- `VWAP_pos`

Все числовые признаки, кроме `open_time`, сохраняются как `float32`. Строки отсортированы по `open_time` по возрастанию.

## Семантика сторон

- `is_buyer_maker = false` → агрессивная покупка (`buy`)
- `is_buyer_maker = true` → агрессивная продажа (`sell`)

## Конфигурация

Настройки передаются через переменные окружения. Для старта скопируйте `.env.example` в `.env`.

| Переменная | Обязательна | Описание |
|---|---:|---|
| `AWS_ACCESS_KEY_ID` | да | Access key для S3-compatible storage |
| `AWS_SECRET_ACCESS_KEY` | да | Secret key для S3-compatible storage |
| `AWS_DEFAULT_REGION` | да | Регион |
| `S3_ENDPOINT_URL` | да | Endpoint S3-compatible storage |
| `S3_BUCKET` | да | Bucket с данными |
| `RAW_PREFIX` | да | Префикс исходных данных |
| `FEATURES_PREFIX` | да | Префикс выходных данных |
| `SYMBOL` | да | Торговая пара |
| `INTERVAL` | нет | Интервал свечей, по умолчанию `1m` |
| `FEATURE_DATASET_NAME` | нет | Имя датасета, по умолчанию `price_pressure` |
| `SKIP_EXISTING` | нет | Пропускать уже существующие партиции, по умолчанию `true` |
| `START_DATE` | нет | Нижняя граница периода в формате `YYYY-MM-DD` |
| `END_DATE` | нет | Верхняя граница периода в формате `YYYY-MM-DD` |

## Локальный запуск

```bash
cp .env.example .env
# заполнить секреты и нужные значения в .env

docker build -t price-pressure-features:test .
docker run --rm --env-file .env price-pressure-features:test
```
