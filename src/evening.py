"""저녁 6시 '퇴근길 이슈 한 장': 오늘 가장 이슈가 된 뉴스 1개를 한 장(1080x1350)으로 정리."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from .render import PAD, H, W, WEEKDAYS, Painter
from .summarize import BRAND_TAG, _extract_json, limit_hashtags

KST = timezone(timedelta(hours=9))

PROMPT = """너는 인스타그램 '{account}' 계정의 에디터야. 지금은 저녁 6시 '퇴근길 이슈 한 장' 게시물을 만들 차례야.
아래 오늘 기사 후보 중에서 오늘 하루 가장 이슈가 된 경제 뉴스 딱 1개를 골라, 직장인이 한 장으로 이해할 수 있게 정리해.

고르는 기준:
- 여러 언론사가 함께 다룬 주제일수록 이슈가 큰 거야. 비슷한 기사가 많은 주제를 우선해.
- 직장인의 지갑·일자리·투자에 영향이 큰 뉴스를 우선해.
- 오늘 아침 카드뉴스에서 이미 다룬 뉴스도 골라도 돼. 그럴 땐 아침 이후 나온 새 내용과 의미를 더 깊게 써.

규칙:
- 후보 기사에 나온 사실과 숫자만 써. 기사에 없는 숫자·전망·원인은 지어내지 마. 확실하지 않으면 빼.
- 기사 문장을 그대로 베끼지 말고 네 말로 다시 써. 투자 권유 표현 금지.
- 말투는 '~해요/~예요' 체.
- 중요: 모든 문자열 값 안에는 큰따옴표를 절대 쓰지 마. 인용이 필요하면 작은따옴표(')나 「」를 써.

각 항목 길이 (꼭 지켜, 한 장에 들어가야 해):
- tag: 분야명 2~4자 (예: 금리, 증시, 부동산, 환율, 고용)
- title: 16자 이내 헤드라인, 숫자가 있으면 넣기
- one_line: 한 줄 요약 30자 이내
- what: 무슨 일인지 2문장, 합쳐서 70자 이내
- numbers: 기사에 나온 핵심 숫자 2~3개. value는 8자 이내(예: 1.0%, 3조 원), label은 12자 이내. 기사에 숫자가 없으면 빈 배열 []
- why: 왜 이런 일이 생겼는지 1~2개, 각 32자 이내 (기사에 근거가 있을 때만)
- impact: 그래서 나한테 무슨 의미인지 2개, 각 32자 이내
- watch: 앞으로 지켜볼 것 1문장 36자 이내
- sources: 참고한 언론사 이름 목록
- caption: 이미지를 안 보고 캡션만 읽어도 뉴스를 충분히 이해할 수 있는 자세한 해설. 이미지보다 더 깊게, 배경과 맥락까지 풀어줘.
  공백 포함 700~1100자. 줄바꿈은 \\n, 문단 사이엔 빈 줄(\\n\\n). 아래 형식을 그대로 지켜:
  (1줄) 궁금증을 일으키는 훅 한 문장
  (빈 줄)
  📌 무슨 일이 있었나
  누가·언제·무엇을 했는지 3~4문장. 핵심 숫자는 문장 안에 넣어.
  (빈 줄)
  🔍 왜 중요할까
  이 일이 생긴 배경과 시장·업계 맥락 3~4문장. 이전 흐름과 비교할 수 있으면 비교해.
  (빈 줄)
  💡 나한테는 어떤 의미?
  직장인·투자자·대출자 등 독자 입장에서의 영향 2~3문장. 투자 권유는 금지, '확인해볼 것' 위주로.
  (빈 줄)
  👀 앞으로 지켜볼 것
  다음 일정이나 변수 1~2문장.
  (빈 줄)
  댓글로 답하기 쉬운 질문 한 줄
  '이 한 장, 필요한 동료에게 보내주세요' 같은 공유 유도 한 줄
  · 캡션에도 기사에 없는 사실·숫자·전망은 절대 지어내지 마. 기사 정보가 부족하면 짧아져도 괜찮아.
  · 전문 용어는 처음 나올 때 괄호로 쉽게 풀어줘 (예: FCF(잉여현금흐름)).
  · 캡션 본문에는 언론사 이름을 쓰지 마 ('○○일보는 ~라고 평가' 금지). 출처는 sources에만 넣으면 자동으로 아래에 붙어. sources에는 캡션에 쓴 내용의 언론사를 빠짐없이 넣어.
- hashtags: 이 뉴스 주제에 딱 맞는 4개, '#' 포함. 계정 태그는 넣지 마.
- photo_queries: 무료 사진 사이트에서 이 뉴스에 어울리는 실사 배경 사진을 찾을 영어 검색어 3개. 구체적인 장면 2~4단어.
  · 한국 국내 뉴스면 1~2번째 검색어에 한국 장면이 나오게 Seoul, Korea, Korean won 같은 말을 넣어
    (예: 금리 → "Seoul bank street", "Korean won banknotes", "bank interest rate";
         부동산 → "Seoul apartment complex", "Korea apartment buildings", "real estate housing";
         증시 → "Seoul financial district", "stock market chart", "stock trading screen").
  · 해외 뉴스면 그 나라·주제 장면으로 (예: 미국 연준 → "Washington DC", "US dollar bills", "federal reserve").
  · 3번째는 한국·나라 이름 없이 주제만 담은 넓은 검색어.
  · 실존 인물 이름, 회사 로고·상표, 국기는 넣지 마.

오늘 날짜: {date}

[오늘 아침 카드뉴스에서 다룬 뉴스]
{morning}

[오늘 기사 후보]
{articles}

아래 JSON만 출력해 (설명·코드블록 없이):
{{"tag": "...", "title": "...", "one_line": "...", "what": "...",
  "numbers": [{{"value": "...", "label": "..."}}], "why": ["..."], "impact": ["...", "..."],
  "watch": "...", "sources": ["..."], "caption": "...", "hashtags": ["#..."],
  "photo_queries": ["...", "...", "..."]}}
"""

DEFAULT_THEME = {  # 저녁은 요일 색 대신 노을 톤 하나로 고정 → 피드에서 아침 카드와 구분
    "background": "#1B1020", "card": "#2B1B33", "accent": "#FF9E5E",
    "text": "#FFF7F0", "subtext": "#C9B2AC",
}


def _strs(v, n):
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in (v or []) if str(x).strip()][:n]


def _validate(data: dict) -> dict:
    if not str(data.get("title") or "").strip():
        raise ValueError("title 없음")
    out = {
        "tag": str(data.get("tag") or "경제")[:5],
        "title": str(data["title"]).strip(),
        "one_line": str(data.get("one_line") or "").strip(),
        "what": str(data.get("what") or "").strip(),
        "why": _strs(data.get("why"), 2),
        "impact": _strs(data.get("impact"), 2),
        "watch": str(data.get("watch") or "").strip(),
        "sources": _strs(data.get("sources"), 4),
        "numbers": [],
    }
    for nb in data.get("numbers") or []:
        if isinstance(nb, dict) and nb.get("value"):
            out["numbers"].append({"value": str(nb["value"]).strip(), "label": str(nb.get("label") or "").strip()})
    out["numbers"] = out["numbers"][:3]
    if not out["what"] and not out["impact"]:
        raise ValueError("본문 없음")
    cap = data.get("caption")
    if not isinstance(cap, str) or not cap.strip():
        cap = f"오늘 하루 가장 뜨거웠던 경제 이슈, 한 장으로 정리했어요.\n{out['title']}"
    out["caption"] = cap.replace("\\n", "\n").strip()
    out["photo_queries"] = _strs(data.get("photo_queries"), 3) + ["Seoul city skyline", "economy business"]
    out["hashtags"] = limit_hashtags(data.get("hashtags") or ["#경제뉴스", "#경제이슈", "#재테크", "#직장인"])
    return out


def write(cfg: dict, articles: list[dict], morning_items: list[dict]) -> dict:
    import anthropic

    if not articles:
        raise RuntimeError("오늘 기사가 없어서 저녁 게시는 건너뜁니다.")
    listing = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']}\n   {re.sub('<[^>]+>', '', a['summary'])}"
        for i, a in enumerate(articles)
    )
    morning = "\n".join(f"- [{it.get('tag', '')}] {it['headline']}" for it in morning_items) or "(없음)"
    now = datetime.now(KST)
    today = now.strftime("%Y년 %m월 %d일 ") + WEEKDAYS[now.weekday()] + "요일"
    prompt = PROMPT.format(account=cfg["account_name"], date=today, morning=morning, articles=listing)
    client = anthropic.Anthropic()

    last = None
    for attempt in range(3):
        msg = client.messages.create(model=cfg["model"], max_tokens=8000,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        print(f"[저녁 원고 시도 {attempt + 1}] stop_reason={msg.stop_reason}")
        try:
            data = _validate(_extract_json(text))
            data["date"] = now.strftime("%Y.%m.%d") + f" {WEEKDAYS[now.weekday()]}"
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  → 원고 해석 실패: {e}\n  → 응답 앞부분: {text[:400]}")
    raise RuntimeError(f"저녁 원고 생성 실패 (3회 시도): {last}")


def caption(post: dict) -> str:
    tail = []
    if post.get("sources"):
        tail += ["", "📰 출처: " + ", ".join(post["sources"])]
    if post.get("photo"):
        ph = post["photo"]
        tail += [f"📷 사진: {ph.get('photographer') or ph.get('provider', '')} / {ph.get('provider', 'Pexels')}"]
    tail += ["", "☕ 아침 7시 전엔 오늘의 경제뉴스 5가지 카드뉴스가 올라와요", "",
             " ".join(limit_hashtags(post.get("hashtags", [])) or [BRAND_TAG])]
    tail_txt = "\n".join(tail)
    body = post["caption"].strip()
    room = 2200 - len(tail_txt) - 1  # 인스타 캡션 최대 2200자: 해시태그·출처는 꼭 남기고 본문을 줄임
    if len(body) > room:
        body = body[:room].rsplit("\n", 1)[0].rstrip()
    return body + "\n" + tail_txt


# ---------------- 이미지 ----------------
class EveningPainter(Painter):
    def __init__(self, cfg: dict):
        super().__init__(cfg)
        t = {**DEFAULT_THEME, **(cfg.get("evening_theme") or {})}
        self.bg, self.card, self.accent = t["background"], t["card"], t["accent"]
        self.text, self.sub = t["text"], t["subtext"]

    k = 1.0  # 내용이 길면 글씨·간격을 줄이는 배율
    photo = None  # 위쪽 배너 사진 (PIL Image)
    ph = 0  # 배너 높이

    def banner(self, img):
        """사진을 위쪽에 꽉 채우고, 위는 살짝 어둡게·아래는 배경색으로 자연스럽게 이어지게."""
        src = self.photo
        scale = max(W / src.width, self.ph / src.height)
        im = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
        left, top = (im.width - W) // 2, (im.height - self.ph) // 2
        img.paste(im.crop((left, top, left + W, top + self.ph)), (0, 0))
        bg = Image.new("RGB", (W, self.ph), self.bg)
        mask = Image.new("L", (1, self.ph))
        for yy in range(self.ph):
            t = yy / self.ph
            top_dark = max(0.0, 0.55 * (1 - t / 0.3))          # 위쪽 글씨 잘 보이게
            fade = max(0.0, min(1.0, (t - 0.35) / 0.65)) ** 1.2  # 아래로 갈수록 배경색
            mask.putpixel((0, yy), round(255 * max(top_dark, fade)))
        img.paste(bg, (0, 0), mask.resize((W, self.ph)))

    def F(self, size, bold=True):
        return self.font(max(18, round(size * self.k)), bold)

    def g(self, px):
        return round(px * self.k)

    def fit(self, d, text, sizes, max_w, max_lines, bold=True):
        for s in sizes:
            f = self.F(s, bold)
            if len(self.wrap(d, text, f, max_w)) <= max_lines:
                return f
        return self.F(sizes[-1], bold)

    def label(self, d, xy, text):
        d.text(xy, text, font=self.F(30), fill=self.accent)
        return xy[1] + self.g(46)

    def bullets(self, d, x, y, items, max_w, size=34):
        for it in items:
            f = self.fit(d, it, (size, size - 3, size - 6), max_w - 34, 1, bold=False)
            fs = f.size
            d.ellipse([x, y + fs * 0.45, x + 10, y + fs * 0.45 + 10], fill=self.accent)
            y = self.block(d, (x + 30, y), it, f, self.text, max_w - 34, 1.3) + self.g(8)
        return y

    def draw(self, post: dict) -> Image.Image:
        # 한 장 안에 다 들어갈 때까지 배율을 줄여가며 다시 그림
        steps = ([(470, 1.0), (470, 0.93), (420, 0.93), (420, 0.86), (370, 0.86), (370, 0.8), (330, 0.8), (330, 0.74)]
                 if self.photo else [(0, k) for k in (1.0, 0.93, 0.86, 0.8, 0.74)])
        for ph, k in steps:
            self.ph, self.k = ph, k
            img, bottom = self._draw(post)
            if bottom <= H - 130:
                break
        return img

    def _draw(self, post: dict):
        img = Image.new("RGB", (W, H), self.bg)
        if self.photo:
            self.banner(img)
        d = ImageDraw.Draw(img)
        inner = W - 2 * PAD
        d.rectangle([0, 0, W, 14], fill=self.accent)
        d.text((PAD, 52), "퇴근길 이슈 한 장", font=self.font(32), fill=self.accent)
        df = self.font(28, bold=False)
        d.text((W - PAD - d.textlength(post["date"], font=df), 56), post["date"], font=df,
               fill=self.text if self.photo else self.sub)

        # 태그 + 제목 + 한 줄 요약 (사진이 있으면 사진 아래쪽에 겹쳐 시작)
        y = self.ph - 120 if self.photo else 128
        tf = self.font(28)
        tw = d.textlength(post["tag"], font=tf)
        if self.photo:  # 사진 위에서는 채운 태그로 또렷하게
            d.rounded_rectangle([PAD, y, PAD + tw + 40, y + 50], radius=25, fill=self.accent)
            d.text((PAD + 20, y + 8), post["tag"], font=tf, fill=self.bg)
        else:
            d.rounded_rectangle([PAD, y, PAD + tw + 40, y + 50], radius=25, outline=self.accent, width=3)
            d.text((PAD + 20, y + 8), post["tag"], font=tf, fill=self.accent)
        y += 72
        y = self.block(d, (PAD, y), post["title"], self.fit(d, post["title"], (84, 74, 64, 56), inner, 2),
                       self.text, inner, 1.18) + self.g(18)
        if post["one_line"]:
            y = self.block(d, (PAD, y), post["one_line"], self.fit(d, post["one_line"], (38, 34, 30), inner, 1, False),
                           self.sub, inner) + self.g(26)

        # 무슨 일?
        y = self.label(d, (PAD, y), "무슨 일?")
        y = self.block(d, (PAD, y), post["what"], self.fit(d, post["what"], (36, 33, 30), inner, 3, False),
                       self.text, inner, 1.4) + self.g(24)

        # 숫자로 보면
        nums = post["numbers"]
        if nums:
            gap, bh = 20, self.g(140)
            bw = (inner - gap * (len(nums) - 1)) / len(nums)
            for i, nb in enumerate(nums):
                x0 = PAD + i * (bw + gap)
                d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=24, fill=self.card)
                vf = self.fit(d, nb["value"], (54, 46, 40, 34), bw - 40, 1)
                d.text((x0 + 24, y + self.g(20)), nb["value"], font=vf, fill=self.accent)
                if nb["label"]:
                    lf = self.fit(d, nb["label"], (28, 25, 22), bw - 40, 1, False)
                    d.text((x0 + 24, y + self.g(90)), self.wrap(d, nb["label"], lf, bw - 40)[0], font=lf, fill=self.sub)
            y += bh + self.g(28)

        # 왜?
        if post["why"]:
            y = self.label(d, (PAD, y), "왜?")
            y = self.bullets(d, PAD, y, post["why"], inner) + self.g(16)

        # 그래서 나한테는? (강조 박스: 높이를 먼저 재고 박스 → 글씨 순서로 그림)
        if post["impact"]:
            top = y
            probe = ImageDraw.Draw(Image.new("RGB", (W, H)))
            yy = self.bullets(probe, PAD + 36, top + self.g(26) + self.g(46), post["impact"], inner - 72)
            bottom = yy + self.g(16)
            d.rounded_rectangle([PAD, top, W - PAD, bottom], radius=28, fill=self.card)
            d.rectangle([PAD, top + 24, PAD + 8, bottom - 24], fill=self.accent)
            yy = self.label(d, (PAD + 36, top + self.g(26)), "그래서 나한테는?")
            self.bullets(d, PAD + 36, yy, post["impact"], inner - 72)
            y = bottom + self.g(30)

        # 앞으로 볼 것
        if post["watch"]:
            lw = self.g(200)
            wf = self.fit(d, post["watch"], (32, 29, 26), inner - lw, 2, False)
            d.text((PAD, y + 2), "앞으로 볼 것", font=self.F(28), fill=self.accent)
            y = self.block(d, (PAD + lw, y), post["watch"], wf, self.text, inner - lw, 1.35)

        # 하단: 출처 + 핸들
        d.line([PAD, H - 110, W - PAD, H - 110], fill=self.card, width=2)
        d.text((PAD, H - 82), self.handle, font=self.font(30), fill=self.accent)
        if post["sources"]:
            src = "출처 " + ", ".join(post["sources"]) + (f" · 사진 {post.get('photo', {}).get('provider', 'Pixabay')}" if self.photo else "")
            for sz in (24, 22, 20):
                sf = self.font(sz, bold=False)
                if d.textlength(src, font=sf) <= inner - 320:
                    break
            d.text((W - PAD - d.textlength(src, font=sf), H - 78), src, font=sf, fill=self.sub)
        return img, y


def render(cfg: dict, post: dict, out: Path, photo_path: Path | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    painter = EveningPainter(cfg)
    if photo_path and Path(photo_path).exists():
        painter.photo = Image.open(photo_path).convert("RGB")
    painter.draw(post).save(out, "JPEG", quality=92)
    return out
