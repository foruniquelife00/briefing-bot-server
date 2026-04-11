import json
import os
import yfinance as yf
import anthropic
import config
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

AI_WATCHLIST_FILE   = "/root/briefing-bot/ai_watchlist.json"
USER_WATCHLIST_FILE = "/root/briefing-bot/watchlist.json"
MAX_AI_STOCKS       = 50

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# 섹터 태그 정의
SECTOR_TAGS = {
    "반도체": ["삼성전자","SK하이닉스","한미반도체","SOXL","SMH","AMD","엔비디아","TSMC","마이크론"],
    "방산":   ["한화에어로스페이스","한국항공우주","LIG넥스원","현대로템","한화시스템"],
    "바이오": ["셀트리온","삼성바이오로직스","HLB","알테오젠","리가켐바이오"],
    "2차전지":["LG에너지솔루션","삼성SDI","에코프로비엠","포스코퓨처엠"],
    "AI·플랫폼":["네이버","카카오","NVIDIA","마이크로소프트","메타","알파벳"],
    "금융":   ["KB금융","신한지주","하나금융지주","삼성생명"],
    "자동차": ["현대차","기아","현대모비스"],
    "에너지": ["S-Oil","GS","한국가스공사","엑슨모빌","쉐브론"],
    "ETF":    ["QQQ","TQQQ","SPY","SOXL","GLD","TLT","KODEX 200"],
}

def get_sector_tag(name: str) -> str:
    for sector, stocks in SECTOR_TAGS.items():
        if name in stocks:
            return sector
    return "기타"

def get_investment_tag(rate: float, pos52: float) -> str:
    """투자 성격 태그"""
    if pos52 >= 90:
        return "신고가돌파"
    elif pos52 <= 10:
        return "역발상"
    elif abs(rate) >= 5:
        return "모멘텀"
    elif pos52 >= 60:
        return "상승추세"
    else:
        return "안정"

def get_all_stocks_score() -> list:
    from watchlist import STOCK_MAP
    print(f"전체 {len(STOCK_MAP)}개 종목 스코어링 중...")

    def score_stock(name, ticker):
        try:
            t      = yf.Ticker(ticker)
            info   = t.fast_info
            price  = info.last_price
            prev   = info.regular_market_previous_close
            high52 = info.year_high
            low52  = info.year_low
            rate   = (price - prev) / prev * 100
            score  = 0
            score += abs(rate) * 2
            if high52 and price >= high52 * 0.90: score += 15
            if low52  and price <= low52  * 1.10: score += 10
            pos52 = (price - low52) / (high52 - low52) * 100 if high52 != low52 else 50
            if pos52 >= 70: score += 8
            elif pos52 >= 50: score += 4
            return {
                "name": name, "ticker": ticker,
                "price": price, "rate": rate,
                "high52": high52, "low52": low52,
                "score": score, "pos52": pos52,
                "sector": get_sector_tag(name),
                "inv_tag": get_investment_tag(rate, pos52),
            }
        except:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(score_stock, name, ticker): name
                   for name, ticker in STOCK_MAP.items()}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)
    print(f"스코어링 완료: {len(results)}개")
    return results


def get_market_context() -> str:
    try:
        import requests
        from eco_calendar import get_this_week_events
        from collector import get_index
        sp500 = get_index("^GSPC")
        kospi = get_index("^KS11")
        res   = requests.get("https://api.alternative.me/fng/", timeout=5)
        fgi   = res.json()
        return f"""
S&P500: {sp500['value']} ({sp500['rate']})
코스피: {kospi['value']} ({kospi['rate']})
공포탐욕지수: {fgi['data'][0]['value']} ({fgi['data'][0]['value_classification']})
이번 주 캘린더:
{get_this_week_events()}"""
    except Exception as e:
        return f"시장 데이터 오류: {e}"


def select_ai_watchlist(scored_stocks: list, market_context: str) -> tuple:
    """Claude가 시황 기반으로 워치리스트 50개 선정 + 태그 + 근거"""
    stock_summary = "\n".join([
        f"- {s['name']} ({s['ticker']}): "
        f"{str(int(s['price'])) + '원' if s['ticker'].endswith(('.KS','.KQ')) else '$' + str(round(s['price'],2))} "
        f"({s['rate']:+.2f}%) 점수:{s['score']:.1f} 섹터:{s['sector']} 성격:{s['inv_tag']}"
        for s in scored_stocks[:100]
    ])

    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y년 %m월 %d일")

    prompt = f"""오늘은 {today}입니다.

## 현재 시장 상황
{market_context}

## 모멘텀 스코어 상위 100개 종목
{stock_summary}

## 요청
위 데이터를 분석하여 이번 주 주목할 종목 30개만 선정해주세요.
반드시 아래 JSON 형식으로만 답변하세요. 설명 없이 JSON만:

{{
  "weekly_theme": "이번 주 핵심 테마 1~2줄",
  "sector_focus": ["섹터1", "섹터2", "섹터3"],
  "risk_warning": "주요 리스크 1줄",
  "stocks": [
    {{"name": "종목명", "sector": "섹터", "style": "모멘텀|안정|역발상|성장|배당", "reason": "이유 15자 이내"}}
  ]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        import re
        text = message.content[0].text
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return data
    except Exception as e:
        print(f"JSON 파싱 오류: {e}")
    return {}


def load_ai_watchlist() -> list:
    if os.path.exists(AI_WATCHLIST_FILE):
        with open(AI_WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [s["name"] if isinstance(s, dict) else s
                    for s in data.get("stocks", [])]
    return []


def load_ai_watchlist_full() -> dict:
    if os.path.exists(AI_WATCHLIST_FILE):
        with open(AI_WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_ai_watchlist(data: dict):
    data["updated_at"] = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    with open(AI_WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"AI 워치리스트 저장: {len(data.get('stocks', []))}개")


def load_user_watchlist() -> list:
    if os.path.exists(USER_WATCHLIST_FILE):
        with open(USER_WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def get_combined_watchlist() -> list:
    ai_list   = load_ai_watchlist()
    user_list = load_user_watchlist()
    return list(dict.fromkeys(ai_list + user_list))


def update_ai_watchlist():
    print("AI 워치리스트 업데이트 시작...")
    scored  = get_all_stocks_score()
    print("시장 컨텍스트 수집 중...")
    context = get_market_context()
    print("Claude 워치리스트 선정 중...")
    data    = select_ai_watchlist(scored, context)

    if data and data.get("stocks"):
        save_ai_watchlist(data)
        print(f"\n✅ AI 워치리스트 업데이트 완료!")
        print(f"이번 주 테마: {data.get('weekly_theme','')}")
        print(f"주목 섹터: {data.get('sector_focus', [])}")
        print(f"선정 종목: {len(data['stocks'])}개")
        return data
    else:
        print("❌ AI 워치리스트 선정 실패")
        return {}


if __name__ == "__main__":
    data = update_ai_watchlist()
    if data:
        print(f"\n리스크 경고: {data.get('risk_warning','')}")
        print("\n=== 종목별 태그 ===")
        for s in data.get("stocks", [])[:10]:
            print(f"  {s['name']} [{s['sector']}] [{s['style']}] - {s['reason']}")
