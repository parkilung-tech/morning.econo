"""릴스용 움직이는 첫 장면(질문형 훅) + 장면 이어붙이기. ffmpeg 필요.

릴스는 첫 1~2초에 넘길지 정해져서, 정지 화면 대신
질문이 튀어나오고 → 밑줄이 그어지고 → 답(숫자)이 올라오는 짧은 움직임으로 시작해요.
첫 프레임부터 질문이 보이게 해서 넘기기 전에 읽히도록 했어요.
"""
import math
import subprocess
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from .render import Painter

W, H, FPS = 1080, 1920, 30
FADE = 0.4         # 장면 사이 전환 길이(초)
HOOK_SEC = 2.8     # 움직이는 첫 장면 길이
PAD = 90


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _phase(t: float, start: float, end: float) -> float:
    return _ease((t - start) / (end - start))


def _text_layer(p: Painter, text: str, sizes, color, max_w, spacing=1.18, max_lines=3, bold=True):
    """글씨만 투명 배경에 그린 레이어 (크기를 바꿔가며 max_lines 안에 맞춤)."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for s in sizes:
        f = p.font(s, bold)
        lines = []
        for para in text.split("\n"):
            lines += p.wrap(probe, para, f, max_w)
        if len(lines) <= max_lines:
            break
    lh = int(f.size * spacing)
    layer = Image.new("RGBA", (max_w, lh * len(lines) + int(f.size * 0.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, ln in enumerate(lines):
        d.text((0, i * lh), ln, font=f, fill=color)
    return layer


def _fade(layer: Image.Image, a: float) -> Image.Image:
    if a >= 1:
        return layer
    out = layer.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * a)))
    return out


def hook_frames(cfg: dict, theme: dict, day: date, question: str, answer: str,
                top_label: str, out_dir: Path, seconds: float = HOOK_SEC) -> str:
    """질문형 훅 장면을 프레임 이미지들로 저장하고 ffmpeg 입력 패턴을 돌려줌."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("hook_*.jpg"):
        old.unlink()
    p = Painter(cfg, day)
    bg, accent, text, sub = theme["background"], theme["accent"], theme["text"], theme["subtext"]
    inner = W - 2 * PAD

    q = _text_layer(p, question, (128, 116, 104, 92), text, inner)
    a = _text_layer(p, answer, (64, 58, 52), accent, inner, 1.25, 2)
    lab = _text_layer(p, top_label, (40,), sub, inner, max_lines=1, bold=False)
    down = _text_layer(p, "3분 정리 ↓", (44,), sub, inner, max_lines=1, bold=False)

    # 인스타 릴스 화면은 위 약 250px, 아래 약 450px가 버튼·캡션에 가려져서 그 사이에 배치
    q_y = 560
    line_y = q_y + q.height + 24
    a_y = line_y + 70

    base = Image.new("RGB", (W, H), bg)
    bd = ImageDraw.Draw(base)
    bd.rectangle([0, 0, W, 16], fill=accent)
    bd.text((PAD, 300), p.brand, font=p.font(40), fill=accent)
    base = base.convert("RGBA")
    base.alpha_composite(lab, (PAD, 380))

    n = round(seconds * FPS)
    for i in range(n):
        t = i / FPS
        img = base.copy()
        # 1) 질문: 첫 프레임부터 보이고, 살짝 커지며 제자리로 (0~0.45초)
        k = _phase(t, 0, 0.45)
        scale = 0.9 + 0.1 * k
        qs = q.resize((max(1, round(q.width * scale)), max(1, round(q.height * scale))), Image.LANCZOS)
        img.alpha_composite(_fade(qs, 0.75 + 0.25 * k), (PAD, q_y + round(40 * (1 - k))))
        # 2) 밑줄이 그어짐 (0.35~0.75초)
        lw = round(200 * _phase(t, 0.35, 0.75))
        if lw > 0:
            ImageDraw.Draw(img).rectangle([PAD, line_y, PAD + lw, line_y + 14], fill=accent)
        # 3) 답(그날 핵심 숫자 뉴스)이 아래에서 올라옴 (0.6~1.05초)
        k = _phase(t, 0.6, 1.05)
        if k > 0:
            img.alpha_composite(_fade(a, k), (PAD, a_y + round(50 * (1 - k))))
        # 4) '3분 정리 ↓' 가 나타나서 살짝 통통 튐 (1.1초~)
        k = _phase(t, 1.1, 1.45)
        if k > 0:
            bounce = round(10 * math.sin((t - 1.1) * 2 * math.pi * 1.4)) if t > 1.45 else 0
            img.alpha_composite(_fade(down, k), (PAD, 1360 + bounce))
        img.convert("RGB").save(out_dir / f"hook_{i:03d}.jpg", "JPEG", quality=93)
    return str(out_dir / "hook_%03d.jpg")


def pick_bgm(folder: str, day: date) -> Path | None:
    files = sorted(
        p for p in Path(folder).glob("*")
        if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")
    ) if Path(folder).is_dir() else []
    return files[day.toordinal() % len(files)] if files else None  # 날마다 다른 곡


def render_video(scenes: list[tuple[str, float, bool]], out: Path, bg_hex: str, bgm: Path | None) -> float:
    """scenes = [(이미지 또는 프레임 패턴, 길이(초), 프레임 묶음 여부)] → 1080x1920 mp4."""
    n = len(scenes)
    durs = [d for _, d, _ in scenes]
    total = sum(durs) - FADE * (n - 1)
    bg = bg_hex.lstrip("#")

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for src, d, is_seq in scenes:
        if is_seq:
            cmd += ["-framerate", str(FPS), "-i", src]
        else:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", src]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = []
    for i, (_, d, is_seq) in enumerate(scenes):
        # 프레임 묶음은 마지막 프레임을 조금 늘려서 전환 중에도 화면이 비지 않게
        hold = f",tpad=stop_mode=clone:stop_duration={FADE}" if is_seq else ""
        parts.append(
            f"[{i}:v]scale={W}:-2:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{bg},"
            f"setsar=1,format=yuv420p,fps={FPS}{hold}[v{i}]"
        )
    last, offset = "v0", 0.0
    for i in range(1, n):
        offset += durs[i - 1] - FADE
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[x{i}]")
        last = f"x{i}"
    parts.append(
        f"[{n}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume=0.8,"
        f"afade=t=in:d=0.3,afade=t=out:st={max(0, total - 1):.3f}:d=1[a]"
    )
    cmd += [
        "-filter_complex", ";".join(parts), "-map", f"[{last}]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{total:.3f}", str(out),
    ]
    subprocess.run(cmd, check=True)
    return total
