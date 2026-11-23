from morning_scout.sources.search import build_request, parse_results


def test_request_restricts_domains_only_when_sites_are_given() -> None:
    assert "include_domains" not in build_request("q", "day")
    body = build_request("q", "week", ("x.com", "instagram.com"))
    assert body["include_domains"] == ["x.com", "instagram.com"]
    assert body["time_range"] == "week"
    assert body["search_depth"] == "basic"


def test_parse_results_uses_given_topic() -> None:
    payload = {"results": [{"url": "https://x.com/a/status/1", "title": "Post", "content": "a  b"}]}
    (item,) = parse_results(payload, topic="Jobs")
    assert item.topic == "Jobs" and item.snippet == "a b"
