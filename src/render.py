"""카드뉴스 이미지(1080x1350, 4:5) 생성."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
PAD = 90
KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"


def pick_theme(cfg: dict, day: date | None = None) -> dict:
    """오늘(한국 시간) 요일에 맞는 색상. 요일 색이 없으면 기존 theme 사용."""
    day = day or datetime.now(KST).date()
    themes = cfg.get("themes") or {}
    return themes.get(WEEKDAYS[day.weekday()]) or cfg["theme"]


class Painter:
    def __init__(self, cfg: dict, day: date | None = None):
        t = pick_theme(cfg, day)
        self.bg, self.card, self.accent = t["background"], t["card"], t["accent"]
        self.text, self.sub = t["text"], t["subtext"]
        self.bold_path = cfg["font_path"]
        self.reg_path = cfg.get("font_regular_path", cfg["font_path"])
        self.idx = cfg.get("font_index", 0)
        self.brand = cfg["account_name"]
        self.handle = cfg["handle"]

    def font(self, size: int, bold=True):
        return ImageFont.truetype(self.bold_path if bold else self.reg_path, size, index=self.idx)

    # ---------- helpers ----------
    @staticmethod
    def wrap(draw, text, font, max_w):
        lines, line = [], ""
        for word in text.split(" "):
            trial = (line + " " + word).strip()
            if draw.textlength(trial, font=font) <= max_w:
                line = trial
                continue
            if line:
                lines.append(line)
            line = ""
            for ch in word:  # 한 단어가 너무 길면 글자 단위로 자름
                if draw.textlength(line + ch, font=font) > max_w:
                    lines.append(line)
                    line = ch
                else:
                    line += ch
        if line:
            lines.append(line)
        return lines

    def block(self, draw, xy, text, font, fill, max_w, spacing=1.35):
        x, y = xy
        size = font.size
        for para in text.split("\n"):
            for ln in self.wrap(draw, para, font, max_w):
                draw.text((x, y), ln, font=font, fill=fill)
                y += int(size * spacing)
        return y

    def base(self, page, total):
        img = Image.new("RGB", (W, H), self.bg)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 14], fill=self.accent)
        d.text((PAD, 60), self.brand, font=self.font(30), fill=self.accent)
        f = self.font(26, bold=False)
        label = f"{page} / {total}"
        d.text((W - PAD - d.textlength(label, font=f), 64), label, font=f, fill=self.sub)
        d.text((PAD, H - 90), self.handle, font=self.font(26, bold=False), fill=self.sub)
        return img, d

    # ---------- cards ----------
    def cover(self, script, total):
        img, d = self.base(1, total)
        d.text((PAD, 300), script["date"], font=self.font(40, bold=False), fill=self.sub)
        # 헤드라인이 길면 글씨를 줄여 2줄 안에 맞춤 (아래 뉴스 목록과 겹치지 않게)
        for size in (110, 96, 84, 74):
            tf = self.font(size)
            if len(self.wrap(d, script["cover_title"], tf, W - 2 * PAD)) <= 2:
                break
        y = self.block(d, (PAD, 380), script["cover_title"], tf, self.text, W - 2 * PAD, 1.2)
        d.rectangle([PAD, y + 30, PAD + 120, y + 40], fill=self.accent)
        y = self.block(d, (PAD, y + 80), script["cover_subtitle"], self.font(46, bold=False), self.sub, W - 2 * PAD)
        # 오늘의 키워드 목록
        y = max(y + 60, 900)
        f = self.font(36, bold=False)
        for i, it in enumerate(script["items"], 1):
            d.text((PAD, y), f"{i:02d}", font=self.font(36), fill=self.accent)
            d.text((PAD + 80, y), it["headline"], font=f, fill=self.text)
            y += 58
        f = self.font(32)
        msg = "넘겨서 보기  →"
        d.text((W - PAD - d.textlength(msg, font=f), H - 96), msg, font=f, fill=self.accent)
        return img

    def item(self, it, n, page, total):
        img, d = self.base(page, total)
        d.text((PAD, 200), f"{n:02d}", font=self.font(120), fill=self.accent)
        # 태그 알약
        tf = self.font(34)
        tw = d.textlength(it["tag"], font=tf)
        tx = PAD + 190
        d.rounded_rectangle([tx, 245, tx + tw + 48, 305], radius=30, outline=self.accent, width=3)
        d.text((tx + 24, 251), it["tag"], font=tf, fill=self.accent)
        y = self.block(d, (PAD, 400), it["headline"], self.font(82), self.text, W - 2 * PAD, 1.25)
        # 요점 박스
        top = y + 50
        pf = self.font(42, bold=False)
        n_lines = sum(len(self.wrap(d, p, pf, W - 2 * PAD - 80)) for p in it["points"])
        bottom = top + 50 + n_lines * int(42 * 1.45) + 30 * len(it["points"]) + 30
        d.rounded_rectangle([PAD - 20, top, W - PAD + 20, bottom], radius=28, fill=self.card)
        y = top + 50
        for i, p in enumerate(it["points"]):
            color = self.accent if i == len(it["points"]) - 1 else self.text
            d.ellipse([PAD + 20, y + 18, PAD + 34, y + 32], fill=self.accent)
            y = self.block(d, (PAD + 60, y), p, pf, color, W - 2 * PAD - 80, 1.45) + 30
        sf = self.font(26, bold=False)
        src = f"출처 {it.get('source', '')}"
        d.text((W - PAD - d.textlength(src, font=sf), H - 90), src, font=sf, fill=self.sub)
        return img

    def outro(self, total):
        img, d = self.base(total, total)
        d.rectangle([0, H - 140, W, H], fill=self.bg)  # 기본 하단 핸들 가리기
        y = self.block(d, (PAD, 280), "매일 아침\n3분이면 끝", self.font(110), self.text, W - 2 * PAD, 1.2)
        y = self.block(d, (PAD, y + 40), "출근 전 꼭 알아야 할 뉴스만 골라 정리해드려요.", self.font(44, bold=False), self.sub, W - 2 * PAD)
        y += 80
        # CTA는 하나로 집중: 동료에게 보내기(DM 공유)가 노출에 가장 크게 작용
        d.rounded_rectangle([PAD, y, W - PAD, y + 130], radius=65, fill=self.accent)
        label = "이 뉴스, 필요한 동료에게 보내기"
        lf = self.font(46)
        d.text(((W - d.textlength(label, font=lf)) / 2, y + 34), label, font=lf, fill=self.bg)
        y += 130 + 50
        sub = "팔로우하면 매일 아침 7시 전에 도착해요"
        sf = self.font(36, bold=False)
        d.text(((W - d.textlength(sub, font=sf)) / 2, y), sub, font=sf, fill=self.sub)
        d.text((PAD, y + 110), self.handle, font=self.font(56), fill=self.accent)
        return img


def render_all(cfg: dict, script: dict, out_dir: Path, day: date | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = Painter(cfg, day)
    total = len(script["items"]) + 2
    images = [p.cover(script, total)]
    images += [p.item(it, i, i + 1, total) for i, it in enumerate(script["items"], 1)]
    images.append(p.outro(total))
    paths = []
    for i, img in enumerate(images, 1):
        path = out_dir / f"card_{i:02d}.jpg"
        img.save(path, "JPEG", quality=92)
        paths.append(path)
    return paths
