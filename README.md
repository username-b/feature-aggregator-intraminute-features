# BTC Features Aggregator

Самодостаточный Docker-проект для генерации minute-level датасета `btc_features` для модели `ADAUSDT`.

Проект использует ADAUSDT как minute backbone:

```text
raw/klines/symbol=ADAUSDT/interval=1m/date=<YYYY-MM-DD>/data.parquet
```

и читает BTCUSDT minute klines из:

```text
raw/klines/symbol=BTCUSDT/interval=1m/date=<YYYY-MM-DD>/data.parquet
```

Результат записывается в:

```text
features/btc_features/symbol=ADAUSDT/interval=1m/date=<YYYY-MM-DD>/data.parquet
```

Состав минут итогового parquet в точности повторяет ADAUSDT backbone. Если BTCUSDT не содержит какой-либо минуты backbone, признаки этой строки после join заполняются нулями.

## Состав выходного parquet

- `open_time`
- `btc_log_return`
- `btc_volatility`
- `btc_volume_log`
- `btc_quote_volume_log`
- `btc_zscore`
- `btc_rolling_volatility`

Все признаки, кроме `open_time`, сохраняются как `float32`. Строки отсортированы по `open_time` по возрастанию.

## Правила расчета

- `btc_log_return` использует предыдущую BTC-минуту, включая предыдущий daily parquet;
- `btc_zscore` и `btc_rolling_volatility` используют trailing window в 60 минут без future data;
- если предыдущий BTC parquet отсутствует, первая доступная BTC-минута текущего ряда получает `btc_log_return = 0`;
- если BTC parquet за день отсутствует целиком, итоговый ADA-backbone сохраняется, а BTC-признаки становятся нулевыми.

## Конфигурация

| Переменная | Обязательна | Описание |
|---|---:|---|
| `AWS_ACCESS_KEY_ID` | да | Access key для S3-compatible storage |
| `AWS_SECRET_ACCESS_KEY` | да | Secret key для S3-compatible storage |
| `AWS_DEFAULT_REGION` | да | Регион |
| `S3_ENDPOINT_URL` | да | Endpoint S3-compatible storage |
| `S3_BUCKET` | да | Bucket с данными |
| `RAW_PREFIX` | да | Префикс исходных данных |
| `FEATURES_PREFIX` | да | Префикс выходных данных |
| `SYMBOL` | да | Символ backbone, для этого pipeline `ADAUSDT` |
| `INTERVAL` | нет | Интервал свечей, по умолчанию `1m` |
| `FEATURE_DATASET_NAME` | нет | Имя датасета, по умолчанию `btc_features` |
| `SKIP_EXISTING` | нет | Пропускать уже существующие партиции, по умолчанию `true` |
| `START_DATE` | нет | Нижняя граница периода в формате `YYYY-MM-DD` |
| `END_DATE` | нет | Верхняя граница периода в формате `YYYY-MM-DD` |

## Локальный запуск

```bash
cp .env.example .env
# заполнить секреты и нужные значения в .env

docker build -t btc-features:test .
docker run --rm --env-file .env btc-features:test
```
