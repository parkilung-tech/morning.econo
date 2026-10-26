"""카드 이미지(4:5)들 → 릴스용 세로 영상(1080x1920, 9:16). ffmpeg 필요."""
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from .render import WEEKDAYS, Painter, pick_theme

W, H, FPS = 1080, 1920, 30
FADE = 0.4  # 카드 사이 전환 길이(초)
HOOK_SEC = 2.0  # 첫 장면(헤드라인 큰 글씨) 길이


def make_hook(cfg: dict, post: dict, out: Path, day: date) -> Path:
    """릴스 첫 장면: 세로 화면 가득 그날 헤드라인. 릴스는 첫 1초에 넘길지 정해져서 글씨를 크게."""
    t = pick_theme(cfg, day)
    p = Painter(cfg, day)
    img = Image.new("RGB", (W, H), t["background"])
    d = ImageDraw.Draw(img)
    pad = 90
    d.rectangle([0, 0, W, 16], fill=t["accent"])
    # 인스타 릴스 화면은 위쪽 약 250px, 아래쪽 약 450px가 버튼·캡션에 가려져서 그 사이에 배치
    d.text((pad, 300), cfg["account_name"], font=p.font(40), fill=t["accent"])
    date_txt = f"{day.strftime('%m.%d')} {WEEKDAYS[day.weekday()]}요일 경제뉴스"
    d.text((pad, 560), date_txt, font=p.font(46, bold=False), fill=t["subtext"])
    y = p.block(d, (pad, 650), post["cover_title"], p.font(132), t["text"], W - 2 * pad, 1.18)
    d.rectangle([pad, y + 30, pad + 160, y + 44], fill=t["accent"])
    if post.get("cover_subtitle"):
        p.block(d, (pad, y + 100), post["cover_subtitle"], p.font(54, bold=False), t["subtext"], W - 2 * pad)
    d.text((pad, 1380), cfg["handle"], font=p.font(40, bold=False), fill=t["subtext"])
    img.save(out, "JPEG", quality=92)
    return out


def _pick_bgm(folder: str, day: date) -> Path | None:
    files = sorted(
        p for p in Path(folder).glob("*")
        if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")
    ) if Path(folder).is_dir() else []
    return files[day.toordinal() % len(files)] if files else None  # 날마다 다른 곡


def make_reel(cfg: dict, images: list[Path], out: Path, day: date, post: dict | None = None) -> Path:
    images = list(images)
    if post:  # 작은 글씨 목록이 있는 표지 대신, 큰 헤드라인 첫 장면으로 시작
        images[0] = make_hook(cfg, post, Path(tempfile.gettempdir()) / "reel_hook.jpg", day)
    n = len(images)
    sec = float(cfg.get("reel_seconds_per_card", 3))
    durs = [sec] * n
    durs[0] = HOOK_SEC if post else max(2.0, sec - 0.5)
    durs[-1] = sec + 0.5           # 마지막 장은 조금 길게
    total = sum(durs) - FADE * (n - 1)
    bg = pick_theme(cfg, day)["background"].lstrip("#")
    bgm = _pick_bgm(cfg.get("reel_bgm_dir", "assets/bgm"), day)

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for img, d in zip(images, durs):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(img)]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = [
        f"[{i}:v]scale={W}:-2:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{bg},"
        f"setsar=1,format=yuv420p,fps={FPS}[v{i}]"
        for i in range(n)
    ]
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
    print(f"릴스 영상 생성: {out} ({total:.1f}초, 음원: {bgm.name if bgm else '없음'})")
    return out
