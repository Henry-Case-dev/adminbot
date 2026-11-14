"""Мутационный плагин (mutation-red для `fc-anchor`).

Отключает применение предметного анкера на рантайме, НЕ меняя код:
    .venv/Scripts/python.exe -m pytest tests/test_factcheck_subject_contract.py \
        -k TestMaterialAnchorInQuestionQuery -q \
        -p mutation_no_anchor_plugin
(положить каталог этого файла в PYTHONPATH).

Ожидаемо падают 4 теста: запрос вопроса/материала без темы и контролируемый
агрегатор; негативные (паритетные) тесты проходят — они и не должны зависеть от
анкера.
"""
from services import factcheck_planner as fsp

fsp._with_material_anchor = lambda terms, anchor_terms: list(terms)
