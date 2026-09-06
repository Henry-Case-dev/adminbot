"""Раунд 7 (chat-lore-management-v2, B5) — runtime-держатель компонентов лора.

Единые инстансы ChatLoreStore / ChatLoreCache / LoreNotify / LoreWorker
создаются в bot.py on_startup и кладутся сюда (`set_lore_components`);
чтение — модульными геттерами (руки-хендлеры bot.py, API-роуты
web/api/chat_lore.py, инжект direct_chat). Тесты подменяют компоненты через
`set_lore_components(...)`/`reset_lore_runtime()` (autouse-fixture).

Раунд 9 (AGI Memory, spec §3.6.1/Q2, T-816/T-817): + компонент db
(SQLite DatabaseService — read-only источник users_meta для web-api)
и relations (RelationsService): `set_lore_components(..., db=None,
relations=None)` + геттеры get_lore_db()/get_relations_service() (None —
не установлены; fail-open в вызывающих).

Раунд 9 (AGI Memory, spec §3.6.2, T-828/T-829): + воркеры «сна»/
ностальгии (ручной запуск и логи в web/api/memory_agi.py):
`set_lore_components(..., dream=None, nostalgia=None)` + геттеры
get_dream_worker()/get_nostalgia_worker() (None — не установлен → 503).
"""
import logging

logger = logging.getLogger(__name__)

_store = None
_cache = None
_notify = None
_worker = None
_db = None
_relations = None
_dream = None
_nostalgia = None


def set_lore_components(store=None, cache=None, notify=None, worker=None,
                        db=None, relations=None, dream=None, nostalgia=None):
    """Внедрение компонентов (bot.py on_startup / тесты)."""
    global _store, _cache, _notify, _worker, _db, _relations, _dream
    global _nostalgia
    _store = store
    _cache = cache
    _notify = notify
    _worker = worker
    _db = db
    _relations = relations
    _dream = dream
    _nostalgia = nostalgia


def reset_lore_runtime() -> None:
    """Полный сброс (shutdown/тесты)."""
    global _store, _cache, _notify, _worker, _db, _relations, _dream
    global _nostalgia
    _store = _cache = _notify = _worker = _db = _relations = None
    _dream = _nostalgia = None


def get_lore_store():
    return _store


def get_lore_cache():
    return _cache


def get_lore_notify():
    return _notify


def get_lore_worker():
    return _worker


def get_lore_db():
    """SQLite DatabaseService (Q2): web-api relations читает users_meta
    только через runtime; None — не установлен (SQLite-часть пуста)."""
    return _db


def get_relations_service():
    """RelationsService (spec §3.1.2): ленивый пересчёт users_meta +
    manual-мерж из PG. None — не установлен."""
    return _relations


def get_dream_worker():
    """DreamWorker (spec §3.4.1): ручной run_once/логи «сна» (F2-API).
    None — не установлен (fail-open: 503 в web/api/memory_agi.py)."""
    return _dream


def get_nostalgia_worker():
    """NostalgiaWorker (spec §3.5.5): ручной run_once/логи ностальгии.
    None — не установлен (fail-open: 503 в web/api/memory_agi.py)."""
    return _nostalgia
