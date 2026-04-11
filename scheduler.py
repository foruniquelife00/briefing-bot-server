import schedule
import time
import logging
from datetime import datetime, timezone

from collector    import get_market_data
from analyzer     import analyze_and_save
from sender       import send_telegram
from alert        import check_alerts

logging.basicConfig(
    filename="/root/briefing-bot/briefing.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def run_briefing():
    weekday = datetime.now(timezone.utc).weekday()
    if weekday >= 5:
        logging.info("주말 — 건너뜀")
        return
    try:
        data = get_market_data()
        msg  = analyze_and_save(data)
        ok   = send_telegram(msg)
        logging.info(f"브리핑 {'성공' if ok else '실패'}")
    except Exception as e:
        logging.error(f"브리핑 오류: {e}")

def run_alert():
    try:
        check_alerts()
    except Exception as e:
        logging.error(f"알림 오류: {e}")

if __name__ == "__main__":
    # 매일 KST 07:20 브리핑
    schedule.every().day.at("22:20").do(run_briefing)
    # 30분마다 급등락 알림 체크
    schedule.every(30).minutes.do(run_alert)

    print("스케줄러 시작")
    print("  브리핑: 매일 KST 07:20 (월~금)")
    print("  알림:   30분마다 (장 시간만)")
    logging.info("스케줄러 시작")

    run_briefing()

    while True:
        schedule.run_pending()
        time.sleep(30)
