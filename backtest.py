import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta
import config

DB_PATH = config.DB_PATH


def get_all_recommendations() -> list:
    """전체 추천 종목 이력 조회"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT date, stock_name, ticker, buy_price, target_price, stop_loss
        FROM recommendations
        ORDER BY date ASC
    """).fetchall()
    conn.close()
    return rows


def get_price_on_date(ticker: str, date_str: str) -> float:
    """특정 날짜의 종가 조회"""
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(start=date_str, period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[0])
    except:
        pass
    return None


def run_backtest() -> dict:
    """전체 백테스팅 실행"""
    rows = get_all_recommendations()
    if not rows:
        return {"error": "추천 종목 데이터 없음"}

    results = []
    for row in rows:
        date, name, ticker, buy_price, target, stop = row

        # 현재가 조회
        try:
            current = yf.Ticker(ticker).fast_info.last_price
        except:
            continue

        rate    = (current - buy_price) / buy_price * 100
        is_kr   = ticker.endswith(".KS") or ticker.endswith(".KQ")
        fmt     = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"

        # 결과 판정
        if current >= target:
            outcome = "목표달성"
            outcome_icon = "🎯"
        elif current <= stop:
            outcome = "손절"
            outcome_icon = "🛑"
        elif rate > 0:
            outcome = "수익중"
            outcome_icon = "✅"
        else:
            outcome = "손실중"
            outcome_icon = "⚠️"

        # 보유 기간
        buy_date = datetime.strptime(date, "%Y-%m-%d")
        today    = datetime.now()
        hold_days = (today - buy_date).days

        results.append({
            "date":       date,
            "name":       name,
            "ticker":     ticker,
            "buy_price":  buy_price,
            "current":    current,
            "target":     target,
            "stop":       stop,
            "rate":       rate,
            "outcome":    outcome,
            "outcome_icon": outcome_icon,
            "hold_days":  hold_days,
            "buy_str":    fmt(buy_price),
            "current_str": fmt(current),
            "target_str": fmt(target),
            "stop_str":   fmt(stop),
        })

    if not results:
        return {"error": "분석 가능한 데이터 없음"}

    # 통계 계산
    total      = len(results)
    wins       = sum(1 for r in results if r["rate"] > 0)
    target_hits = sum(1 for r in results if r["outcome"] == "목표달성")
    stop_hits  = sum(1 for r in results if r["outcome"] == "손절")
    avg_rate   = sum(r["rate"] for r in results) / total
    max_profit = max(results, key=lambda x: x["rate"])
    max_loss   = min(results, key=lambda x: x["rate"])
    avg_hold   = sum(r["hold_days"] for r in results) / total

    # 섹터별 성과
    kr_results = [r for r in results if r["ticker"].endswith(".KS") or r["ticker"].endswith(".KQ")]
    us_results = [r for r in results if not r["ticker"].endswith(".KS") and not r["ticker"].endswith(".KQ")]

    kr_avg = sum(r["rate"] for r in kr_results) / len(kr_results) if kr_results else 0
    us_avg = sum(r["rate"] for r in us_results) / len(us_results) if us_results else 0

    return {
        "results":      results,
        "total":        total,
        "wins":         wins,
        "win_rate":     wins / total * 100,
        "target_hits":  target_hits,
        "stop_hits":    stop_hits,
        "avg_rate":     avg_rate,
        "max_profit":   max_profit,
        "max_loss":     max_loss,
        "avg_hold":     avg_hold,
        "kr_avg":       kr_avg,
        "us_avg":       us_avg,
        "kr_count":     len(kr_results),
        "us_count":     len(us_results),
    }


def format_backtest_report(bt: dict) -> str:
    """백테스팅 결과 텍스트 리포트"""
    if "error" in bt:
        return f"❌ {bt['error']}"

    lines = [
        "📊 백테스팅 리포트",
        "═" * 24,
        f"분석 기간: 전체 추천 종목",
        f"총 추천 수: {bt['total']}건",
        "",
        "📈 성과 요약",
        "─" * 24,
        f"평균 수익률:  {bt['avg_rate']:+.2f}%",
        f"승률:         {bt['win_rate']:.0f}% ({bt['wins']}/{bt['total']})",
        f"목표가 달성:  {bt['target_hits']}건 ({bt['target_hits']/bt['total']*100:.0f}%)",
        f"손절 발생:    {bt['stop_hits']}건 ({bt['stop_hits']/bt['total']*100:.0f}%)",
        f"평균 보유:    {bt['avg_hold']:.0f}일",
        "",
        "🏆 최고 성과",
        f"  {bt['max_profit']['name']}: {bt['max_profit']['rate']:+.2f}%",
        "",
        "💥 최저 성과",
        f"  {bt['max_loss']['name']}: {bt['max_loss']['rate']:+.2f}%",
        "",
        "🌐 섹터별 성과",
        "─" * 24,
        f"🇰🇷 국내 ({bt['kr_count']}건): 평균 {bt['kr_avg']:+.2f}%",
        f"🇺🇸 해외 ({bt['us_count']}건): 평균 {bt['us_avg']:+.2f}%",
        "",
        "📋 종목별 상세",
        "─" * 24,
    ]

    for r in bt["results"]:
        lines.append(
            f"{r['outcome_icon']} {r['date']} {r['name']}: "
            f"{r['buy_str']} → {r['current_str']} "
            f"({r['rate']:+.2f}%) {r['hold_days']}일"
        )

    lines.append("═" * 24)
    return "\n".join(lines)


def save_backtest_to_db(bt: dict):
    """백테스팅 결과 DB 저장"""
    if "error" in bt:
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_summary (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date    TEXT NOT NULL,
            total       INTEGER,
            win_rate    REAL,
            avg_rate    REAL,
            target_hits INTEGER,
            stop_hits   INTEGER,
            avg_hold    REAL,
            kr_avg      REAL,
            us_avg      REAL
        )
    """)
    conn.execute("""
        INSERT INTO backtest_summary
            (run_date, total, win_rate, avg_rate, target_hits,
             stop_hits, avg_hold, kr_avg, us_avg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d"),
        bt["total"],
        bt["win_rate"],
        bt["avg_rate"],
        bt["target_hits"],
        bt["stop_hits"],
        bt["avg_hold"],
        bt["kr_avg"],
        bt["us_avg"],
    ))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    print("백테스팅 실행 중...")
    bt = run_backtest()
    report = format_backtest_report(bt)
    print(report)
    save_backtest_to_db(bt)
    print("\nDB 저장 완료!")
