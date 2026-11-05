"""릴스 v2 원고: 뉴스 1개 → 큰 글씨 컷(beats) 4개 + 마무리. Claude가 작성."""
import re

import anthropic

from .summarize import _extract_json

PROMPT = """너는 인스타그램 경제 계정 '{brand}'의 릴스 작가야.
아래 뉴스 1개로 10초짜리 릴스 대본을 써. 화면마다 큰 글씨 한 덩어리만 나오고 1.5초 안에 읽혀야 해.

뉴스:
{news}

컷 구성 (순서 고정):
1) 첫 컷: 숫자가 있으면 type "drop" — 대상(big)과 숫자(number), 오르면 direction "up", 내리면 "down".
   숫자가 없거나 오르내림이 아닌 숫자면 type "text" — 직장인이 '어, 내 얘기네' 하고 멈출 한 줄(big).
   kicker는 '{date} · 분야' 형식 (예: 11.05 · 증시).
2) 둘째 컷: type "text", kicker "왜?", big = 이유 한 줄.
3) 셋째 컷: type "question", big = 내 월급·대출·물가·투자·일자리와 연결한 질문 (물음표로 끝).
4) 넷째 컷: type "action", kicker "오늘 할 일", big = 독자가 오늘 해볼 일 한 줄.

글자 규칙 (중요):
- big은 줄바꿈(\\n)으로 나눠 최대 3줄, 한 줄은 7자 이내(공백 포함, 넘치면 줄을 나눠). drop의 big은 6자 이내 한 줄.
- number는 기호 포함 8자 이내 (예: −3,000엔, +6.63%, 9천억弗). 하락은 '−', 상승은 '+'를 앞에.
- 뉴스에 있는 사실·숫자만 써. 없는 숫자를 만들거나 결과를 단정하지 마. 과장·낚시·투자 권유 금지.
- 기사 문장을 그대로 베끼지 말고 네 말로.
- 문자열 안에 큰따옴표 금지.
{offday}
JSON만 출력:
{{"beats": [{{"type": "drop", "kicker": "...", "big": "...", "number": "...", "direction": "down"}},
  {{"type": "text", "kicker": "왜?", "big": "..."}},
  {{"type": "question", "big": "..."}},
  {{"type": "action", "kicker": "오늘 할 일", "big": "..."}}]}}
"""

OFFDAY = "- 오늘은 쉬는 날이라 '출근', '퇴근' 같은 말은 쓰지 마."


def _clean(beats: list) -> list[dict]:
    out = []
    for b in beats or []:
        if not isinstance(b, dict) or b.get("type") not in ("drop", "text", "question", "action"):
            continue
        big = str(b.get("big") or "").replace("\\n", "\n").strip()
        if not big:
            continue
        lines = [ln.strip() for ln in big.split("\n") if ln.strip()][:3]
        c = {"type": b["type"], "big": "\n".join(lines)}
        if b.get("kicker"):
            c["kicker"] = str(b["kicker"]).strip()[:16]
        if b["type"] == "drop":
            num = str(b.get("number") or "").strip()
            if not num or len(num) > 10:
                c["type"] = "text"  # 숫자가 없으면 글자 컷으로
            else:
                c["number"] = num.replace("-", "−")
                c["direction"] = "up" if b.get("direction") == "up" or num.startswith("+") else "down"
                c["big"] = lines[0]
        if b["type"] == "question" and not c["big"].endswith("?"):
            c["big"] += "?"
        out.append(c)
    if len(out) < 3:
        raise ValueError(f"컷이 부족함 ({len(out)}개)")
    return out[:4] + [{"type": "outro"}]


def write_beats(cfg: dict, news: str, day, day_off: bool = False) -> list[dict]:
    from .dayoff import brand_name
    prompt = PROMPT.format(brand=brand_name(cfg, day), news=news, date=f"{day:%m.%d}",
                           offday=OFFDAY if day_off else "")
    client = anthropic.Anthropic()
    last = None
    for attempt in range(3):
        msg = client.messages.create(model=cfg["model"], max_tokens=2000,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return _clean(_extract_json(text).get("beats"))
        except (ValueError, TypeError, AttributeError) as e:
            last = e
            print(f"[릴스 대본 시도 {attempt + 1}] 실패: {e} / {text[:300]}")
    raise RuntimeError(f"릴스 대본 생성 실패: {last}")


def news_from_item(item: dict) -> str:
    return f"[{item.get('tag', '')}] {item['headline']}\n" + "\n".join(f"- {p}" for p in item.get("points", []))


def news_from_evening(post: dict) -> str:
    parts = [f"[{post.get('tag', '')}] {post.get('title', '')}", post.get("one_line", ""), post.get("what", "")]
    parts += [f"- 왜: {w}" for w in post.get("why", [])]
    parts += [f"- 영향: {w}" for w in post.get("impact", [])]
    if post.get("numbers"):
        parts.append(f"숫자: {post['numbers']}")
    return re.sub(r"\n{2,}", "\n", "\n".join(p for p in parts if p))
