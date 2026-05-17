# Future Returns Target Aggregator

Самодостаточный Docker-проект для генерации target dataset `future_returns` по minute-level `klines` для `ADAUSDT`.

Источник:

```text
raw/klines/symbol=ADAUSDT/interval=1m/date=<YYYY-MM-DD>/data.parquet
```

Результат:

```text
targets/future_returns/symbol=ADAUSDT/interval=1m/date=<YYYY-MM-DD>/data.parquet
```

Состав минут итогового parquet в точности повторяет daily backbone исходного `klines` parquet.

## Состав выходного parquet

- `open_time`
- `return_1m`
- `return_2m`
- `...`
- `return_120m`

Все target-колонки сохраняются как `float32`. Строки отсортированы по `open_time` по возрастанию.

## Правила расчета

Для каждой минуты `t`:

```text
return_n(t) = (close_{t+n} - close_t) / close_t
```

для горизонтов `1m ... 120m`.

- future data использовать разрешено;
- для последних минут дня автоматически подгружаются следующие daily parquet-файлы, пока не будет доступно минимум 120 минут вперед;
- если future close отсутствует, соответствующий target равен `0`;
- если `close_t = 0`, соответствующий target равен `0`.

## Конфигурация

| Переменная | Обязательна | Описание |
|---|---:|---|
| `AWS_ACCESS_KEY_ID` | да | Access key для S3-compatible storage |
| `AWS_SECRET_ACCESS_KEY` | да | Secret key для S3-compatible storage |
| `AWS_DEFAULT_REGION` | да | Регион |
| `S3_ENDPOINT_URL` | да | Endpoint S3-compatible storage |
| `S3_BUCKET` | да | Bucket с данными |
| `RAW_PREFIX` | да | Префикс исходных данных |
| `FEATURES_PREFIX` | да | Сохраняется для совместимости с окружением |
| `TARGETS_PREFIX` | да | Префикс target datasets |
| `SYMBOL` | да | Торговая пара |
| `INTERVAL` | нет | Интервал свечей, по умолчанию `1m` |
| `TARGET_DATASET_NAME` | нет | Имя target dataset, по умолчанию `future_returns` |
| `SKIP_EXISTING` | нет | Пропускать уже существующие партиции, по умолчанию `true` |
| `START_DATE` | нет | Нижняя граница периода в формате `YYYY-MM-DD` |
| `END_DATE` | нет | Верхняя граница периода в формате `YYYY-MM-DD` |

## Локальный запуск

```bash
cp .env.example .env
# заполнить секреты и нужные значения в .env

docker build -t future-returns:test .
docker run --rm --env-file .env future-returns:test
```
