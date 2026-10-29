"""RSS에서 최근 뉴스를 모으고, 이미 다룬 기사는 걸러낸다."""
import json
import time
from pathlib import Path
from urllib.parse import quote

import feedparser

SEEN_PATH = Path("data/seen.json")


def _google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"


def _load_seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
    return set()


def save_seen(links: list[str]) -> None:
    seen = list(_load_seen() | set(links))[-2000:]  # 너무 커지지 않게
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")


def fetch(cfg: dict, lookback_hours: float | None = None, skip_seen: bool = True) -> list[dict]:
    urls = [_google_news_url(q) for q in cfg.get("google_news_queries", [])]
    urls += cfg.get("extra_feeds", [])
    cutoff = time.time() - (lookback_hours or cfg.get("lookback_hours", 24)) * 3600
    seen = _load_seen() if skip_seen else set()

    articles, titles = [], set()
    for url in urls:
        feed = feedparser.parse(url)
        for e in feed.entries:
            link = e.get("link", "")
            title = e.get("title", "").strip()
            ts = e.get("published_parsed") or e.get("updated_parsed")
            if ts and time.mktime(ts) < cutoff:
                continue
            key = title[:30]
            if not title or link in seen or key in titles:
                continue
            titles.add(key)
            source = ""
            if "source" in e and hasattr(e.source, "title"):
                source = e.source.title
            elif " - " in title:
                source = title.rsplit(" - ", 1)[-1]
            articles.append({
                "title": title,
                "summary": e.get("summary", "")[:300],
                "source": source,
                "link": link,
            })
    return articles[: cfg.get("max_candidates", 30)]
