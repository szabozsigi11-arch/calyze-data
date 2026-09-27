"""Hivatalos közlemények címkeként (pipeline/news/official.py)."""

from datetime import date

from pipeline.news import official as news

FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Federal Reserve issues FOMC statement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm</link>
<pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
<item><title>Older release</title><link>https://www.federalreserve.gov/old.htm</link>
<pubDate>Mon, 12 Oct 2026 18:00:00 GMT</pubDate></item>
<item><title>Phishing</title><link>https://evil.example/fomc</link>
<pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
<item><title>Plain http</title><link>http://www.federalreserve.gov/x.htm</link>
<pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
</channel></rss>"""


class Resp:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.content = ("\ufeff" + text).encode()


def test_esemeny_vagy_sokk_nelkul_nem_ker_le_semmit():
    called = []
    out = news.official_news(date(2026, 10, 21), [], fetch=lambda u: called.append(u))
    assert out == {"status": "no_trigger"}
    assert called == []


def test_esemeny_napjan_csak_a_kiado_sajat_linkje_es_az_ablak():
    def fetch(url: str) -> Resp:
        return Resp(200, FEED) if "federalreserve" in url else Resp(503)

    out = news.official_news(date(2026, 10, 28), [], fetch=fetch)
    assert out["triggers"] == ["event:fomc-2026-10-28"]
    assert [i["title"] for i in out["items"]] == ["Federal Reserve issues FOMC statement"]
    assert out["failed_sources"] == ["European Central Bank"]


def test_sokk_is_indok():
    assert news.triggers(date(2026, 10, 21), ["vix"]) == ["shock:vix"]


def test_entitast_hozo_csatornat_nem_ertelmez():
    evil = (
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel><item>&a;</item></channel></rss>'
    )
    assert news.parse_feed(evil, "Federal Reserve", "www.federalreserve.gov") == []
