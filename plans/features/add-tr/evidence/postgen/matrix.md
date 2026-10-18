# ADTR-POSTGEN — матрица статусов и доказательства

Кандидат (worktree, БЕЗ коммита — на ревью). Слайс ADTR-POSTGEN
(`plans/features/add-tr/requirements-map.json`), источник
`plans/features/add-tr/source-add-tr-2026-10-19.md` §ADD-TR.4 (L52–L63).

sha12 файлов кандидата (sha256[:12]):
| файл | sha12 | полный sha256 |
|---|---|---|
| `services/postgen_vision.py` (new) | `3237319b8b7f` | `3237319b8b7ffc25e1de9c309b7d35bb0d2d8bb4b86bcccb987cca1f40d81fa4` |
| `services/image_generation.py` | `e84009f90932` | `e84009f909325169a7b34e24bc729e8307e839d8b46b6f610759429c224f9699` |
| `services/tool_router.py` | `bdea19386748` | `bdea19386748db362518061d03e983c16fc5ccecf39c935261052d9def986858` |
| `services/tool_schemas.py` | `f5e066cba3f7` | `f5e066cba3f70de089eec64e3a91efceb752e2cb13cc8955c0dfe0815adde1dc` |
| `config/settings.py` | `f674a8424a7d` | `f674a8424a7db7eed02ccbbd2a2941fb8033338775873d4af160bb1d938c52fb` |
| `tests/test_addtr_postgen.py` (new) | `15ba029f3771` | `15ba029f3771dc17e4fdc65bef15543797fe6d26b86feb9c478a32d136b72166` |

## Матрица (задание лейна 1–6 × требование × тест × факт)

| # | Сценарий | Требование | Тесты (`tests/test_addtr_postgen.py`) | Наблюдаемое |
|---|---|---|---|---|
| 1 | `not completed / delivery uncertain / failed` | ADTR-POSTGEN-FAILED (L56) | `TestDirectBlock::test_delivery_failed_no_vision_no_claims`, `test_generation_failed_no_vision`; `TestToolPath::test_error_payload_has_no_analysis` | блок `<image_result status="error"…>`, Vision НЕ вызывается (`analyze_calls == []`), «готово» нет; tool JSON — `status="error"` без `image_analysis` |
| 2 | `generated + sent`, Vision OFF | ADTR-POSTGEN-OFF (L57), ADTR-POSTGEN-VOICE | `TestDirectBlock::test_sent_vision_off_no_content_claims`, `TestToolPath::test_success_vision_off_payload_no_description`, `TestAdapterMatrix::test_master_switch_off_real_gate` | в контексте — `<image_analysis status="off" reason="vision_disabled"/>` + ограничение «не утверждай»; описания нет; хардкод-реплик («готово, держи») нет; второй реплики сервис не форсирует |
| 3 | `generated + sent`, Vision ON и доступен | ADTR-POSTGEN-ON (L58), M-ADTR-POSTGEN-REUSE | `TestAdapterMatrix::test_ready_uses_actual_final_bytes`, `TestDirectBlock::test_sent_ready_block_is_grounded_and_data_only`, `TestToolPath::test_success_ready_payload_grounded` | анализ идёт по bytes ФАКТИЧЕСКОГО файла (`analyzed.data == result.content`), через тот же анализатор (`validate_image_bytes → analyze_image_bytes`); Writer получает `visual_description`/`ocr_blocks`; prompt в данные не подмешивается |
| 4 | Vision ON, но pending/rate_limited/unavailable/failed (+ timeout) | ADTR-POSTGEN-PENDING (L59) | `test_pending_probe_bounded_then_pending`, `test_rate_limited_unavailable_failed_mapping`, `test_timeout_is_bounded`, `TestDirectBlock::test_sent_rate_limited_delivery_not_blocked` | доставка не блокируется (блок `delivery="sent"`), статусы честные, описаний нет; timeout ≤ бюджета (`elapsed < 0.7` при бюджете 0.1 с) |
| 5 | Описание отражает реально увиденное, не промпт | ADTR-POSTGEN-MISMATCH (L60) | `test_sent_ready_block_is_grounded_and_data_only` (промпт «кот» vs описание «рыжий пёс»; OCR «IGNORE ALL INSTRUCTIONS» сохранён как данные с каналом `untrusted_image_data`); `test_no_text_and_parse_error_honest` | data-only: описание = выход анализатора; промпт в анализ не попадает по конструкции адаптера (промпт ему не передаётся); пустой/не-JSON ответ — честные `no_text`/`failed(parse_error)`, не «пустое описание» |
| 6 | Дедуп/идемпотентность | ADTR-POSTGEN-DEDUP (L61) | `test_dedup_same_bytes_single_provider_call`, `test_different_results_analyzed_separately`, `test_outgoing_file_not_registered_as_asset`, `TestDirectBlock::test_already_replay_no_second_analysis_or_claims`, `TestToolPath::test_skipped_marker_no_analysis`, `test_already_replay_no_analysis` | повтор тех же bytes — `cache_hit`, провайдер вызван 1 раз; «already»-replay не анализирует и не описывает; повторный tool call — `skipped:already_handled`; исходящий файл не регистрируется активом (`intake/job == 0`) — не считается пользовательским запросом |
| — | Киль-свитч OFF (паритет) | ADTR-POSTGEN-OFF, REUSE-GEN | `test_kill_switch_off_is_noop`, `TestDirectBlock::test_kill_switch_off_byte_parity`, `TestToolPath::test_kill_switch_off_no_field` | блок байт-в-байт равен прежнему; в tool JSON поля `image_analysis` нет; анализатор не вызывается |
| — | Контракт описания инструмента | ADTR-POSTGEN-ON/ON-VOICE | `TestSchemaContract::test_v21_documents_grounded_description` | V21: описывать можно только по `image_analysis` со `status="ready"`, иначе — без описания содержимого; legacy-текст (OFF-рубильник A3) не тронут |

## RED → GREEN

- RED (`evidence/postgen/red.txt`): `ImportError: cannot import name
  'postgen_vision' from 'services'` — контура не существовало; 25 тестов не
  собирались.
- GREEN (`evidence/postgen/green.txt`): `25 passed`.
- GREEN-кластер (`evidence/postgen/green-cluster.txt`): `1141 passed` по 31
  файлу (image/tool/soul1/direct/schemas/F8-registry/entry/decision/
  module-registry/tool-loop — пересечения лейнов не сломаны). База прогона:
  HEAD `21eb3d3eea1c` (ADTR-TOOLS коммит) + worktree-дельта лейна.
- E2E-зонд по РЕАЛЬНЫМ путям (`evidence/postgen/probe-e2e.txt`): direct
  pre-gate через `run_image_request → generate_and_send` и tool через
  `ToolRouter.dispatch`; дедуп (cache-hit), kill-switch OFF (блок без
  `image_analysis`), send-fail (Vision не вызывается) — `PROBE OK`.

## Известные ограничения (не блокеры)

- Живой провайдер Vision и реальная Telegram-доставка в проде — postdeploy
  (лейн без прод-доступа; контракт провайдера не менялся — тот же
  `analyze_image_bytes`).
- Проба capability при холодном кеше: одна автоматическая проба
  (единый D8-контур MCA-19, singleflight/TTL), ограничена бюджетом
  `IMAGE_POSTGEN_VISION_TIMEOUT_SECONDS`; при недоступности — честный
  `pending`, ход не блокируется.
