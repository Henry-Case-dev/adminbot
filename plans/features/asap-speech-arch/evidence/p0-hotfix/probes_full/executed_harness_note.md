# Исполненный probe_full.py — расхождение с закоммиченным пробником

| Копия | Байт | sha256 |
|---|---|---|
| `/tmp/p0-full-new/probe_full.py` (new-дерево) | 23011 | `cea538c4df25bd097e5c164633eeb6369704a652a6319dd021b0b07a01982e3f` |
| `/tmp/p0-probe/probe_full.py` — **исполненный** | 23055 | `3dcf602fa8249a7a8827d4a397f400694319c0e13a1c5114a48d8b13274ee35e` |
| `probes_full/harness_probe_full.py` (в репозитории) | 23563 | `d0d510da847b7f501787996d411a5c908b2989f7d15f246194B33293A912AF29` |

Наблюдаемое поведение исполненной копии (из `raw_full_*.json` и лога):

- ключа `analysis_predicate` в raw нет ни в одном из 4 прогонов → флаг
  `include_analysis` в plan-блок не передавался;
- на old-варианте — `AttributeError: module 'services.direct_l1' has no
  attribute 'analysis_directive_needed'` (обращение к атрибуту напрямую, без
  ветки `_adn is None` из закоммиченной версии);
- счётчики `analysis_directive`/`analysis_writer` считают ASCII-литерал,
  которого в русских текстах нет (`repro_predicate.py`:
  `ascii_marker_in_text=false`), поэтому их значение всегда 0.

Следствие: исполненная копия проверяет поведение L2 old/new, но **не**
проверяет наличие точных analysis-текстов в payload. Чтобы закрыть 1×/0,
следующему сеансу нужно исполнить именно закоммиченный
`harness_probe_full.py` (sha `d0d510da…`) с планом research/deep_research и
считать `plan_block.count(ANALYSIS_DIRECTIVE_TEXT)`, а не ASCII-маркер.
Локальная воспроизводимость — `probes_full/repro_predicate.py`.
