"""Раунд 7 (chat-lore-management-v2, B5) — runtime-держатель компонентов лора.

Единые инстансы ChatLoreStore / ChatLoreCache / LoreNotify / LoreWorker
создаются в bot.py on_startup и кладутся сюда (`set_lore_components`);
чтение — модульными геттерами (руки-хендлеры bot.py, API-роуты
web/api/chat_lore.py, инжект direct_chat). Тесты подменяют компоненты через
`set_lore_components(...)`/`reset_lore_runtime()` (autouse-fixture).
"""
import logging

logger = logging.getLogger(__name__)

_store = None
_cache = None
_notify = None
_worker = None


def set_lore_components(store=None, cache=None, notify=None, worker=None):
    """Внедрение компонентов (bot.py on_startup / тесты)."""
    global _store, _cache, _notify, _worker
    _store = store
    _cache = cache
    _notify = notify
    _worker = worker


def reset_lore_runtime() -> None:
    """Полный сброс (shutdown/тесты)."""
    global _store, _cache, _notify, _worker
    _store = _cache = _notify = _worker = None


def get_lore_store():
    return _store


def get_lore_cache():
    return _cache


def get_lore_notify():
    return _notify


def get_lore_worker():
    return _worker
