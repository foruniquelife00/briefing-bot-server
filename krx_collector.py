import sqlite3
import yfinance as yf
import FinanceDataReader as fdr
from datetime import datetime, timezone, timedelta
import config

DB_PATH = config.DB_PATH

# KRX API 키 (승인 후 추가)
KRX_API_KEY = getattr(config, 'KRX_API_KEY', None)


def init_krx_db():
    """외국인 순매수·공매도 DB 초기화"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS foreign_trading (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            stock_name      TEXT NOT NULL,
            foreign_hold    REAL,
            foreign_hold_chg REAL,
            close_price     REAL,
            volume          REAL,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_indicators (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL UNIQUE,
            kospi_close REAL,
            kospi_vol   REAL,
            kosdaq_close REAL,
            usd_krw     REAL,
            vix         REAL,
            us_10y      REAL,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()


def collect_foreign_holdings() -> list:
    """주요 종목 외국인 보유비율 수집 (yfinance)"""
    from watchlist import STOCK_MAP, load_watchlist
    watchlist = load_watchlist()

    today  = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    results = []

    # 워치리스트 국내 종목만
    kr_stocks = [
        (name, STOCK_MAP[name])
        for name in watchlist
        if name in STOCK_MAP and STOCK_MAP[name].endswith(('.KS', '.KQ'))
    ]

    print(f"외국인 보유비율 수집 중... ({len(kr_stocks)}개)")

    conn = sqlite3.connect(DB_PATH)

    for name, ticker in kr_stocks[:20]:  # 상위 20개만
        try:
            t    = yf.Ticker(ticker)
            info = t.info
            hold = info.get('heldPercentInstitutions', 0) or 0

            # 전날 보유비율과 비교
            prev = conn.execute("""
                SELECT foreign_hold FROM foreign_trading
                WHERE ticker = ? ORDER BY date DESC LIMIT 1
            """, (ticker,)).fetchone()

            hold_chg = (hold - prev[0]) if prev else 0.0
            price    = t.fast_info.last_price

            conn.execute("""
                INSERT OR REPLACE INTO foreign_trading
                    (date, ticker, stock_name, foreign_hold, foreign_hold_chg, close_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (today, ticker, name, hold, hold_chg, price))

            results.append({
                "name":      name,
                "ticker":    ticker,
                "hold":      f"{hold*100:.1f}%",
                "hold_chg":  hold_chg,
                "signal":    "🟢 매수" if hold_chg > 0 else "🔴 매도" if hold_chg < 0 else "⚪ 유지",
            })
        except Exception as e:
            pass

    conn.commit()
    conn.close()
    return results


def collect_market_indicators() -> dict:
    """시장 거시 지표 수집"""
    today    = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    data = {}
    try:
        # 코스피
        kospi = fdr.DataReader('KS11', week_ago, today)
        if not kospi.empty:
            data['kospi_close'] = float(kospi['Close'].iloc[-1])
            data['kospi_vol']   = float(kospi['Volume'].iloc[-1])

        # 원달러
        usd = yf.Ticker("USDKRW=X").fast_info.last_price
        data['usd_krw'] = usd

        # VIX
        vix = yf.Ticker("^VIX").fast_info.last_price
        data['vix'] = vix

        # 미국 10년물 금리
        us10y = yf.Ticker("^TNX").fast_info.last_price
        data['us_10y'] = us10y

        # DB 저장
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT OR REPLACE INTO market_indicators
                (date, kospi_close, kospi_vol, usd_krw, vix, us_10y)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            today,
            data.get('kospi_close'),
            data.get('kospi_vol'),
            data.get('usd_krw'),
            data.get('vix'),
            data.get('us_10y'),
        ))
        conn.commit()
        conn.close()
        print(f"시장 지표 저장 완료: VIX={data.get('vix',0):.1f} 금리={data.get('us_10y',0):.2f}%")

    except Exception as e:
        print(f"시장 지표 수집 오류: {e}")

    return data


def get_foreign_signal_summary() -> str:
    """외국인 매수/매도 신호 요약 (브리핑용)"""
    conn  = sqlite3.connect(DB_PATH)
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT stock_name, foreign_hold, foreign_hold_chg
        FROM foreign_trading
        WHERE date = ?
        ORDER BY foreign_hold_chg DESC
    """, (today,)).fetchall()
    conn.close()

    if not rows:
        return "외국인 데이터 없음"

    buy_stocks  = [(r[0], r[2]) for r in rows if r[2] > 0.001]
    sell_stocks = [(r[0], r[2]) for r in rows if r[2] < -0.001]

    lines = ["📊 외국인 보유비율 변화"]
    if buy_stocks:
        lines.append("🟢 증가: " + ", ".join([f"{n}(+{c*100:.2f}%)" for n, c in buy_stocks[:3]]))
    if sell_stocks:
        lines.append("🔴 감소: " + ", ".join([f"{n}({c*100:.2f}%)" for n, c in sell_stocks[:3]]))

    # 시장 지표
    conn = sqlite3.connect(DB_PATH)
    ind  = conn.execute("""
        SELECT vix, us_10y, usd_krw FROM market_indicators
        ORDER BY date DESC LIMIT 1
    """).fetchone()
    conn.close()

    if ind:
        lines.append(f"📈 VIX: {ind[0]:.1f} | 미국10년물: {ind[1]:.2f}% | 원달러: {ind[2]:,.0f}원")

    return "\n".join(lines)


def run_daily_collection():
    """매일 실행할 데이터 수집"""
    print("=== KRX 데이터 수집 시작 ===")
    init_krx_db()
    collect_market_indicators()
    results = collect_foreign_holdings()
    print(f"외국인 데이터 수집: {len(results)}개")
    print(get_foreign_signal_summary())


if __name__ == "__main__":
    run_daily_collection()




def get_krx_daily_trade(market="kospi"):
    """KRX OpenAPI - 일별매매정보 (종가·등락률·거래량·시가총액)"""
    import requests as req
    import config
    from datetime import datetime, timedelta

    api_map = {
        "kospi":  "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
        "kosdaq": "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
    }
    url = api_map.get(market, api_map["kospi"])

    today = datetime.now()
    bas_dd = today.strftime("%Y%m%d")
    for i in range(1, 5):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            bas_dd = d.strftime("%Y%m%d")
            break

    headers = {"AUTH_KEY": config.KRX_API_KEY}
    params  = {"basDd": bas_dd}

    try:
        res   = req.get(url, params=params, headers=headers, timeout=10)
        items = res.json().get("OutBlock_1", [])
        result = {}
        for item in items:
            code = item.get("ISU_CD", "")  # "005930" 형태
            result[code] = {
                "name":   item.get("ISU_NM",""),
                "close":  item.get("TDD_CLSPRC",""),
                "chg":    item.get("CMPPREVDD_PRC",""),
                "chg_rt": item.get("FLUC_RT",""),
                "volume": item.get("ACC_TRDVOL",""),
                "value":  item.get("ACC_TRDVAL",""),
                "mktcap": item.get("MKTCAP",""),
                "open":   item.get("TDD_OPNPRC",""),
                "high":   item.get("TDD_HGPRC",""),
                "low":    item.get("TDD_LWPRC",""),
            }
        print(f"KRX {market.upper()} 일별매매정보: {len(result)}건 ({bas_dd})")
        return result
    except Exception as e:
        print(f"KRX 일별매매정보 오류: {e}")
        return {}


def get_krx_stock_meta(market="kospi"):
    """KRX OpenAPI - 종목기본정보 (상장일·액면가·상장주식수)"""
    import requests as req
    import config
    from datetime import datetime, timedelta

    api_map = {
        "kospi":  "https://data-dbg.krx.co.kr/svc/apis/sto/stk_isu_base_info",
        "kosdaq": "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_isu_base_info",
    }
    url = api_map.get(market, api_map["kospi"])

    today = datetime.now()
    bas_dd = today.strftime("%Y%m%d")
    for i in range(1, 5):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            bas_dd = d.strftime("%Y%m%d")
            break

    headers = {"AUTH_KEY": config.KRX_API_KEY}
    params  = {"basDd": bas_dd}

    try:
        res   = req.get(url, params=params, headers=headers, timeout=10)
        items = res.json().get("OutBlock_1", [])
        result = {}
        for item in items:
            code = item.get("ISU_SRT_CD", "")
            result[code] = {
                "name":     item.get("ISU_ABBRV",""),
                "full_nm":  item.get("ISU_NM",""),
                "list_dd":  item.get("LIST_DD",""),
                "mkt":      item.get("MKT_TP_NM",""),
                "parval":   item.get("PARVAL",""),
                "list_shrs":item.get("LIST_SHRS",""),
            }
        print(f"KRX {market.upper()} 종목메타: {len(result)}건")
        return result
    except Exception as e:
        print(f"KRX 종목메타 오류: {e}")
        return {}
