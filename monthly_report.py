import anthropic
import sqlite3
import yfinance as yf
import requests
import config
from datetime import datetime, timezone, timedelta
from sender import send_all

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """당신은 세계 최고 수준의 투자 애널리스트입니다.
30년 이상 실전 투자 경험. 매월 1일 지난달 성과를 냉철하게 분석하고
다음 달 전략을 제시합니다. 5천만원 운용 기준."""


def get_monthly_performance() -> dict:
    """지난달 추천 종목 전체 성과"""
    conn = sqlite3.connect(config.DB_PATH)
    now  = datetime.now(timezone.utc)
    # 지난달
    first_this = now.replace(day=1)
    last_month_end   = first_this - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    d1 = last_month_start.strftime("%Y-%m-%d")
    d2 = last_month_end.strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT date, stock_name, ticker, buy_price, target_price, stop_loss
        FROM recommendations
        WHERE date >= ? AND date <= ?
        ORDER BY date ASC
    """, (d1, d2)).fetchall()
    conn.close()

    if not rows:
        return {"records": [], "summary": "지난달 추천 종목 기록 없음"}

    records   = []
    total_rate = 0
    wins       = 0
    target_hits = 0
    stop_hits   = 0

    for row in rows:
        date, name, ticker, buy_price, target, stop = row
        try:
            current = yf.Ticker(ticker).fast_info.last_price
            rate    = (current - buy_price) / buy_price * 100
            is_kr   = ticker.endswith(".KS") or ticker.endswith(".KQ")
            fmt     = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"

            if current >= target:
                status = "🎯 목표 달성"
                target_hits += 1
                wins += 1
            elif current <= stop:
                status = "🛑 손절"
                stop_hits += 1
            elif rate >= 0:
                status = "✅ 수익"
                wins += 1
            else:
                status = "⚠️ 손실"

            records.append({
                "date":    date,
                "name":    name,
                "buy":     fmt(buy_price),
                "current": fmt(current),
                "rate":    f"{rate:+.2f}%",
                "status":  status,
                "raw_rate": rate,
            })
            total_rate += rate
        except:
            pass

    count    = len(records)
    avg_rate = total_rate / count if count else 0
    win_rate = wins / count * 100 if count else 0

    return {
        "records":      records,
        "count":        count,
        "avg_rate":     avg_rate,
        "win_rate":     win_rate,
        "target_hits":  target_hits,
        "stop_hits":    stop_hits,
        "month":        last_month_start.strftime("%Y년 %m월"),
    }


def get_monthly_market() -> str:
    """지난달 시장 성과"""
    tickers = {
        "S&P500":  "^GSPC",
        "NASDAQ":  "^IXIC",
        "코스피":  "^KS11",
        "코스닥":  "^KQ11",
        "원/달러": "USDKRW=X",
    }
    lines = []
    for name, ticker in tickers.items():
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period="1mo")
            if len(hist) >= 2:
                start = hist["Close"].iloc[0]
                end   = hist["Close"].iloc[-1]
                rate  = (end - start) / start * 100
                arrow = "▲" if rate >= 0 else "▼"
                lines.append(f"- {name}: {arrow} {rate:+.2f}%")
        except:
            pass
    return "\n".join(lines)


def generate_monthly_report() -> str:
    """월간 성과 리포트 생성"""
    perf   = get_monthly_performance()
    market = get_monthly_market()
    today  = datetime.now(timezone(timedelta(hours=9))).strftime("%Y년 %m월 %d일")

    # 공포탐욕지수
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        fgi = res.json()
        fgi_score  = int(fgi["data"][0]["value"])
        fgi_rating = fgi["data"][0]["value_classification"]
    except:
        fgi_score  = "N/A"
        fgi_rating = "N/A"

    # 성과 텍스트 구성
    if perf["records"]:
        rec_lines = []
        for r in perf["records"]:
            rec_lines.append(
                f"  {r['status']} {r['date']} {r['name']}: "
                f"{r['buy']} → {r['current']} ({r['rate']})"
            )
        rec_str = "\n".join(rec_lines)
        summary = (
            f"총 {perf['count']}건 | "
            f"평균 수익률 {perf['avg_rate']:+.2f}% | "
            f"승률 {perf['win_rate']:.0f}% | "
            f"목표 달성 {perf['target_hits']}건 | "
            f"손절 {perf['stop_hits']}건"
        )
    else:
        rec_str = "기록 없음"
        summary = "데이터 없음"

    prompt = f"""오늘은 {today}입니다. {perf.get('month', '지난달')} 월간 투자 성과 리포트를 작성해주세요.

## 📊 지난달 시장 성과
{market}

## 🧠 현재 공포탐욕지수
{fgi_score} ({fgi_rating})

## 📈 지난달 추천 종목 성과
{summary}

상세:
{rec_str}

## 📝 월간 리포트 형식
1. 📌 {perf.get('month', '지난달')} 한줄 총평
2. 📊 시장 분석 (지난달 주요 흐름 3~4줄)
3. 📈 추천 종목 성과 분석
   - 잘된 점
   - 아쉬운 점
   - 개선할 점
4. 💼 포트폴리오 월간 수익률 추정
5. 🔍 이번 달 주요 변수 및 전망
6. 🧭 이번 달 투자 전략
   - 집중 섹터
   - 비중 조정안
   - 헤지 전략
7. ⭐ 이번 달 주목 종목 3개
8. 💬 애널리스트 월간 한마디"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    briefing = message.content[0].text
    month    = perf.get("month", "지난달")
    header   = f"📅 {month} 월간 투자 성과 리포트\n{today}\n{'━' * 22}\n\n"
    return header + briefing


def send_monthly_report():
    """월간 성과 리포트 발송"""
    print("월간 리포트 생성 중...")
    try:
        msg    = generate_monthly_report()
        today  = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m")
        result = send_all(msg, subject=f"📅 {today} 월간 투자 성과 리포트")
        print(f"텔레그램: {'✅' if result['telegram'] else '❌'}")
        print(f"이메일:   {'✅' if result['email'] else '❌'}")
    except Exception as e:
        print(f"월간 리포트 오류: {e}")


if __name__ == "__main__":
    send_monthly_report()
