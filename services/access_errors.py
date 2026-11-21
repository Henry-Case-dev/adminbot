"""MOD-ACL-UX-01 M4C C2 — общее исключение строгого чтения ACL-хранилища.

Единый тип для строгих read-путей (`GET /api/access/*`): матрица
`param_permissions`, chat-грант `chat_admins`, профиль `chat_profiles`.
Смысл — «данные прав не прочитаны» (HTTP 503), а НЕ «прав нет» (403) и НЕ
«пустой список» (200).

Модуль без импортов проекта: его может импортировать и `services/access.py`
(реэкспорт для совместимости с C1), и `services/roles.py`,
и `services/chat_params.py` без циклов.
"""


class AccessStorageUnavailable(RuntimeError):
    """Строгое чтение ACL-хранилища недоступно (GET /api/access/* → 503)."""
