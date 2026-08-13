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
    # KST 기준 요일 판단 (UTC 기준이면 KST 월요일=UTC 일요일로 오판 → 월요일 누락)
    weekday = datetime.now(timezone(timedelta(hours=9))).weekday()
    if weekday >= 5:
        logging.info("주말 — 브리핑 건너뜀")
        return
    logging.info("브리핑 시작")
    print("[브리핑] 시작", flush=True)   # oneshot timer.log 추적용
    try:
        from collector  import get_market_data
        from analyzer   import analyze_and_save
        from sender     import send_telegram, send_email
        from datetime   import datetime as dt
        data    = get_market_data()
        print("[브리핑] 수집 완료 → 분석 시작", flush=True)
        msg     = analyze_and_save(data)
        print("[브리핑] 분석 완료 → 발송", flush=True)

        # ── 역할 경계 C+ 하이브리드 (GPT 20260807 §2) ──
        #   독립 1~2줄 위반 → 그 줄만 제거 후 발송 (sent_redacted)
        #   섹션제목/연속줄/3줄이상/문맥붕괴 → 전체 차단 (blocked_role_boundary)
        #   검사기 오류 → fail-safe 전체 차단
        # 발송 결과는 briefing_delivery_log에 기록한다 (§3 — history는 생성 증거일 뿐).
        from role_boundary import apply_cplus, audit_only
        from datetime import datetime as _dt
        import delivery_status as DS
        _tag = f"daily_{_dt.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')}"
        _rec = {"kind": "daily", "generated_ok": 1, "role_boundary_checked": 1}

        cp = apply_cplus(msg)
        audit_only(msg, _tag)                       # 오탐·정탐 사례는 계속 기록 (§4)
        _rec["role_boundary_action"] = cp["action"]
        _rec["violation_types"] = ", ".join(sorted({v["type"] for v in cp["violations"]})) or None
        _rec["redacted_count"] = len(cp["removed"])

        if cp["action"] == "block":
            logging.error(f"[역할경계] 전체 차단: {cp['reason']} / "
                          f"{[v['type'] for v in cp['violations']]}")
            print(f"[브리핑] ⛔ 전체 차단 — {cp['reason']}", flush=True)
            notified = 0
            try:
                types = ", ".join(sorted({v["type"] for v in cp["violations"]}))
                notified = int(bool(send_telegram(
                    "⛔ <b>브리핑 발송 차단</b> (역할 경계 C+)\n"
                    f"사유: {cp['reason']}\n유형: {types}\n"
                    "매매 지시성 문구가 제거로 해결되지 않아 전체 차단됐습니다.\n"
                    "원문은 서버 role_boundary_audit.log 참조.\n"
                    "※ 오탐일 수 있습니다 — 확인 후 검사기 조정 필요")))
            except Exception as _ne:
                logging.error(f"[역할경계] 차단 알림 발송 실패: {_ne}")
            DS.record(final_delivery_status=DS.BLOCKED, notified=notified,
                      detail=cp["reason"], **_rec)
            return

        if cp["action"] == "redact":
            msg = cp["text"]
            logging.warning(f"[역할경계] 부분 제거 후 발송: {len(cp['removed'])}줄 — "
                            f"{[t for t, _ in cp['removed']]}")
            print(f"[브리핑] ✂ {len(cp['removed'])}줄 제거 후 발송", flush=True)
            try:
                rm = "\n".join(f"· [{t}] {s[:60]}" for t, s in cp["removed"])
                send_telegram("✂ <b>브리핑 일부 문장 제거</b> (역할 경계 C+)\n"
                              "아래 문장이 매매지시성으로 판단돼 제거된 뒤 발송됩니다.\n"
                              f"{rm}\n※ 오탐이면 알려주세요 — 검사기 조정 필요")
            except Exception as _ne:
                logging.error(f"[역할경계] 제거 알림 발송 실패: {_ne}")

        # ── 발송 + 결과 기록 (§3) ──
        tg_ok   = send_telegram(msg)
        subject = f"📊 투자 브리핑 | {dt.now().strftime('%Y-%m-%d (%a)')}"
        em_ok   = send_email(subject, msg)
        # 이메일은 None=비활성 / False=실패 / True=성공 (2026-08-13 중단 결정)
        em_txt = "성공" if em_ok else ("비활성" if em_ok is None else "실패")
        logging.info(f"브리핑 텔레그램={'성공' if tg_ok else '실패'} / 이메일={em_txt}")
        print(f"[브리핑] 텔레그램={'성공' if tg_ok else '실패'} / 이메일={em_txt}", flush=True)

        if tg_ok:
            final = DS.SENT_REDACTED if cp["action"] == "redact" else DS.SENT_FULL
            notified = 1 if cp["action"] == "redact" else 0
        else:
            final = DS.FAILED_DELIVERY
            notified = 0
            logging.error("[브리핑] 텔레그램 발송 실패 — failed_delivery")
        DS.record(send_attempted=1, telegram_ok=int(bool(tg_ok)), email_ok=int(bool(em_ok)),
                  final_delivery_status=final, notified=notified, **_rec)

    except Exception as e:
        import traceback
        logging.error(f"브리핑 오류: {e}")
        print(f"[브리핑] 오류: {e}", flush=True)
        traceback.print_exc()   # timer.log에 전체 traceback
        # 생성/발송 어느 단계든 예외면 failed 로 남긴다 (조용한 실패 방지)
        try:
            import delivery_status as _DS
            _DS.record(kind="daily", generated_ok=0,
                       final_delivery_status=_DS.FAILED_GEN, detail=str(e)[:200])
        except Exception:
            pass

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


def run_briefing_review():
    """KST 17:50 - 아침 브리핑 복기 (DB/로그 기록만, 텔레그램 발송 안 함)"""
    weekday = datetime.now(timezone(timedelta(hours=9))).weekday()
    if weekday >= 5:
        return
    try:
        from evaluator import evaluate_briefing
        result = evaluate_briefing()
        logging.info(f"브리핑 복기 완료\n{result}")
        print(f"[복기]\n{result}")
        # 초기 단계: 텔레그램 자동 발송 안 함 (품질 확인 후 활성화)
    except Exception as e:
        logging.error(f"브리핑 복기 오류: {e}")


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
    # ⚠ 일일 브리핑(06:50)·복기(17:50)는 systemd timer로 이관 (GPT B안, 2026-07-10)
    #   briefing-morning.timer / briefing-review.timer — schedule 좀비 재발(06-26, 07-07~) 대응.
    #   여기 다시 추가하면 timer와 중복 발송됨. 간격·주간·백업 작업만 schedule 유지.
    schedule.every().monday.at("21:50").do(run_weekly)
    schedule.every().friday.at("14:00").do(run_friday)
    schedule.every().day.at("21:50").do(run_monthly_if_first)
    schedule.every(30).minutes.do(run_alert_if_market_open)
    schedule.every(60).minutes.do(run_event_detection_if_daytime)
    schedule.every().day.at("01:00").do(run_git_backup)

    logging.info("스케줄러 시작 — KST 07:30 브리핑 / 30분마다 알림")
    print("스케줄러 시작 — KST 07:30 브리핑 / 30분마다 알림")

    while True:
        schedule.run_pending()
        time.sleep(30)


def _validate_config():
    """시작 시 필수 키 검증 — 누락이면 즉시 명확한 에러로 종료 (fail-fast)"""
    required = ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY", "DB_PATH"]
    missing = [k for k in required if not getattr(config, k, None)]
    if missing:
        msg = f"[FATAL] config.py 필수 키 누락: {', '.join(missing)} — 확인 후 재시작"
        print(msg)
        logging.error(msg)
        raise SystemExit(1)


def main():
    _validate_config()
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

    # (제거됨 2026-07-10) 시작 시 자동 브리핑 — restart 때 중복 발송의 원인이었고,
    # 브리핑은 이제 briefing-morning.timer가 06:50에 확실히 실행 (놓친 날은 timer 수동 start)

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
    import sys as _sys
    # oneshot 모드 (systemd timer용, GPT B안): python3 bot.py briefing|review
    if len(_sys.argv) > 1 and _sys.argv[1] == "briefing":
        _validate_config(); run_briefing()
        # ── 성공 판정 (GPT 20260807 §3) ──
        # ★ 기존 'briefing_history에 오늘 기록 있음 = 성공' 판정은 폐기했다.
        #   history는 '생성 성공' 증거일 뿐 '발송 성공' 증거가 아니며,
        #   2026-08-05 사고(차단 미발송인데 SUCCESS 판정)의 직접 원인이었다.
        #   → briefing_delivery_log의 final_delivery_status로 판정한다.
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        import sqlite3 as _sq
        _kst = _dt.now(_tz(_td(hours=9)))
        if _kst.weekday() < 5:   # 평일만 판정
            import delivery_status as _DS
            _DS.init_delivery_log()
            _c = _sq.connect(config.DB_PATH)
            _c.row_factory = _sq.Row
            _r = _c.execute("SELECT * FROM briefing_delivery_log "
                            "WHERE run_date=? AND kind='daily'",
                            (_kst.strftime("%Y-%m-%d"),)).fetchone()
            _c.close()
            if _r is None:
                print("[브리핑] 실패 — 발송 기록 자체가 없음 (exit 1)", flush=True)
                _sys.exit(1)
            _st = _r["final_delivery_status"]
            if _st in (_DS.SENT_FULL, _DS.SENT_REDACTED):
                print(f"[브리핑] 성공 — {_st}", flush=True)
            elif _st == _DS.BLOCKED:
                # 차단은 '의도된 동작'이나 발송은 안 됐다.
                # 알림까지 갔으면 silent failure가 아니므로 exit 0, 아니면 실패로 드러낸다.
                if _r["notified"]:
                    print("[브리핑] 차단됨(알림 발송 완료) — blocked_role_boundary", flush=True)
                else:
                    print("[브리핑] ⛔ 차단 + 알림 실패 = silent failure (exit 1)", flush=True)
                    _sys.exit(1)
            else:
                print(f"[브리핑] 실패 — {_st} (exit 1)", flush=True)
                _sys.exit(1)
    elif len(_sys.argv) > 1 and _sys.argv[1] == "review":
        _validate_config(); run_briefing_review()
    else:
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


