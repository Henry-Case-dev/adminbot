"""GoodmorningRelay — утренняя рассылка медиа (Epic 30, R30-3, D88/D93).

Plain-send БЕЗ reply/quote (прецедент OlyaRelay): бот просто будит чат,
цитировать спящих нечем — они ещё не написали ничего умного.

Типы (D93): photo/video/animation — С caption; audio/voice — skip с
WARNING (caption им недоступен, а молча будить — грубо); unsupported —
debug-skip. Пустая/отсутствующая папка → WARNING + False.
Регистр расширения не мешает: `goodmorning_05_gif.MP4` → animation
по gif-маркеру (suffix.lower() + word-boundary детект, как в CommonRelay).

Выбор материала и подписи (GM-media-quantum, AMEND):
  * пул медиа перечитывается с диска НА КАЖДОЙ отправке (`_scan_directory`
    вызывается в `send_goodmorning`) — новый файл, положенный в
    `GOODMORNING_MEDIA_DIR` при живом процессе, попадает в пул сразу, без
    рестарта и без «кеша», «used»-флагов и лимитов по mtime/размеру;
  * выбор делает ЕДИНСТВЕННЫЙ источник поведенческой случайности проекта —
    `services.mca_random_source.RandomSourceService` (`draw_index`): quantum
    (ANU) либо его штатный pseudorandom-фолбэк. Второго энтропийного стека
    нет; `random` используется только как аварийный фолбэк, когда источник
    недоступен/выключен, и это честно помечается в журнале (`fallback_reason`);
  * метка `quantum` ставится ТОЛЬКО при реальном draw провайдера (есть
    `draw_id`). Выбор без расхода значения — единственный оставшийся в цикле
    файл (`n == 1`), выключенный/отложенный гейт, отказ источника — пишется
    как `pseudorandom` + `fallback_reason` (`disabled`, `single_candidate`,
    `provider_unavailable`, …): журнал не приписывает quantum там, где его
    не было;
  * каждый выбор = отдельный draw (медиа и подпись — разные draw'ы), журнал
    `mca_random_draws` получает source/provider/draw_id/created_at/pool;
  * цикл: внутри цикла файл (и подпись) не повторяются; новый файл попадает
    в текущий цикл; исчерпанный пул честно начинает новый цикл. Состояние
    цикла durable (`var/goodmorning_state.json`, atomic replace, fail-open:
    ошибка записи не блокирует рассылку).
"""
import json
import logging
import os
import random
import tempfile
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from services.goodmorning_captions import GOODMORNING_CAPTIONS

logger = logging.getLogger(__name__)

MEDIA_PHOTO = "photo"
MEDIA_VIDEO = "video"
MEDIA_ANIMATION = "animation"
MEDIA_AUDIO = "audio"
MEDIA_VOICE = "voice"

_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".webm"}
_AUDIO_EXTENSIONS: set[str] = {".mp3"}
_VOICE_EXTENSIONS: set[str] = {".ogg"}

# Журнальные метки draw'ов (не exploration-purpose: probability-карта
# `EXPLORATION_PROBABILITY_KEYS` не расширяется, второго контура нет).
DRAW_PURPOSE_MEDIA = "goodmorning_media"
DRAW_PURPOSE_CAPTION = "goodmorning_caption"
DRAW_POLICY_VERSION = "gm-media-quantum-v1"

KIND_MEDIA = "media"
KIND_CAPTION = "caption"

STATE_VERSION = 1
ENV_STATE_FILE = "GOODMORNING_STATE_FILE"
DEFAULT_STATE_FILE = os.path.join("var", "goodmorning_state.json")

SOURCE_PSEUDORANDOM = "pseudorandom"


class GoodmorningRelay:
    """Epic 30: утренняя рассылка — случайное медиа + caption, plain-send."""

    def __init__(self, bot: Bot, media_dir: str, *, random_source=None,
                 state_path: str | Path | None = None) -> None:
        self._bot = bot
        self._media_dir = media_dir
        # DI единственного источника случайности (mca-10a). None → общий
        # singleton `mca_random_source.get_service()` (лениво, в async-пути).
        self._random_source = random_source
        self._state_path = (str(state_path) if state_path is not None
                            else os.getenv(ENV_STATE_FILE, DEFAULT_STATE_FILE))

    def _detect_media_type(self, filepath: Path) -> str | None:
        """Тип файла по расширению + gif-маркер в имени.

        КОПИЯ логики CommonRelay (прецедент дублирования: OlyaRelay,
        ARCHITECTURE 4.3; вынос в media_utils — будущий рефакторинг,
        вне скоупа). suffix.lower() + word-boundary gif-детект (D93).
        """
        ext = filepath.suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            return MEDIA_PHOTO
        if ext in _VIDEO_EXTENSIONS:
            fname = filepath.name.lower()
            if "_gif" in fname or fname.startswith("gif") or ".gif." in fname:
                return MEDIA_ANIMATION
            return MEDIA_VIDEO
        if ext in _AUDIO_EXTENSIONS:
            return MEDIA_AUDIO
        if ext in _VOICE_EXTENSIONS:
            return MEDIA_VOICE
        return None

    def _scan_directory(self) -> list[tuple[Path, str]]:
        """Скан GOODMORNING_MEDIA_DIR (заново, на каждую отправку).

        Только photo/video/animation (D93): audio/voice → WARNING + SKIP;
        unsupported → debug-skip; пустая/отсутствующая папка → WARNING + [].
        Подпапки не сканируются (плоская папка — контракт README); их наличие
        логируется, чтобы «файл не виден» объяснялось сразу.
        """
        base = Path(self._media_dir)
        if not base.exists() or not base.is_dir():
            logger.warning(
                "Goodmorning: media directory not found %s — рассылка без завтрака",
                base,
            )
            return []

        files: list[tuple[Path, str]] = []
        skipped_dirs: list[str] = []
        for entry in base.iterdir():
            try:
                if entry.is_dir():
                    skipped_dirs.append(entry.name)
                    continue
                if not entry.is_file():
                    continue
                media_type = self._detect_media_type(entry)
                if media_type in (MEDIA_PHOTO, MEDIA_VIDEO, MEDIA_ANIMATION):
                    files.append((entry, media_type))
                elif media_type in (MEDIA_AUDIO, MEDIA_VOICE):
                    # D93: caption недоступен — будить музыкой молча нельзя
                    logger.warning(
                        "Goodmorning: %s skipped — caption недоступен (D93)",
                        entry.name,
                    )
                else:
                    logger.debug(
                        "Goodmorning: skipping unsupported file %s", entry.name
                    )
            except OSError:
                logger.warning(
                    "Goodmorning: cannot access entry %s — skipping", entry
                )
                continue

        if skipped_dirs:
            logger.info(
                "Goodmorning: подпапки не сканируются (плоская папка): %s",
                sorted(skipped_dirs),
            )

        if not files:
            logger.warning(
                "Goodmorning: no sendable media in %s — утро отменяется", base
            )
            return []

        logger.info(
            "Goodmorning: scanned %s — found %d files: %s",
            base,
            len(files),
            [(f.name, mt) for f, mt in files],
        )
        return files

    # ── durable-состояние цикла (fail-open) ────────────────────────────────
    def _state_file(self) -> Path:
        return Path(self._state_path)

    def _load_state(self) -> dict:
        try:
            raw = self._state_file().read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.warning(
                "Goodmorning: rotation state unreadable — новый цикл | path=%s",
                self._state_path,
            )
            return {}

    def _save_state(self, state: dict) -> None:
        """Atomic replace (tmp + os.replace); ошибка → WARNING, рассылка жива."""
        path = self._state_file()
        tmp_name = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False)
            os.replace(tmp_name, path)
            tmp_name = None
        except Exception:
            logger.warning(
                "Goodmorning: rotation state write failed — in-memory only | "
                "path=%s", self._state_path, exc_info=True)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    # ── draw из единственного RandomSource ────────────────────────────────
    async def _draw_index(self, n: int, *, chat_id, purpose: str,
                          candidates) -> tuple[int | None, dict]:
        """Один свежий draw `RandomSourceService.draw_index` (mca-10a).

        Returns:
            (index | None, diag). `None` — источник недоступен/выключен/
            отложил draw; вызывающий берёт штатный фолбэк и честно пишет
            `fallback_reason`. Исключение источника рассылку не блокирует.
        """
        diag = {"source": None, "provider": None, "draw_id": None,
                "fallback_reason": None, "reason": None, "deferred": False}
        if n <= 0:
            return None, diag
        try:
            service = self._random_source
            if service is None:
                from services import mca_random_source
                service = mca_random_source.get_service()
            result = await service.draw_index(
                n, chat_id=chat_id, purpose=purpose,
                policy_version=DRAW_POLICY_VERSION,
                candidates=list(candidates),
            )
        except Exception:
            logger.warning(
                "Goodmorning: random source draw failed — фолбэк | chat_id=%s | "
                "purpose=%s", chat_id, purpose, exc_info=True)
            diag["fallback_reason"] = "provider_unavailable"
            return None, diag
        diag.update(
            source=getattr(result, "source", None),
            provider=getattr(result, "provider", None),
            draw_id=getattr(result, "draw_id", None),
            fallback_reason=getattr(result, "fallback_reason", None),
            reason=getattr(result, "reason", None),
            deferred=bool(getattr(result, "deferred", False)),
        )
        index = getattr(result, "index", None)
        if index is None:
            if not diag["fallback_reason"]:
                diag["fallback_reason"] = diag["reason"] or "no_draw"
            return None, diag
        try:
            bounded = max(0, min(int(index), n - 1))
        except (TypeError, ValueError):
            diag["fallback_reason"] = "validation_failed"
            return None, diag
        self._honest_label(diag, n)
        return bounded, diag

    @staticmethod
    def _honest_label(diag: dict, n: int) -> None:
        """`quantum` — только при реальном draw провайдера (`draw_id` есть).

        Выбор без расхода значения (`n == 1`: единственный оставшийся в цикле
        файл; гейт выключен/отложен; источник вернул индекс, не сходив в ANU)
        — это НЕ quantum-выбор: подпись источника понижается до
        `pseudorandom`, а причина пишется в `fallback_reason`. Иначе журнал
        врал бы (`source=quantum`, `draw_id=None`).
        """
        if diag.get("source") == SOURCE_PSEUDORANDOM:
            return
        if diag.get("draw_id"):
            return
        diag["source"] = SOURCE_PSEUDORANDOM
        if not diag.get("fallback_reason"):
            diag["fallback_reason"] = (
                diag.get("reason")
                or ("single_candidate" if n <= 1 else "no_provider_draw"))

    @staticmethod
    def _allowed(keys: list[str], used: list[str]) -> tuple[list[int], bool]:
        """Индексы, ещё не бывшие в текущем цикле (новый файл — сразу в пуле).

        `cycle_started=True` — пул исчерпан честно, начинаем новый цикл."""
        used_set = {str(u) for u in used or ()}
        allowed = [i for i, key in enumerate(keys) if key not in used_set]
        if not allowed:
            return list(range(len(keys))), True
        return allowed, False

    async def _pick(self, keys: list[str], *, used: list[str], chat_id,
                    purpose: str, journal_ids: list[str] | None = None
                    ) -> tuple[int, bool, dict]:
        """Выбор позиции в пуле: quantum-draw по остатку цикла, фолбэк — random."""
        allowed, cycle_started = self._allowed(keys, used)
        labels = journal_ids if journal_ids is not None else keys
        draw_candidates = [labels[i] for i in allowed]
        index, diag = await self._draw_index(
            len(allowed), chat_id=chat_id, purpose=purpose,
            candidates=draw_candidates)
        if index is None:
            # Штатный фолбэк проекта для этого пути — прежний выбор `random`
            # (поведение 2.58.x). Источник не выдал draw — не врём, помечаем:
            # выбранное значение пришло из фолбэка, а не из quantum.
            index = random.randrange(len(allowed))
            diag["source"] = SOURCE_PSEUDORANDOM
            diag["fallback_reason"] = (
                diag.get("fallback_reason") or diag.get("reason")
                or "source_unavailable")
        return allowed[index], cycle_started, diag

    @staticmethod
    def _remember(state: dict, kind: str, keys: list[str], used: list[str],
                  chosen_key: str, cycle_started: bool) -> None:
        """Отметить выбор в цикле (только после успешной отправки)."""
        keys_set = set(keys)
        kept = [] if cycle_started else [str(u) for u in used if u in keys_set]
        kept.append(chosen_key)
        entry = state.get(kind) if isinstance(state.get(kind), dict) else {}
        try:
            cycles = int(entry.get("cycles") or 0)
        except (TypeError, ValueError):
            cycles = 0
        state[kind] = {"used": kept, "cycles": cycles + (1 if cycle_started else 0)}

    async def send_goodmorning(self, chat_id: int) -> bool:
        """Случайный файл + случайная капция, plain-send БЕЗ ReplyParameters.

        Материал и подпись выбирает единственный RandomSource (quantum →
        штатный pseudorandom-фолбэк); каждый выбор журналируется (source,
        draw_id, pool). Внутри цикла повторов нет.

        Returns:
            True — отправлено; False — нечего отправлять или ошибка
            (лог + False, job не падает).
        """
        files = self._scan_directory()
        if not files or not GOODMORNING_CAPTIONS:
            return False

        media_keys = [path.name for path, _ in files]
        captions = list(GOODMORNING_CAPTIONS)
        state = self._load_state()
        media_state = state.get(KIND_MEDIA) if isinstance(
            state.get(KIND_MEDIA), dict) else {}
        caption_state = state.get(KIND_CAPTION) if isinstance(
            state.get(KIND_CAPTION), dict) else {}
        media_used = list(media_state.get("used") or [])
        caption_used = list(caption_state.get("used") or [])

        media_pos, media_cycle, media_diag = await self._pick(
            media_keys, used=media_used, chat_id=chat_id,
            purpose=DRAW_PURPOSE_MEDIA)
        caption_pos, caption_cycle, caption_diag = await self._pick(
            captions, used=caption_used, chat_id=chat_id,
            purpose=DRAW_PURPOSE_CAPTION,
            journal_ids=[str(i) for i in range(len(captions))])

        filepath, media_type = files[media_pos]
        caption = captions[caption_pos]
        input_file = FSInputFile(str(filepath))

        try:
            sent = None
            if media_type == MEDIA_PHOTO:
                sent = await self._bot.send_photo(
                    chat_id=chat_id, photo=input_file, caption=caption
                )
            elif media_type == MEDIA_VIDEO:
                sent = await self._bot.send_video(
                    chat_id=chat_id, video=input_file, caption=caption
                )
            elif media_type == MEDIA_ANIMATION:
                sent = await self._bot.send_animation(
                    chat_id=chat_id, animation=input_file, caption=caption
                )
            else:
                raise ValueError(f"Unknown media_type: {media_type}")
        except Exception:
            logger.exception(
                "Goodmorning: send failed | chat_id=%s | file=%s | type=%s",
                chat_id,
                filepath.name,
                media_type,
            )
            return False

        # Цикл двигаем только после доставки: упавшая отправка не «съедает»
        # файл у следующего утра.
        self._remember(state, KIND_MEDIA, media_keys, media_used,
                       media_keys[media_pos], media_cycle)
        self._remember(state, KIND_CAPTION, captions, caption_used,
                       captions[caption_pos], caption_cycle)
        self._save_state(state)

        # MCA-22 (C2, fix round-1 M-4): доставленная медиа-подпись —
        # слова бота → durable ledger (`media_caption`). Fail-open.
        try:
            from services import bot_output_ledger as _bol
            await _bol.record_delivered_output(
                None, chat_id=chat_id,
                tg_message_id=getattr(sent, "message_id", None),
                text=None, caption=caption,
                bot_user_id=getattr(self._bot, "id", None),
                output_kind="media_caption",
                source_feature="goodmorning_relay")
        except Exception:
            logger.warning(
                "[mca22] goodmorning ledger record failed | chat_id=%s",
                chat_id, exc_info=True)

        logger.info(
            "Goodmorning: sent | chat_id=%s | file=%s | type=%s | caption=%r | "
            "media_pool=%d media_index=%d media_source=%s media_draw_id=%s "
            "media_fallback=%s media_cycle=%s | caption_pool=%d "
            "caption_index=%d caption_source=%s caption_draw_id=%s "
            "caption_fallback=%s caption_cycle=%s",
            chat_id,
            filepath.name,
            media_type,
            caption,
            len(media_keys),
            media_pos,
            media_diag.get("source"),
            media_diag.get("draw_id"),
            media_diag.get("fallback_reason"),
            media_cycle,
            len(captions),
            caption_pos,
            caption_diag.get("source"),
            caption_diag.get("draw_id"),
            caption_diag.get("fallback_reason"),
            caption_cycle,
        )
        return True
