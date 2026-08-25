"""Epic 67 (D266, Section 71.2) — паттерн Стратегия для транскрибации.

Замена или ДОБАВЛЕНИЕ сервиса распознавания речи = новый класс-наследник
BaseTranscriber + добавление в список стратегий VoiceTranscriber
(SmartModule/service.py, порядок = Primary → Fallback); остальной код
(хендлер, инъекция памяти) не меняется.
"""
from abc import ABC, abstractmethod


class BaseTranscriber(ABC):
    """Одна стратегия распознавания речи: файл аудио → текст."""

    name: str = ""
    timeout: float = 0.0                # сек; asyncio.wait_for в контроллере

    @property
    def available(self) -> bool:
        """False = стратегия пропускается контроллером (например, нет API key)."""
        return True

    @abstractmethod
    async def transcribe(self, file_path: str) -> str:
        """file_path → расшифровка ('' если сервис ничего не расслышал).

        Ошибки API/сети НЕ глотаются — пробрасываются контроллеру, он решает
        фолбэк (строго одна попытка на стратегию, без ретраев внутри).
        """
