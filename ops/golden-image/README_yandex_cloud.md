# Golden image for Yandex Cloud container jobs

Этот пакет собирает универсальный образ `container-runner-ubuntu2404` для временных VM, которые запускают Docker-контейнеры.

## Почему образ сделан именно так

Этот репозиторий уже поставляет приложение в Docker-контейнере. Поэтому golden image не включает код проекта и секреты. Он содержит только стабильную среду исполнения:

- Ubuntu 24.04 LTS;
- Docker Engine;
- Docker Buildx и Docker Compose plugin;
- `git`, `curl`, `jq`, `cloud-init`;
- базовый SSH hardening;
- ротацию docker-логов;
- каталог `/opt/feature-jobs`;
- serial console для диагностики в Yandex Cloud.

## Что нужно на машине сборки

- Linux-хост или WSL2;
- `packer`;
- `qemu-system-x86_64`;
- `qemu-img`;
- доступ в интернет до `cloud-images.ubuntu.com` и `download.docker.com`.

## Как собрать образ

```bash
cd ops/golden-image
chmod +x build.sh fetch-ubuntu-checksum.sh scripts/provision.sh
./fetch-ubuntu-checksum.sh
./build.sh
```

На выходе будет файл:

```text
output/container-runner-ubuntu2404/container-runner-ubuntu2404-optimized.qcow2
```

Именно его нужно импортировать в Yandex Cloud.

Если на машине сборки нет KVM, добавьте в `variables.pkrvars.hcl`:

```hcl
accelerator = "tcg"
```

Сборка станет медленнее, но останется рабочей.

## Как загрузить образ в Yandex Cloud

1. Загрузите `.qcow2` в Object Storage.
2. Создайте signed URL на скачивание.
3. В Compute Cloud создайте новый image из этого URL.
4. При создании VM выберите вкладку `Пользовательский` и выберите созданный image.

Рекомендуемое имя image:

```text
container-runner-ubuntu2404-v1
```

## Рекомендуемые настройки VM

| Параметр | Значение |
|---|---|
| Тип диска | SSD |
| Размер boot-диска | 20 GB |
| CPU | 2 vCPU |
| RAM | 2 GB минимум, 4 GB с запасом |
| Удалять диск вместе с VM | Да, если VM временная |
| Public IP | Только если нужен прямой SSH |
| Доступ | Только по SSH-ключу |

## Как запускать job

Используйте `cloud-init/job-runner.example.yaml` как шаблон пользовательских данных VM.

В production-сценарии лучше:

1. собирать Docker image приложения заранее в CI;
2. публиковать его в registry с tag по версии и git SHA;
3. на VM выполнять только `docker pull` и `docker run`.

Это быстрее и воспроизводимее, чем собирать приложение на каждой новой VM.

## Что изменить перед production

- заменить статические S3-ключи на более безопасный механизм передачи секретов;
- заменить `registry.example/...` на настоящий registry;
- ограничить входящий SSH по security group;
- при необходимости добавить auto-shutdown после успешного завершения job.
