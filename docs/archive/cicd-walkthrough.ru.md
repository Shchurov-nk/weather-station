# CI/CD: от пустого `.github/` до автодеплоя — учебный разбор

Это продолжение `walkthrough.ru.md` (фазы 0–2). Здесь — фазы CI/CD: как репозиторий
получил конвейер «push в main → линт → тесты → миграции → сборка образа → публикация
в GHCR → деплой на VPS по ssh». Разобран каждый файл, каждая команда и одна настоящая
поломка с методикой отладки. Прочитав, вы должны суметь повторить всё с нуля
в любом другом проекте.

Коммиты этой серии (читать `git show <sha>` параллельно с текстом):

```
12351ab add ci: ruff, pytest, migrations, docker build smoke
7f888e2 pin python 3.13, enable ruff import sorting
e2c265b add ci badge to readme          (+ bb1daaf add MIT license)
47c0d09 fix setup-uv tag in ci          <- история отладки, §4
4e1d873 ci: push api image to ghcr on main
2c868d4 cd: deploy from ghcr via ssh    <- ветка cd-ghcr, ещё не в main
```

---

## 1. GitHub Actions за пять минут: словарь

Прежде чем читать YAML, нужно пять слов:

- **Workflow** — один файл в `.github/workflows/`. У нас он один: `ci.yml`.
- **Event (trigger)** — что запускает workflow: секция `on:`. У нас — `push` в main
  и любой `pull_request`.
- **Job** — независимая единица работы. Джобы одного workflow по умолчанию
  бегут **параллельно**, каждый на своей свежей виртуалке.
- **Runner** — та самая виртуалка. `runs-on: ubuntu-latest` — облачная машина
  GitHub c предустановленными Docker, compose v2, python, psql и т.д.
  После джоба она уничтожается — состояние между джобами не сохраняется.
- **Step** — шаг внутри джоба: либо `run:` (shell-команда), либо `uses:`
  (готовый **action** — переиспользуемый кусок логики из чужого репозитория,
  версия указывается после `@`).

Ключевое следствие «каждый джоб — свежая машина»: всё, что джобу нужно
(код, зависимости, докер-образы), он добывает сам, с нуля, каждый раз.
Поэтому первый шаг почти любого джоба — `actions/checkout` (клонирует репозиторий),
а кеши — отдельный механизм, а не «остался с прошлого раза».

## 2. Фаза CI: четыре джоба в `ci.yml`

Схема:

```
push в main / PR
      │
      ├── lint        ruff по всему api/
      ├── test        pytest, 7 юнит-тестов, без БД
      ├── migrations  настоящий compose-стек db, миграции с нуля + идемпотентность
      └── build       docker build (на main — ещё и push в GHCR, см. §5)
```

Четыре **отдельных** джоба, а не четыре шага одного джоба, по двум причинам:
они бегут параллельно (весь CI — по времени самого медленного, а не суммы),
и в интерфейсе GitHub сразу видно, *что именно* сломалось.

### 2.1 `lint` и `test` — построчно

```yaml
  lint:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: api
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.0.0
        with:
          enable-cache: true
          cache-dependency-glob: api/uv.lock
      - run: uv sync --frozen
      - run: uv run ruff check .
```

- `defaults.run.working-directory: api` — все `run:`-шаги выполняются из `api/`.
  Это важно не только для краткости: pytest у нас **обязан** запускаться из `api/`
  (плоский модуль, `conftest.py` кладёт `api/` в `sys.path` — см. walkthrough §8).
  Заметьте: на `uses:`-шаги working-directory не влияет.
- `actions/checkout@v7` — клонирует репозиторий в рабочую директорию раннера.
  Без него на машине пусто.
- `astral-sh/setup-uv@v10.0.0` — официальный action от Astral: ставит uv
  и (с `enable-cache: true`) кеширует скачанные пакеты между прогонами.
  `cache-dependency-glob: api/uv.lock` — ключ кеша считается от лок-файла:
  изменился lock → старый кеш не используется. Почему версия прибита гвоздями
  до патча (`v10.0.0`, а не `v10`) — это история поломки, §4.
- `uv sync --frozen` — создать venv строго по `uv.lock`. `--frozen` запрещает uv
  «молча дорезолвить» зависимости, если lock разошёлся с `pyproject.toml` —
  вместо этого ошибка. Тот же флаг стоит в Dockerfile: CI и прод собираются
  из одного и того же зафиксированного набора версий. Группа `dev`
  (pytest, ruff) у uv ставится по умолчанию — отдельного флага не нужно.
- `uv run ruff check .` — запуск ruff **из venv**, т.е. той версии, что в lock.
  Никаких «а у меня локально другой ruff»: локально вы запускаете буквально
  ту же команду — `cd api && uv run ruff check .`.

`test` отличается одной строкой: `uv run pytest -q`. Тесты не требуют Postgres —
пул соединений замокан (`mock.patch.object`), поэтому джоб дешёвый и быстрый.
Это осознанный дизайн из фазы 2: юнит-тесты проверяют HTTP-контракт
(401/422/201/500), а взаимодействие с настоящей БД проверяет следующий джоб.

### 2.2 Пины версий: `.python-version` и `[tool.ruff]`

Два маленьких файла-«якоря», без которых CI проверял бы не то, что работает в проде.

**`api/.python-version`** — одна строка `3.13`. До него локальный venv жил
на Python 3.14, а докер-образ — на `python:3.13-slim`: тесты локально гоняли
не ту версию интерпретатора, что в проде. uv читает этот файл при `uv sync`
и сам скачивает нужный CPython — и локально, и на раннере. Один файл — три
согласованные среды (локально / CI / Docker).

**`api/pyproject.toml`**, добавка:

```toml
[tool.ruff]
target-version = "py313"

[tool.ruff.lint]
# Import sorting (isort) is not in ruff's default select.
extend-select = ["I"]
```

Тонкость, из-за которой это не «просто конфиг»: ruff по умолчанию проверяет
только правила `E4`, `E7`, `E9`, `F`. Правила `I` (сортировка импортов) в
дефолте **нет** — а в истории репозитория уже есть коммит `0efd999
"sort imports (ruff I001)"`. То есть до этой добавки голый `ruff check` в CI
молча пропускал бы то, что мы однажды чинили руками. Мораль: **CI проверяет
ровно то, что сконфигурировано, а не то, что вы имели в виду.** Явный конфиг —
часть контракта.

### 2.3 `migrations` — самый интересный джоб

Задача: проверить, что схема БД собирается с нуля на пустом Postgres и что
раннер миграций идемпотентен. Очевидный путь — «service container»
(встроенная в Actions возможность поднять постгрес рядом с джобом) — здесь
**не подходит**, и понимание почему — половина ценности этого джоба:

1. `db/apply_migrations.sh` читает файлы из `/migrations/*.sql` — путь существует
   только внутри нашего контейнера db (bind mount из `compose.yaml`).
2. Миграция `002_grants_dashboard_ro.sql` выдаёт права роли `dashboard_ro`,
   а роль создаёт `db/init/01_bootstrap.sh` — скрипт, который постгрес-образ
   запускает при первом старте на пустом томе (`/docker-entrypoint-initdb.d`).
   В голом service container роли не будет — миграция упадёт.
3. Самое главное: в проде работает связка «образ postgres:17 + init + bootstrap +
   миграции + healthcheck» из `compose.yaml`. Тестировать надо **её**, а не
   похожую сборку. Docker и compose v2 на раннере уже есть — почему бы не
   поднять ровно прод-стек?

```yaml
  migrations:
    runs-on: ubuntu-latest
    env:
      DOMAIN: localhost
      POSTGRES_USER: ci
      POSTGRES_PASSWORD: ci
      POSTGRES_DB: ci
      DASHBOARD_RO_PASSWORD: ci
      SENSOR_TOKEN: ci
    steps:
      - uses: actions/checkout@v7
      - run: docker compose up -d --wait db
      - run: timeout 60 docker compose exec -T db sh -c 'until pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do sleep 1; done'
      - name: re-run is a no-op (idempotence)
        run: |
          out=$(docker compose exec -T db apply_migrations)
          echo "$out"
          ! echo "$out" | grep -q '^apply'
      - name: every migration file is recorded
        run: |
          applied=$(docker compose exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM schema_migrations"')
          files=$(ls db/migrations/*.sql | wc -l)
          echo "applied=$applied files=$files"
          test "$applied" -eq "$files"
      - if: failure()
        run: docker compose logs db
```

Построчно:

- **`env:` на уровне джоба.** Локально compose берёт `${POSTGRES_USER}` и прочее
  из файла `.env`. На раннере `.env` нет — но compose интерполирует и из обычных
  переменных окружения. Значения фиктивные (`ci`): база одноразовая, умрёт
  вместе с раннером. Обратите внимание: перечислены **все** переменные, которые
  использует `compose.yaml`, включая `DOMAIN`, хотя caddy мы не поднимаем —
  compose интерполирует весь файл целиком и ругается на отсутствующие.
- **`docker compose up -d --wait db`** — поднять только сервис `db` (не весь стек)
  и ждать, пока его healthcheck не станет healthy. Первый старт на пустом томе =
  постгрес запускает init-скрипты = bootstrap создаёт роль и прогоняет все
  миграции. То есть сам факт успешного старта — уже тест «схема собирается с нуля».
- **Строка с `pg_isready -h 127.0.0.1` — защита от гонки, самая тонкая деталь
  джоба.** Как стартует официальный образ postgres на пустом томе: сначала
  **временный** сервер, который слушает *только unix-сокет* (не TCP), на нём
  выполняются init-скрипты, затем временный сервер гасится и стартует настоящий,
  уже с TCP. Наш healthcheck (`pg_isready` без `-h`) ходит через unix-сокет —
  и потому может ответить «готов» ещё на *временном* сервере, посреди
  инициализации. `--wait` вернётся, а bootstrap ещё не дописал миграции —
  и следующий шаг наперегонки с ним начнёт применять те же файлы. Ожидание
  TCP (`-h 127.0.0.1`) закрывает гонку полностью: TCP появляется только после
  окончания init. `timeout 60` — чтобы при реальной поломке джоб упал за минуту,
  а не висел до таймаута раннера. Урок: **healthcheck отвечает на вопрос „жив
  ли процесс“, а не „закончилась ли инициализация“** — это разные вопросы.
- **Проверка идемпотентности.** `docker compose exec -T db apply_migrations` —
  второй прогон раннера по уже инициализированной базе. `-T` отключает
  выделение TTY (в CI его нет; без `-T` exec падает). Скрипт печатает
  `skip <файл>` для применённых миграций и `apply <файл>` для новых. После
  bootstrap новых быть не должно, поэтому:
  `! echo "$out" | grep -q '^apply'` — «в выводе нет ни одной строки apply».
  `!` инвертирует код возврата grep. Это одновременно два теста: bootstrap
  реально применил всё (иначе сейчас были бы apply), и повторный запуск
  ничего не ломает.
- **Сверка количества.** Число строк в таблице `schema_migrations` должно
  равняться числу файлов `db/migrations/*.sql`. `psql -tA` — вывод без
  заголовков (`-t`) и выравнивания (`-A`): голое число, пригодное для `test -eq`.
- **`if: failure()`** — шаг, который выполняется *только если* джоб уже упал:
  печатает логи контейнера db. Без него отладка красного CI превращается
  в гадание; с ним причина (ошибка SQL, падение bootstrap) — прямо в логе джоба.

### 2.4 `build` — Dockerfile тоже код

```yaml
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: docker build ./api
```

(Так джоб выглядел в фазе CI; в фазе GHCR он подрос — §5.) Зачем собирать образ
на каждый PR? Dockerfile — деплой-артефакт: если он не собирается, деплоить
нечего. Типичная поломка, которую ловит именно этот джоб: добавили зависимость
в `pyproject.toml`, забыли `uv lock` — локально всё работает (venv дорезолвил),
а `uv sync --frozen` внутри сборки падает. Лучше узнать об этом в PR, чем во
время деплоя.

## 3. Мелкая гигиена: бейдж и лицензия

- **CI-бейдж** в README — однострочник-маркдаун:
  `[![ci](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)](.../actions/workflows/ci.yml)`.
  GitHub отдаёт SVG со статусом последнего прогона workflow на main.
- **LICENSE (MIT)** — репозиторий публичный; без файла лицензии чужой код
  по умолчанию «all rights reserved», и юридически им пользоваться нельзя.
  MIT — «делайте что хотите, но без гарантий и претензий», стандарт для
  учебных и хобби-проектов.

## 4. История поломки: красный CI и как его читать

Первый же прогон: `migrations` и `build` зелёные, `lint` и `test` — красные.
Разбор по шагам — это методика, применимая к любому красному CI.

**Шаг 1: где именно упало.** Не открывая браузер — GitHub API отдаёт статусы
джобов анонимно (репозиторий публичный):

```bash
# id последнего прогона
run_id=$(curl -s "https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=1&branch=main" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['workflow_runs'][0]['id'])")
# джобы и их упавшие шаги
curl -s "https://api.github.com/repos/<owner>/<repo>/actions/runs/$run_id/jobs" | python3 - <<'EOF'
import sys, json
for j in json.load(sys.stdin)['jobs']:
    print(j['name'], j['conclusion'])
    for s in j['steps']:
        if s['conclusion'] not in ('success', 'skipped'):
            print('  FAILED:', s['name'])
EOF
```

Ответ: оба джоба упали на шаге **«Set up job»**. Это не наш шаг — это фаза,
в которой раннер *скачивает указанные в `uses:` экшены*. Падение здесь означает:
какой-то `uses:`-референс не резолвится. Смотрим, чем отличаются красные джобы
от зелёных: только `astral-sh/setup-uv@v10`.

**Шаг 2: проверить гипотезу.** Существует ли тег `v10` в репозитории экшена?

```bash
git ls-remote --tags https://github.com/astral-sh/setup-uv "v10*"
# -> refs/tags/v10.0.0        (есть полный тег)
git ls-remote https://github.com/astral-sh/setup-uv "refs/tags/v10"
# -> пусто                    (мажорного тега v10 НЕТ)
```

Вот и причина. Исторически авторы экшенов ведут «движущиеся» мажорные теги
(`v4` переставляется на каждый `v4.x.y`), и `uses: ...@v4` — общепринятая
запись. Но setup-uv перестал двигать мажорные теги после `v7` — а
`releases/latest` при этом честно показывал `v10.0.0`. Референс `@v10`
указывал на несуществующий тег.

**Шаг 3: фикс.** Прибить полный тег:

```yaml
      # Full tag: setup-uv stopped publishing moving major tags after v7.
      - uses: astral-sh/setup-uv@v10.0.0
```

Коммит `47c0d09 fix setup-uv tag in ci` — и CI зелёный.

Уроки: (1) «Set up job» = проблема с резолвом экшенов, ваши шаги ещё даже
не начинались; (2) `git ls-remote` — способ спросить у любого репозитория
«какие у тебя теги», не клонируя его; (3) комментарий рядом с фиксом обязателен —
иначе следующий человек «поправит» `v10.0.0` обратно на `v10`.

## 5. Фаза GHCR: образ собирает CI, а не сервер

**Зачем.** VPS — 1 ГБ RAM; `docker build` рядом с работающим Postgres упирается
в OOM (из-за этого в runbook §4 появился swap). Логичный ход: собирать образ
на раннере GitHub (бесплатно, быстро), складывать в реестр, а серверу оставить
только `docker compose pull`. Реестр — GHCR (GitHub Container Registry):
он «прилагается» к репозиторию, аутентификация в CI — встроенным токеном.

**Правка Dockerfile** — одна строка после `FROM`:

```dockerfile
# Ties the GHCR package to this repo on GitHub.
LABEL org.opencontainers.image.source=https://github.com/<owner>/<repo>
```

`LABEL` — произвольные метаданные образа; ключ `org.opencontainers.image.source` —
стандартный (спецификация OCI), GitHub по нему привязывает пакет к репозиторию
(пакет появляется на странице репо, наследует права).

**Джоб `build` после апгрейда:**

```yaml
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    env:
      IMAGE: ghcr.io/shchurov-nk/weather-station-api
    steps:
      - uses: actions/checkout@v7
      - run: docker build -t "$IMAGE:latest" -t "$IMAGE:sha-${GITHUB_SHA::7}" ./api
      - if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        run: |
          echo "${{ secrets.GITHUB_TOKEN }}" | docker login ghcr.io -u "${{ github.actor }}" --password-stdin
          docker push --all-tags "$IMAGE"
```

- **`permissions:`** — каждому джобу GitHub выдаёт одноразовый токен
  `GITHUB_TOKEN`; этот блок задаёт его права. По принципу наименьших привилегий:
  читать код, писать пакеты — и ничего больше. Токен живёт только внутри джоба —
  снаружи (например, с VPS) им воспользоваться нельзя. Запомните это — оно
  объяснит, почему пакет придётся делать публичным.
- **Имя образа** — `ghcr.io/<владелец>/<имя>` и обязательно в **нижнем регистре**
  (у нас владелец `Shchurov-nk` → `shchurov-nk`; реестры не принимают заглавные).
- **Два тега за одну сборку**: `-t` можно повторять. `latest` — «текущий прод»,
  на него смотрит compose. `sha-<короткий хеш>` — неподвижная метка конкретного
  коммита: форензика («что именно крутится?») и аварийный откат на старую
  версию руками. `${GITHUB_SHA::7}` — bash-срез строки: первые 7 символов
  полного хеша коммита (переменную `GITHUB_SHA` раннер ставит сам).
- **`if:` на шаге пуша** — сборка происходит на любом событии (PR тоже —
  это и есть smoke-тест), а публикация только с main. PR от посторонних
  людей ничего в реестр записать не могут.
- **`docker login ... --password-stdin`** — пароль через stdin, а не аргументом:
  аргументы команд видны в списке процессов и логах. `github.actor` — кто
  запустил workflow.
- **Почему не готовые экшены** `docker/build-push-action` + `metadata-action`:
  они умеют то же самое, но это два сторонних слоя абстракции ради трёх
  прозрачных команд. В духе roadmap («никакой магии без супервизора») выбраны
  голые команды — их можно прочитать, повторить руками и отладить.

**Ручной шаг после первого пуша** — пакет создаётся **приватным**. Страница
пакета → Package settings → Change visibility → **Public**. Зачем: VPS будет
делать `docker pull` анонимно, без единого секрета на сервере (репозиторий
и так публичный — скрывать нечего). Альтернатива для приватного пакета —
classic PAT c правом `read:packages` и `docker login ghcr.io` на сервере.

Проверка фазы: `docker pull ghcr.io/shchurov-nk/weather-station-api:latest`
с любой машины, без логина.

## 6. Фаза CD: ветка `cd-ghcr`

Всё ниже живёт в ветке `cd-ghcr` и мержится в main **только после** ручного
деплоя стека на VPS (runbook §0–9), добавления секретов и переключения пакета
в Public. Порядок не каприз: закоммить мы `image:` в compose до появления
публичного образа — первый же `compose pull` на сервере упал бы. Скрытые
зависимости между фазами — вещь, которую стоит искать в любом плане.

### 6.1 `compose.yaml`: два ключа у одного сервиса

```yaml
  api:
    # CI builds and publishes this image; the VPS only pulls it (see
    # scripts/deploy.sh). Local dev still builds: `up -d --build`.
    image: ghcr.io/shchurov-nk/weather-station-api:latest
    build: ./api
```

`image:` и `build:` вместе — легальная и удобная комбинация, но её семантика
зависит от команды, поэтому контракт зафиксирован комментарием:

- `docker compose up -d --build` — собрать локально из `./api` и назвать
  результат `ghcr.io/...:latest`. Путь разработчика: ничего не тянется из сети.
- `docker compose pull api && docker compose up -d` — скачать образ из реестра.
  Путь сервера: ничего не собирается.

Один файл обслуживает оба мира; выбор делает команда, а не конфиг.

### 6.2 `scripts/deploy.sh` — серверная половина деплоя

```bash
#!/bin/bash
# Deploys the current checkout on the VPS: pull the api image from GHCR,
# apply migrations, restart what changed. CI runs this over ssh AFTER
# `git pull --ff-only` — the pull stays outside so the script never
# rewrites itself mid-run. Safe to run by hand too.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, where compose.yaml lives

# Only api: postgres/caddy upgrades stay deliberate, not a deploy side effect.
docker compose pull api

# Idempotent; new *.sql files arrived with git pull (bind mount).
docker compose exec -T db apply_migrations

docker compose up -d
docker compose ps

DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2-)
curl -fsS --max-time 10 "https://${DOMAIN}/table" > /dev/null && echo "smoke OK"

# Old api image layers add up fast on a small disk.
docker image prune -f
```

Разбор решений:

- **Почему `git pull` не внутри скрипта.** CI выполняет
  `git pull --ff-only && ./scripts/deploy.sh`. Если бы pull был внутри,
  bash читал бы файл, который git только что перезаписал *под работающим
  интерпретатором* — классический источник «скрипт выполнил половину старой
  версии и половину новой». Снаружи — сначала обновились файлы, потом
  запустилась уже новая версия скрипта.
- **`--ff-only`** — «только перемотка»: если история на сервере разошлась
  с origin (кто-то правил файлы прямо на VPS), pull не будет молча мержить,
  а упадёт — и деплой остановится с внятной ошибкой. Локальные правки на
  сервере — это дрейф, о котором нужно узнавать, а не прятать его в merge.
- **`pull api`, а не `pull`** — postgres и caddy обновляются только осознанным
  решением человека, а не как побочный эффект каждого деплоя.
- **Миграции до `up -d`** — новая версия api получает уже готовую схему.
  Новые `*.sql` приехали вместе с `git pull` (каталог миграций — bind mount
  в контейнер db), раннер идемпотентен — старые файлы напечатают `skip`.
- **`up -d` без флагов** — compose пересоздаёт только контейнеры, чей образ
  или конфиг изменился. Обновился api — перезапустится только api (секунды
  простоя); db и caddy не трогаются.
- **Smoke-тест** — `curl -fsS` на публичный URL: `-f` превращает HTTP-ошибку
  в ненулевой код возврата → из-за `set -e` деплой станет красным в Actions.
  Минимальная проверка «прод жив после выката», прямо в пайплайне.
- **`docker image prune -f`** — каждый деплой приносит новый образ; старые
  безымянные слои на 25-гигабайтном диске накапливаются быстро.
- `set -euo pipefail` — стандартная защита: падать на первой ошибке (`-e`),
  на неопределённой переменной (`-u`), не терять ошибки внутри пайпов
  (`pipefail`). Подробнее — walkthrough §11 про backup.sh.

### 6.3 `backup.sh` и `.env`: почему пришлось трогать бэкапы

Скрытая зависимость №2. Runbook §9 предлагал вписать ping-URL healthchecks.io
прямо в последнюю строку `backup.sh` на сервере. Теперь так нельзя по двум
причинам: локальная правка отслеживаемого файла сломает `git pull --ff-only`
(см. выше — каждый деплой начнёт падать), а закоммитить URL в публичный
репозиторий тоже нельзя — это секрет (любой сможет «пинговать» ваш чек,
маскируя мёртвые бэкапы). Решение — секрет переезжает в `.env` (он в
`.gitignore`):

```bash
# Dead man's switch: healthchecks.io alerts when the ping stops arriving.
# The URL lives in .env (gitignored): no secrets in the repo, and the server
# checkout stays clean for the `git pull --ff-only` that deploys run.
PING_URL=$(grep -E '^HEALTHCHECKS_PING_URL=' .env | cut -d= -f2- || true)
if [ -n "$PING_URL" ]; then
    curl -fsS -m 10 --retry 3 "$PING_URL" > /dev/null
fi
```

Две bash-детали, обе — источники реальных багов:

- `|| true` после пайпа: если переменной в `.env` нет, `grep` вернёт 1,
  а при `pipefail` это уронило бы весь скрипт. `|| true` превращает
  «не нашлось» в пустую строку.
- Полный `if`, а не идиома `[ -n "$PING_URL" ] && curl ...`. Ловушка: если
  короткая форма — **последняя строка** скрипта и условие ложно, `[` вернёт 1,
  и весь скрипт (с `set -e` это неважно, важен код возврата последней команды)
  завершится «ошибкой» — cron сочтёт бэкап упавшим при пустой переменной.
  `if` без `else` в ложной ветке возвращает 0.

В `.env.example` добавлена документированная пустая `HEALTHCHECKS_PING_URL=` —
этот файл у нас играет роль списка всех «ручек» стека.

### 6.4 Джоб `deploy` — мост между GitHub и сервером

```yaml
  deploy:
    runs-on: ubuntu-latest
    needs: [lint, test, migrations, build]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    concurrency:
      group: deploy-production
      cancel-in-progress: false
    steps:
      - name: ssh key and pinned host key
        run: |
          install -m 700 -d ~/.ssh
          printf '%s\n' "${{ secrets.VPS_SSH_KEY }}" > ~/.ssh/id_ed25519
          chmod 600 ~/.ssh/id_ed25519
          printf '%s\n' "${{ secrets.VPS_KNOWN_HOSTS }}" > ~/.ssh/known_hosts
      - run: |
          ssh -o BatchMode=yes deploy@193.124.115.214 \
            'cd /opt/weather-station && git pull --ff-only && ./scripts/deploy.sh'
```

- **`needs:`** — единственное место, где джобы перестают быть параллельными:
  deploy ждёт все четыре и запускается только если все зелёные. Это и есть
  «деплой после зелёных тестов» — не соглашение, а машинное правило.
- **`if:`** — та же пара условий, что у пуша образа: только событие `push`
  и только ветка main. На PR деплоя не существует даже как «пропущенного» шага
  с секретами в окружении.
- **`concurrency:`** — страховка от переплетающихся деплоев: два пуша подряд
  не будут одновременно дёргать сервер. Точная семантика GitHub: в группе
  максимум один выполняющийся и один ожидающий; если пушей три, промежуточный
  ожидающий отменяется — задеплоится самый свежий main, что нам и нужно.
  `cancel-in-progress: false` — *выполняющийся* деплой не убивают на середине
  (оборвать `apply_migrations` на полпути — худший сценарий).
- **Секреты.** Settings → Secrets and variables → Actions. В логах GitHub
  их значения автоматически маскируются. Здесь их два:
  - `VPS_SSH_KEY` — приватная часть **выделенного** ключа, созданного только
    для деплоя (`ssh-keygen -t ed25519 -f ws_deploy_key -N '' -C gha-deploy`).
    Не личный ключ: у личного слишком широкие полномочия, и его нельзя
    отозвать, не потеряв собственный доступ. Утечёт деплойный — удалить одну
    строку из `authorized_keys`.
  - `VPS_KNOWN_HOSTS` — вывод `ssh-keyscan -t ed25519 193.124.115.214`,
    **сверенный** с отпечатком, который показывает доверенная машина.
- **Пиннинг host key вместо `StrictHostKeyChecking=no`.** Раннер видит сервер
  впервые в жизни — каждый раз. Отключить проверку — значит согласиться
  говорить с *кем угодно*, кто отвечает по этому IP (MITM получит и код
  выполнить, и ключ перехватить негде — но выполнит наши команды у себя).
  Записав известный ключ хоста заранее, мы требуем: сервер обязан доказать,
  что он тот самый. `install -m 700 -d` — создать каталог сразу с правами
  (ssh отказывается работать с ключами, доступными группе/остальным —
  потому же `chmod 600` на ключ).
- **`BatchMode=yes`** — ssh никогда не задаёт интерактивных вопросов
  (пароль? принять ключ хоста?) — в CI отвечать некому, лучше мгновенно упасть.
- **Почему на сервере остаётся git-чекаут.** Образ в GHCR — это только api.
  А `compose.yaml`, `Caddyfile`, `db/migrations/`, `apply_migrations.sh`,
  `backup.sh` — файлы, которые контейнеры получают bind mount'ами из
  `/opt/weather-station`. Гибрид «git pull для файлов + compose pull для
  образа» — честная модель того, из чего состоит это приложение.

Опциональное укрепление на потом: forced command в `authorized_keys`
(`command="cd /opt/weather-station && git pull --ff-only && ./scripts/deploy.sh" ssh-ed25519 AAAA...`) —
тогда даже укравший ключ сможет запустить только деплой, и ничего больше.

**Откат** после плохого релиза: `git revert <sha> && git push` — конвейер сам
соберёт и выкатит предыдущее состояние кода. Аварийный путь: на VPS руками
поднять образ по неподвижному тегу `sha-<старый>`.

## 7. Как смотреть CI без браузера и `gh`

Публичный репозиторий — публичный API, обычный `curl` без токена:

```bash
# последний прогон на main: статус и заключение
curl -s "https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=1&branch=main" \
  | python3 -c "import sys,json; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['status'], r['conclusion'], r['head_sha'][:7])"
# status: queued / in_progress / completed; conclusion: success / failure (когда completed)
```

Дальше по `run_id` — эндпоинт `/actions/runs/<id>/jobs` из §4. Если стоит
`gh` CLI, то же самое — `gh run list`, `gh run watch`, `gh run view --log-failed`.

## 8. Чеклист воспроизведения с нуля

Порядок важен (см. скрытые зависимости, §6).

1. **CI**: `.github/workflows/ci.yml` (lint, test, migrations, build-smoke) +
   `[tool.ruff]` в `pyproject.toml` + `api/.python-version`. Проверить локально
   (`cd api && uv sync && uv run ruff check . && uv run pytest`), запушить,
   дождаться четырёх зелёных джобов.
2. **Первый деплой руками** по `vps-runbook.md` §0–9: DuckDNS → пользователь
   deploy + ключи + ufw + unattended-upgrades + swap + docker → clone в
   `/opt/weather-station`, `.env` (chmod 600), `docker compose up -d --build` →
   приёмка (401/201, nmap) → прошивка ESP32 → cron бэкапов.
3. **GHCR**: `LABEL org.opencontainers.image.source` в Dockerfile; джоб build →
   build+push с `permissions: packages: write`; после первого пуша — пакет
   в Public; проверить анонимный `docker pull`.
4. **Секреты**: выделенный ключ ed25519 → публичная часть в `authorized_keys`
   на VPS, приватная — в секрет `VPS_SSH_KEY`; `ssh-keyscan` (сверить
   отпечаток!) → `VPS_KNOWN_HOSTS`; `HEALTHCHECKS_PING_URL=` в `.env` на VPS.
5. **CD**: `image:` в compose + `scripts/deploy.sh` + правка `backup.sh` +
   deploy-джоб (`needs`, `if`, `concurrency`) — у нас всё это ветка `cd-ghcr`;
   merge в main = первый автодеплой. Проверить: цепочка в Actions зелёная,
   `docker compose ps` на VPS показывает api из `ghcr.io/...`, два пуша подряд
   не переплетаются.

## 9. Упражнения

1. Сломайте порядок импортов в `app.py` и запушьте в ветку — убедитесь, что
   `lint` краснеет. Почему до `[tool.ruff]` он остался бы зелёным?
2. Добавьте зависимость в `pyproject.toml` без `uv lock` — какой джоб упадёт
   первым и с какой ошибкой?
3. Напишите миграцию `003` с синтаксической ошибкой в SQL. Что покажет джоб
   `migrations`? Останется ли строка о ней в `schema_migrations`? (Подсказка:
   `--single-transaction` в `apply_migrations.sh`.)
4. Объясните своими словами, почему `pg_isready` через unix-сокет может
   ответить «готов» раньше, чем закончилась инициализация, а через TCP — нет.
5. Уберите мысленно `concurrency` из deploy-джоба и придумайте сценарий
   с двумя пушами, в котором сервер окажется в несогласованном состоянии.
6. Что именно сможет сделать злоумышленник, укравший `VPS_SSH_KEY`, если
   в `authorized_keys` настроен forced command? А без него?

## 10. Карта тем для изучения

- **GitHub Actions**: workflow/job/step, `needs`, `if`, `permissions`,
  `concurrency`, секреты, `GITHUB_TOKEN` — docs.github.com/actions.
- **Реестры контейнеров**: теги (движущиеся vs неподвижные), OCI-лейблы,
  GHCR и права пакетов.
- **SSH**: known_hosts и host key pinning, `ssh-keyscan`, BatchMode,
  forced commands в `authorized_keys`.
- **Bash для CI**: `set -euo pipefail` и его ловушки (`[ -n ] &&` в конце
  скрипта, `|| true` в пайпах), `$(...)`, срезы `${VAR::7}`.
- **Postgres в контейнере**: жизненный цикл init (`docker-entrypoint-initdb.d`),
  временный сервер без TCP, healthcheck vs готовность.
- Следующий уровень (по roadmap §7): деплой по тегам/релизам, staging-окружение,
  `docker compose --wait` + healthcheck для api вместо smoke-curl.
