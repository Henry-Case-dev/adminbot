"""F2 (T-1854, ADR-1019-2 D1 + ADR-1019-8 D2) — единый источник
sentinel-семантики лимитов.

⚠️ Три семейства sentinel'ов **НЕ взаимозаменяемы** (ADR-1019-8 §D2). Одно и
то же число `0` означает РАЗНОЕ:

| Семейство          | `0`                          | `< 0`              | `> 0`       |
|--------------------|------------------------------|--------------------|-------------|
| Бюджет (ключ/фон)  | `forbidden` (запрет)         | `unlimited`        | `cap`       |
| Контекст           | `unset` (не задано → дефолт) | `unlimited`        | `cap`       |
| Retention (дни)    | `eternal` (вечно, purge — нет) | `invalid` → fallback | `cap` (N) |

Бюджетный `0 = запрет` — канон F-7/F-15, сохранён **осознанно**; безлимит —
только явный отрицательный sentinel (`UNLIMITED = -1`). «0 = безлимит» не
используется (обратная совместимость + неоднозначность).

Хелперы — чистые функции без I/O и без значений токенов/ключей (R17). Мусор
трактуется безопасно: бюджет → `forbidden`, retention → `invalid`,
контекст → `unset`.
"""

FORBIDDEN: int = 0          # 0 = запрет (канон F-7/F-15)
UNLIMITED: int = -1         # любое < 0 = безлимит по метрике
UNLIMITED_LABEL = "безлимит"        # для UI/логов («Безлимит (∞)»)


def _as_int(value) -> int | None:
    """Безопасный int-каст (bool → int; мусор/NaN/inf → None)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            try:
                f = float(text)
                return int(f) if f.is_integer() else None
            except ValueError:
                return None
    return None


# ── Семейство «бюджет» (ключ direct-чата, фон воркеров) ─────────────────────

def budget_state(limit) -> str:
    """`'forbidden'` (==0, в т.ч. мусор) | `'unlimited'` (<0) | `'cap'` (>0)."""
    value = _as_int(limit)
    if value is None or value == FORBIDDEN:
        return "forbidden"
    if value < 0:
        return "unlimited"
    return "cap"


def is_forbidden(limit) -> bool:
    """True = метрика запрещена (0/мусор); консервативный дефолт."""
    return budget_state(limit) == "forbidden"


def is_unlimited(limit) -> bool:
    """True = метрика не ограничена (любое < 0)."""
    return budget_state(limit) == "unlimited"


# ── Семейство «контекст» (F4): 0 = не задано → глобальный дефолт ─────────────

def context_state(limit) -> str:
    """`'unset'` (==0/мусор) | `'unlimited'` (<0) | `'cap'` (>0)."""
    value = _as_int(limit)
    if value is None or value == 0:
        return "unset"
    if value < 0:
        return "unlimited"
    return "cap"


# ── Семейство «retention» (F7): 0 = вечно, purge категорически запрещён ─────

def retention_state(days) -> str:
    """`'eternal'` (==0) | `'cap'` (>0, хранить N дней) | `'invalid'` (<0/мусор).

    `invalid` → вызывающий обязан сделать fallback на глобальный дефолт +
    WARNING (аддитивность с F7); негатив не может означать «минус дней»."""
    value = _as_int(days)
    if value is None or value < 0:
        return "invalid"
    if value == 0:
        return "eternal"
    return "cap"
