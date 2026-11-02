"""카드 이미지(4:5)들 → 릴스용 세로 영상(1080x1920, 9:16). ffmpeg 필요."""
import tempfile
from datetime import date
from pathlib import Path

from .motion import HOOK_SEC, hook_frames, pick_bgm, render_video
from .render import WEEKDAYS, pick_theme


def hook_question(post: dict) -> str:
    q = (post.get("reel_hook") or "").strip()
    if q:
        return q
    tag = (post.get("items") or [{}])[0].get("tag") or "경제"
    return f"{tag} 뉴스, 내 지갑엔 무슨 일?"


def make_reel(cfg: dict, images: list[Path], out: Path, day: date, post: dict | None = None) -> Path:
    """첫 장면 = 움직이는 질문형 훅, 이후 뉴스 카드들(표지는 훅과 겹쳐서 뺌)."""
    images = list(images)
    theme = pick_theme(cfg, day)
    sec = float(cfg.get("reel_seconds_per_card", 3))
    scenes = []
    if post:
        label = "이번 주 경제 총정리" if post.get("weekly") else \
            f"{day.strftime('%m.%d')} {WEEKDAYS[day.weekday()]}요일 경제뉴스"
        answer = post["items"][0]["headline"] if post.get("items") else post.get("cover_title", "")
        pattern = hook_frames(cfg, theme, day, hook_question(post), answer, label,
                              Path(tempfile.mkdtemp(prefix="reel_hook_")))
        scenes.append((pattern, HOOK_SEC, True))
        images = images[1:]  # 글씨 작은 표지 대신 훅으로 시작
    for i, img in enumerate(images):
        scenes.append((str(img), sec + (0.5 if i == len(images) - 1 else 0), False))  # 마지막 장은 조금 길게
    bgm = pick_bgm(cfg.get("reel_bgm_dir", "assets/bgm"), day)
    total = render_video(scenes, out, theme["background"], bgm)
    print(f"릴스 영상 생성: {out} ({total:.1f}초, 음원: {bgm.name if bgm else '없음'})")
    return out


def make_evening_reel(cfg: dict, card: Path, post: dict, theme: dict, out: Path, day: date) -> Path:
    """저녁 이슈 한 장 → 릴스: 질문형 훅 → 이슈 카드(읽을 시간 넉넉히)."""
    from .dayoff import is_day_off
    label = "오늘의 이슈 한 장" if is_day_off(day, cfg) else "퇴근길 이슈 한 장"
    q = (post.get("hook") or "").strip() or f"{post.get('tag', '경제')} 이슈, 나한테 무슨 상관?"
    pattern = hook_frames(cfg, theme, day, q, post["title"], label,
                          Path(tempfile.mkdtemp(prefix="evening_hook_")))
    scenes = [(pattern, HOOK_SEC, True), (str(card), float(cfg.get("evening_reel_card_seconds", 9)), False)]
    bgm = pick_bgm(cfg.get("reel_bgm_dir", "assets/bgm"), day)
    total = render_video(scenes, out, theme["background"], bgm)
    print(f"저녁 릴스 생성: {out} ({total:.1f}초)")
    return out
