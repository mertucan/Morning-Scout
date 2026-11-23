import pytest

from morning_scout.messages import system_prompt
from morning_scout.models import Item, PageChange
from morning_scout.render import email_html, email_text, ntfy_message
from morning_scout.summarizer import (
    Source,
    build_prompt,
    fallback_summary,
    parse_digest,
    render_digest,
    with_retries,
)

ITEMS = [
    Item("news", "AI", "Model [beta] launched", "https://a.example/1", "snippet"),
    Item("search", "Python release", "Python 3.15", "https://b.example/2"),
]
CHANGES = [PageChange("Apply page", "https://c.example", "+ open")]

SOURCES = {
    "S1": Source("First article - Publisher", "https://a.example/1"),
    "S2": Source("Second article", "https://b.example/2"),
    "S3": Source("Third article", "https://c.example/3"),
}


def test_prompt_uses_source_ids_instead_of_urls() -> None:
    prompt, sources = build_prompt(ITEMS, CHANGES)
    assert "https://" not in prompt
    assert prompt.index("AI") < prompt.index("[S1]")
    assert {key: source.url for key, source in sources.items()} == {
        "S1": "https://a.example/1",
        "S2": "https://b.example/2",
        "S3": "https://c.example",
    }
    assert sources["S1"].title == "Model [beta] launched"
    assert "+ open" in prompt


def test_render_digest_numbers_citations_per_topic_with_source_list() -> None:
    sections = [
        {
            "topic": "KPSS",
            "bullets": [
                {"text": "Point  one.", "sources": ["S2", "S1"]},
                {"text": "Point two.", "sources": ["[s1]", "S99"]},
            ],
        },
        {"topic": "AI", "bullets": [{"text": "Point three.", "sources": ["S3"]}]},
        {"topic": "Empty", "bullets": []},
    ]

    text = render_digest(sections, SOURCES, "tr")

    assert text == (
        "### KPSS\n\n"
        "- Point one. [[1]](https://b.example/2) [[2]](https://a.example/1)\n"
        "- Point two. [[2]](https://a.example/1)\n\n"
        "**Kaynaklar**\n\n"
        "1. [Second article](https://b.example/2)\n"
        "2. [First article - Publisher](https://a.example/1)\n\n"
        "### AI\n\n"
        "- Point three. [[1]](https://c.example/3)\n\n"
        "**Kaynaklar**\n\n"
        "1. [Third article](https://c.example/3)"
    )


def test_render_digest_keeps_bullets_without_valid_sources() -> None:
    sections = [{"topic": "Q", "bullets": [{"text": "No clear evidence.", "sources": ["S9"]}]}]
    assert render_digest(sections, SOURCES, "tr") == "### Q\n\n- No clear evidence."


def test_parse_digest_rejects_unexpected_shapes() -> None:
    assert parse_digest('{"sections": [{"topic": "A", "bullets": [{"text": "x"}]}]}')
    for raw in ["not json", "[]", '{"other": 1}']:
        with pytest.raises(ValueError):
            parse_digest(raw)


def test_system_prompt_forbids_invention_and_localises() -> None:
    tr = system_prompt("tr")
    assert "uydurma" in tr and "kanıt" in tr
    assert "Write in English" in system_prompt("en")
    assert "'de'" in system_prompt("de")


def test_fallback_lists_titles_and_links() -> None:
    text = fallback_summary(ITEMS, CHANGES, "tr")
    assert "[Model (beta) launched](https://a.example/1)" in text
    assert "### Python release" in text
    assert "[Apply page](https://c.example)" in text


def test_ntfy_message_short_is_unchanged() -> None:
    assert ntfy_message("hello", "tr") == "hello"


def test_ntfy_message_is_truncated_on_line_boundary() -> None:
    long = "\n".join(f"- madde {i} çok önemli bir gelişme" for i in range(500))
    message = ntfy_message(long, "tr", max_bytes=500)
    assert len(message.encode("utf-8")) <= 500
    assert message.endswith("devamı e-postada.")


def test_ntfy_message_drops_citations_and_source_lists() -> None:
    summary = (
        "### AI\n\n"
        "- Model launched. [[1]](https://a.example/1) [[2]](https://b.example/2)\n\n"
        "**Kaynaklar**\n\n"
        "1. [First](https://a.example/1)\n"
        "2. [Second](https://b.example/2)\n\n"
        "### Raw\n\n"
        "- [Raw headline](https://c.example/3)"
    )
    expected = "### AI\n\n- Model launched.\n\n### Raw\n\n- Raw headline"
    assert ntfy_message(summary, "tr") == expected


def test_email_html_has_clickable_links_and_no_raw_html() -> None:
    html = email_html(
        "### AI\n- News <script>x</script> [Src](https://a.example/?a=1&b=2)", "T", "tr"
    )
    assert 'href="https://a.example/?a=1&amp;b=2"' in html
    assert "<script>" not in html


def test_email_html_superscripts_citations_and_styles_sources() -> None:
    summary = (
        "### AI\n\n- Point. [[1]](https://a.example)\n\n**Kaynaklar**\n\n1. [A](https://a.example)"
    )
    html = email_html(summary, "T", "tr")
    assert '<sup style="font-size:11px;"><a style="color:#2563eb;" target="_blank" ' in html
    assert ">[1]</a></sup>" in html
    assert '<ol style="font-size:13px;color:#57534e;margin-top:0;">' in html


def test_email_text_expands_links() -> None:
    assert email_text("- [Src](https://a.example)") == "- Src (https://a.example)\n"


class _ApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"error {code}")
        self.code = code


def test_retries_transient_errors_then_succeeds() -> None:
    outcomes = [_ApiError(503), _ApiError(429), "ok"]
    waits: list[float] = []

    def call() -> str:
        result = outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    assert with_retries(call, delays=(1, 2, 3), sleep=waits.append) == "ok"
    assert waits == [1, 2]


def test_does_not_retry_permanent_errors() -> None:
    waits: list[float] = []

    def call() -> str:
        raise _ApiError(403)

    with pytest.raises(_ApiError):
        with_retries(call, delays=(1, 2), sleep=waits.append)
    assert waits == []


def test_gives_up_after_last_delay() -> None:
    waits: list[float] = []

    def call() -> str:
        raise _ApiError(503)

    with pytest.raises(_ApiError):
        with_retries(call, delays=(1, 2), sleep=waits.append)
    assert waits == [1, 2]


def test_falls_back_to_second_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    from morning_scout import summarizer

    calls: list[str] = []
    answer = '{"sections": [{"topic": "AI", "bullets": [{"text": "Özet.", "sources": ["S1"]}]}]}'

    class FakeModels:
        def generate_content(self, *, model: str, contents: str, config: object) -> object:
            calls.append(model)
            if model == "busy-model":
                raise _ApiError(503)
            return type("Response", (), {"text": answer})()

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(summarizer, "RETRY_DELAYS", ())

    text = summarizer.summarize_with_gemini(
        ITEMS, [], api_key="k", models=["busy-model", "spare-model"], language="tr"
    )
    assert text.startswith("### AI\n\n- Özet. [[1]](https://a.example/1)")
    assert calls == ["busy-model", "spare-model"]


def test_invalid_json_counts_as_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    from morning_scout import summarizer

    class FakeModels:
        def generate_content(self, **_kwargs: object) -> object:
            return type("Response", (), {"text": "### Not JSON"})()

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    with pytest.raises(summarizer.SummaryError):
        summarizer.summarize_with_gemini(ITEMS, [], api_key="k", models=["m"], language="tr")


def test_prompt_shows_focus_for_topics_and_pages() -> None:
    changes = [PageChange("Job board", "https://c.example", "+ new", focus="only IT jobs")]
    prompt, _ = build_prompt(ITEMS, changes, {"AI": "only open models"})
    assert "## Konu / Topic: AI\nOdak (yalnızca bu konu)" in prompt
    assert "Focus (this topic only): only open models" in prompt
    assert "Focus (this page only): only IT jobs" in prompt
    assert prompt.count("Odak (") == 2  # "Python release" has no focus


def test_long_source_titles_are_shortened_at_a_word() -> None:
    from morning_scout.summarizer import shorten

    assert shorten("short title") == "short title"
    caption = "Kamu Alım on Instagram: " + "çok uzun bir gönderi metni " * 10
    result = shorten(caption, limit=40)
    assert len(result) <= 41 and result.endswith("…") and not result.endswith(" …")


def test_select_topics_keeps_matching_sections_ignoring_case_and_accents() -> None:
    from morning_scout.render import select_topics

    digest = "Note\n\n### THY\n\n- a\n\n### Önlisans İlanları\n\n- b\n\n**Kaynaklar**\n\n1. x"
    assert select_topics(digest, ["önlisans  ilanları"]) == (
        "Note\n\n### Önlisans İlanları\n\n- b\n\n**Kaynaklar**\n\n1. x"
    )
    assert select_topics(digest, ["Missing"]) is None


def test_prompt_starts_with_todays_date_for_deadlines() -> None:
    from datetime import date

    prompt, _ = build_prompt(ITEMS, [], today=date(2026, 11, 24))
    assert prompt.startswith("Bugünün tarihi / Today's date: 24.11.2026")
    assert "Today's date" not in build_prompt(ITEMS, [])[0]
    assert "yarın" in system_prompt("tr") and "tomorrow" in system_prompt("en")
