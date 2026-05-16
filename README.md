# Intraminute Features Aggregator

Самодостаточный Docker-проект для генерации одного логического блока фичей: `intraminute_features`.

Проект читает минутные свечи из S3-совместимого хранилища:

```text
raw/klines/symbol=<SYMBOL>/interval=<INTERVAL>/date=<YYYY-MM-DD>/data.parquet
```

и записывает рассчитанные фичи в:

```text
features/intraminute_features/symbol=<SYMBOL>/interval=<INTERVAL>/date=<YYYY-MM-DD>/data.parquet
```

## Состав фичей

- `log_close`
- `candle_range`
- `body`
- `upper_wick`
- `lower_wick`
- `body_norm`
- `wick_upper_norm`
- `wick_lower_norm`
- `volume_log`
- `quote_volume_log`
- `taker_buy_ratio`

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
| `FEATURE_DATASET_NAME` | нет | Имя датасета фичей, по умолчанию `intraminute_features` |
| `SKIP_EXISTING` | нет | Пропускать уже существующие партиции, по умолчанию `true` |
| `START_DATE` | нет | Нижняя граница периода в формате `YYYY-MM-DD` |
| `END_DATE` | нет | Верхняя граница периода в формате `YYYY-MM-DD` |

## Локальный запуск

```bash
cp .env.example .env
# заполнить секреты и нужные значения в .env

docker build -t intraminute-features:test .
docker run --rm --env-file .env intraminute-features:test
```

## Запуск на VM

Предполагается, что VM уже создана из пользовательского образа, в котором установлены Docker и git.

```bash
git clone <repo-url>
cd feature-aggregator-intraminute-features
cp .env.example .env
# заполнить .env

docker build -t intraminute-features:v0.1.0 .
docker run --rm --env-file .env intraminute-features:v0.1.0
```

## Версионирование

Рекомендуемый порядок:

- git tag фиксирует версию исходного кода;
- Docker tag повторяет версию git tag;
- при необходимости дополнительно ставится tag с git SHA.

Пример:

```text
intraminute-features:v0.1.0
intraminute-features:git-a1b2c3d
```

## Основной файл для изменений

Обычная новая версия логики фичей должна затрагивать прежде всего:

```text
aggregate_features.py
```

Остальные файлы меняются только при изменении интерфейса конфигурации, зависимостей или эксплуатационного процесса.
