import yfinance as yf
import requests
from bs4 import BeautifulSoup
import time

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
})

def get_index(ticker: str) -> dict:
    try:
        t     = yf.Ticker(ticker)
        info  = t.fast_info
        price = info.last_price
        prev  = info.regular_market_previous_close
        change = price - prev
        rate   = (change / prev) * 100
        return {
            "value":  f"{price:,.2f}",
            "change": f"{change:+,.2f}",
            "rate":   f"{rate:+.2f}%",
            "up":     rate >= 0,
        }
    except Exception as e:
        print(f"{ticker} 오류: {e}")
        return {"value": "N/A", "change": "N/A", "rate": "N/A", "up": None}

def get_stock_detail(name: str, ticker: str) -> dict:
    try:
        t    = yf.Ticker(ticker)
        info = t.fast_info
        full = t.info

        price      = info.last_price
        prev_close = info.regular_market_previous_close
        change     = price - prev_close
        rate       = (change / prev_close) * 100
        high52     = info.year_high
        low52      = info.year_low
        per        = full.get("trailingPE", "N/A")
        per        = round(per, 1) if isinstance(per, float) else "N/A"
        volume     = info.three_month_average_volume or 0

        is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")
        fmt   = lambda x: f"{int(x):,}원" if is_kr else f"${x:,.2f}"

        return {
            "name":         name,
            "ticker":       ticker,
            "price":        fmt(price),
            "change":       f"{int(change):+,}원" if is_kr else f"${change:+.2f}",
            "rate":         f"{rate:+.2f}%",
            "week52_high":  fmt(high52),
            "week52_low":   fmt(low52),
            "per":          str(per),
            "up":           rate >= 0,
            "raw_price":    price,
            "raw_prev":     prev_close,
            "raw_rate":     rate,
            "raw_high52":   high52,
            "raw_low52":    low52,
            "volume":       volume,
        }
    except Exception as e:
        print(f"  {name} 오류: {e}")
        return {
            "name": name, "ticker": ticker,
            "price": "N/A", "change": "N/A", "rate": "N/A",
            "week52_high": "N/A", "week52_low": "N/A",
            "per": "N/A", "up": None,
            "raw_price": None, "raw_prev": None,
            "raw_rate": 0, "raw_high52": None,
            "raw_low52": None, "volume": 0,
        }

def filter_top_candidates(stocks: dict, top_n: int = 40) -> dict:
    """
    2단계 필터링 — 브리핑 추천용 후보 압축
    기준:
      1. 등락률 상위/하위 (모멘텀)
      2. 52주 고가 근접 (강세 신호)
      3. 52주 저가 근접 (역발상 기회)
    """
    valid = {k: v for k, v in stocks.items() if v.get("raw_price")}

    scored = []
    for name, s in valid.items():
        score = 0
        rate  = s.get("raw_rate", 0)
        price = s.get("raw_price", 0)
        high  = s.get("raw_high52", 1)
        low   = s.get("raw_low52", 1)

        # 등락률 모멘텀 점수
        score += abs(rate) * 2

        # 52주 고가 근접 (90% 이상)
        if high and price >= high * 0.90:
            score += 10

        # 52주 저가 근접 (110% 이하) — 역발상
        if low and price <= low * 1.10:
            score += 8

        scored.append((score, name, s))

    # 점수 내림차순 정렬
    scored.sort(key=lambda x: x[0], reverse=True)

    # 상위 top_n개 반환
    return {name: s for _, name, s in scored[:top_n]}

def get_market_data() -> dict:
    data = {}

    print("주요 지수 수집 중...")
    data["sp500"]  = get_index("^GSPC")
    data["nasdaq"] = get_index("^IXIC")
    data["dow"]    = get_index("^DJI")
    data["nikkei"] = get_index("^N225")
    data["kospi"]  = get_index("^KS11")
    data["kosdaq"] = get_index("^KQ11")
    print("지수 완료")

    time.sleep(1)

    try:
        usd_krw = yf.Ticker("USDKRW=X")
        data["usd_krw"] = f"{usd_krw.fast_info.last_price:,.2f}"
        print("환율 완료")
    except Exception as e:
        print(f"환율 오류: {e}")
        data["usd_krw"] = "N/A"

    time.sleep(1)

    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        fgi = res.json()
        data["fgi_score"]  = int(fgi["data"][0]["value"])
        data["fgi_rating"] = fgi["data"][0]["value_classification"]
        print("공포탐욕지수 완료")
    except Exception as e:
        print(f"공포탐욕지수 오류: {e}")
        data["fgi_score"]  = "N/A"
        data["fgi_rating"] = "N/A"

    time.sleep(1)

    try:
        res = SESSION.get(
            "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258",
            timeout=10
        )
        soup = BeautifulSoup(res.text, "lxml")
        data["news"] = [n.text.strip() for n in soup.select(".articleSubject a")[:5]]
        print(f"뉴스 완료: {len(data['news'])}건")
    except Exception as e:
        print(f"뉴스 오류: {e}")
        data["news"] = []

    time.sleep(1)

    # 1단계: 워치리스트 전체 수집
    from ai_watchlist import get_combined_watchlist
    from watchlist import STOCK_MAP
    watchlist = get_combined_watchlist()
    print(f"워치리스트 {len(watchlist)}개 병렬 수집 중...")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_stocks = {}
    def fetch(name):
        ticker = STOCK_MAP.get(name)
        if not ticker:
            return name, None
        return name, get_stock_detail(name, ticker)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch, name): name for name in watchlist}
        for future in as_completed(futures):
            name, result = future.result()
            if result:
                all_stocks[name] = result

    print(f"전체 수집 완료: {len(all_stocks)}개")

    # 2단계: 브리핑 추천용 후보 필터링 (상위 40개)
    top_candidates = filter_top_candidates(all_stocks, top_n=40)
    print(f"필터링 후보: {len(top_candidates)}개")

    data["stocks"]         = all_stocks      # 전체 (대시보드·시세 조회용)
    data["top_candidates"] = top_candidates  # 필터링된 후보 (브리핑 추천용)

    return data

if __name__ == "__main__":
    data = get_market_data()
    print("\n=== 브리핑 추천 후보 TOP 10 ===")
    candidates = data["top_candidates"]
    for i, (name, s) in enumerate(list(candidates.items())[:10]):
        print(f"{i+1}. {name}: {s['price']} ({s['rate']})")


def get_premarket_data() -> dict:
    """미국 주요 지수 + 종목 프리마켓 데이터"""
    targets = {
        "S&P500 선물": "^GSPC",
        "나스닥 선물": "^IXIC",
        "DOW 선물":    "^DJI",
        "엔비디아":    "NVDA",
        "애플":        "AAPL",
        "테슬라":      "TSLA",
    }

    results = {}
    for name, ticker in targets.items():
        try:
            info = yf.Ticker(ticker).info
            pre_price  = info.get("preMarketPrice")
            pre_change = info.get("preMarketChangePercent")
            reg_price  = info.get("regularMarketPrice")

            if pre_price and reg_price:
                diff = pre_price - reg_price
                rate = pre_change * 100 if pre_change else (diff / reg_price * 100)
                arrow = "▲" if rate >= 0 else "▼"
                results[name] = {
                    "pre_price":  f"${pre_price:,.2f}",
                    "reg_price":  f"${reg_price:,.2f}",
                    "rate":       f"{arrow} {rate:+.2f}%",
                    "raw_rate":   rate,
                }
            else:
                results[name] = None
        except Exception as e:
            print(f"프리마켓 {name} 오류: {e}")
            results[name] = None

    return results


def get_commodity_data() -> dict:
    """유가·금·은 실시간"""
    targets = {
        "WTI유가":  "CL=F",
        "브렌트유": "BZ=F",
        "금":       "GC=F",
        "은":       "SI=F",
    }

    results = {}
    for name, ticker in targets.items():
        try:
            t     = yf.Ticker(ticker)
            info  = t.fast_info
            price = info.last_price
            prev  = info.regular_market_previous_close
            rate  = (price - prev) / prev * 100
            arrow = "▲" if rate >= 0 else "▼"

            if "유" in name:
                results[name] = {
                    "price": f"${price:.2f}",
                    "rate":  f"{arrow} {rate:+.2f}%",
                    "raw_rate": rate,
                }
            else:
                results[name] = {
                    "price": f"${price:,.2f}",
                    "rate":  f"{arrow} {rate:+.2f}%",
                    "raw_rate": rate,
                }
        except Exception as e:
            print(f"원자재 {name} 오류: {e}")
            results[name] = None

    return results
