import sqlite3
import yfinance as yf
import numpy as np
from datetime import datetime, timezone, timedelta
import config

DB_PATH = config.DB_PATH


def get_rsi(ticker: str, period: int = 14) -> float:
    """RSI 계산"""
    try:
        hist = yf.Ticker(ticker).history(period="1mo")
        if len(hist) < period:
            return 50.0
        delta  = hist["Close"].diff()
        gain   = delta.where(delta > 0, 0).rolling(period).mean()
        loss   = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs     = gain / loss
        rsi    = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except:
        return 50.0


def get_macd(ticker: str) -> dict:
    """MACD 계산"""
    try:
        hist   = yf.Ticker(ticker).history(period="3mo")
        close  = hist["Close"]
        ema12  = close.ewm(span=12).mean()
        ema26  = close.ewm(span=26).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        hist_val = macd - signal
        return {
            "macd":      float(macd.iloc[-1]),
            "signal":    float(signal.iloc[-1]),
            "histogram": float(hist_val.iloc[-1]),
            "cross":     "golden" if macd.iloc[-1] > signal.iloc[-1] else "dead",
        }
    except:
        return {"macd": 0, "signal": 0, "histogram": 0, "cross": "none"}


def signal1_factor_score(ticker: str) -> dict:
    """신호1: 팩터 스코어 (모멘텀·52주 위치)"""
    try:
        t      = yf.Ticker(ticker)
        info   = t.fast_info
        price  = info.last_price
        prev   = info.regular_market_previous_close
        high52 = info.year_high
        low52  = info.year_low
        rate   = (price - prev) / prev * 100
        pos52  = (price - low52) / (high52 - low52) * 100 if high52 != low52 else 50

        score = 0
        if rate > 3:     score += 2
        elif rate > 0:   score += 1
        elif rate < -3:  score -= 2
        else:            score -= 1

        if pos52 >= 80:  score += 2
        elif pos52 >= 60: score += 1
        elif pos52 <= 20: score -= 1

        return {
            "score":  score,
            "signal": score >= 2,
            "detail": f"등락률 {rate:+.1f}% | 52주 위치 {pos52:.0f}%",
        }
    except:
        return {"score": 0, "signal": False, "detail": "데이터 없음"}


def signal2_technical(ticker: str) -> dict:
    """신호2: 기술적 지표 (RSI·MACD)"""
    try:
        rsi  = get_rsi(ticker)
        macd = get_macd(ticker)

        score = 0
        if rsi <= 30:    score += 2   # 과매도 → 매수
        elif rsi <= 45:  score += 1
        elif rsi >= 70:  score -= 2   # 과매수 → 주의
        elif rsi >= 60:  score -= 1

        if macd["cross"] == "golden":   score += 1
        elif macd["cross"] == "dead":   score -= 1
        if macd["histogram"] > 0:       score += 1

        return {
            "score":  score,
            "signal": score >= 2,
            "detail": f"RSI {rsi:.1f} | MACD {macd['cross']} | 히스토그램 {macd['histogram']:+.2f}",
        }
    except:
        return {"score": 0, "signal": False, "detail": "데이터 없음"}


def signal3_foreign(ticker: str) -> dict:
    """신호3: 외국인 포지션 변화"""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT foreign_hold, foreign_hold_chg
            FROM foreign_trading
            WHERE ticker = ?
            ORDER BY date DESC LIMIT 3
        """, (ticker,)).fetchall()
        conn.close()

        if not rows:
            return {"score": 0, "signal": False, "detail": "데이터 없음"}

        latest_chg = rows[0][1]
        trend = sum(r[1] for r in rows) / len(rows)

        score = 0
        if latest_chg > 0.005:  score += 2
        elif latest_chg > 0:    score += 1
        elif latest_chg < -0.005: score -= 2
        elif latest_chg < 0:    score -= 1

        if trend > 0: score += 1

        return {
            "score":  score,
            "signal": score >= 1,
            "detail": f"최근 변화 {latest_chg*100:+.2f}% | 3일 추세 {trend*100:+.2f}%",
        }
    except:
        return {"score": 0, "signal": False, "detail": "데이터 없음"}


def signal4_ai_watchlist(name: str) -> dict:
    """신호4: AI 워치리스트 선정 여부"""
    try:
        from ai_watchlist import load_ai_watchlist
        ai_list = load_ai_watchlist()
        in_list = name in ai_list

        return {
            "score":  2 if in_list else 0,
            "signal": in_list,
            "detail": "AI 워치리스트 선정" if in_list else "AI 미선정",
        }
    except:
        return {"score": 0, "signal": False, "detail": "데이터 없음"}


def signal5_trust_score(briefing_text: str, market_data: dict) -> dict:
    """신호5: 신뢰도 점수"""
    try:
        from trust_score import calculate_trust_score
        ts = calculate_trust_score(briefing_text, market_data)
        score = ts["total"]
        return {
            "score":  2 if score >= 70 else 1 if score >= 55 else 0,
            "signal": score >= 60,
            "detail": f"신뢰도 {score}/100",
        }
    except:
        return {"score": 0, "signal": False, "detail": "데이터 없음"}


def calculate_ensemble(
    name:          str,
    ticker:        str,
    briefing_text: str = "",
    market_data:   dict = {},
) -> dict:
    """앙상블 신호 종합 계산"""
    s1 = signal1_factor_score(ticker)
    s2 = signal2_technical(ticker)
    s3 = signal3_foreign(ticker)
    s4 = signal4_ai_watchlist(name)
    s5 = signal5_trust_score(briefing_text, market_data)

    signals   = [s1, s2, s3, s4, s5]
    positive  = sum(1 for s in signals if s["signal"])
    total_score = sum(s["score"] for s in signals)

    # CONFIDENCE 등급
    if positive >= 4 or total_score >= 7:
        confidence = "🟢 HIGH"
        grade      = 3
    elif positive >= 3 or total_score >= 4:
        confidence = "🟡 MEDIUM"
        grade      = 2
    elif positive >= 2 or total_score >= 2:
        confidence = "🟠 LOW"
        grade      = 1
    else:
        confidence = "🔴 AVOID"
        grade      = 0

    return {
        "name":       name,
        "ticker":     ticker,
        "confidence": confidence,
        "grade":      grade,
        "positive":   positive,
        "total_score": total_score,
        "signals": {
            "팩터스코어":   s1,
            "기술적지표":   s2,
            "외국인포지션": s3,
            "AI워치리스트": s4,
            "신뢰도점수":   s5,
        }
    }


def format_ensemble_report(result: dict) -> str:
    """앙상블 리포트 텍스트"""
    lines = [
        f"\n🎯 앙상블 신호: {result['name']}",
        f"{'─' * 24}",
        f"종합: {result['confidence']} "
        f"({result['positive']}/5 신호 | 점수 {result['total_score']})",
        "─ 신호별 상세 ─",
    ]
    icons = {
        "팩터스코어":   "1️⃣",
        "기술적지표":   "2️⃣",
        "외국인포지션": "3️⃣",
        "AI워치리스트": "4️⃣",
        "신뢰도점수":   "5️⃣",
    }
    for name, s in result["signals"].items():
        status = "✅" if s["signal"] else "❌"
        lines.append(f"{icons[name]} {name}: {status} {s['detail']}")
    lines.append("─" * 24)
    return "\n".join(lines)


def save_ensemble_to_db(result: dict):
    """앙상블 결과 DB 저장"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ensemble_signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            stock_name  TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            confidence  TEXT,
            grade       INTEGER,
            positive    INTEGER,
            total_score INTEGER,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    conn.execute("""
        INSERT INTO ensemble_signals
            (date, stock_name, ticker, confidence, grade, positive, total_score)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        today, result["name"], result["ticker"],
        result["confidence"], result["grade"],
        result["positive"], result["total_score"],
    ))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    from collector import get_market_data
    print("시장 데이터 수집 중...")
    market = get_market_data()

    # 테스트 종목
    test_stocks = [
        ("SK하이닉스", "000660.KS"),
        ("삼성전자",   "005930.KS"),
        ("SOXL",      "SOXL"),
    ]
    for name, ticker in test_stocks:
        print(f"\n{name} 분석 중...")
        result = calculate_ensemble(name, ticker, "", market)
        print(format_ensemble_report(result))
        save_ensemble_to_db(result)
