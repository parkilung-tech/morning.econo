"""
사용법
  python main.py build     # 뉴스 수집 → 원고 작성 → 카드 이미지 생성 (게시 X)
  python main.py publish   # build로 만든 오늘 게시물을 인스타에 올림
  python main.py reel-build    # 오늘 카드로 릴스 영상(reel.mp4) 만들기
  python main.py reel-publish  # 저장소에 올라간 reel.mp4를 릴스로 게시
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


def build():
    from src import fetch_news, summarize

    # 이미 오늘 게시했으면 다시 만들지 않음 (다시 실행해도 중복 게시 방지)
    existing = OUT / "post.json"
    if existing.exists() and json.loads(existing.read_text(encoding="utf-8")).get("published_id"):
        print("오늘 카드뉴스는 이미 게시됨, 새로 만들지 않음")
        return

    articles = fetch_news.fetch(CFG)
    print(f"후보 기사 {len(articles)}건")
    script = summarize.write_script(CFG, articles)
    paths = render.render_all(CFG, script, OUT)
    script["caption_full"] = summarize.build_caption(script)
    script["images"] = [p.name for p in paths]
    (OUT / "post.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    fetch_news.save_seen([a["link"] for a in articles])
    print(f"카드 {len(paths)}장 생성 → {OUT}")


def publish():
    from src.publish import Instagram

    post = json.loads((OUT / "post.json").read_text(encoding="utf-8"))
    if post.get("published_id"):
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


def _reel_todo():
    """릴스를 올려야 하면 post를, 아니면 None을 돌려줌."""
    if not CFG.get("reel_enabled", True):
        print("릴스 꺼져 있음 (config.yaml reel_enabled)")
        return None
    post = json.loads((OUT / "post.json").read_text(encoding="utf-8"))
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
    make_reel(CFG, images, OUT / "reel.mp4", datetime.now(KST).date())


def reel_publish():
    """저장소에 올라간 reel.mp4를 공개 주소로 넘겨 릴스 게시."""
    post = _reel_todo()
    if not post:
        return
    if not (OUT / "reel.mp4").exists():
        raise RuntimeError("reel.mp4가 없음 (reel-build 먼저 실행)")
    from src.publish import Instagram

    # jsDelivr는 GitHub 공개 저장소 파일을 video/mp4 형식으로 내보내줌.
    # 커밋 번호(REEL_SHA)를 주소에 넣어 캐시된 옛 파일이 나가지 않게 함.
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ.get("REEL_SHA", "main")
    url = f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/output/{TODAY}/reel.mp4"
    for _ in range(12):
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            break
        time.sleep(10)
    else:
        raise RuntimeError(f"영상 주소 접근 불가: {url}")
    print(f"영상 주소: {url} ({r.headers.get('content-type')})")

    ig = Instagram(CFG["graph_api_version"])
    reel_id = ig.publish_reel(url, post["caption_full"], CFG.get("reel_share_to_feed", False))
    post["reel_id"] = reel_id
    (OUT / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"릴스 게시 완료: {reel_id}")


def sample():
    script = json.loads(Path("sample_script.json").read_text(encoding="utf-8"))
    script["date"] = datetime.now(KST).strftime("%Y.%m.%d")
    paths = render.render_all(CFG, script, Path("output/sample"))
    print(f"샘플 카드 {len(paths)}장 → output/sample")


if __name__ == "__main__":
    {"build": build, "publish": publish, "reel-build": reel_build,
     "reel-publish": reel_publish, "sample": sample}[sys.argv[1] if len(sys.argv) > 1 else "build"]()
