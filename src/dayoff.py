"""오늘이 쉬는 날(토·일·공휴일)인지 판단. 쉬는 날엔 '출근길·퇴근길' 표현을 쓰지 않아요."""
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def holiday_name(day: date, cfg: dict | None = None) -> str:
    """공휴일 이름 (공휴일이 아니면 빈 문자열). 대체공휴일·선거일 포함."""
    extra = {str(k): v for k, v in ((cfg or {}).get("extra_days_off") or {}).items()}
    if day.isoformat() in extra:
        return str(extra[day.isoformat()] or "휴일")
    try:
        import holidays  # GitHub Actions에서 requirements.txt로 설치됨
        return holidays.KR(years=day.year, language="ko").get(day, "") or ""
    except Exception:  # noqa: BLE001  (패키지가 없으면 주말만 판단)
        return ""


def is_day_off(day: date | None = None, cfg: dict | None = None) -> bool:
    day = day or datetime.now(KST).date()
    return day.weekday() >= 5 or bool(holiday_name(day, cfg))


def describe(day: date | None = None, cfg: dict | None = None) -> str:
    """프롬프트용 설명: '토요일', '공휴일(성탄절)' 등. 평일이면 빈 문자열."""
    day = day or datetime.now(KST).date()
    name = holiday_name(day, cfg)
    if name:
        return f"공휴일({name})"
    return "토요일" if day.weekday() == 5 else "일요일" if day.weekday() == 6 else ""


def brand_name(cfg: dict, day: date | None = None) -> str:
    """카드 상단 브랜드명. 쉬는 날엔 '출근길' 대신 '주말/휴일 경제 한 잔'."""
    day = day or datetime.now(KST).date()
    if not is_day_off(day, cfg):
        return cfg["account_name"]
    return cfg.get("dayoff_brand_holiday" if holiday_name(day, cfg) else "dayoff_brand_weekend") or (
        "휴일 경제 한 잔" if holiday_name(day, cfg) else "주말 경제 한 잔")
