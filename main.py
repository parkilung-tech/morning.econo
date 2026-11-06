"""
사용법
  python main.py build     # 뉴스 수집 → 원고 작성 → 카드 이미지 생성 (게시 X)
  python main.py publish   # build로 만든 오늘 게시물을 인스타에 올림
  python main.py reel-build    # 오늘 카드로 릴스 영상(reel.mp4) 만들기
  python main.py reel-publish  # 저장소에 올라간 reel.mp4를 릴스로 게시
  python main.py evening-build    # 저녁: 오늘 가장 큰 이슈 1개를 한 장으로 (evening.jpg)
  python main.py evening-publish  # 저녁 한 장을 오후 6시에 게시
  python main.py threads          # 아침 카드뉴스를 스레드 요약 글로 게시
  python main.py threads-preview  # 스레드 글만 만들어 보기 (게시 X)
  python main.py sample    # API 키 없이 샘플 원고로 카드만 만들어보기
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml

from src import render

KST = timezone(timedelta(hours=9))
CFG = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")
OUT = Path("output") / TODAY


def is_recap_day() -> bool:
    day = CFG.get("weekly_recap_day") or ""
    return bool(day) and "월화수목금토일"[datetime.now(KST).weekday()] == day


def this_week_items() -> list[dict]:
    """이번 주 월요일~어제 게시한 뉴스 목록 (토요일이면 월~금 5일치, 총정리 재료)."""
    now = datetime.now(KST).date()
    items = []
    for i in range(now.weekday(), 0, -1):
        day = now - timedelta(days=i)
        path = Path("output") / day.isoformat() / "post.json"
        if not path.exists():
            continue
        post = json.loads(path.read_text(encoding="utf-8"))
        if not post.get("published_id"):
            continue
        for it in post.get("items", []):
            items.append({**it, "day": f"{day:%m/%d}"})
    return items


def recent_issues() -> list[str]:
    """어제 저녁 이슈 제목 (오늘 아침에 같은 뉴스를 또 고르지 않게)."""
    yday = datetime.now(KST).date() - timedelta(days=1)
    path = Path("output") / yday.isoformat() / "evening.json"
    if not path.exists():
        return []
    ev = json.loads(path.read_text(encoding="utf-8"))
    return [f"{ev.get('title', '')} — {ev.get('one_line', '')}".strip(" —")] if ev.get("title") else []


def evening_as_reel() -> bool:
    return CFG.get("evening_format", "reel") == "reel"


def build():
    from src import fetch_news, summarize

    # 이미 오늘 게시했으면 다시 만들지 않음 (다시 실행해도 중복 게시 방지)
    existing = OUT / "post.json"
    if existing.exists() and json.loads(existing.read_text(encoding="utf-8")).get("published_id"):
        print("오늘 카드뉴스는 이미 게시됨, 새로 만들지 않음")
        return

    articles = fetch_news.fetch(CFG)
    print(f"후보 기사 {len(articles)}건")
    week_items = this_week_items() if is_recap_day() else []
    if week_items:
        print(f"이번 주 총정리: 이번 주 뉴스 {len(week_items)}건 + 오늘 기사")
    script = summarize.write_script(CFG, articles, week_items, recent_issues())
    paths = render.render_all(CFG, script, OUT)
    script["caption_full"] = summarize.build_caption(script)
    script["images"] = [p.name for p in paths]
    (OUT / "post.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    fetch_news.save_seen([a["link"] for a in articles])
    print(f"카드 {len(paths)}장 생성 → {OUT}")


def publish():
    from src.publish import Instagram

    post = json.loads((OUT / "post.json").read_text(encoding="utf-8"))
    force = os.environ.get("FORCE_REPUBLISH") == "1"  # 수정본 다시 올리기 (기존 게시물은 앱에서 직접 삭제)
    if post.get("published_id") and not force:
        print("이미 게시됨, 건너뜀")
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    base = CFG["image_base_url"].format(repo=repo).rstrip("/")
    urls = [f"{base}/{TODAY}/{name}" for name in post["images"]]
    # 이미지 주소가 실제로 열리는지 확인 (푸시 직후 반영 지연 대비)
    for _ in range(12):
        if all(requests.head(u, timeout=15).status_code == 200 for u in urls):
            break
        time.sleep(10)
    else:
        raise RuntimeError(f"이미지 주소 접근 불가: {urls[0]}")

    ig = Instagram(CFG["graph_api_version"])
    media_id = ig.publish_carousel(urls, post["caption_full"])
    post["published_id"] = media_id
    (OUT / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"게시 완료: {media_id}")


def _video_url(name: str) -> str:
    """jsDelivr는 GitHub 공개 저장소 파일을 video/mp4 형식으로 내보내줌.
    커밋 번호(REEL_SHA)를 주소에 넣어 캐시된 옛 파일이 나가지 않게 함."""
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ.get("REEL_SHA", "main")
    return f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/output/{TODAY}/{name}"


def _wait_url(url: str) -> str:
    """푸시 직후 반영 지연 대비: 주소가 열릴 때까지 최대 2분 기다림."""
    for _ in range(12):
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            print(f"주소 확인: {url} ({r.headers.get('content-type')})")
            return url
        time.sleep(10)
    raise RuntimeError(f"주소 접근 불가: {url}")


def _reel_todo():
    """릴스를 올려야 하면 post를, 아니면 None을 돌려줌."""
    if not CFG.get("reel_enabled", True):
        print("릴스 꺼져 있음 (config.yaml reel_enabled)")
        return None
    path = OUT / "post.json"
    if not path.exists():
        print("::warning::오늘 카드뉴스가 없음, 릴스 건너뜀")
        return None
    post = json.loads(path.read_text(encoding="utf-8"))
    if not post.get("published_id"):
        print("::warning::오늘 카드뉴스가 게시 기록이 없음, 릴스 건너뜀 (아침 게시 로그 확인)")
        return None
    if post.get("reel_id"):
        print("릴스 이미 게시됨, 건너뜀")
        return None
    return post


def reel_build():
    """오늘 카드 이미지로 릴스 영상(output/날짜/reel.mp4) 생성."""
    post = _reel_todo()
    if not post:
        return
    from src.reel import make_reel

    images = [OUT / name for name in post["images"]]
    # 첫 장면 색을 카드와 똑같이 맞추려고, 카드를 만든 날짜로 요일 색을 고름
    day = datetime.strptime(OUT.name, "%Y-%m-%d").date()  # output/날짜 폴더 = 카드 만든 날
    if not post.get("reel_beats"):
        _pick_fresh_reel_beats(post, day)
    if _reel_v2(post, lambda rs: rs.news_from_item(post["items"][0]), OUT / "reel.mp4", day):
        (OUT / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    make_reel(CFG, images, OUT / "reel.mp4", day, post)


def _beats_text(beats) -> str:
    import re
    parts = []
    for b in beats or []:
        parts += [str(b.get(k, "")) for k in ("big", "number")]
    return re.sub(r"\s+", "", " ".join(parts))


def _recent_reel_beats(day, days: int = 7) -> list[list[dict]]:
    """최근 며칠간 실제로 만든 릴스(점심·저녁) 대본들."""
    out = []
    for i in range(1, days + 1):
        folder = Path("output") / (day - timedelta(days=i)).isoformat()
        for name in ("post.json", "evening.json"):
            f = folder / name
            if f.exists():
                beats = json.loads(f.read_text(encoding="utf-8")).get("reel_beats")
                if beats:
                    out.append(beats)
    return out


def _is_repeat(beats, recent) -> bool:
    """첫 컷(제목·숫자)이 같거나 대본 글자가 절반 이상 겹치면 '같은 릴스'로 봄."""
    def key(b):
        first = (b or [{}])[0]
        return (str(first.get("big", "")).replace("\n", "").replace(" ", ""), str(first.get("number", "")))
    def bigrams(t):
        return {t[i:i + 2] for i in range(len(t) - 1)}
    a = bigrams(_beats_text(beats))
    for old in recent:
        if key(beats)[0] and key(beats) == key(old):
            return True
        b = bigrams(_beats_text(old))
        if a and b and len(a & b) / min(len(a), len(b)) >= 0.5:
            return True
    return False


def _pick_fresh_reel_beats(post: dict, day) -> None:
    """점심 릴스 소재가 최근 릴스와 겹치면 다음 뉴스로 바꿔 대본을 만듦 (총정리 날 재탕 방지)."""
    if CFG.get("reel_style", "v2") != "v2" or not post.get("items"):
        return
    from src import reel_script as rs
    from src.dayoff import is_day_off
    recent = _recent_reel_beats(day)
    for idx, item in enumerate(post["items"][:3]):
        try:
            beats = rs.write_beats(CFG, rs.news_from_item(item), day, is_day_off(day, CFG))
        except Exception as e:
            print(f"::warning::릴스 대본 실패({idx + 1}번 뉴스): {e}")
            return
        if not _is_repeat(beats, recent):
            post["reel_beats"], post["reel_item"] = beats, idx
            if idx:
                print(f"최근 릴스와 겹쳐서 {idx + 1}번 뉴스로 릴스를 만듦: {item.get('headline')}")
            return
        print(f"[중복] {idx + 1}번 뉴스는 최근 릴스와 같음 → 다음 뉴스로")
    print("::warning::상위 3개 뉴스가 모두 최근 릴스와 겹쳐 1번 뉴스로 만듦")


def _reel_v2(post: dict, news, out: Path, day) -> bool:
    """뉴스 1개 큰 글씨 릴스(v2). 실패하면 False → 예전 방식으로 대신 만듦."""
    if CFG.get("reel_style", "v2") != "v2":
        return False
    from src import reel_script as rs
    from src.dayoff import is_day_off
    from src.reel_v2 import make_reel_v2
    try:
        if not post.get("reel_beats"):  # 다시 실행해도 같은 대본 사용 (API 재호출 X)
            post["reel_beats"] = rs.write_beats(CFG, news(rs), day, is_day_off(day, CFG))
        print("릴스 대본:", json.dumps(post["reel_beats"], ensure_ascii=False))
        make_reel_v2(CFG, post["reel_beats"], out, day)
        return True
    except Exception as e:  # 대본·영상 실패해도 게시는 되게
        print(f"::warning::릴스 v2 실패, 예전 방식으로 만듦: {e}")
        return False


def reel_publish():
    """저장소에 올라간 reel.mp4를 공개 주소로 넘겨 릴스 게시."""
    post = _reel_todo()
    if not post:
        return
    if not (OUT / "reel.mp4").exists():
        raise RuntimeError("reel.mp4가 없음 (reel-build 먼저 실행)")
    from src.publish import Instagram

    url = _wait_url(_video_url("reel.mp4"))

    ig = Instagram(CFG["graph_api_version"])
    from src.summarize import build_reel_caption
    reel_id = ig.publish_reel(url, build_reel_caption(post), CFG.get("reel_share_to_feed", False))
    post["reel_id"] = reel_id
    (OUT / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"릴스 게시 완료: {reel_id}")


def evening_build():
    """오늘 가장 이슈가 된 뉴스 1개 → output/날짜/evening.jpg + evening.json."""
    if not CFG.get("evening_enabled", True):
        print("저녁 게시 꺼져 있음 (config.yaml evening_enabled)")
        return
    path = OUT / "evening.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("published_id"):
        print("오늘 저녁 게시물은 이미 게시됨")
        return
    from src import evening, fetch_news

    # 아침에 이미 본 기사도 다시 봐야 '오늘 가장 큰 이슈'를 고를 수 있어서 seen 필터는 끔
    articles = fetch_news.fetch({**CFG, "max_candidates": 40}, lookback_hours=14, skip_seen=False)
    print(f"저녁 후보 기사 {len(articles)}건")
    morning = OUT / "post.json"
    items = json.loads(morning.read_text(encoding="utf-8")).get("items", []) if morning.exists() else []
    post = evening.write(CFG, articles, items)
    OUT.mkdir(parents=True, exist_ok=True)
    photo_path = None
    if CFG.get("evening_photo", True):
        from src import photo
        info = photo.find(post.get("photo_queries", []), OUT / "evening_photo.jpg")
        if info:
            post["photo"], photo_path = info, OUT / "evening_photo.jpg"
    evening.render(CFG, post, OUT / "evening.jpg", photo_path)
    post["caption_full"] = evening.caption(post)
    if evening_as_reel():  # 피드는 아침 카드뉴스 하루 1개만 → 저녁은 릴스로
        from src.reel import make_evening_reel
        day = datetime.now(KST).date()
        if not _reel_v2(post, lambda rs: rs.news_from_evening(post), OUT / "evening.mp4", day):
            make_evening_reel(CFG, OUT / "evening.jpg", post, evening.theme(CFG), OUT / "evening.mp4", day)
        post["format"] = "reel"
    path.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저녁 이슈: {post['title']} → {OUT / 'evening.jpg'}")


def evening_publish():
    path = OUT / "evening.json"
    if not path.exists():
        print("오늘 저녁 게시물이 없음, 건너뜀")
        return
    post = json.loads(path.read_text(encoding="utf-8"))
    if post.get("published_id"):
        print("이미 게시됨, 건너뜀")
        return
    # 예약 실행이 조금 일찍 시작돼도 정확히 오후 6시에 올라가게 기다림 (최대 30분)
    target = datetime.now(KST).replace(hour=CFG.get("evening_hour", 18), minute=0, second=0, microsecond=0)
    wait = (target - datetime.now(KST)).total_seconds()
    if 0 < wait <= 1800:
        print(f"오후 {target:%H:%M}까지 {wait / 60:.0f}분 대기")
        time.sleep(wait)

    from src.publish import Instagram
    ig = Instagram(CFG["graph_api_version"])
    if post.get("format") == "reel" and (OUT / "evening.mp4").exists():
        url = _wait_url(_video_url("evening.mp4"))
        post["published_id"] = ig.publish_reel(url, post["caption_full"], share_to_feed=False)
    else:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        base = CFG["image_base_url"].format(repo=repo).rstrip("/")
        url = _wait_url(f"{base}/{TODAY}/evening.jpg")
        post["published_id"] = ig.publish_image(url, post["caption_full"])
    path.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저녁 게시 완료: {post['published_id']}")


def threads(dry_run: bool = False):
    """아침 카드뉴스를 스레드용 요약 글로 바꿔 게시 (인스타 게시가 끝난 뒤 실행)."""
    if not CFG.get("threads_enabled", True):
        print("스레드 게시 꺼져 있음 (config.yaml threads_enabled)")
        return
    path = OUT / "post.json"
    if not path.exists():
        print("::warning::오늘 카드뉴스가 없음, 스레드 건너뜀")
        return
    post = json.loads(path.read_text(encoding="utf-8"))
    if post.get("threads_id") and not dry_run:
        print("스레드 이미 게시됨, 건너뜀")
        return
    from src import threads as th

    text = th.compose(CFG, post)
    print(f"----- 스레드 글 ({len(text)}자) -----\n{text}\n-----")
    if dry_run:
        return
    if not os.environ.get("THREADS_ACCESS_TOKEN"):
        print("::warning::THREADS_ACCESS_TOKEN Secret이 없어 스레드 게시 건너뜀 (README 6단계)")
        return
    urls = None
    if CFG.get("threads_attach_cards", False):
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        base = CFG["image_base_url"].format(repo=repo).rstrip("/")
        urls = [f"{base}/{TODAY}/{name}" for name in post["images"]]
    post["threads_id"] = th.Threads().publish(text, urls)
    post["threads_text"] = text
    path.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"스레드 게시 완료: {post['threads_id']}")


def sample():
    script = json.loads(Path("sample_script.json").read_text(encoding="utf-8"))
    script["date"] = datetime.now(KST).strftime("%Y.%m.%d")
    paths = render.render_all(CFG, script, Path("output/sample"))
    print(f"샘플 카드 {len(paths)}장 → output/sample")


if __name__ == "__main__":
    {"build": build, "publish": publish, "reel-build": reel_build,
     "reel-publish": reel_publish, "evening-build": evening_build,
     "evening-publish": evening_publish, "threads": threads,
     "threads-preview": lambda: threads(dry_run=True), "sample": sample}[sys.argv[1] if len(sys.argv) > 1 else "build"]()
