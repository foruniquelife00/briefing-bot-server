import requests
import time
import logging
from datetime import datetime, timezone, timedelta
import threading
import schedule
from pathlib import Path

import config
from watchlist import (
    add_stock, remove_stock, get_watchlist_text,
    get_stock_price, get_available_stocks
)

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    filename=str(BASE_DIR / "briefing.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE_URL = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"

HELP_MSG = """안녕하세요! 투자 브리핑 봇입니다 📊

📋 워치리스트 관리
  /목록 — 현재 워치리스트 확인
  /추가 종목명 — 종목 추가
  /삭제 종목명 — 종목 삭제
  /종목목록 — 추가 가능한 전체 종목

📈 시세 조회
  /시세 종목명 — 실시간 시세 조회

📊 성과 확인
  /성과 — 이번 주 추천 종목 성과
  /누적성과 — 최근 20일 누적 성과

❓ /help — 도움말"""


def get_updates(offset=None):
    try:
        res = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"timeout": 30, "offset": offset},
            timeout=35
        )
        return res.json().get("result", [])
    except Exception as e:
        logging.error(f"getUpdates 오류: {e}")
        return []


_BOT_HEADER = "📰 [브리핑봇]\n"   # briefing-bot-server 식별 헤더


def send_message(chat_id: int, text: str):
    try:
        tagged = _BOT_HEADER + text
        chunks = [tagged[i:i+4000] for i in range(0, len(tagged), 4000)]
        for chunk in chunks:
            requests.post(f"{BASE_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text":    chunk,
            }, timeout=30)
    except Exception as e:
        logging.error(f"sendMessage 오류: {e}")


def handle_message(chat_id: int, text: str):
    text = text.strip()
    logging.info(f"수신: '{text}' from {chat_id}")

    if text in ("/start", "/help"):
        send_message(chat_id, HELP_MSG)
        return

    if text == "/목록":
        send_message(chat_id, get_watchlist_text())
        return

    if text == "/종목목록":
        send_message(chat_id, get_available_stocks())
        return

    if text.startswith("/추가 "):
        send_message(chat_id, add_stock(text[4:].strip()))
        return

    if text.startswith("/삭제 "):
        send_message(chat_id, remove_stock(text[4:].strip()))
        return

    if text.startswith("/시세 "):
        name = text[4:].strip()
        send_message(chat_id, f"🔍 {name} 시세 조회 중...")
        send_message(chat_id, get_stock_price(name))
        return

    if text == "/성과":
        from performance import generate_weekly_report
        send_message(chat_id, generate_weekly_report())
        return

    if text == "/누적성과":
        from performance import get_all_performance
        send_message(chat_id, get_all_performance())
        return

    if text == "/알림목록":
        from alert import get_alert_settings_text
        send_message(chat_id, get_alert_settings_text())
        return

    if text.startswith("/알림설정 "):
        parts = text[6:].strip().split()
        if len(parts) >= 2:
            try:
                name = " ".join(parts[:-1])
                val  = float(parts[-1])
                from alert import set_alert_threshold
                send_message(chat_id, set_alert_threshold(name, val))
            except:
                send_message(chat_id, "사용법: /알림설정 종목명 숫자 (예: /알림설정 삼성전자 5)")
        return

    if text.startswith("/알림삭제 "):
        name = text[6:].strip()
        from alert import delete_alert_threshold
        send_message(chat_id, delete_alert_threshold(name))
        return

    if text == "/포트폴리오":
        from portfolio import get_portfolio_status
        send_message(chat_id, get_portfolio_status())
        return

    if text.startswith("/포트폴리오추가 ") or text.startswith("/포트폴리오 추가 "):
        parts = text[9:].strip().split()
        if len(parts) >= 3:
            try:
                raw = text.replace("/포트폴리오 추가 ", "").replace("/포트폴리오추가 ", "")
                parts = raw.split()
                name  = " ".join(parts[:-2])
                qty   = float(parts[-2])
                price = float(parts[-1].replace(",",""))
                from portfolio import add_portfolio
                send_message(chat_id, add_portfolio(name, qty, price))
            except:
                send_message(chat_id, "사용법: /포트폴리오추가 종목명 수량 매수가\n예: /포트폴리오추가 삼성전자 10 204000")
        return

    if text.startswith("/포트폴리오삭제 "):
        name = text[9:].strip()
        from portfolio import remove_portfolio
        send_message(chat_id, remove_portfolio(name))
        return

    if text == "/백테스팅":
        send_message(chat_id, "🔬 백테스팅 분석 중...")
        from backtest import run_backtest, format_backtest_report, save_backtest_to_db
        bt = run_backtest()
        save_backtest_to_db(bt)
        send_message(chat_id, format_backtest_report(bt))
        return

    if not text.startswith("/"):
        return

    send_message(chat_id, "❓ 알 수 없는 명령어예요.\n/help 를 입력하면 사용 가능한 명령어를 볼 수 있어요.")


# ── 스케줄러 ──────────────────────────────────────

def run_briefing():
    weekday = datetime.now(timezone.utc).weekday()
    if weekday >= 5:
        logging.info("주말 — 브리핑 건너뜀")
        return
    logging.info("브리핑 시작")
    try:
        from collector  import get_market_data
        from analyzer   import analyze_and_save
        from sender     import send_telegram, send_email
        from datetime   import datetime as dt
        data    = get_market_data()
        msg     = analyze_and_save(data)
        tg_ok   = send_telegram(msg)
        subject = f"📊 투자 브리핑 | {dt.now().strftime('%Y-%m-%d (%a)')}"
        em_ok   = send_email(subject, msg)
        logging.info(f"브리핑 텔레그램={'성공' if tg_ok else '실패'} / 이메일={'성공' if em_ok else '실패'}")
    except Exception as e:
        logging.error(f"브리핑 오류: {e}")

def run_monthly_if_first():
    from datetime import datetime, timezone
    if datetime.now(timezone.utc).day == 1:
        try:
            from monthly_report import send_monthly_report
            send_monthly_report()
        except Exception as e:
            logging.error(f"월간 리포트 오류: {e}")

def run_friday():
    try:
        from weekly_report import send_friday_report
        send_friday_report()
    except Exception as e:
        logging.error(f"금요일 리포트 오류: {e}")

def run_weekly():
    try:
        from weekly_report import send_weekly_report
        send_weekly_report()
    except Exception as e:
        logging.error(f"주간 뉴스레터 오류: {e}")

def run_alert():
    try:
        from alert import check_alerts
        check_alerts()
    except Exception as e:
        logging.error(f"알림 오류: {e}")

def run_event_detection():
    """30분마다 실시간 이벤트 감지"""
    try:
        from event_engine import run_event_detection as detect
        detect()
    except Exception as e:
        logging.error(f"이벤트 감지 오류: {e}")


def is_market_open() -> bool:
    """한국 장 시간 체크 (KST 09:00~15:30 평일)"""
    from datetime import datetime, timezone, timedelta
    kst = datetime.now(timezone(timedelta(hours=9)))
    if kst.weekday() >= 5:
        return False
    h, m = kst.hour, kst.minute
    return (h == 9) or (10 <= h <= 14) or (h == 15 and m <= 30)


def is_daytime() -> bool:
    """낮 시간 체크 (KST 07:00~23:00)"""
    from datetime import datetime, timezone, timedelta
    kst = datetime.now(timezone(timedelta(hours=9)))
    return 7 <= kst.hour <= 23


def run_alert_if_market_open():
    """장 시간에만 급등락 알림"""
    if is_market_open():
        run_alert()


def run_event_detection_if_daytime():
    """낮 시간에만 이벤트 감지"""
    if is_daytime():
        run_event_detection()

def run_git_backup():
    """매일 GitHub 자동 백업"""
    try:
        import subprocess
        from datetime import datetime, timezone, timedelta
        kst  = datetime.now(timezone(timedelta(hours=9)))
        date = kst.strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "-C", str(BASE_DIR), "add", "."], check=True)
        result = subprocess.run(
            ["git", "-C", str(BASE_DIR), "commit", "-m", f"🤖 자동 백업: {date}"],
            capture_output=True, text=True
        )
        if "nothing to commit" not in result.stdout:
            subprocess.run(["git", "-C", str(BASE_DIR), "push"], check=True)
            logging.info("GitHub 백업 완료")
        else:
            logging.info("GitHub 백업: 변경사항 없음")
    except Exception as e:
        logging.error(f"GitHub 백업 오류: {e}")



def run_scheduler():
    # KST 07:30 = UTC 22:30
    schedule.every().day.at("22:30").do(run_briefing)
    schedule.every().monday.at("22:30").do(run_weekly)
    schedule.every().friday.at("14:00").do(run_friday)
    schedule.every().day.at("22:30").do(run_monthly_if_first)
    schedule.every(30).minutes.do(run_alert_if_market_open)
    schedule.every(60).minutes.do(run_event_detection_if_daytime)
    schedule.every().day.at("01:00").do(run_git_backup)

    logging.info("스케줄러 시작 — KST 07:30 브리핑 / 30분마다 알림")
    print("스케줄러 시작 — KST 07:30 브리핑 / 30분마다 알림")

    while True:
        schedule.run_pending()
        time.sleep(30)


def main():
    # 명령어 등록
    commands = [
        {"command": "목록",     "description": "워치리스트 확인"},
        {"command": "추가",     "description": "종목 추가 (예: /추가 삼성전자)"},
        {"command": "삭제",     "description": "종목 삭제 (예: /삭제 삼성전자)"},
        {"command": "시세",     "description": "실시간 시세 (예: /시세 삼성전자)"},
        {"command": "종목목록", "description": "추가 가능한 전체 종목"},
        {"command": "성과",     "description": "이번 주 성과"},
        {"command": "누적성과", "description": "최근 20일 누적 성과"},
        {"command": "help",     "description": "도움말"},
    ]
    try:
        requests.post(f"{BASE_URL}/setMyCommands", json={"commands": commands})
    except Exception as e:
        logging.error(f"명령어 등록 오류: {e}")

    # 시작 시 오늘 브리핑 없으면 즉시 실행
    import sqlite3 as _sqlite3
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _kst = _dt.now(_tz(_td(hours=9)))
    _today = _kst.strftime("%Y-%m-%d")
    if _kst.weekday() < 5:
        try:
            _conn = _sqlite3.connect(config.DB_PATH)
            _row = _conn.execute("SELECT id FROM briefing_history WHERE date = ?", (_today,)).fetchone()
            _conn.close()
            if not _row:
                logging.info("오늘 브리핑 없음 → 즉시 실행")
                threading.Thread(target=run_briefing, daemon=True).start()
        except Exception as _e:
            logging.error(f"브리핑 체크 오류: {_e}")

    # 스케줄러 백그라운드 스레드
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()

    print("봇 시작! 메시지 대기 중...")
    logging.info("봇 시작")

    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or update.get("channel_post")
            if not message:
                continue
            chat_id = message["chat"]["id"]
            text    = message.get("text", "")
            if text:
                handle_message(chat_id, text)
        time.sleep(1)


if __name__ == "__main__":
    main()


import requests
import time
import logging
from datetime import datetime, timezone, timedelta
import threading
import schedule

import config
from watchlist import (
    add_stock, remove_stock, get_watchlist_text,
    get_stock_price, get_available_stocks
)

logging.basicConfig(
    filename=str(BASE_DIR / "briefing.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE_URL = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"

HELP_MSG = """안녕하세요! 투자 브리핑 봇입니다 📊

📋 워치리스트 관리
  /목록 — 현재 워치리스트 확인
  /추가 종목명 — 종목 추가
  /삭제 종목명 — 종목 삭제
  /종목목록 — 추가 가능한 전체 종목

📈 시세 조회
  /시세 종목명 — 실시간 시세 조회

📊 성과 확인
  /성과 — 이번 주 추천 종목 성과
  /누적성과 — 최근 20일 누적 성과

❓ /help — 도움말"""


