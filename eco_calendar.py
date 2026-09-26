import os
from concurrent.futures import ThreadPoolExecutor
import requests
from datetime import datetime, timedelta, timezone
import config


# 주요 경제 지표 FRED Release ID
IMPORTANT_RELEASES = {
    101: ("📌", "🇺🇸 FOMC 보도자료"),
    53:  ("📌", "🇺🇸 GDP 발표"),
    10:  ("📌", "🇺🇸 소비자물가지수(CPI)"),
    50:  ("📌", "🇺🇸 고용보고서"),
    46:  ("⚠️", "🇺🇸 생산자물가지수(PPI)"),
}

def get_fred_calendar(days: int = 7) -> list | None:
    """Get a verified subset of this week's U.S. release dates from FRED."""
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    if not fred_key:
        print("FRED 캘린더 오류: FRED_API_KEY 환경변수 미설정")
        return None

    def fetch_release(release_id: int) -> list:
        response = requests.get(
            "https://api.stlouisfed.org/fred/release/dates",
            params={
                "api_key": fred_key,
                "file_type": "json",
                "release_id": release_id,
                "sort_order": "desc",
                "limit": 100,
                "include_release_dates_with_no_data": "true",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("release_dates"), list):
            raise ValueError("Unexpected FRED release response")
        return data["release_dates"]

    try:
        with ThreadPoolExecutor(max_workers=len(IMPORTANT_RELEASES)) as pool:
            release_dates = list(pool.map(fetch_release, IMPORTANT_RELEASES))

        events = []
        seen = set()
        for release_id, items in zip(IMPORTANT_RELEASES, release_dates):
            importance, name = IMPORTANT_RELEASES[release_id]
            for item in items:
                date_text = item.get("date", "")
                if not (monday.isoformat() <= date_text <= friday.isoformat()):
                    continue
                published_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                event_key = (release_id, date_text)
                if event_key in seen:
                    continue
                seen.add(event_key)
                events.append({
                    "date": published_date.strftime("%m/%d (%a)"),
                    "raw_date": date_text,
                    "event": name,
                    "importance": importance,
                    "is_today": published_date == today,
                })
        events.sort(key=lambda event: (event["raw_date"], event["event"]))
        return events
    except Exception as exc:
        # Exception text may include an API URL containing the key.
        print(f"FRED 캘린더 오류: {type(exc).__name__}")
        return None


def get_this_week_events() -> str:
    """이번 주 경제 캘린더 텍스트 생성"""
    events = get_fred_calendar()

    if events is None:
        return "이번 주 경제 일정 정보를 확인하지 못했습니다"
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
