# `mca-02-safe-fetch-cookies` — аудит cookies/профиля (T-3807; R17-safe)

> Карта «потребитель → настройка → сценарий». Значения секретов/реальные пути не
> приводятся (R17). Источник: рабочая ветка (незакоммиченная волна 10.27) + `git ls-files`.

## 1. Потребители cookies / proxy / профиля

| # | Потребитель | Настройка / env | Сценарий | Режим |
|---|---|---|---|---|
| C1 | `services/youtube_transcript_engine.py` (`YouTubeTranscriptEngine.__init__`) | `YOUTUBE_COOKIES_FILE`, hot `keys.youtube_cookies_file`; `YOUTUBE_TRANSCRIPT_PROXY_URL/USERNAME/PASSWORD/DOMAIN/PORT`, hot `keys./limits.youtube_transcript_proxy_*` | Логирование presence (R17); resident-proxy для `youtube-transcript-api` | READ (не логирует значения) |
| C2 | `config/settings.py::build_ytdlp_base_opts` | `YOUTUBE_COOKIES_FILE` → `cookiefile`; `YOUTUBE_TRANSCRIPT_PROXY_URL` → `proxy`; `YTDLP_POT_PROVIDER` | Единый источник yt-dlp-опций (probe/скачивание/субтитры) | READ |
| C3 | `services/youtube_transcript_engine.py::_ytdlp_opts` | `build_ytdlp_base_opts()` (+`player_client`) | Субтитры через yt-dlp (ru/en) | READ |
| C4 | `tools/video_downloader.py::probe` / `download_ytdlp` | `build_ytdlp_base_opts()` | Метаданные и скачивание YouTube | READ |
| C5 | `tools/video_downloader.py::download_env_summary` | presence-only (`cookies/proxy/pot/cobalt`) | Диагностика окружения (R17: только set/absent) | READ (presence) |
| C6 | `handlers/youtube.py::_log_yt_credentials_presence` | presence-only cookies/proxy/pot | R17-safe старт-лог | READ (presence) |
| C7 | `tools/cookies_export.py` | `--profile <user_data_dir>`, `--out <Netscape>` | Экспорт Netscape-cookies (Playwright / yt-dlp) | WRITE отдельного файла (0o600) |
| C8 | `services/youtube_transcript_engine.py::_transcript_proxy_config` | Webshare-креды (env/hot) | `GenericProxyConfig` для transcript-api | READ (значения не логируются; N5 — `sanitize`) |

**Volume mounts / внешние скрипты:** в репозитории не найдено `systemd`/`docker-compose`/shell-скриптов,
монтирующих cookies/профиль (`Get-ChildItem` по `*.sh/*.service/*.yml/Dockerfile*` → 0 совпадений).
Резидентный/гео-прокси задаётся через env/hot, не через mount.

## 2. Упаковка (секреты не попадают в артефакты)

- `.gitignore` уже исключает: `media/*cookies*`, `*cookies*.txt`, `*.cookies`, `chrome-profile/`,
  `bot-chrome-profile/`.
- `git ls-files` **чист**: cookies/профиль не отслеживаются (совпадают только `.env.example`,
  тесты и инструмент экспорта — без секретов).
- Фактические runtime-файлы в рабочем дереве (`media/srv_cookies.txt`, `cookies.txt`) —
  **ignored и НЕ удаляются** этим шагом (исключение из упаковки ≠ удаление на сервере).

## 3. Политика переноса / cleanup

- **Перенос не требуется**: существующие ссылки (`YOUTUBE_COOKIES_FILE` env/hot) рабочие;
  перенос в закрытый runtime-каталог не выполнялся, оригиналы сохранены.
- **Cleanup:** лишняя копия не удалялась — авторизованный video-сценарий на этом шаге
  достоверно не проверялся (нет доступа к реальным cookies/профилю/сети YouTube-аккаунта),
  поэтому зафиксирован `cleanup_deferred_dependency_unverified` (runtime-файлы остаются).
- **Сессии не отзываются** автоматически; при подтверждённом раскрытии — уведомление владельцу
  без потери работоспособности (значения секретов в отчёт не помещаются).
- **Наблюдение:** новые архивы/артефакты формируются без cookies/профиля (правила `.gitignore`);
  при сборке релиза `mca-release` — повторная проверка `git ls-files`.

## 4. Что НЕ менялось

- `services/database.py` (Δ DDL = 0), `param_catalog.py` (Δ каталога = 0),
  секреты/пути/значения не переписывались и не удалялись.
