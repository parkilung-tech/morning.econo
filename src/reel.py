"""카드 이미지(4:5)들 → 릴스용 세로 영상(1080x1920, 9:16). ffmpeg 필요."""
import subprocess
from datetime import date
from pathlib import Path

from .render import pick_theme

W, H, FPS = 1080, 1920, 30
FADE = 0.4  # 카드 사이 전환 길이(초)


def _pick_bgm(folder: str, day: date) -> Path | None:
    files = sorted(
        p for p in Path(folder).glob("*")
        if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")
    ) if Path(folder).is_dir() else []
    return files[day.toordinal() % len(files)] if files else None  # 날마다 다른 곡


def make_reel(cfg: dict, images: list[Path], out: Path, day: date) -> Path:
    n = len(images)
    sec = float(cfg.get("reel_seconds_per_card", 3))
    durs = [sec] * n
    durs[0] = max(2.0, sec - 0.5)  # 표지는 짧게
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
