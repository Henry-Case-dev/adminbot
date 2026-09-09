"""Epic 24 — alias resolution (R7/D61, Section 33.6).

Cascade: alias (JSON dict from SUMMARY_ALIASES) → nickname (first+last name)
→ username (without @) → user_id. '@' never appears in results.

Epic 60 (66.9, T-487): canon_name — обратная карта «имя → канон-алиас» для
привязки фактов графа к людям (карточки /persona агрегируются по канон-имени).
"""
import json
import logging

logger = logging.getLogger(__name__)


class AliasResolver:
    """Resolves participant display names for the summary context."""

    def __init__(self, raw_json):
        """Принимает строку JSON (env) или dict (hot.get-кэш: json-тип каталога
        коэрсится в dict) — оба варианта заводятся без ошибок."""
        self._aliases: dict[str, str] = {}
        self._by_name: dict[str, str] = {}
        self._cache: dict[tuple, str] = {}
        if raw_json:
            if isinstance(raw_json, dict):
                data = raw_json
            else:
                try:
                    data = json.loads(raw_json)
                except (ValueError, TypeError):
                    logger.warning(
                        "SUMMARY_ALIASES invalid JSON — aliases disabled: %r",
                        raw_json)
                    data = None
            if not isinstance(data, dict):
                logger.warning(
                    "SUMMARY_ALIASES is not a JSON object — aliases disabled"
                )
            else:
                self._aliases = {str(k): str(v) for k, v in data.items()}
        self._by_name = {value.casefold(): value for value in self._aliases.values()}

    def canon_name(self, name: str) -> str:
        """66.9 (T-487): имя → канон-алиас (обратная карта). Совпадение с
        алиасом (регистронезависимо) → канон-написание алиаса; иначе — имя
        как есть (normalize не трогаем — caller сам нормализует)."""
        text = str(name or "").strip()
        return self._by_name.get(text.casefold(), text)

    def resolve(
        self,
        user_id: int,
        nickname: str | None = None,
        username: str | None = None,
    ) -> str:
        """Resolve user display name. '@' is stripped on every level."""
        key = (int(user_id), nickname, username)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        name = ""
        alias = self._aliases.get(str(user_id))
        if alias:
            name = str(alias).strip()
        elif isinstance(nickname, str) and nickname.strip():
            name = nickname.strip()
        elif isinstance(username, str) and username.strip():
            name = username.lstrip("@").strip()

        if not name:
            name = str(user_id)
        name = name.lstrip("@").strip()  # guarantee: no @ on any branch
        self._cache[key] = name
        return name


async def build_alias_resolver(chat_id: int) -> AliasResolver:
    """Раунд 10.4 (B-12): per-chat/ЛС резолв алиасов — override чата →
    глобальные (единый chat_params-путь, НЕ зависим от summary_enabled
    гейта — Hotfix-R10-инвариант). Fail-open: профиль/кэш недоступен →
    глобальные алиасы (наследование — ЛС не исключение из наследования)."""
    try:
        from services import chat_params, hot_config as hot
        from config.settings import settings
        default = hot.get("limits.summary_aliases", settings.SUMMARY_ALIASES)
        raw = await chat_params.get_chat_param(
            chat_id, "limits.summary_aliases", default)
    except Exception:
        logger.warning(
            "alias resolver per-chat failed — fail-open global | chat=%s",
            chat_id, exc_info=True)
        raw = None
    if raw is None:
        try:
            from services import hot_config as hot
            from config.settings import settings
            raw = hot.get("limits.summary_aliases",
                          settings.SUMMARY_ALIASES)
        except Exception:
            raw = None
    return AliasResolver(raw)
