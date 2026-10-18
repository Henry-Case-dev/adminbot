FIX2 (V-FIX2) — hashes/команды, 2026-10-19 (обновлено после NF-1)
Runner: .venv\Scripts\python.exe -m pytest (та же среда, что в приёмке 2.58.91)
База (HEAD до правок): e3fa4e97 (master, после ревью-коммита V-FIX2);
правки — без коммита (на ревью). `web/app.js` НЕ менялся (b14ef48ab16a) —
UI-правка для NF-1 не потребовалась: `web/app.js::api()` уже ставит
`X-Chat-Id` для активного чата, поэтому проба приходит с контекстом чата,
а серверный фикс делает `state` контекстно-корректным.

Изменённые файлы (sha256 / sha12):
    services/mca_vision.py                 f8cb004c6c84
      f8cb004c6c840ddf6935b2df6fdf58dfc9a568e3b6c62b4b14c980b591d4d342
    web/api/routes.py                      d54cc29695c7
      d54cc29695c702e79b3410007bf3f08490d045a2e99679c16495a129736fb9e2
    tests/test_p0_vision_fix_core.py       458d31d3d4fb
      458d31d3d4fbc77b44b37681ffca5ae22b8561a96ccb414e6af4eb10cd5f5d04
    tests/test_round1025_f8_registry.py    b29e03417cf2  (re-pin ROUTES_SHA256_F11)
      b29e03417cf21f2a8fd675b2808bc415c42f8fcb01023b816240705d1f185e25
    tests/test_mca23_planned_vs_actual.py  0f7a932e9038  (re-pin ROUTES_SHA256_F11)
      0f7a932e9038ef47968eccde195f4b80c898342c1b7d9208f351f61cdef0dda8

Команды прогонов (логи рядом):
    RED    : py -3 -m pytest tests/test_p0_vision_fix_core.py -k "fix2 or per_chat_context" -q
             (при откаченных services/mca_vision.py + web/api/routes.py через git stash)
             → red-2026-10-19.txt: 6 failed, среди них реальный прод-симптом
               'skipped: maximum number of running instances reached (1)'
    RED-2  : тот же stash-прогон для live-ретрая 429 →
             sqlite3.IntegrityError UNIQUE ... mca_media_analyses.revision
             (test_fix2_rate_limited_live_retry_succeeds_after_limit)
    RED-NF1: py -3 -m pytest ... -k "vision_test_state_per_chat" -q
             (при откаченном web/api/routes.py — NF-1 изолированно)
             → red-nf1-2026-10-19.txt: 1 failed, `assert False is True`
               (state пробы оставался глобальным при per-chat ON)
    GREEN  : .venv\Scripts\python.exe -m pytest tests/test_p0_vision_fix_core.py
             -k "fix2 or per_chat_context" -v
             → green-new-tests-2026-10-19.txt: 7 passed
               (6 fix2 + расширенный тест пробы NF-1)
    SWEEP  : .venv\Scripts\python.exe -m pytest <16 файлов: vision core + mca19 A–G +
             rework r1 + mca10b + mca23 + round1025 + addtr_postgen +
             settings_worker_sync + mca17_perimeter + asap7_module_completeness>
             → sweep-2026-10-19.txt: 323 passed
    UI-E2E : .venv\Scripts\python.exe -m pytest tests/test_p0_vision_ui_e2e.py -q
             → ui-e2e-2026-10-19.txt: 7 passed (реальный UI-контракт
               GET /api/vision/state через headless-браузер; web/* не менялись)
    D11    : .venv\Scripts\python.exe -m pytest tests/test_asap8_v6_p1_d11_registry.py -q
             → 16 passed (изолированно)

Pre-existing (не связано с FIX2, воспроизведено на чистом HEAD):
    1) tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer
       — 201 commit-вызов в services/database.py при allow-map 198 (документировано
       в plans/features/p0-vision-universal/evidence/fix-core/design-note-d9-and-flag-2026-10-19.md §4).
    2) tests/test_asap8_v6_p1_d11_registry.py::TestD11EffectiveGates::test_env_off_beats_product_toggle
       — падает в СОВМЕСТНОМ прогоне (17 файлов) из-за загрязнения hot-config кеша
       предыдущими тестами; на чистом HEAD (git stash правок) падает так же, изолированно — зелёный.
       К FIX2 не относится (правки в mca_vision/vision-state гейты D11 не трогают).
    3) tests/test_p0_vision_ui_e2e.py через `py -3` (без .venv) — ModuleNotFoundError: playwright
       (среда; через .venv — 7 passed).
