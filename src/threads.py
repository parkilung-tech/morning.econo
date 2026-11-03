"""아침 카드뉴스(post.json) → 스레드 요약 글 작성 + 스레드 API로 게시.

양식:
  ☕ N월 N일 출근길 경제 한 잔

  1️⃣ (분야 태그)
  핵심 내용 1~2문장, '~해요/~중' 말투
  ... (5️⃣까지)

  📌 이번 주 체크
  독자가 해볼 행동 1~2개를 쉼표로

  카드뉴스로 자세히 보기 👉 @morning.econo
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
HOST = "https://graph.threads.net"
MAX_LEN = 500  # 스레드 글 최대 글자 수
NUMS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

PROMPT = """아래는 오늘 인스타 카드뉴스에 올린 경제 뉴스 {n}개야. 스레드에 올릴 짧은 요약을 만들어줘.

규칙:
- 뉴스마다 summary 한 줄: 핵심 내용 1~2문장, '~해요/~중' 말투, 45자 이내. 숫자가 있으면 넣어.
- 카드에 있는 사실만 쓰고 추측·과장·투자 권유 금지.
- check: 이번 주에 독자가 직접 해볼 수 있는 행동 1~2개를 쉼표로 이은 한 줄, 40자 이내 (예: 내 대출 금리 확인, 연금 속 반도체 비중 점검).
{offday}- 문자열 안에 큰따옴표 쓰지 마.

뉴스:
{items}

아래 JSON만 출력해 (설명·코드블록 없이):
{{"summaries": ["...", "..."], "check": "..."}}
"""
OFFDAY = "- 오늘은 쉬는 날이라 '출근', '출근길', '퇴근길' 같은 말은 쓰지 마.\n"


def _header(cfg: dict, post: dict) -> str:
    from .dayoff import brand_name
    now = datetime.now(KST)
    if post.get("weekly"):
        return f"☕ {now.month}월 {now.day}일 이번 주 경제 총정리"
    return f"☕ {now.month}월 {now.day}일 {brand_name(cfg)}"


def _ai_parts(cfg: dict, post: dict) -> tuple[list[str], str] | None:
    """Claude로 뉴스별 한 줄 요약 + '이번 주 체크' 작성. 실패하면 None."""
    try:
        import anthropic
        import json_repair
        from .dayoff import is_day_off

        items = post["items"]
        listing = "\n".join(
            f"{i+1}. [{it['tag']}] {it['headline']}: {' / '.join(it['points'])}" for i, it in enumerate(items)
        )
        prompt = PROMPT.format(n=len(items), items=listing, offday=OFFDAY if is_day_off(cfg=cfg) else "")
        msg = anthropic.Anthropic().messages.create(
            model=cfg["model"], max_tokens=2000, messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        data = json_repair.loads(text[text.find("{"):])
        sums = [str(s).strip() for s in data.get("summaries", [])]
        if len(sums) != len(items) or not all(sums):
            raise ValueError(f"요약 개수가 안 맞음: {len(sums)}")
        return sums, str(data.get("check") or "").strip()
    except Exception as err:  # noqa: BLE001  (실패해도 기본 요약으로 게시)
        print(f"::warning::스레드 요약 AI 작성 실패, 기본 요약 사용: {err}")
        return None


def compose(cfg: dict, post: dict) -> str:
    items = post["items"]
    parts = _ai_parts(cfg, post)
    if parts:
        sums, check = parts
    else:  # 카드 문장 그대로 활용
        sums = [it["points"][0] for it in items]
        check = items[0]["points"][-1] if items[0]["points"] else ""
    handle = cfg.get("handle", "@morning.econo")

    def build(long: bool) -> str:
        lines = [_header(cfg, post), ""]
        for i, (it, s) in enumerate(zip(items, sums)):
            if not long:  # 길면 첫 문장만
                s = re.split(r"(?<=[요중다])[,.]?\s", s, maxsplit=1)[0]
            lines += [f"{NUMS[i]} {it['tag']}", s, ""]
        if check:
            lines += ["📌 이번 주 체크", check, ""]
        lines.append(f"카드뉴스로 자세히 보기 👉 {handle}")
        return "\n".join(lines)

    text = build(True)
    if len(text) > MAX_LEN:
        text = build(False)
    if len(text) > MAX_LEN:  # 그래도 길면 체크 줄을 줄임
        check = check.split(",")[0]
        text = build(False)
    return text[:MAX_LEN]


class Threads:
    def __init__(self, version: str = "v1.0"):
        self.token = os.environ["THREADS_ACCESS_TOKEN"]
        self.user_id = os.environ.get("THREADS_USER_ID") or "me"
        self.base = f"{HOST}/{version}"

    def _post(self, path, **params):
        params["access_token"] = self.token
        r = requests.post(f"{self.base}/{path}", data=params, timeout=60)
        if not r.ok:
            raise RuntimeError(f"스레드 API 오류 {r.status_code}: {r.text}")
        return r.json()

    def _wait_ready(self, cid, tries=24):
        for _ in range(tries):
            r = requests.get(f"{self.base}/{cid}",
                             params={"fields": "status,error_message", "access_token": self.token},
                             timeout=30).json()
            status = r.get("status")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"스레드 컨테이너 실패: {r}")
            time.sleep(5)
        raise TimeoutError("스레드 컨테이너 준비 시간 초과")

    def publish(self, text: str, image_urls: list[str] | None = None) -> str:
        if image_urls:
            children = [self._post(f"{self.user_id}/threads", media_type="IMAGE",
                                   image_url=u, is_carousel_item="true")["id"] for u in image_urls[:20]]
            for cid in children:
                self._wait_ready(cid)
            c = self._post(f"{self.user_id}/threads", media_type="CAROUSEL",
                           children=",".join(children), text=text)
        else:
            c = self._post(f"{self.user_id}/threads", media_type="TEXT", text=text)
        self._wait_ready(c["id"])
        return self._post(f"{self.user_id}/threads_publish", creation_id=c["id"])["id"]
