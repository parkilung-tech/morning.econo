"""Pexels(무료·상업적 사용 가능)에서 뉴스 주제에 맞는 사진을 찾아 내려받기.

- PEXELS_API_KEY 환경변수가 없거나 검색이 실패하면 None을 돌려주고, 카드는 사진 없이 만들어져요.
- 최근에 쓴 사진은 다시 안 쓰도록 data/photos_used.json에 기록해요.
"""
import json
import os
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

USED_PATH = Path("data/photos_used.json")
API = "https://api.pexels.com/v1/search"


def _load_used() -> list:
    try:
        return json.loads(USED_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save_used(pid) -> None:
    used = (_load_used() + [pid])[-300:]
    USED_PATH.parent.mkdir(parents=True, exist_ok=True)
    USED_PATH.write_text(json.dumps(used), encoding="utf-8")


def find(queries: list[str], out: Path) -> dict | None:
    """검색어를 차례로 시도해 가로 사진 1장을 out에 저장. 사진 정보(작가·주소) 반환."""
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        print("PEXELS_API_KEY 없음 → 사진 없이 만듦")
        return None
    used = set(_load_used())
    for q in [q for q in queries if q]:
        try:
            r = requests.get(API, headers={"Authorization": key}, timeout=20,
                             params={"query": q, "orientation": "landscape", "per_page": 20, "size": "large"})
            r.raise_for_status()
            photos = [p for p in r.json().get("photos", []) if p["id"] not in used]
        except Exception as e:  # noqa: BLE001
            print(f"사진 검색 실패({q}): {e}")
            continue
        if not photos:
            print(f"사진 없음: {q}")
            continue
        p = photos[0]
        try:
            img = requests.get(p["src"]["large2x"], timeout=30)
            img.raise_for_status()
            Image.open(BytesIO(img.content)).convert("RGB").save(out, "JPEG", quality=92)
        except Exception as e:  # noqa: BLE001
            print(f"사진 내려받기 실패: {e}")
            continue
        _save_used(p["id"])
        print(f"사진: '{q}' → {p['url']} (by {p['photographer']})")
        return {"file": out.name, "query": q, "photographer": p["photographer"], "url": p["url"], "id": p["id"]}
    return None
