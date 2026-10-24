"""Claude로 기사 선별 + 카드뉴스 원고 + 캡션 작성."""
import json
import json_repair
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
- caption은 3~5줄, 첫 줄은 궁금증을 일으키는 훅. 끝에 '저장해두고 출근길에 보세요' 같은 저장 유도 한 줄. 줄바꿈은 \\n으로 표시.
- hashtags는 12~15개, '#' 포함, 대형/중형/소형 태그 섞기.
- 중요: 모든 문자열 값 안에는 큰따옴표를 절대 쓰지 마. 인용이 필요하면 작은따옴표(')나 「」를 써.

오늘 날짜: {date}

후보 기사:
{articles}

아래 JSON만 출력해 (설명·코드블록 없이). 키 순서를 지켜:
{{"cover_title": "...(14자 이내)", "cover_subtitle": "...(24자 이내)",
  "caption": "...", "hashtags": ["#..."],
  "items": [{{"tag": "...", "headline": "...", "points": ["...","...","..."], "source": "..."}}]}}
"""

DEFAULT_HASHTAGS = [
    "#경제뉴스", "#오늘의뉴스", "#카드뉴스", "#경제공부", "#직장인",
    "#출근길", "#재테크", "#뉴스요약", "#경제상식", "#모닝뉴스",
]


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("응답에 JSON이 없음")
    data = json_repair.loads(text[start:])
    if not isinstance(data, dict):
        raise ValueError("JSON 형식이 아님")
    return data


def _validate(data: dict, n: int) -> dict:
    """빠진 항목은 기본값으로 채우고, 기사 목록이 없으면 실패 처리."""
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("items 없음")

    clean = []
    for it in items:
        if not isinstance(it, dict) or not it.get("headline"):
            continue
        points = it.get("points") or []
        if not isinstance(points, list):
            points = [str(points)]
        clean.append({
            "tag": str(it.get("tag") or "경제"),
            "headline": str(it["headline"]),
            "points": [str(p) for p in points][:3],
            "source": str(it.get("source") or ""),
        })
    if not clean:
        raise ValueError("유효한 기사가 하나도 없음")
    data["items"] = clean[:n]

    data["cover_title"] = str(data.get("cover_title") or "오늘의 경제 뉴스")
    data["cover_subtitle"] = str(data.get("cover_subtitle") or "")

    caption = data.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        heads = "\n".join(f"✔️ {it['headline']}" for it in data["items"])
        caption = f"오늘 꼭 알아야 할 경제 뉴스 {len(data['items'])}가지\n{heads}\n저장해두고 출근길에 보세요"
    data["caption"] = caption.replace("\\n", "\n")

    tags = data.get("hashtags")
    if not isinstance(tags, list) or not tags:
        tags = DEFAULT_HASHTAGS
    data["hashtags"] = [t if str(t).startswith("#") else f"#{t}" for t in map(str, tags)]
    return data


def write_script(cfg: dict, articles: list[dict]) -> dict:
    if not articles:
        raise RuntimeError("새 기사가 없어서 오늘은 건너뜁니다.")
    listing = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']}\n   {re.sub('<[^>]+>', '', a['summary'])}"
        for i, a in enumerate(articles)
    )
    today = datetime.now(KST).strftime("%Y년 %m월 %d일 (%a)")
    n = cfg["news_per_post"]
    prompt = PROMPT.format(
        account=cfg["account_name"], topic=cfg["topic"], n=n,
        date=today, articles=listing,
    )
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용

    last_error = None
    for attempt in range(3):
        msg = client.messages.create(
            model=cfg["model"], max_tokens=12000,
            messages=[{"role": "user", "content": prompt}],
        )
        print(f"[원고 시도 {attempt + 1}] stop_reason={msg.stop_reason}")
        text = "".join(b.text for b in msg.content if b.type == "text")

        if msg.stop_reason == "max_tokens":
            last_error = "응답이 한도에서 잘림"
            print("  → 응답이 잘려서 다시 시도합니다.")
            continue
        try:
            data = _validate(_extract_json(text), n)
            data["date"] = datetime.now(KST).strftime("%Y.%m.%d")
            return data
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            last_error = e
            print(f"  → 원고 해석 실패: {e}")
            print(f"  → 응답 앞부분: {text[:500]}")
    raise RuntimeError(f"원고 생성 실패 (3회 시도): {last_error}")


def build_caption(script: dict) -> str:
    sources = sorted({it["source"] for it in script.get("items", []) if it.get("source")})
    parts = [script.get("caption", "").strip()]
    if sources:
        parts += ["", "📰 출처: " + ", ".join(sources)]
    parts += ["", " ".join(script.get("hashtags", []))]
    return "\n".join(parts)[:2200]  # 인스타 캡션 최대 길이
