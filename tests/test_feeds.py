from morning_scout.app import select_new
from morning_scout.sources.feeds import MAX_ENTRIES_PER_FEED
from morning_scout.sources.news import parse_feed
from morning_scout.state import State

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Jobs</title>
<item><link>https://jobs.example/1</link><category>Contract staff</category>
<title>Agency - 5 programmers</title><description>Agency - 5 programmers</description></item>
<item><link>https://jobs.example/2</link>
<title>Same Title</title><description>Different text</description></item>
<item><link>https://jobs.example/3</link><title>Same Title</title></item>
</channel></rss>"""


def test_feed_entries_become_feed_items_with_category() -> None:
    items = parse_feed(RSS, "Public jobs", source="feed", limit=MAX_ENTRIES_PER_FEED)
    assert [i.url for i in items] == [f"https://jobs.example/{n}" for n in (1, 2, 3)]
    assert {i.source for i in items} == {"feed"} and {i.topic for i in items} == {"Public jobs"}
    assert items[0].snippet == "[Contract staff]"  # description repeated the title
    assert items[1].snippet == "Different text"


def test_feed_items_are_deduplicated_by_url_only() -> None:
    items = parse_feed(RSS, "Public jobs", source="feed")
    fresh, keys = select_new(items, State())
    assert len(fresh) == 3  # same title, different listing: both kept
    state = State()
    state.mark_seen(keys, __import__("datetime").date(2026, 11, 25))
    assert select_new(items, state)[0] == []
