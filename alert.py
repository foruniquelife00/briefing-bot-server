import yfinance as yf
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from watchlist import load_watchlist, STOCK_MAP
# ★ requests / config 직접 import 제거 (2026-09-04)
#   자체 requests.post로 텔레그램을 발송하던 코드가 버그의 원인이었다.
#   발송은 sender.send_telegram(검증된 경로)에 위임한다 — check_alerts()에서 지연 import.

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
    """
    '오늘 이 종목 알림을 이미 보냈다'고 기록만 한다. 발송은 하지 않는다.

    ★ 2026-09-04 수정 — 이 함수가 기록과 발송을 겸하면서 3중 실패가 있었다:
        1) 미정의 변수 `message`를 참조해 NameError → 알림이 실제로 발송되지 않음
        2) 그런데 save_alert_log()가 먼저 실행되어 '오늘 보냄'으로 기록 → 재시도 차단
        3) 호출측은 그대로 "알림 발송" 로그를 출력 → 성공처럼 보임
      except가 NameError를 삼켜 몇 달간 조용히 미발송 상태였다.
      → 발송 책임을 sender.send_telegram(검증된 경로: HTTP status 확인·bool 반환)으로
        옮기고, 이 함수는 기록만 한다. 기록은 '발송 성공 후'에만 호출한다.
      (CLAUDE.md 보고 원칙: "완료 로그 ≠ 성공", "실패는 조용히 넘기지 않는다")
    """
    log = load_alert_log()
    log[name] = today
    save_alert_log(log)

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

    if not alerts:
        print(f"급등락 없음 ({len(watchlist)}개 스캔)")
        return {"attempted": 0, "sent": 0, "failed": 0, "errors": []}

    return dispatch_alerts(alerts, today)


def dispatch_alerts(alerts: list, today: str, sender=None) -> dict:
    """
    급등락 알림 발송 → **성공한 것만** 기록.

    ★ 2026-09-04 신설 — 순서가 이 함수의 존재 이유다.
      기록을 먼저 하면 발송 실패 시 그날 재시도가 영구히 막힌다(직전 버그의 핵심).
      반드시 '발송 성공 확인 → 기록' 순서를 지킨다.

    alerts: [(종목명, 메시지), ...]
    sender: 발송 함수(msg)->bool. 기본값은 sender.send_telegram.
            테스트에서 주입할 수 있도록 인자로 분리했다.
    반환: {"attempted","sent","failed","errors"}
    실패가 1건이라도 있으면 RuntimeError — 조용히 넘기지 않는다.
    """
    if sender is None:
        from sender import send_telegram   # 헤더·4096자 분할·상태확인 포함
        sender = send_telegram

    sent = failed = 0
    errors = []
    for name, msg in alerts:
        if sender(msg):
            mark_alerted(name, today)          # ★ 성공했을 때만 '보냄' 기록
            sent += 1
            print(f"알림 발송 성공: {name}")
        else:
            failed += 1
            errors.append(name)
            # 기록하지 않으므로 다음 30분 주기에 자동 재시도된다
            print(f"[ERROR] 알림 발송 실패: {name} — 미기록(다음 주기 재시도)")

    result = {"attempted": len(alerts), "sent": sent,
              "failed": failed, "errors": errors}
    if failed:
        # 조용히 넘기지 않는다 — 호출측(bot.run_alert)이 logging.error로 남긴다
        raise RuntimeError(
            f"급등락 알림 발송 실패 {failed}/{len(alerts)}건: {', '.join(errors)}")
    return result

if __name__ == "__main__":
    print(get_alert_settings_text())
    print(f"\n장 시간 여부: {is_market_hours()}")
