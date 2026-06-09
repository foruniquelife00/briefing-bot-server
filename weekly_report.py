import anthropic
import requests
import config
from datetime import datetime, timezone, timedelta
from performance import get_all_performance
from eco_calendar import get_this_week_events, get_us_news_sentiment, format_sentiment
from collector import get_index, get_commodity_data
from sender import send_all
import yfinance as yf

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """당신은 시장 배경을 해석하는 거시 시장 애널리스트입니다.
30년 이상 거시·시장 분석 경험. 매주 월요일 한 주 시장 배경 전망을 작성합니다.

## 절대 규칙 (역할 경계)
1. 개별 종목 추천/목표가/매수 의견/포트폴리오 종목 배분 금지
2. 종목명은 시장 배경 설명용으로만 (예: "반도체 대형주 강세"). "○○ 매수/목표가" 금지
3. 종목 판단은 시그널봇(수급 기반) 역할. 주간 뉴스레터는 시장 배경·섹터 분위기·리스크만
4. 확정 예측 금지, 관찰 포인트로 서술
자산배분은 '현금 비중 조절' 같은 거시 관점까지만 허용, 개별 종목 배분 금지."""


def get_last_week_summary() -> str:
    """지난주 시장 요약"""
    try:
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
                hist = t.history(period="5d")
                if len(hist) >= 2:
                    start = hist["Close"].iloc[0]
                    end   = hist["Close"].iloc[-1]
                    rate  = (end - start) / start * 100
                    arrow = "▲" if rate >= 0 else "▼"
                    if ticker == "USDKRW=X":
                        lines.append(f"- {name}: {end:,.2f}원 ({arrow} {rate:+.2f}%)")
                    else:
                        lines.append(f"- {name}: {end:,.2f} ({arrow} {rate:+.2f}%)")
            except:
                pass
        return "\n".join(lines)
    except Exception as e:
        return f"지난주 데이터 오류: {e}"


def generate_weekly_briefing() -> str:
    """주간 뉴스레터 생성"""
    today     = datetime.now(timezone(timedelta(hours=9)))
    week_num  = today.isocalendar()[1]
    date_str  = today.strftime("%Y년 %m월 %d일")

    last_week    = get_last_week_summary()
    performance  = get_all_performance()
    calendar_str = get_this_week_events()
    sentiment    = get_us_news_sentiment()
    sentiment_str = format_sentiment(sentiment)

    # 원자재
    commodity = get_commodity_data()
    com_lines = []
    for name, d in commodity.items():
        if d:
            com_lines.append(f"- {name}: {d['price']} ({d['rate']})")
    com_str = "\n".join(com_lines)

    # 공포탐욕지수
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        fgi = res.json()
        fgi_score  = int(fgi["data"][0]["value"])
        fgi_rating = fgi["data"][0]["value_classification"]
    except:
        fgi_score  = "N/A"
        fgi_rating = "N/A"

    prompt = f"""오늘은 {date_str} 월요일입니다. {week_num}주차 주간 투자 뉴스레터를 작성해주세요.

## 📊 지난주 시장 성과
{last_week}

## 🛢️ 원자재 현황
{com_str}

## 🧠 공포탐욕지수
{fgi_score} ({fgi_rating})

## 🌐 글로벌 뉴스 감성
{sentiment_str}

## 📅 이번 주 경제 캘린더
{calendar_str}

## 📈 추천 종목 최근 성과
{performance}

## 작성 규칙
- 개별 종목 추천/목표가/포트폴리오 종목 배분 금지 (종목명은 배경 설명용만)
- 종목 추천이 필요하면 "시그널봇의 수급 관심목록 참고" 안내로 대체
- 확정 예측 금지, 관찰 포인트로 서술

## 📝 주간 뉴스레터 형식 (시장 배경 중심)
1. 📌 이번 주 한줄 전망 + 시장 톤
2. 📊 지난주 시장 총평 (3~4줄)
3. 🔍 이번 주 핵심 변수 3가지
4. 📅 이번 주 주목할 경제 이벤트 (캘린더 기반)
5. 🔭 이번 주 주목할 섹터 (관찰 중심: 강세/약세/전환)
6. 🧭 거시 관점 자산 운용 (현금 비중 조절 등, 개별 종목 배분 금지)
7. ⚠️ 이번 주 리스크 요인
8. 🔗 시그널봇 연결 — "개별 종목은 시그널봇 수급 관심목록 참고"
9. 💬 애널리스트 주간 한마디"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    briefing = message.content[0].text
    header   = f"📰 {week_num}주차 주간 투자 뉴스레터\n{date_str}\n{'━' * 22}\n\n"
    return header + briefing


def send_weekly_report():
    """주간 뉴스레터 발송"""
    print("주간 뉴스레터 생성 중...")
    try:
        msg    = generate_weekly_briefing()
        today  = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m.%d")
        result = send_all(msg, subject=f"📰 주간 투자 뉴스레터 {today}")
        print(f"텔레그램: {'✅' if result['telegram'] else '❌'}")
        print(f"이메일:   {'✅' if result['email'] else '❌'}")
    except Exception as e:
        print(f"주간 뉴스레터 오류: {e}")


if __name__ == "__main__":
    send_weekly_report()


FRIDAY_SYSTEM_PROMPT = """당신은 시장 배경을 해석하는 거시 시장 애널리스트입니다.
30년 이상 거시·시장 분석 경험. 매주 금요일 장 마감 후 주간 시장 결산과 다음 주 배경 전망을 작성합니다.
다음 주는 낙관·중립·비관 3가지 지수 시나리오를 확률과 함께 제시합니다.

## 절대 규칙 (역할 경계)
1. 개별 종목 추천/목표가/매수 의견 금지 (종목명은 시장 배경 설명용만)
2. 지수 시나리오·섹터 흐름·리스크는 OK, 개별 종목 매수 판단은 시그널봇 역할
3. 확정 예측 금지, 시나리오·관찰 포인트로 서술"""


def get_weekly_performance() -> str:
    """이번 주 월~금 시장 성과"""
    tickers = {
        "S&P500":  "^GSPC",
        "NASDAQ":  "^IXIC",
        "DOW":     "^DJI",
        "코스피":  "^KS11",
        "코스닥":  "^KQ11",
        "원/달러": "USDKRW=X",
    }
    lines = []
    for name, ticker in tickers.items():
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if len(hist) >= 2:
                start = hist["Close"].iloc[0]
                end   = hist["Close"].iloc[-1]
                rate  = (end - start) / start * 100
                arrow = "▲" if rate >= 0 else "▼"
                if ticker == "USDKRW=X":
                    lines.append(f"- {name}: {end:,.2f}원 ({arrow} {rate:+.2f}%)")
                else:
                    lines.append(f"- {name}: {end:,.2f} ({arrow} {rate:+.2f}%)")
        except:
            pass
    return "\n".join(lines)


def generate_friday_briefing() -> str:
    """금요일 주간 결산 + 다음 주 예측 리포트"""
    today    = datetime.now(timezone(timedelta(hours=9)))
    date_str = today.strftime("%Y년 %m월 %d일")
    week_num = today.isocalendar()[1]

    weekly_perf  = get_weekly_performance()
    performance  = get_all_performance()
    calendar_str = get_this_week_events()
    sentiment    = get_us_news_sentiment()
    sentiment_str = format_sentiment(sentiment)

    # 원자재
    commodity = get_commodity_data()
    com_lines = []
    for name, d in commodity.items():
        if d:
            com_lines.append(f"- {name}: {d['price']} ({d['rate']})")
    com_str = "\n".join(com_lines)

    # 공포탐욕지수
    try:
        import requests as req
        res = req.get("https://api.alternative.me/fng/", timeout=10)
        fgi = res.json()
        fgi_score  = int(fgi["data"][0]["value"])
        fgi_rating = fgi["data"][0]["value_classification"]
    except:
        fgi_score  = "N/A"
        fgi_rating = "N/A"

    prompt = f"""오늘은 {date_str} 금요일입니다. {week_num}주차 주간 결산 및 다음 주 예측 리포트를 작성해주세요.

## 📊 이번 주 시장 성과 (월~금)
{weekly_perf}

## 🛢️ 원자재 주간 마감
{com_str}

## 🧠 공포탐욕지수
{fgi_score} ({fgi_rating})

## 🌐 글로벌 뉴스 감성
{sentiment_str}

## 📅 다음 주 경제 캘린더
{calendar_str}

## 📈 이번 주 추천 종목 성과
{performance}

## 작성 규칙
- 개별 종목 추천/목표가 금지 (종목명은 시장 배경 설명용만)
- 지수 시나리오·섹터 흐름은 OK, 개별 종목 매수 판단은 시그널봇 역할

## 📝 금요일 마감 리포트 형식 (시장 배경 중심)
1. 📌 이번 주 한줄 총평
2. 📊 주간 시장 성과 분석 (3~4줄)
3. 🔭 주간 섹터 흐름 결산 (강세/약세 섹터, 종목 추천 아님)
4. 🌍 미국 시장 주간 마감 분석
5. 🛢️ 원자재·환율 주간 동향 및 영향
6. 🔮 다음 주 예측 시나리오 (지수 기준)
   - 🟢 낙관 (확률 %) : 조건 + 목표 지수
   - 🟡 중립 (확률 %) : 조건 + 예상 지수
   - 🔴 비관 (확률 %) : 조건 + 하방 지수
7. 📅 다음 주 주요 경제 이벤트 및 영향
8. 🧭 거시 관점 대응 (현금 비중 등) + 시그널봇 연결 안내
   - 단기 (월~수)
   - 후반 (목~금)
9. ⭐ 다음 주 주목 종목 3개 (섹터 분산)
10. ⚠️ 다음 주 주요 리스크
11. 💬 애널리스트 주말 한마디"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2500,
        system=FRIDAY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    briefing = message.content[0].text
    header   = f"📊 {week_num}주차 주간 결산 & 다음 주 예측\n{date_str} 마감\n{'━' * 22}\n\n"
    return header + briefing


def send_friday_report():
    """금요일 마감 리포트 발송"""
    print("금요일 마감 리포트 생성 중...")
    try:
        msg    = generate_friday_briefing()
        today  = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m.%d")
        result = send_all(msg, subject=f"📊 주간 결산 & 다음 주 예측 {today}")
        print(f"텔레그램: {'✅' if result['telegram'] else '❌'}")
        print(f"이메일:   {'✅' if result['email'] else '❌'}")
    except Exception as e:
        print(f"금요일 리포트 오류: {e}")
