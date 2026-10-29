"""무료 실사 사진(상업적 사용 가능)에서 뉴스 주제에 맞는 사진을 찾아 내려받기.

- Pixabay(PIXABAY_API_KEY) → Pexels(PEXELS_API_KEY) 순서로, 키가 있는 곳만 사용해요.
- 키가 없거나 검색이 실패하면 None을 돌려주고, 카드는 사진 없이 만들어져요.
- Pixabay 규칙상 사진 주소를 그대로 쓰지 않고 내려받아서 카드 안에 합쳐 써요.
- 최근에 쓴 사진은 다시 안 쓰도록 data/photos_used.json에 기록해요.
"""
import json
import os
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

USED_PATH = Path("data/photos_used.json")


def _load_used() -> list:
    try:
        return json.loads(USED_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save_used(pid: str) -> None:
    used = (_load_used() + [pid])[-300:]
    USED_PATH.parent.mkdir(parents=True, exist_ok=True)
    USED_PATH.write_text(json.dumps(used), encoding="utf-8")


def _pixabay(key: str, q: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/", timeout=20, params={
        "key": key, "q": q[:100], "image_type": "photo", "orientation": "horizontal",
        "safesearch": "true", "min_width": 1200, "per_page": 30, "order": "popular",
    })
    r.raise_for_status()
    return [{"id": f"pixabay:{h['id']}", "img": h["largeImageURL"], "url": h["pageURL"],
             "photographer": h.get("user", ""), "provider": "Pixabay"} for h in r.json().get("hits", [])]


def _pexels(key: str, q: str) -> list[dict]:
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=20,
                     params={"query": q, "orientation": "landscape", "per_page": 20, "size": "large"})
    r.raise_for_status()
    return [{"id": f"pexels:{p['id']}", "img": p["src"]["large2x"], "url": p["url"],
             "photographer": p.get("photographer", ""), "provider": "Pexels"} for p in r.json().get("photos", [])]


def find(queries: list[str], out: Path) -> dict | None:
    """검색어를 차례로 시도해 가로 사진 1장을 out에 저장. 사진 정보(작가·출처·주소) 반환."""
    providers = []
    if os.environ.get("PIXABAY_API_KEY", "").strip():
        providers.append((_pixabay, os.environ["PIXABAY_API_KEY"].strip()))
    if os.environ.get("PEXELS_API_KEY", "").strip():
        providers.append((_pexels, os.environ["PEXELS_API_KEY"].strip()))
    if not providers:
        print("사진 API 키 없음(PIXABAY_API_KEY) → 사진 없이 만듦")
        return None

    used = set(_load_used())
    for q in [q for q in queries if q]:
        for search, key in providers:
            try:
                photos = [p for p in search(key, q) if p["id"] not in used]
            except Exception as e:  # noqa: BLE001
                print(f"사진 검색 실패({search.__name__[1:]}, {q}): {e}")
                continue
            for p in photos[:3]:  # 내려받기 실패하면 다음 사진
                try:
                    r = requests.get(p["img"], timeout=30)
                    r.raise_for_status()
                    Image.open(BytesIO(r.content)).convert("RGB").save(out, "JPEG", quality=92)
                except Exception as e:  # noqa: BLE001
                    print(f"사진 내려받기 실패: {e}")
                    continue
                _save_used(p["id"])
                print(f"사진: '{q}' → {p['url']} (by {p['photographer']}, {p['provider']})")
                return {"file": out.name, "query": q, **{k: p[k] for k in ("id", "url", "photographer", "provider")}}
        print(f"사진 없음: {q}")
    return None
