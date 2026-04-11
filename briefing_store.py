import sqlite3
import json
from datetime import datetime, timezone, timedelta
import config

DB_PATH = config.DB_PATH

def init_briefing_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS briefing_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT NOT NULL,
            weekday       TEXT NOT NULL,
            briefing_text TEXT NOT NULL,
            gpt_analysis  TEXT,
            claude_verify TEXT,
            trust_score   INTEGER,
            recommended   TEXT,
            buy_price     REAL,
            fgi_score     INTEGER,
            kospi         TEXT,
            sp500         TEXT,
            usd_krw       TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()


def save_briefing(
    briefing_text: str,
    market_data:   dict,
    gpt_analysis:  str = "",
    claude_verify: str = "",
    trust_score:   int = 0,
):
    """브리핑 전문 저장"""
    init_briefing_db()

    kst     = datetime.now(timezone(timedelta(hours=9)))
    date    = kst.strftime("%Y-%m-%d")
    weekday = ["월","화","수","목","금","토","일"][kst.weekday()]

    # 추천 종목 추출
    import re
    rec_match = re.search(r'추천 종목.*?\n[*\s]*([가-힣A-Za-z0-9]+)', briefing_text)
    recommended = rec_match.group(1) if rec_match else ""

    # 매수가 추출
    price_match = re.search(r'현재가[:\s]*([0-9,]+)', briefing_text)
    buy_price   = float(price_match.group(1).replace(",","")) if price_match else 0

    # 신뢰도 점수 추출
    if not trust_score:
        score_match = re.search(r'신뢰도\s*점수[:\s]*(\d+)', claude_verify)
        trust_score = int(score_match.group(1)) if score_match else 0

    conn = sqlite3.connect(DB_PATH)
    # 오늘 이미 저장된 경우 덮어쓰기
    conn.execute("DELETE FROM briefing_history WHERE date = ?", (date,))
    conn.execute("""
        INSERT INTO briefing_history
            (date, weekday, briefing_text, gpt_analysis, claude_verify,
             trust_score, recommended, buy_price, fgi_score, kospi, sp500, usd_krw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date,
        weekday,
        briefing_text,
        gpt_analysis,
        claude_verify,
        trust_score,
        recommended,
        buy_price,
        market_data.get("fgi_score", 0),
        market_data.get("kospi",  {}).get("value", ""),
        market_data.get("sp500",  {}).get("value", ""),
        market_data.get("usd_krw", ""),
    ))
    conn.commit()
    conn.close()
    print(f"브리핑 저장 완료: {date} ({weekday}) 신뢰도:{trust_score}")


def get_recent_briefings(days: int = 5) -> list:
    """최근 N일 브리핑 조회"""
    init_briefing_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT date, weekday, briefing_text, gpt_analysis, claude_verify,
               trust_score, recommended, buy_price, fgi_score, kospi, sp500, usd_krw
        FROM briefing_history
        ORDER BY date DESC
        LIMIT ?
    """, (days,)).fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            "date":         row[0],
            "weekday":      row[1],
            "briefing":     row[2],
            "gpt":          row[3],
            "claude":       row[4],
            "trust_score":  row[5],
            "recommended":  row[6],
            "buy_price":    row[7],
            "fgi_score":    row[8],
            "kospi":        row[9],
            "sp500":        row[10],
            "usd_krw":      row[11],
        })
    return results


def build_context_prompt(days: int = 3) -> str:
    """최근 브리핑을 Claude 컨텍스트로 변환"""
    recent = get_recent_briefings(days)
    if not recent:
        return "이전 브리핑 데이터 없음"

    lines = ["## 📚 최근 브리핑 컨텍스트\n"]
    for b in recent:
        lines.append(f"### {b['date']} ({b['weekday']})")
        lines.append(f"- 코스피: {b['kospi']} | S&P500: {b['sp500']} | 원달러: {b['usd_krw']}원")
        lines.append(f"- 공포탐욕지수: {b['fgi_score']}")
        lines.append(f"- 추천 종목: {b['recommended']} (매수가: {int(b['buy_price']):,}원)" if b['buy_price'] else f"- 추천 종목: {b['recommended']}")
        lines.append(f"- AI 신뢰도: {b['trust_score']}/100")

        # 추천 종목 현재 성과
        if b['recommended'] and b['buy_price']:
            try:
                from watchlist import STOCK_MAP
                ticker = STOCK_MAP.get(b['recommended'])
                if ticker:
                    import yfinance as yf
                    current = yf.Ticker(ticker).fast_info.last_price
                    rate    = (current - b['buy_price']) / b['buy_price'] * 100
                    lines.append(f"- 추천 종목 현재 성과: {rate:+.2f}%")
            except:
                pass
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    init_briefing_db()
    print("브리핑 DB 초기화 완료")
    print("\n최근 컨텍스트:")
    print(build_context_prompt())
