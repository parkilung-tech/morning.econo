"""Claude로 기사 선별 + 카드뉴스 원고 + 캡션 작성."""
import json
import re
from datetime import datetime, timezone, timedelta

import anthropic

KST = timezone(timedelta(hours=9))

PROMPT = """너는 인스타그램 '{account}' 계정의 에디터야. 주제는 '{topic}'.
아래 후보 기사 중 직장인이 오늘 꼭 알아야 할 뉴스 {n}개를 골라 카드뉴스 원고를 만들어.

규칙:
- 기사 문장을 그대로 베끼지 말고 반드시 네 말로 다시 써. (저작권)
- 사실만 쓰고 추측·과장 금지. 투자 권유 표현 금지.
- headline은 18자 이내, 핵심 키워드가 앞에 오게.
- points는 정확히 3개, 각 32자 이내. 마지막 항목은 '그래서 나한테 무슨 의미?' 관점.
- tag는 2~4자 분야명 (예: 금리, 부동산, 증시, 환율, 산업).
- source는 언론사 이름.
- caption은 3~5줄, 첫 줄은 궁금증을 일으키는 훅. 끝에 '저장해두고 출근길에 보세요' 같은 저장 유도 한 줄.
- hashtags는 12~15개, '#' 포함, 대형/중형/소형 태그 섞기.

오늘 날짜: {date}

후보 기사:
{articles}

아래 JSON만 출력해 (설명·코드블록 없이):
{{"cover_title": "...(14자 이내)", "cover_subtitle": "...(24자 이내)",
  "items": [{{"tag": "...", "headline": "...", "points": ["...","...","..."], "source": "..."}}],
  "caption": "...", "hashtags": ["#..."]}}
"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def write_script(cfg: dict, articles: list[dict]) -> dict:
    if not articles:
        raise RuntimeError("새 기사가 없어서 오늘은 건너뜁니다.")
    listing = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']}\n   {re.sub('<[^>]+>', '', a['summary'])}"
        for i, a in enumerate(articles)
    )
    today = datetime.now(KST).strftime("%Y년 %m월 %d일 (%a)")
    prompt = PROMPT.format(
        account=cfg["account_name"], topic=cfg["topic"], n=cfg["news_per_post"],
        date=today, articles=listing,
    )
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    for attempt in range(2):
        msg = client.messages.create(
            model=cfg["model"], max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            data = _extract_json(next(b.text for b in msg.content if b.type == "text"))
            data["items"] = data["items"][: cfg["news_per_post"]]
            data["date"] = datetime.now(KST).strftime("%Y.%m.%d")
            return data
        except (json.JSONDecodeError, KeyError, ValueError):
            if attempt == 1:
                raise
    raise RuntimeError("원고 생성 실패")


def build_caption(script: dict) -> str:
    sources = sorted({it["source"] for it in script["items"] if it.get("source")})
    parts = [
        script["caption"].strip(),
        "",
        "📰 출처: " + ", ".join(sources),
        "",
        " ".join(script["hashtags"]),
    ]
    return "\n".join(parts)[:2200]  # 인스타 캡션 최대 길이
