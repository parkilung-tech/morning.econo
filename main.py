"""
사용법
  python main.py build     # 뉴스 수집 → 원고 작성 → 카드 이미지 생성 (게시 X)
  python main.py publish   # build로 만든 오늘 게시물을 인스타에 올림
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


def sample():
    script = json.loads(Path("sample_script.json").read_text(encoding="utf-8"))
    script["date"] = datetime.now(KST).strftime("%Y.%m.%d")
    paths = render.render_all(CFG, script, Path("output/sample"))
    print(f"샘플 카드 {len(paths)}장 → output/sample")


if __name__ == "__main__":
    {"build": build, "publish": publish, "sample": sample}[sys.argv[1] if len(sys.argv) > 1 else "build"]()
