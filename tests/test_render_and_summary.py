from morning_scout.messages import system_prompt
from morning_scout.models import Item, PageChange
from morning_scout.render import email_html, email_text, ntfy_message
from morning_scout.summarizer import build_prompt, fallback_summary

ITEMS = [
    Item("news", "AI", "Model [beta] launched", "https://a.example/1", "snippet"),
    Item("search", "Python release", "Python 3.15", "https://b.example/2"),
]
CHANGES = [PageChange("Apply page", "https://c.example", "+ open")]


def test_prompt_contains_sources_grouped_by_topic() -> None:
    prompt = build_prompt(ITEMS, CHANGES)
    assert prompt.index("AI") < prompt.index("https://a.example/1")
    assert "https://c.example" in prompt and "+ open" in prompt


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
