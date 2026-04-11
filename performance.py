import sqlite3
import yfinance as yf
from datetime import datetime, timezone
import re
import os

DB_PATH = "/root/briefing-bot/performance.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            stock_name  TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            buy_price   REAL NOT NULL,
            target_price REAL NOT NULL,
            stop_loss   REAL NOT NULL,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS performance_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_id      INTEGER NOT NULL,
            check_date  TEXT NOT NULL,
            current_price REAL NOT NULL,
            profit_rate REAL NOT NULL,
            status      TEXT NOT NULL,
            FOREIGN KEY (rec_id) REFERENCES recommendations(id)
        )
    """)
    conn.commit()
    return conn


def extract_recommendation(briefing_text: str, stocks: dict) -> dict:
    """브리핑 텍스트에서 추천 종목 정보 추출"""
    from watchlist import STOCK_MAP

    result = {}

    # 종목명 찾기
    for name in stocks:
        if name in briefing_text:
            result["stock_name"] = name
            result["ticker"]     = STOCK_MAP.get(name, "")
            break

    if not result:
        return {}

    # 현재가 추출
    price_pattern    = r'현재가[:\s]*([0-9,]+(?:\.[0-9]+)?)'
    target_pattern   = r'목표가[:\s]*([0-9,]+(?:\.[0-9]+)?)'
    stoploss_pattern = r'손절가[:\s]*([0-9,]+(?:\.[0-9]+)?)'

    def extract_num(pattern, text):
        m = re.search(pattern, text)
        if m:
            return float(m.group(1).replace(",", ""))
        return None

    result["buy_price"]    = extract_num(price_pattern,    briefing_text)
    result["target_price"] = extract_num(target_pattern,   briefing_text)
    result["stop_loss"]    = extract_num(stoploss_pattern, briefing_text)

    return result


def save_recommendation(briefing_text: str, stocks: dict) -> str:
    """브리핑에서 추천 종목 추출 후 DB 저장"""
    rec = extract_recommendation(briefing_text, stocks)

    if not rec or not all([
        rec.get("stock_name"),
        rec.get("buy_price"),
        rec.get("target_price"),
        rec.get("stop_loss"),
    ]):
        return "⚠️ 추천 종목 정보 추출 실패"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn  = init_db()

    # 오늘 이미 저장된 경우 덮어쓰기
    conn.execute(
        "DELETE FROM recommendations WHERE date = ?", (today,)
    )
    conn.execute("""
        INSERT INTO recommendations
            (date, stock_name, ticker, buy_price, target_price, stop_loss)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        today,
        rec["stock_name"],
        rec["ticker"],
        rec["buy_price"],
        rec["target_price"],
        rec["stop_loss"],
    ))
    conn.commit()
    conn.close()
    return f"✅ 추천 종목 저장: {rec['stock_name']} ({rec['buy_price']:,.0f}원)"


def get_current_price(ticker: str) -> float:
    try:
        t = yf.Ticker(ticker)
        return t.fast_info.last_price
    except:
        return None


def generate_weekly_report() -> str:
    """이번 주 추천 종목 성과 리포트 생성"""
    conn = init_db()

    # 이번 주 월~금 추천 종목 조회
    today  = datetime.now(timezone.utc)
    monday = today.date().strftime("%Y-%m-%d")
    rows   = conn.execute("""
        SELECT date, stock_name, ticker, buy_price, target_price, stop_loss
        FROM recommendations
        WHERE date >= ?
        ORDER BY date ASC
    """, (monday,)).fetchall()
    conn.close()

    if not rows:
        return "📊 이번 주 추천 종목 기록이 없어요."

    lines = [
        "📈 이번 주 추천 종목 성과 리포트",
        "─" * 24,
    ]

    total_rate = 0
    count      = 0

    for row in rows:
        date, name, ticker, buy_price, target, stop = row
        current = get_current_price(ticker)

        if current is None:
            continue

        rate    = (current - buy_price) / buy_price * 100
        is_kr   = ticker.endswith(".KS")
        fmt     = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
        arrow   = "▲" if rate >= 0 else "▼"

        # 상태 판단
        if current >= target:
            status = "🎯 목표가 달성!"
        elif current <= stop:
            status = "🛑 손절가 터치"
        elif rate >= 0:
            status = "✅ 수익 중"
        else:
            status = "⚠️ 손실 중"

        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday_kr = ["월","화","수","목","금","토","일"][dt.weekday()]

        lines += [
            f"\n📅 {date} ({weekday_kr}) 추천: {name}",
            f"  매수가:  {fmt(buy_price)}",
            f"  현재가:  {fmt(current)}  {arrow} {rate:+.2f}%",
            f"  목표가:  {fmt(target)}",
            f"  손절가:  {fmt(stop)}",
            f"  상태:    {status}",
        ]

        total_rate += rate
        count      += 1

    if count > 0:
        avg_rate = total_rate / count
        arrow    = "▲" if avg_rate >= 0 else "▼"
        lines += [
            "",
            "─" * 24,
            f"📊 주간 평균 수익률: {arrow} {avg_rate:+.2f}%",
            f"📌 추천 {count}건 / 이번 주 기준",
        ]

    return "\n".join(lines)


def get_all_performance() -> str:
    """전체 누적 성과 조회"""
    conn = init_db()
    rows = conn.execute("""
        SELECT date, stock_name, ticker, buy_price, target_price, stop_loss
        FROM recommendations
        ORDER BY date DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        return "📊 아직 추천 종목 기록이 없어요."

    lines = ["📊 최근 20일 추천 종목 성과", "─" * 24]
    total_rate = 0
    count      = 0
    win        = 0

    for row in rows:
        date, name, ticker, buy_price, target, stop = row
        current = get_current_price(ticker)
        if current is None:
            continue

        rate  = (current - buy_price) / buy_price * 100
        is_kr = ticker.endswith(".KS")
        fmt   = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
        arrow = "▲" if rate >= 0 else "▼"

        if current >= target:
            status = "🎯"
        elif current <= stop:
            status = "🛑"
        elif rate >= 0:
            status = "✅"
            win += 1
        else:
            status = "⚠️"

        lines.append(f"{status} {date} {name}: {fmt(buy_price)} → {fmt(current)} ({arrow}{abs(rate):.1f}%)")
        total_rate += rate
        count      += 1

    if count > 0:
        avg  = total_rate / count
        lines += [
            "─" * 24,
            f"평균 수익률: {avg:+.2f}%",
            f"승률: {win}/{count} ({win/count*100:.0f}%)",
        ]

    return "\n".join(lines)


if __name__ == "__main__":
    # 테스트용 더미 데이터 저장
    test_briefing = """
⭐ 오늘의 추천 종목
SK하이닉스 (000660.KS)
현재가: 916,000원
목표가: 1,053,400원
손절가: 851,880원
추천 이유: HBM 수요 급증
"""
    from collector import get_market_data
    data = get_market_data()
    print(save_recommendation(test_briefing, data["stocks"]))
    print()
    print(generate_weekly_report())
