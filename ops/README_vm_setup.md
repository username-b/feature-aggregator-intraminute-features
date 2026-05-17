# VM setup for temporary feature jobs

Этот документ описывает рабочий процесс для временной VM, которая живёт несколько часов и удаляется после завершения расчёта.

## Что должно быть уже в пользовательском образе VM

- Docker Engine
- Docker Buildx plugin
- Docker Compose plugin
- git
- curl
- jq
- cloud-init

Docker не должен устанавливаться заново на каждой новой VM: он должен быть уже включён в базовый пользовательский образ VM.

Готовый пакет для сборки такого образа под Yandex Cloud находится в:

```text
ops/golden-image/
```

## Ручной минимум для новой VM

1. Создать VM из подготовленного пользовательского образа.
2. Подключиться по SSH.
3. Для прототипа можно клонировать репозиторий:

   ```bash
   git clone <repo-url>
   cd feature-aggregator-intraminute-features
   ```

4. Создать рабочий `.env`:

   ```bash
   cp .env.example .env
   nano .env
   ```

5. Для прототипа можно собрать и запустить контейнер:

   ```bash
   docker build -t intraminute-features:v0.1.0 .
   docker run --rm --env-file .env intraminute-features:v0.1.0
   ```

6. После проверки результата удалить VM.

## Целевой вариант эксплуатации

Для production-процесса лучше:

1. собирать Docker image приложения заранее в CI;
2. публиковать image в registry по git tag и git SHA;
3. при создании VM передавать через cloud-init только параметры job и команду `docker pull` + `docker run`;
4. удалять временную VM после завершения расчёта.

## Что имеет смысл автоматизировать позже

- сборку и публикацию Docker image по git tag;
- автоматический запуск контейнера через cloud-init;
- передачу версии образа как параметра при создании VM;
- автоотключение VM после успешного завершения job.
