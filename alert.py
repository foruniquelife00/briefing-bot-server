import yfinance as yf
import requests
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import config
from watchlist import load_watchlist, STOCK_MAP

BASE_DIR = Path(__file__).resolve().parent
ALERT_LOG_FILE      = str(BASE_DIR / "alert_log.json")
ALERT_SETTINGS_FILE = str(BASE_DIR / "alert_settings.json")
DEFAULT_THRESHOLD   = 3.0  # 기본 임계값 3%

def load_alert_log() -> dict:
    if os.path.exists(ALERT_LOG_FILE):
        with open(ALERT_LOG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_alert_log(log: dict):
    with open(ALERT_LOG_FILE, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def load_alert_settings() -> dict:
    """종목별 개인화 임계값 로드"""
    if os.path.exists(ALERT_SETTINGS_FILE):
        with open(ALERT_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_alert_settings(settings: dict):
    with open(ALERT_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def set_alert_threshold(name: str, threshold: float) -> str:
    """종목 알림 임계값 설정"""
    if name not in STOCK_MAP:
        return f"❌ '{name}' 는 지원하지 않는 종목이에요."
    if threshold < 1 or threshold > 20:
        return f"❌ 임계값은 1~20% 사이로 설정해주세요."
    settings = load_alert_settings()
    settings[name] = threshold
    save_alert_settings(settings)
    return f"✅ '{name}' 알림 임계값을 ±{threshold}%로 설정했어요."

def delete_alert_threshold(name: str) -> str:
    """종목 알림 임계값 삭제 (기본값으로 복원)"""
    settings = load_alert_settings()
    if name not in settings:
        return f"⚠️ '{name}' 는 개인 설정이 없어요. (기본값 ±{DEFAULT_THRESHOLD}% 적용 중)"
    del settings[name]
    save_alert_settings(settings)
    return f"✅ '{name}' 알림 설정을 삭제했어요. (기본값 ±{DEFAULT_THRESHOLD}%로 복원)"

def get_alert_settings_text() -> str:
    """현재 알림 설정 목록"""
    settings  = load_alert_settings()
    watchlist = load_watchlist()

    lines = [f"🔔 알림 임계값 설정\n(기본값: ±{DEFAULT_THRESHOLD}%)\n"]

    custom = {k: v for k, v in settings.items() if k in watchlist}
    default = [s for s in watchlist if s not in settings]

    if custom:
        lines.append("⚙️ 개인 설정")
        for name, val in custom.items():
            lines.append(f"  • {name}: ±{val}%")

    if default:
        lines.append(f"\n📋 기본값 적용 ({len(default)}개)")
        lines.append(f"  ±{DEFAULT_THRESHOLD}% 적용 중")

    lines.append("\n명령어: /알림설정 종목명 숫자 | /알림삭제 종목명")
    return "\n".join(lines)

def is_market_hours() -> bool:
    """KST 09:00~15:30 장 시간 체크"""
    kst     = datetime.now(timezone(timedelta(hours=9)))
    weekday = kst.weekday()
    if weekday >= 5:
        return False
    hour   = kst.hour
    minute = kst.minute
    if hour < 9:
        return False
    if hour > 15:
        return False
    if hour == 15 and minute > 30:
        return False
    return True

def already_alerted(name: str, today: str) -> bool:
    log = load_alert_log()
    return log.get(name) == today

def mark_alerted(name: str, today: str):
    log = load_alert_log()
    log[name] = today
    save_alert_log(log)

    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text":    message,
        }, timeout=10)
    except Exception as e:
        print(f"텔레그램 오류: {e}")

def check_alerts():
    """워치리스트 전체 스캔 후 급등락 알림"""
    if not is_market_hours():
        print("장 시간 외 — 스킵")
        return

    today     = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    watchlist = load_watchlist()
    settings  = load_alert_settings()
    alerts    = []

    for name in watchlist:
        ticker = STOCK_MAP.get(name)
        if not ticker:
            continue
        if already_alerted(name, today):
            continue

        # 종목별 임계값 (개인 설정 or 기본값)
        threshold = settings.get(name, DEFAULT_THRESHOLD)

        try:
            t      = yf.Ticker(ticker)
            info   = t.fast_info
            price  = info.last_price
            prev   = info.regular_market_previous_close
            rate   = (price - prev) / prev * 100
            is_kr  = ticker.endswith(".KS") or ticker.endswith(".KQ")

            if abs(rate) < threshold:
                continue

            arrow  = "🚀" if rate >= 5 else "▲" if rate > 0 else "💥" if rate <= -5 else "▼"
            fmt    = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"

            high52 = info.year_high
            low52  = info.year_low
            extra  = ""
            if price >= high52 * 0.98:
                extra = "\n  🏆 52주 신고가 근접!"
            elif price <= low52 * 1.02:
                extra = "\n  ⚠️ 52주 신저가 근접!"

            msg = (
                f"🚨 급등락 알림\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{arrow} {name} ({ticker})\n"
                f"  현재가: {fmt(price)}\n"
                f"  등락:   {rate:+.2f}% (임계값 ±{threshold}%){extra}\n"
                f"  기준가: {fmt(prev)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            alerts.append((name, msg))

        except Exception as e:
            print(f"{name} 오류: {e}")

    for name, msg in alerts:
        mark_alerted(name, today)
        print(f"알림 발송: {name}")

    if not alerts:
        print(f"급등락 없음 ({len(watchlist)}개 스캔)")

if __name__ == "__main__":
    print(get_alert_settings_text())
    print(f"\n장 시간 여부: {is_market_hours()}")
