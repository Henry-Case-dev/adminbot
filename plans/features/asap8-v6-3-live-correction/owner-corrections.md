# Owner corrections — asap8-v6-3-live-correction

Хронологический реестр уточнений владельца поверх зафиксированного снапшота
ТЗ (source-lines-37423-EOF.md, SHA256 d0b4f611…). Снапшот не переписывается;
 corrections имеют приоритет над противоречащими формулировками ТЗ.

## CORR-1 (2026-10-15, до join Wave 2) — Production background is FROZEN

Статус: ДЕЙСТВУЕТ, обязательный corrective constraint для U08/W2-GLASS и всех
дальнейших UI-волн (W3/W4), а также Reviewer-gate Wave 2.

1. Существующий production полигональный фон AdminBot (web/static/polygon-background.js
   + весь связанный CSS/HTML/SVG/JS rendering stack, доводился в несколько
   итераций) — утверждённый защищённый визуальный актив. ЗАМОРОЖЕН: запрещено
   менять геометрию/количество/размер/расположение/форму/composition полигонов,
   цвета/gradients/opacity/blending, анимацию (скорость/направления/timing/
   easing), responsive-поведение, реализацию «ради glass», упрощать ради
   производительности, любые минимальные визуальные корректировки без
   отдельного разрешения владельца. Принцип «минимально изменим фон, чтобы
   рефракция работала» — запрещён.
2. Liquid Glass адаптируется к фону; фон не адаптируется к glass.
   Слоистая модель: existing polygon background (НЕ МЕНЯТЬ) → glass optics →
   panel tint/rim/specular → content. Разрешено менять только glass-side:
   displacement/refraction layer, glass mask, synchronized decorative
   sampling/clone (если технически необходим; воспроизводит существующий фон,
   не заменяя его), rim/specular/tint, composition. Клонирование live DOM с
   контентом/данными запрещено.
3. Test backgrounds (grid, straight lines, blue wave, contrast gradient,
   evidence-сцены) — ТОЛЬКО в glass-teststand/acceptance/evidence/автотестах.
   Никогда в production UI. Тестовый стенд — не новый дизайн AdminBot.
4. Формулировки ТЗ U08 про aurora/mesh, «уменьшить доминирование геометрических
   линий/сеток», адаптацию фона — НЕ являются разрешением переделывать
   существующий полигональный фон. «Стекло показывает реальный underlying
   background» = преломлять существующий полигональный фон.
5. Reviewer-gate W2-GLASS (обязательно до APPROVED/join Wave 2):
   A. Preservation — git-diff нетронутости всего rendering stack фона
      относительно baseline f1418d7 + screenshot comparison до/после
      (одинаковый route/viewport/scroll) → «background unchanged, glass
      changed». Test grid/wave отсутствуют в production.
   B. Glass — Tier A преломляет существующую подложку; Tier B rim/specular/
      depth; content не искажается; fallback не требует изменения фона.
   Если production background визуально изменился — W2-GLASS не APPROVED,
   пока фон не восстановлен из git (не реконструирован вручную).
6. Ограничение адресовано W2-GLASS; SHELL/FULLSCREEN не перезапускаются,
   backend Wave 1/W3 не затронут. W3/W4 UI-правки наследуют этот constraint.

Критерий одним предложением: в production остаётся тот же существовавший
полигональный фон; все новые visual changes U08 — только в glass-слоях
поверх него; grid/wave/gradient стенды — исключительно в test/evidence.
