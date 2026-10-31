"""Claude로 기사 선별 + 카드뉴스 원고 + 캡션 작성."""
import json
import json_repair
import re
from datetime import datetime, timezone, timedelta

import anthropic

KST = timezone(timedelta(hours=9))

TASK_DAILY = "아래 후보 기사 중 직장인이 오늘 꼭 알아야 할 뉴스 {n}개를 골라 카드뉴스 원고를 만들어."
TASK_WEEKLY = """오늘은 '이번 주 경제 총정리' 날이야.
아래는 이번 주에 우리가 이미 다룬 뉴스와 오늘 새로 나온 기사야. 이 중 이번 주 흐름을 이해하는 데
가장 중요한 뉴스 {n}개를 골라 총정리 카드뉴스 원고를 만들어.
- 같은 주제가 여러 날 나왔으면 하나로 묶어서 '이번 주에 어떻게 흘러갔는지'를 써.
- points의 마지막 항목은 '다음 주에 지켜볼 것' 관점으로 써.
- caption 첫 줄은 '이번 주 경제, 이것만 기억하세요' 같은 총정리 훅으로, 저장 유도를 꼭 넣어."""

PROMPT = """너는 인스타그램 '{account}' 계정의 에디터야. 주제는 '{topic}'.
{task}

규칙:
- 기사 문장을 그대로 베끼지 말고 반드시 네 말로 다시 써. (저작권)
- 사실만 쓰고 추측·과장 금지. 투자 권유 표현 금지.
- headline은 18자 이내, 핵심 키워드가 앞에 오게.
- points는 정확히 3개, 각 32자 이내. 마지막 항목은 '그래서 나한테 무슨 의미?' 관점.
- tag는 2~4자 분야명 (예: 금리, 부동산, 증시, 환율, 산업).
- items는 가장 임팩트 큰 뉴스를 첫 번째로 놓아.
- cover_title은 첫 번째 뉴스의 핵심을 한 줄로 쓴 헤드라인이야. 숫자가 있으면 꼭 넣어 (예: 메타 8천 명 감원, 경상흑자 日·獨 추월).
  계정 이름, '경제 한 잔', 요일, '오늘의 뉴스' 같은 일반적인 말은 절대 쓰지 마.
- cover_subtitle은 나머지 뉴스를 짧게 예고 (예: 환율·GDP·AI 거품까지 4가지 더).
- source는 언론사 이름.
- caption은 4~6줄, 첫 줄은 궁금증을 일으키는 훅. 끝에서 두 번째 줄은 오늘 뉴스와 관련해 독자가 댓글로 답하기 쉬운 질문 한 줄 (예: 성장률 소식, 체감되시나요?). 마지막 줄은 '이 소식 필요한 동료에게 보내주세요' 같은 공유 유도 한 줄. 줄바꿈은 \\n으로 표시.
- reel_caption은 릴스용 짧은 캡션 2줄. 첫 줄은 오늘 가장 큰 뉴스의 숫자를 넣은 훅, 둘째 줄은 댓글 질문 한 줄. 해시태그 넣지 마.
- hashtags는 정확히 4개, '#' 포함. 오늘 뉴스 주제에 딱 맞는 것으로 대형 1개 + 중소형 3개 (예: #경제뉴스 #코스피 #금리 #재테크). 계정 태그는 자동으로 붙으니 넣지 마.
- 요일을 언급할 때는 아래 '오늘 날짜'의 요일만 써. 다른 요일(예: 내일, 다음 출근일)을 짐작해서 쓰지 마.
- 중요: 모든 문자열 값 안에는 큰따옴표를 절대 쓰지 마. 인용이 필요하면 작은따옴표(')나 「」를 써.

오늘 날짜: {date}

후보 기사:
{articles}

아래 JSON만 출력해 (설명·코드블록 없이). 키 순서를 지켜:
{{"cover_title": "...(14자 이내)", "cover_subtitle": "...(24자 이내)",
  "caption": "...", "reel_caption": "...", "hashtags": ["#..."],
  "items": [{{"tag": "...", "headline": "...", "points": ["...","...","..."], "source": "..."}}]}}
"""

# 인스타는 게시물당 해시태그 최대 5개 → 주제 태그 4개 + 계정 태그 1개
BRAND_TAG = "#출근길경제한잔"
MAX_HASHTAGS = 5
OFFDAY_RULE = """
- 중요: 오늘은 {kind}이라 쉬는 날이야. '출근', '출근길', '퇴근', '퇴근길', '출근 전', '업무 시작 전' 같은 표현은 caption·제목·본문 어디에도 절대 쓰지 마.
  대신 '주말', '쉬는 날', '여유로운 오늘' 같은 말을 쓰고, 공유 유도는 '동료' 대신 '필요한 사람·친구'로 써."""


DEFAULT_HASHTAGS = ["#경제뉴스", "#재테크", "#직장인", "#경제공부"]


def limit_hashtags(tags: list[str]) -> list[str]:
    """중복 제거 후 주제 태그 4개 + 계정 태그 1개로 맞춤."""
    out = []
    for t in tags:
        t = "#" + str(t).strip().lstrip("#").replace(" ", "")
        if len(t) > 1 and t != BRAND_TAG and t not in out:
            out.append(t)
    from .dayoff import is_day_off
    if is_day_off():  # 쉬는 날엔 '출근길' 계정 태그를 빼고 주제 태그만
        return out[:MAX_HASHTAGS]
    return out[: MAX_HASHTAGS - 1] + [BRAND_TAG]


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

    # 표지 제목이 비었거나 계정명 같은 일반 문구면 첫 뉴스 헤드라인으로 대체
    title = str(data.get("cover_title") or "").strip()
    generic = ("경제 한 잔", "경제한잔", "오늘의 경제", "오늘의 뉴스", "꼭 알아야 할", "요일", "총정리", "이번 주 경제")
    if not title or any(g in title for g in generic):
        title = data["items"][0]["headline"]
    data["cover_title"] = title
    data["cover_subtitle"] = str(data.get("cover_subtitle") or "")
    if not data["cover_subtitle"] and len(data["items"]) > 1:
        data["cover_subtitle"] = f"외 {len(data['items']) - 1}가지 뉴스 정리"

    caption = data.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        heads = "\n".join(f"✔️ {it['headline']}" for it in data["items"])
        caption = f"오늘 꼭 알아야 할 경제 뉴스 {len(data['items'])}가지\n{heads}\n저장해두고 다시 보세요"
    data["caption"] = caption.replace("\\n", "\n")

    tags = data.get("hashtags")
    if not isinstance(tags, list) or not tags:
        tags = DEFAULT_HASHTAGS
    data["hashtags"] = limit_hashtags(tags)

    reel = data.get("reel_caption")
    if not isinstance(reel, str) or not reel.strip():
        reel = data["caption"].split("\n")[0]
    data["reel_caption"] = reel.replace("\\n", "\n").strip()
    return data


def write_script(cfg: dict, articles: list[dict], week_items: list[dict] | None = None) -> dict:
    """week_items가 있으면 '이번 주 총정리' 원고, 없으면 평소 원고."""
    if not articles and not week_items:
        raise RuntimeError("새 기사가 없어서 오늘은 건너뜁니다.")
    listing = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']}\n   {re.sub('<[^>]+>', '', a['summary'])}"
        for i, a in enumerate(articles)
    )
    if week_items:
        past = "\n".join(
            f"- ({it['day']}) [{it.get('tag', '')}] {it['headline']}: {' / '.join(it.get('points', []))}"
            f" (출처 {it.get('source', '')})"
            for it in week_items
        )
        listing = f"[이번 주에 이미 다룬 뉴스]\n{past}\n\n[오늘 새 기사]\n{listing or '(없음)'}"
    now = datetime.now(KST)
    # %a는 서버에서 영어(Sun)로 나와서, 한글 요일을 직접 붙임
    today = now.strftime("%Y년 %m월 %d일 ") + "월화수목금토일"[now.weekday()] + "요일"
    n = cfg["news_per_post"]
    task = (TASK_WEEKLY if week_items else TASK_DAILY).format(n=n)
    from .dayoff import brand_name, describe
    kind = describe(now.date(), cfg)
    if kind.startswith("공휴일"):
        today += f" ({kind})"
    prompt = PROMPT.format(
        account=brand_name(cfg), topic=cfg["topic"], task=task,
        date=today, articles=listing,
    )
    if kind:  # 토·일·공휴일엔 출근길 표현 금지
        prompt += OFFDAY_RULE.format(kind=kind)
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
            data["date"] = now.strftime("%Y.%m.%d")
            if week_items:
                monday = now - timedelta(days=now.weekday())
                data["weekly"] = True
                data["date"] = f"{monday:%Y.%m.%d} – {now:%m.%d}"
                data["cover_subtitle"] = f"이번 주 경제 총정리 · {len(data['items'])}가지"
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
    parts += ["", " ".join(limit_hashtags(script.get("hashtags", [])))]
    return "\n".join(parts)[:2200]  # 인스타 캡션 최대 길이


def build_reel_caption(script: dict) -> str:
    """릴스는 짧게: 훅 + 질문 + 카드뉴스 안내 + 해시태그 3개."""
    reel = (script.get("reel_caption") or script.get("caption", "").split("\n")[0]).strip()
    tags = limit_hashtags(script.get("hashtags", []))
    tags = [t for t in tags if t != BRAND_TAG][:2] + ([BRAND_TAG] if BRAND_TAG in tags else [])
    return "\n".join([reel, "", "5가지 뉴스 전체는 오늘 아침 카드뉴스에서 👉 @morning.econo", "", " ".join(tags)])[:2200]
