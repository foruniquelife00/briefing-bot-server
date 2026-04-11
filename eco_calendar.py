import requests
from datetime import datetime, timedelta, timezone
import config

FRED_KEY = "58e3ab37a6fe04de7cf3ab8600d46255"

# 주요 경제 지표 FRED Release ID
IMPORTANT_RELEASES = {
    101:  ("📌", "🇺🇸 FOMC 성명/금리 결정"),
    53:   ("📌", "🇺🇸 GDP 발표"),
    10:   ("📌", "🇺🇸 CPI 소비자물가지수"),
    21:   ("📌", "🇺🇸 비농업 고용지수"),
    50:   ("⚠️", "🇺🇸 PCE 물가지수"),
    11:   ("⚠️", "🇺🇸 PPI 생산자물가지수"),
    14:   ("⚠️", "🇺🇸 소매판매"),
    46:   ("⚠️", "🇺🇸 신규 실업수당 청구"),
    20:   ("⚠️", "🇺🇸 주택착공"),
    19:   ("⚠️", "🇺🇸 기존주택판매"),
    18:   ("⚠️", "🇺🇸 내구재 주문"),
    15:   ("⚠️", "🇺🇸 산업생산"),
    22:   ("⚠️", "🇺🇸 미시간 소비자신뢰"),
    113:  ("⚠️", "🇺🇸 JOLTS 구인건수"),
    103:  ("⚠️", "🇺🇸 ADP 고용보고서"),
    24:   ("⚠️", "🇺🇸 무역수지"),
}

def get_fred_calendar(days: int = 7) -> list:
    """FRED API로 이번 주 주요 경제 지표 발표일 수집"""
    today  = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)

    try:
        res = requests.get(
            "https://api.stlouisfed.org/fred/releases/dates",
            params={
                "api_key":        FRED_KEY,
                "file_type":      "json",
                "realtime_start": monday.strftime("%Y-%m-%d"),
                "realtime_end":   friday.strftime("%Y-%m-%d"),
                "limit":          200,
                "sort_order":     "asc",
            },
            timeout=10
        )
        data = res.json()
        events = []
        for item in data.get("release_dates", []):
            rid  = item.get("release_id")
            date = item.get("date", "")
            if rid in IMPORTANT_RELEASES:
                imp_icon, name = IMPORTANT_RELEASES[rid]
                try:
                    dt = datetime.strptime(date, "%Y-%m-%d")
                    date_fmt = dt.strftime("%m/%d (%a)")
                    is_today = dt.date() == today
                except:
                    date_fmt = date
                    is_today = False

                events.append({
                    "date":       date_fmt,
                    "raw_date":   date,
                    "event":      name,
                    "importance": imp_icon,
                    "is_today":   is_today,
                })

        events.sort(key=lambda x: x["raw_date"])
        return events

    except Exception as e:
        print(f"FRED 캘린더 오류: {e}")
        return []


def get_this_week_events() -> str:
    """이번 주 경제 캘린더 텍스트 생성"""
    events = get_fred_calendar()

    if not events:
        return "이번 주 주요 일정 없음"

    lines = []
    current_date = ""
    for e in events:
        if e["date"] != current_date:
            current_date = e["date"]
            marker = " ◀ 오늘" if e["is_today"] else ""
            lines.append(f"\n📅 {current_date}{marker}")
        lines.append(f"  {e['importance']} {e['event']}")

    return "\n".join(lines).strip()


def get_us_news_sentiment() -> list:
    """Alpha Vantage 뉴스 감성 분석"""
    try:
        res = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "topics":   "economy_macro,financial_markets,earnings",
                "apikey":   config.ALPHA_VANTAGE_KEY,
                "limit":    10,
            },
            timeout=10
        )
        data = res.json()
        results = []
        for item in data.get("feed", [])[:5]:
            score = float(item.get("overall_sentiment_score", 0))
            if score >= 0.15:
                sentiment = "📈 긍정"
            elif score <= -0.15:
                sentiment = "📉 부정"
            else:
                sentiment = "➡ 중립"
            results.append({
                "title":     item.get("title", ""),
                "sentiment": sentiment,
                "score":     round(score, 2),
            })
        return results
    except Exception as e:
        print(f"뉴스 감성 오류: {e}")
        return []


def format_sentiment(news: list) -> str:
    if not news:
        return "감성 데이터 없음"
    return "\n".join([f"  {n['sentiment']} {n['title'][:50]}..." for n in news])


if __name__ == "__main__":
    print("=== 이번 주 경제 캘린더 (FRED 자동) ===")
    print(get_this_week_events())
    print("\n=== 글로벌 뉴스 감성 ===")
    news = get_us_news_sentiment()
    print(format_sentiment(news))
