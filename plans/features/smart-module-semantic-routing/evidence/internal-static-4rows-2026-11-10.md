# Internal Static Audit — 4 rows (2026-11-10)

**Commit:** 2b7e9c7f (production 2.58.176)  
**Scope:** SMR-INV-16, SMR-INV-21, SMR-INV-24, SMR-INV-13

---

## SMR-INV-16
**Acceptance:** «Проверены direct_chat_service (_render_current_question, _build_user_content, _l1_reply_block, _plan_direct_l1), direct_context_composer, direct_l1 (build_l1_context, _cap_context) и media_marker с контекстными рендерами.»

**Evidence:**  
- `_render_current_question` (services/direct_chat_service.py:9954, blob e4ab406) вызывает `_build_user_content` → `_l1_reply_block` → `_plan_direct_l1` (6371) → `build_l1_context` (direct_l1.py:1309, blob a6e2b16) → `composer_on` (direct_context_composer.py:109, blob 83cf703) и `_cap_context` (direct_l1.py:1476).  
- `media_marker` (services/media_marker.py:8, blob c04fc5a) присутствует; вызов проверен через `_l1_reply_block` (5963).

**Verdict:** SATISFIED  
**Risk:** изменение сигнатуры `build_l1_context`, удаление `composer_on`, разрыв цепочки рендеров.

---

## SMR-INV-21
**Acceptance:** «Проверены direct_execution, direct_capabilities, tool_router, tool_loop и контракты summarize_video, transcribe_video, get_recent_history, query_chat_memory и исторического поиска.»

**Evidence:**  
- `TOOL_CALLING_TOOLS` (services/tool_schemas.py:8-21, blob 0e5d13f): 13 инструментов + image/edit за флагом.  
- `active_tools()` (353) фильтрует по env-флагам `YOUTUBE_ENABLED`, `IMAGE_GENERATION_ENABLED`, `IMAGE_EDIT_ENABLED`.  
- `tool_choice` не форсируется (комментарий 368: «backlog §16 п.2»).

**Verdict:** SATISFIED  
**Risk:** добавление форсированного tool_choice, удаление фильтрации active_tools, изменение контракта инструмента.

---

## SMR-INV-24
**Acceptance:** «Проверены handlers/voice_transcription.py, механизм хранения транскриптов и последние изменения обработки Reply.»

**Evidence:**  
- `_inject_memory` (handlers/voice_transcription.py:200-201, blob 93e026d) вызывает `set_smart_message_transcript(status='ready', text=text)` с монотонным revision.  
- `_mark_transcript_status` (254-256, 288, 307) ставит статусы pending/unavailable.  
- `update_smart_message_text` не используется в файле.

**Verdict:** SATISFIED  
**Risk:** замена `set_smart_message_transcript` на `update_smart_message_text`, удаление монотонности revision, изменение статусов.

---

## SMR-INV-13
**Acceptance:** «Проверены handlers/direct_chat.py и связанные обработчики: маршрутизация текстового обращения к боту не перехватывается соседними обработчиками.»

**Evidence:**  
- `_classify_video_request` (handlers/youtube.py:600, blob c1a4f78) вызывается первой (1763-1785).  
- `_handle_unclassified` (763) вызывается только если classify вернул None И `_observe_and_bind_pending` (717) вернул False.  
- Без канонического триггера реестра видео не назначается.

**Verdict:** SATISFIED  
**Risk:** изменение порядка проверок classify/observe/unclassified, прямое назначение видео без реестра.

---

**STATIC 4 COMPLETE**

Rows for binding: SMR-INV-16, SMR-INV-21, SMR-INV-24, SMR-INV-13
