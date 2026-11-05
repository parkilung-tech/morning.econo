"""릴스 v2: 뉴스 1개 = 릴스 1개, 큰 글씨 컷을 빠르게 끊어 보여주는 방식.

기존 릴스는 카드뉴스 이미지를 그대로 넘겨서 글씨가 작고 2~3초 안에 다 읽을 수 없었어요.
v2는 화면마다 한 줄(큰 글씨)만 보여주고, 글자가 튀어나오는 움직임으로 끝까지 보게 만들어요.

beats 예시 (Claude가 생성하거나 직접 써도 됨):
[
  {"type": "drop", "kicker": "11.05 · 증시", "big": "닛케이", "number": "−3,000엔"},
  {"type": "text", "kicker": "왜?", "big": "美 민주당 압승\n소식에 급락"},
  {"type": "question", "big": "내 일본 펀드는\n괜찮을까?"},
  {"type": "action", "kicker": "오늘 할 일", "big": "평가액 한 번\n확인해 보세요"},
  {"type": "outro"}
]
"""
import math
import subprocess
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from .motion import pick_bgm
from .render import Painter, pick_theme

W, H, FPS = 1080, 1920, 30
PAD = 96
SAFE_TOP, SAFE_BOTTOM = 300, 1440   # 릴스 UI(위 버튼, 아래 캡션)에 안 가리는 영역
DUR = {"drop": 2.4, "text": 2.0, "question": 2.0, "action": 2.2, "outro": 1.8}
DOWN = "#FF5A5F"


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _back(t):  # 살짝 넘쳤다가 돌아오는 튀는 움직임
    t = max(0.0, min(1.0, t))
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def _hex(c, a=255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


class Stage:
    def __init__(self, cfg, day):
        self.p = Painter(cfg, day)
        th = pick_theme(cfg, day)
        self.bg, self.card, self.accent = th["background"], th["card"], th["accent"]
        self.text, self.sub = th["text"], th["subtext"]
        self._cache = {}

    def layer(self, text, size, color, max_w=W - 2 * PAD, bold=True, spacing=1.16):
        key = (text, size, color, max_w, bold)
        if key in self._cache:
            return self._cache[key]
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        f = self.p.font(size, bold)
        lines = []
        for para in text.split("\n"):
            lines += self.p.wrap(probe, para, f, max_w)
        lh = int(size * spacing)
        wmax = max(int(probe.textlength(ln, font=f)) for ln in lines) + 8
        img = Image.new("RGBA", (wmax, lh * len(lines) + int(size * 0.35)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i, ln in enumerate(lines):
            d.text((0, i * lh), ln, font=f, fill=color)
        self._cache[key] = img
        return img

    @staticmethod
    def put(canvas, layer, x, y, alpha=1.0, scale=1.0, anchor="lt"):
        if alpha <= 0:
            return
        lay = layer
        if abs(scale - 1) > 0.005:
            lay = layer.resize((max(1, round(layer.width * scale)), max(1, round(layer.height * scale))),
                               Image.BILINEAR)
        if alpha < 1:
            lay = lay.copy()
            lay.putalpha(lay.getchannel("A").point(lambda v: int(v * alpha)))
        if anchor == "cc":
            x, y = x - lay.width // 2, y - lay.height // 2
        elif anchor == "lc":
            y = y - lay.height // 2
        canvas.alpha_composite(lay, (int(x), int(y)))


def _frame_base(st: Stage, progress: float):
    img = Image.new("RGBA", (W, H), _hex(st.bg))
    d = ImageDraw.Draw(img)
    # 위쪽 진행 막대: 얼마나 남았는지 보여서 끝까지 보게 됨
    d.rectangle([0, 0, W, 14], fill=_hex(st.card))
    d.rectangle([0, 0, int(W * progress), 14], fill=_hex(st.accent))
    brand = st.layer(st.p.brand, 38, st.sub, bold=False)
    st.put(img, brand, PAD, SAFE_TOP - 90)
    return img


def _kicker(st, img, text, t, y):
    if not text:
        return
    lay = st.layer(text, 50, st.accent)
    k = _ease_out(t / 0.25)
    st.put(img, lay, PAD - 30 * (1 - k), y, alpha=k)


def beat_drop(st, img, b, t, dur):
    """큰 이름 → 하락 그래프가 그려지고 → 숫자가 쾅 찍힘(살짝 흔들림)."""
    _kicker(st, img, b.get("kicker"), t, SAFE_TOP + 130)
    big = st.layer(b["big"], 150, st.text)
    k = _back(t / 0.35)
    st.put(img, big, PAD, SAFE_TOP + 220, alpha=min(1, t / 0.15), scale=0.85 + 0.15 * k)

    # 그래프: 오르락내리락 하다 마지막에 급락
    gx0, gx1, gy0 = PAD, W - PAD, SAFE_TOP + 500
    pts = [(0, .55), (.12, .45), (.25, .5), (.38, .35), (.5, .42), (.62, .3), (.72, .36), (.8, .32), (1, .95)]
    draw_k = _ease_out((t - 0.25) / 0.9)
    if draw_k > 0:
        d = ImageDraw.Draw(img)
        xs = [gx0 + (gx1 - gx0) * px for px, _ in pts]
        ys = [gy0 + 380 * py for _, py in pts]
        end_x = gx0 + (gx1 - gx0) * draw_k
        line = [(xs[0], ys[0])]
        for i in range(1, len(xs)):
            if xs[i] <= end_x:
                line.append((xs[i], ys[i]))
            else:
                r = (end_x - xs[i - 1]) / (xs[i] - xs[i - 1])
                line.append((end_x, ys[i - 1] + (ys[i] - ys[i - 1]) * r))
                break
        col = DOWN if draw_k > 0.8 else st.sub
        d.line(line, fill=_hex(col), width=14, joint="curve")
        cx, cy = line[-1]
        d.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], fill=_hex(col))

    # 숫자 쾅
    tn = t - 1.15
    if tn > 0:
        num = st.layer(b["number"], 210, DOWN)
        k = _back(tn / 0.3)
        shake = 14 * math.sin(tn * 70) * max(0, 1 - tn / 0.35)
        st.put(img, num, W / 2 + shake, SAFE_TOP + 1060, alpha=min(1, tn / 0.08),
               scale=1.6 - 0.6 * k, anchor="cc")


def beat_text(st, img, b, t, dur, color=None, size=136):
    """줄마다 차례로 아래에서 튀어 올라옴."""
    _kicker(st, img, b.get("kicker"), t, SAFE_TOP + 280)
    lines = b["big"].split("\n")
    y = SAFE_TOP + 400
    for i, ln in enumerate(lines):
        lay = st.layer(ln, size, color or st.text)
        tt = t - 0.12 - i * 0.22
        k = _back(tt / 0.35)
        st.put(img, lay, PAD, y + 60 * (1 - min(1, k)), alpha=max(0, min(1, tt / 0.15)))
        y += lay.height + int(size * 0.08)
    return y


def beat_question(st, img, b, t, dur):
    """질문: 화면 가운데에 크게, 밑줄이 그어지고 물음표가 통통."""
    end_y = beat_text(st, img, {"big": b["big"]}, t, dur, color=st.accent, size=146)
    lw = int((W - 2 * PAD) * 0.45 * _ease_out((t - 0.7) / 0.4))
    if lw > 0:
        ImageDraw.Draw(img).rectangle([PAD, end_y + 20, PAD + lw, end_y + 36], fill=_hex(st.accent))


def beat_action(st, img, b, t, dur):
    """할 일: 체크 표시가 찍히며 마무리."""
    _kicker(st, img, b.get("kicker"), t, SAFE_TOP + 220)
    box_y = SAFE_TOP + 330
    d = ImageDraw.Draw(img)
    k = _ease_out((t - 0.1) / 0.3)
    if k > 0:
        d.rounded_rectangle([PAD, box_y, PAD + int((W - 2 * PAD) * k), box_y + 760], 44, fill=_hex(st.card))
    tt = t - 0.35
    if tt > 0:
        lay = st.layer(b["big"], 118, st.text, max_w=W - 2 * PAD - 120)
        st.put(img, lay, PAD + 60, box_y + 80, alpha=min(1, tt / 0.2))
    tc = t - 0.9
    if tc > 0:
        s = _back(tc / 0.3)
        cx, cy, r = W - PAD - 120, box_y + 650, int(70 * s)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_hex(st.accent))
        if tc > 0.15:
            d.line([(cx - 32, cy), (cx - 8, cy + 26), (cx + 36, cy - 26)], fill=_hex(st.bg), width=16)


def beat_outro(st, img, b, t, dur):
    lines = [("매일 아침 7시", 76, st.sub), ("출근길 경제 한 잔", 112, st.text)]
    y = SAFE_TOP + 480
    for i, (txt, size, col) in enumerate(lines):
        lay = st.layer(txt, size, col)
        k = _back((t - i * 0.15) / 0.35)
        st.put(img, lay, W / 2, y + 40 * (1 - min(1, k)), alpha=max(0, min(1, (t - i * 0.15) / 0.15)),
               anchor="cc")
        y += lay.height + 30
    tf = t - 0.5
    if tf > 0:
        k = _back(tf / 0.3)
        bw, bh = int(560 * (0.9 + 0.1 * k)), int(140 * (0.9 + 0.1 * k))
        cx, cy = W // 2, y + 120
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2], bh // 2, fill=_hex(st.accent))
        st.put(img, st.layer("팔로우하고 받아보기", 52, st.bg), cx, cy - 4, anchor="cc")
        st.put(img, st.layer(st.p.handle, 48, st.sub, bold=False), cx, cy + 150, anchor="cc")


BEATS = {"drop": beat_drop, "text": beat_text, "question": beat_question,
         "action": beat_action, "outro": beat_outro}


def make_reel_v2(cfg: dict, beats: list[dict], out: Path, day: date) -> float:
    st = Stage(cfg, day)
    durs = [float(b.get("sec", DUR[b["type"]])) for b in beats]
    total = sum(durs)
    n = round(total * FPS)
    bgm = pick_bgm(cfg.get("reel_bgm_dir", "assets/bgm"), day)

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    cmd += (["-stream_loop", "-1", "-i", str(bgm)] if bgm
            else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
    cmd += ["-filter_complex",
            f"[1:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume=0.8,afade=t=in:d=0.2,"
            f"afade=t=out:st={max(0, total - 0.8):.3f}:d=0.8[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
            "-t", f"{total:.3f}", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    starts = [sum(durs[:i]) for i in range(len(durs))]
    for i in range(n):
        t = i / FPS
        bi = max(j for j, s in enumerate(starts) if s <= t + 1e-9)
        lt = t - starts[bi]
        img = _frame_base(st, t / total)
        BEATS[beats[bi]["type"]](st, img, beats[bi], lt, durs[bi])
        # 컷 사이 짧은 깜빡임 대신 0.12초 페이드인으로 리듬감
        if bi > 0 and lt < 0.12:
            img = Image.blend(Image.new("RGBA", (W, H), _hex(st.bg)), img, lt / 0.12)
        proc.stdin.write(img.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 실패")
    print(f"릴스 v2 생성: {out} ({total:.1f}초, 음원: {bgm.name if bgm else '없음'})")
    return total


if __name__ == "__main__":  # 샘플: python -m src.reel_v2
    import sys
    import yaml
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    sample = [
        {"type": "drop", "kicker": "11.05 · 증시", "big": "닛케이", "number": "−3,000엔"},
        {"type": "text", "kicker": "왜?", "big": "美 민주당 압승\n소식에 급락"},
        {"type": "question", "big": "내 일본 펀드는\n괜찮을까?"},
        {"type": "action", "kicker": "오늘 할 일", "big": "일본 주식·펀드\n평가액 한 번\n확인해 보세요"},
        {"type": "outro"},
    ]
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_reel_v2.mp4")
    make_reel_v2(cfg, sample, out, date(2026, 11, 5))
