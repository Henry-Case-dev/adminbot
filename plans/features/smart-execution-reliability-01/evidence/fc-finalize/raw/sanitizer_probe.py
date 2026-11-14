from services.factcheck_service import strip_service_tokens as s

cases = {
    "closed": "Нормальный ответ. <chat_context note=\"OCR\">сырой OCR-текст с картинки</chat_context>",
    "closed2": "Нормальный ответ. Но текст дальше. <chat_context>OCR-дамп: секрет</chat_context> Продолжение ответа.",
    "unclosed": "Нормальный ответ. <chat_context note=\"x\">сырой текст с картинки без закрытия",
    "unclosed_mid": "Нормальный ответ. <chat_context>OCR дамп\nи ещё строка\n\nОбычный вывод после абзаца.",
    "raw": "Ответ. <raw>внутренние данные</raw>",
    "ocr_tag": "Ответ. <ocr>распознанный текст</ocr>",
    "chat_time": "Ответ. <Chat_Time_Context source=\"server\">local: 14.11.2026</Chat_Time_Context> конец",
    "mention": "В статье упоминается тег chat_context как пример разметки.",
    "legit": "Курс вырос вдвое — это подтверждается.",
}
for key, value in cases.items():
    print(key, "=>", repr(s(value)))
