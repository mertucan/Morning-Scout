from morning_scout.messages import system_prompt
from morning_scout.models import Item, PageChange
from morning_scout.render import email_html, email_text, ntfy_message
from morning_scout.summarizer import build_prompt, fallback_summary

ITEMS = [
    Item("news", "AI", "Model [beta] launched", "https://a.example/1", "snippet"),
    Item("search", "Python release", "Python 3.15", "https://b.example/2"),
]
CHANGES = [PageChange("Apply page", "https://c.example", "+ open")]


def test_prompt_uses_source_ids_instead_of_urls() -> None:
    prompt, sources = build_prompt(ITEMS, CHANGES)
    assert "https://" not in prompt
    assert prompt.index("AI") < prompt.index("[S1]")
    assert sources == {
        "S1": "https://a.example/1",
        "S2": "https://b.example/2",
        "S3": "https://c.example",
    }
    assert "+ open" in prompt


def test_resolve_sources_inserts_real_links_and_drops_unknown_ids() -> None:
    from morning_scout.summarizer import resolve_sources

    text = "- A [Kaynak](S1), [Kaynak]( [s2] ). B [Kaynak](S99)"
    resolved = resolve_sources(text, {"S1": "https://a.example", "S2": "https://b.example"})
    assert resolved == "- A [Kaynak](https://a.example), [Kaynak](https://b.example). B "


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


def test_email_html_has_clickable_links_and_no_raw_html() -> None:
    html = email_html(
        "### AI\n- News <script>x</script> [Src](https://a.example/?a=1&b=2)", "T", "tr"
    )
    assert 'href="https://a.example/?a=1&amp;b=2"' in html
    assert "<script>" not in html


def test_email_text_expands_links() -> None:
    assert email_text("- [Src](https://a.example)") == "- Src (https://a.example)\n"


class _ApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"error {code}")
        self.code = code


def test_retries_transient_errors_then_succeeds() -> None:
    from morning_scout.summarizer import with_retries

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
    import pytest

    from morning_scout.summarizer import with_retries

    waits: list[float] = []

    def call() -> str:
        raise _ApiError(403)

    with pytest.raises(_ApiError):
        with_retries(call, delays=(1, 2), sleep=waits.append)
    assert waits == []


def test_gives_up_after_last_delay() -> None:
    import pytest

    from morning_scout.summarizer import with_retries

    waits: list[float] = []

    def call() -> str:
        raise _ApiError(503)

    with pytest.raises(_ApiError):
        with_retries(call, delays=(1, 2), sleep=waits.append)
    assert waits == [1, 2]


def test_falls_back_to_second_model(monkeypatch) -> None:
    from google import genai

    from morning_scout import summarizer

    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, contents: str, config: object):
            calls.append(model)
            if model == "busy-model":
                raise _ApiError(503)
            return type("Response", (), {"text": "### Özet [Kaynak](S1)"})()

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(summarizer, "RETRY_DELAYS", ())

    text = summarizer.summarize_with_gemini(
        ITEMS, [], api_key="k", models=["busy-model", "spare-model"], language="tr"
    )
    assert text == "### Özet [Kaynak](https://a.example/1)"
    assert calls == ["busy-model", "spare-model"]


def test_ntfy_message_drops_citations_and_keeps_titles() -> None:
    summary = (
        "### AI\n"
        "- Model launched [Kaynak](https://a.example/1), [Kaynak](https://b.example/2).\n"
        "- [Raw headline](https://c.example/3)"
    )
    assert ntfy_message(summary, "tr") == "### AI\n- Model launched.\n- Raw headline"
