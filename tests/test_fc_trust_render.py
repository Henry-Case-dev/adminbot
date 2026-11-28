"""FCT-S4 U3 — публикация и подписи (FCT-602/603/702/023/193), 28.11.2026.

Контракт: `plans/features/fc-trust-01/evidence/fct-s4-design-2026-11-28/s4-design.md`
(sha `3afe7029…`) §2.1/§3 + decisions (D2: `publication_kind` — отдельная ось).

Проверяется видимый пользователю результат `render_factcheck`/`render_plain`:

* `execution_status=technical_unverified` — честный технический заголовок по
  `execution_cause`, а НЕ «Недостаточно данных для проверки»; внутренние коды
  и ID не публикуются;
* `partial` — содержательный заголовок, подтверждённые части сохраняются,
  рядом короткая оговорка о неполноте (причина — по-русски);
* `publication_kind` — русские подписи (научная статья/препринт/пресс-релиз/
  пересказ/авторская интерпретация); пресс-релиз и интерпретация не выглядят
  «доказательством напрямую»;
* `unverified_media` — оговорка ровно у затронутой части (caption/OCR),
  а не у всей публикации;
* B-1 (FCT-023 backlog): `/article/`/`/articles/` больше не считаются
  журнальной статьёй без реального журнального признака.
"""
from __future__ import annotations

import types

import pytest

from services import factcheck_orchestrator as orch
from services import factcheck_renderer as fr
from services import search_aggregator as sa


def _presentation(text="", links=(), notice=""):
    return orch.FactcheckPresentation(
        text=text, links=tuple(links), reply_to_message_id=1,
        parse_mode=None, notice=notice)


def _ref(evidence_id, url, source_kind="secondary", support="выдержка"):
    return orch.EvidenceRef(evidence_id=evidence_id, url=url,
                            support=support, source_kind=source_kind)


def _evidence(evidence_id, url, publication_kind, source_kind="secondary"):
    """ClaimEvidence-совместимый носитель оси publication_kind (уже U1)."""
    return types.SimpleNamespace(evidence_id=evidence_id, url=url,
                                 publication_kind=publication_kind,
                                 source_kind=source_kind, role="supports",
                                 snippet_only=False)


def _claim(claim_id, *evidence):
    return types.SimpleNamespace(claim_id=claim_id, evidence=tuple(evidence))


def _verdict(*, factual="supported", text="Вывод.",
             refs=(), parts=(), claims=(), links=None,
             execution_status="complete", execution_cause="",
             reason_code=None):
    evidence = orch.EvidenceMap(refs=tuple(refs),
                                allowlist=tuple(r.evidence_id for r in refs))
    return orch.CheckedVerdict(
        verdict_text=text, route="envelope_temporal", factual_verdict=factual,
        temporal_status="current", evidence=evidence,
        reason_code=reason_code, parts=tuple(parts), claims=tuple(claims),
        execution_status=execution_status, execution_cause=execution_cause)


# ── FCT-602/603/193: technical_unverified ≠ «Недостаточно данных» ──────────

class TestTechnicalStatus:
    def test_technical_unverified_headline_is_technical_not_insufficient(self):
        v = _verdict(factual="insufficient_evidence",
                     execution_status="technical_unverified",
                     execution_cause="provider_error")
        p = fr.render_factcheck(_presentation(text="Сервис не ответил."), v)
        assert "<b>Проверка не завершена: поиск недоступен</b>" in p.text
        assert "Недостаточно данных для проверки" not in p.text
        # внутренние коды/ID не публикуются
        for token in ("provider_error", "execution_cause", "reason_code",
                      "status_detail", "ev-1"):
            assert token not in fr.visible_text(p.text)

    @pytest.mark.parametrize("cause,headline", [
        ("provider_error", "поиск недоступен"),
        ("provider_timeout", "поиск не ответил вовремя"),
        ("rate_limit", "превышен лимит запросов"),
        ("deadline_exceeded", "истёк лимит времени"),
        ("resource_limit", "исчерпан лимит проверки"),
        ("source_unreadable", "источники не удалось прочитать"),
        ("source_extract_failed", "материалы не удалось разобрать"),
        ("cancelled", "проверка отменена"),
        ("claim_unidentified", "тезис не удалось выделить"),
    ])
    def test_each_cause_has_human_headline(self, cause, headline):
        v = _verdict(factual="insufficient_evidence",
                     execution_status="technical_unverified",
                     execution_cause=cause)
        p = fr.render_factcheck(_presentation(text="Текст."), v)
        assert f"Проверка не завершена: {headline}" in p.text
        assert ft_not_insufficient(p)

    def test_unknown_cause_has_generic_human_headline(self):
        v = _verdict(factual="insufficient_evidence",
                     execution_status="technical_unverified",
                     execution_cause="")
        p = fr.render_factcheck(_presentation(text="Текст."), v)
        assert "Проверка не завершена: техническая ошибка" in p.text

    def test_headline_code_matches_technical_status(self):
        v = _verdict(execution_status="technical_unverified",
                     execution_cause="rate_limit")
        assert fr.headline_code(v) == "technical:execution:rate_limit"

    def test_complete_insufficient_keeps_content_headline(self):
        """complete + insufficient — содержательная нехватка, не техсбой."""
        v = _verdict(factual="insufficient_evidence",
                     execution_status="complete", execution_cause="")
        p = fr.render_factcheck(_presentation(text="Данных мало."), v)
        assert "<b>Недостаточно данных для проверки</b>" in p.text


def ft_not_insufficient(presentation) -> bool:
    return "Недостаточно данных для проверки" not in fr.visible_text(
        presentation.text)


# ── FCT-602: partial — подтверждённое сохраняется + оговорка ───────────────

class TestPartialStatus:
    def test_partial_keeps_confirmed_body_and_adds_cause_notice(self):
        v = _verdict(factual="supported", execution_status="partial",
                     execution_cause="rate_limit",
                     refs=(_ref("ev-1", "https://example.org/a"),))
        p = fr.render_factcheck(
            _presentation(text="Индекс вырос на 2,1%.",
                          links=("https://example.org/a",)), v)
        assert "<b>Подтверждается</b>" in p.text
        assert "Индекс вырос на 2,1%." in p.text
        assert ("Проверено частично: часть пунктов осталась без проверки "
                "(поисковый сервис ограничил частоту запросов) — это не "
                "опровержение.") in p.text
        assert "Недостаточно данных для проверки" not in p.text
        assert "rate_limit" not in fr.visible_text(p.text)

    def test_partial_keeps_confirmed_part_when_body_empty(self):
        v = _verdict(factual="supported", execution_status="partial",
                     execution_cause="provider_timeout",
                     refs=(_ref("ev-1", "https://example.org/a"),),
                     parts=({"part_id": "c1", "text": "Индекс вырос",
                             "factual_verdict": "supported",
                             "evidence_refs": ["ev-1"]},))
        p = fr.render_factcheck(_presentation(text=""), v)
        assert "По утверждениям:" in p.text
        assert "• Индекс вырос — подтверждается" in p.text
        assert "Проверено частично" in p.text

    def test_complete_supported_has_no_partial_notice(self):
        v = _verdict(factual="supported", execution_status="complete")
        p = fr.render_factcheck(_presentation(text="Всё сходится."), v)
        assert "Проверено частично" not in p.text


# ── FCT-023: подписи publication_kind ──────────────────────────────────────

class TestPublicationKindLabels:
    @pytest.mark.parametrize("url,source_kind,pub_kind,label", [
        ("https://arxiv.org/abs/2401.00001", "research", "preprint",
         "исследование, препринт"),
        ("https://www.nature.com/articles/s41586-026-00001-1", "research",
         "journal_article", "исследование, научная статья"),
        ("https://www.eurekalert.org/news-releases/123", "secondary",
         "press_release", "пересказ, пресс-релиз — не прямое доказательство"),
        ("https://example.org/story/2026/01/markets", "secondary",
         "secondary_report", "пересказ"),
        ("https://example.org/opinion/2026/what-we-think", "secondary",
         "interpretation", "пересказ, авторская интерпретация — не прямое "
                           "доказательство"),
    ])
    def test_part_cite_carries_russian_publication_label(
            self, url, source_kind, pub_kind, label):
        v = _verdict(
            factual="supported",
            refs=(_ref("ev-1", url, source_kind=source_kind),),
            claims=(_claim("c1", _evidence("ev-1", url, pub_kind,
                                           source_kind=source_kind)),),
            parts=({"part_id": "c1", "text": "Проверяемый тезис",
                    "factual_verdict": "supported",
                    "evidence_refs": ["ev-1"]},))
        p = fr.render_factcheck(_presentation(text=""), v)
        assert f"</a> — {label}" in p.text
        # без выдуманных ссылок/служебных полей
        assert pub_kind not in fr.visible_text(p.text)
        assert "ev-1" not in fr.visible_text(p.text)

    def test_sources_row_carries_publication_label(self):
        url = "https://www.prnewswire.com/news-releases/x-301.html"
        v = _verdict(
            factual="insufficient_evidence",
            refs=(_ref("ev-1", url, source_kind="secondary"),),
            claims=(_claim("c1", _evidence("ev-1", url, "press_release")),))
        p = fr.render_factcheck(
            _presentation(text="Краткий вывод.", links=(url,)), v)
        assert ("— пересказ, пресс-релиз — не прямое доказательство"
                in fr.visible_text(p.text))

    def test_non_direct_label_does_not_upgrade_direct_look(self):
        """Пресс-релиз не выглядит прямым подтверждением в подписи."""
        url = "https://www.eurekalert.org/news-releases/9"
        v = _verdict(
            factual="supported",
            refs=(_ref("ev-1", url),),
            claims=(_claim("c1", _evidence("ev-1", url, "press_release")),),
            parts=({"part_id": "c1", "text": "Заявление агентства",
                    "factual_verdict": "supported",
                    "evidence_refs": ["ev-1"]},))
        visible = fr.visible_text(fr.render_factcheck(
            _presentation(text=""), v).text)
        assert "пресс-релиз — не прямое доказательство" in visible
        assert "научная статья" not in visible


# ── FCT-702: per-part unverified_media ─────────────────────────────────────

MEDIA_PART = {"part_id": "c1", "text": "На фото расписание поездов",
              "factual_verdict": "insufficient_evidence",
              "evidence_refs": [], "unverified_media": True}
TEXT_PART = {"part_id": "c2", "text": "Поезда ходят по расписанию",
             "factual_verdict": "supported",
             "evidence_refs": ["ev-1"], "unverified_media": False}


class TestUnverifiedMediaPerPart:
    def test_notice_is_only_on_affected_part(self):
        v = _verdict(factual="mixed",
                     refs=(_ref("ev-1", "https://example.org/a"),),
                     parts=(MEDIA_PART, TEXT_PART))
        p = fr.render_factcheck(_presentation(text=""), v)
        text = fr.visible_text(p.text)
        assert text.count("изображение не проверено") == 1
        media_line = next(line for line in text.splitlines()
                          if "На фото расписание поездов" in line)
        text_line = next(line for line in text.splitlines()
                         if "Поезда ходят по расписанию" in line)
        assert "изображение не проверено" in media_line
        assert "изображение не проверено" not in text_line

    def test_body_does_not_hide_part_caveat(self):
        v = _verdict(factual="mixed",
                     refs=(_ref("ev-1", "https://example.org/a"),),
                     parts=(MEDIA_PART, TEXT_PART))
        p = fr.render_factcheck(
            _presentation(text="Текстовая часть проверена."), v)
        text = fr.visible_text(p.text)
        assert "Текстовая часть проверена." in text
        assert "На фото расписание поездов" in text
        assert text.count("изображение не проверено") == 1
        # оговорка не стала общей концовкой публикации
        assert not text.rstrip().endswith("к этому пункту)")

    def test_no_notice_when_media_verified(self):
        verified = dict(MEDIA_PART, unverified_media=False)
        v = _verdict(factual="mixed",
                     refs=(_ref("ev-1", "https://example.org/a"),),
                     parts=(verified, TEXT_PART))
        p = fr.render_factcheck(_presentation(text=""), v)
        assert "изображение не проверено" not in fr.visible_text(p.text)


# ── FCT-023 backlog B-1: /article(s)/ ≠ журнальная статья ─────────────────

class TestArticlePathBacklog:
    @pytest.mark.parametrize("url", [
        "https://apnews.com/article/markets-fall-2026",
        "https://www.bbc.com/news/articles/c1234567890o",
        "https://www.politico.com/news/2024/01/15/markets-fall",
    ])
    def test_generic_article_path_is_secondary_report(self, url):
        kind, basis = sa.classify_publication_kind(url)
        assert kind == "secondary_report"
        assert kind != "journal_article"

    @pytest.mark.parametrize("url", [
        "https://www.nature.com/articles/s41586-026-00001-1",
        "https://doi.org/10.1038/s41586-026-00001-1",
        "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    ])
    def test_real_journal_signal_stays_journal_article(self, url):
        kind, _basis = sa.classify_publication_kind(url)
        assert kind == "journal_article"

    def test_news_article_renders_as_retelling_not_science(self):
        url = "https://apnews.com/article/markets-fall-2026"
        v = _verdict(
            factual="supported",
            refs=(_ref("ev-1", url),),
            claims=(_claim("c1", _evidence("ev-1", url,
                                           "secondary_report")),),
            parts=({"part_id": "c1", "text": "Рынки упали",
                    "factual_verdict": "supported",
                    "evidence_refs": ["ev-1"]},))
        visible = fr.visible_text(fr.render_factcheck(
            _presentation(text=""), v).text)
        assert "пересказ" in visible
        assert "научная статья" not in visible


# ── Общий egress: никаких внутренних ID/кодов ──────────────────────────────

class TestNoInternalTokens:
    def test_internal_fields_never_published(self):
        v = _verdict(
            factual="insufficient_evidence",
            execution_status="technical_unverified",
            execution_cause="provider_error",
            refs=(_ref("ev-1", "https://example.org/a"),),
            parts=({"part_id": "c1", "text": "Число не сходится",
                    "factual_verdict": "insufficient_evidence",
                    "evidence_refs": ["ev-1"],
                    "status_detail": "provider_error",
                    "gap_note": "status_detail=provider_error"},))
        p = fr.render_factcheck(
            _presentation(text="Краткий итог.",
                          links=("https://example.org/a",)), v)
        visible = fr.visible_text(p.text)
        for token in ("ev-1", "status_detail", "reason_code",
                      "execution_status", "execution_cause", "provider_error"):
            assert token not in visible
        assert "Проверка не завершена: поиск недоступен" in visible

    def test_plain_parity_has_same_structure(self):
        v = _verdict(execution_status="technical_unverified",
                     execution_cause="deadline_exceeded")
        html = fr.render_factcheck(_presentation(text="Текст."), v)
        plain = fr.render_plain(_presentation(text="Текст."), v)
        assert plain.parse_mode is None
        assert "Проверка не завершена: истёк лимит времени" in plain.text
        assert "<b>" not in plain.text
        assert "Проверка не завершена: истёк лимит времени" in html.text
