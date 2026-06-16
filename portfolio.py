import sqlite3
import yfinance as yf
from datetime import datetime, timezone, timedelta
import config

DB_PATH = config.DB_PATH


def init_portfolio_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_name TEXT NOT NULL,
            ticker     TEXT NOT NULL,
            quantity   REAL NOT NULL,
            buy_price  REAL NOT NULL,
            buy_date   TEXT NOT NULL,
            memo       TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()


def add_portfolio(name: str, quantity: float, buy_price: float, memo: str = "") -> str:
    """포트폴리오 종목 추가"""
    from watchlist import STOCK_MAP
    if name not in STOCK_MAP:
        return f"❌ '{name}' 는 지원하지 않는 종목이에요.\n/종목목록 으로 확인해보세요."

    ticker   = STOCK_MAP[name]
    buy_date = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    is_kr    = ticker.endswith(".KS") or ticker.endswith(".KQ")
    buy_str  = f"{int(buy_price):,}원" if is_kr else f"${buy_price:.2f}"
    total    = buy_price * quantity
    total_str = f"{int(total):,}원" if is_kr else f"${total:,.2f}"

    init_portfolio_db()
    conn = sqlite3.connect(DB_PATH)

    # 이미 있으면 수량 추가 (평단가 계산)
    existing = conn.execute(
        "SELECT quantity, buy_price FROM portfolio WHERE stock_name = ?", (name,)
    ).fetchone()

    if existing:
        old_qty   = existing[0]
        old_price = existing[1]
        new_qty   = old_qty + quantity
        new_price = (old_price * old_qty + buy_price * quantity) / new_qty
        conn.execute(
            "UPDATE portfolio SET quantity = ?, buy_price = ? WHERE stock_name = ?",
            (new_qty, new_price, name)
        )
        is_kr2    = ticker.endswith(".KS") or ticker.endswith(".KQ")
        avg_str   = f"{int(new_price):,}원" if is_kr2 else f"${new_price:.2f}"
        msg = (
            f"✅ '{name}' 추가 매수 완료!\n"
            f"추가: {quantity}주 @ {buy_str}\n"
            f"평균 단가: {avg_str}\n"
            f"총 보유: {new_qty}주"
        )
    else:
        conn.execute("""
            INSERT INTO portfolio (stock_name, ticker, quantity, buy_price, buy_date, memo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, ticker, quantity, buy_price, buy_date, memo))
        msg = (
            f"✅ '{name}' 포트폴리오 추가 완료!\n"
            f"수량: {quantity}주 @ {buy_str}\n"
            f"투자금액: {total_str}"
        )

    conn.commit()
    conn.close()
    return msg


def remove_portfolio(name: str) -> str:
    """포트폴리오 종목 삭제"""
    init_portfolio_db()
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT id FROM portfolio WHERE stock_name = ?", (name,)
    ).fetchone()

    if not row:
        conn.close()
        return f"⚠️ '{name}' 는 포트폴리오에 없어요."

    conn.execute("DELETE FROM portfolio WHERE stock_name = ?", (name,))
    conn.commit()
    conn.close()
    return f"✅ '{name}' 를 포트폴리오에서 삭제했어요."


def get_portfolio_status() -> str:
    """포트폴리오 현재 수익률 조회"""
    init_portfolio_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT stock_name, ticker, quantity, buy_price, buy_date
        FROM portfolio ORDER BY buy_date ASC
    """).fetchall()
    conn.close()

    if not rows:
        return "📋 포트폴리오가 비어있어요.\n/포트폴리오추가 종목명 수량 매수가"

    lines        = ["💼 포트폴리오 현황\n"]
    total_invest = 0
    total_current = 0
    items        = []

    from toss_price import get_prices
    _prices = get_prices([r[1] for r in rows])   # 토스 일괄 1콜 + yfinance fallback

    for row in rows:
        name, ticker, qty, buy_price, buy_date = row
        try:
            current  = _prices.get(ticker)
            if current is None:
                continue
            is_kr    = ticker.endswith(".KS") or ticker.endswith(".KQ")
            fmt      = lambda x: f"{int(x):,}원" if is_kr else f"${x:,.2f}"
            rate     = (current - buy_price) / buy_price * 100
            invest   = buy_price * qty
            cur_val  = current * qty
            profit   = cur_val - invest
            arrow    = "▲" if rate >= 0 else "▼"

            total_invest  += invest
            total_current += cur_val

            items.append({
                "name":    name,
                "qty":     qty,
                "buy":     fmt(buy_price),
                "current": fmt(current),
                "rate":    rate,
                "profit":  profit,
                "invest":  invest,
                "cur_val": cur_val,
                "arrow":   arrow,
                "is_kr":   is_kr,
                "fmt":     fmt,
            })
        except:
            pass

    # 종목별 출력
    for item in items:
        profit_str = f"{int(item['profit']):+,}원" if item['is_kr'] else f"${item['profit']:+,.2f}"
        lines.append(
            f"{'📈' if item['rate'] >= 0 else '📉'} {item['name']}\n"
            f"  {item['qty']}주 | 매수 {item['buy']} → 현재 {item['current']}\n"
            f"  {item['arrow']} {item['rate']:+.2f}% ({profit_str})\n"
        )

    # 전체 요약
    total_rate   = (total_current - total_invest) / total_invest * 100 if total_invest else 0
    total_profit = total_current - total_invest
    is_kr_total  = True  # 혼합 포트폴리오는 원화 기준

    lines += [
        "─" * 22,
        f"💰 총 투자금액: {int(total_invest):,}원",
        f"💵 현재 평가액: {int(total_current):,}원",
        f"{'📈' if total_rate >= 0 else '📉'} 총 수익률: {total_rate:+.2f}%",
        f"💹 총 손익: {int(total_profit):+,}원",
    ]

    return "\n".join(lines)


def get_portfolio_data() -> list:
    """대시보드용 포트폴리오 데이터"""
    init_portfolio_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT stock_name, ticker, quantity, buy_price, buy_date
        FROM portfolio ORDER BY buy_date ASC
    """).fetchall()
    conn.close()

    items = []
    from toss_price import get_prices
    _prices = get_prices([r[1] for r in rows])   # 토스 일괄 1콜 + yfinance fallback

    for row in rows:
        name, ticker, qty, buy_price, buy_date = row
        try:
            current = _prices.get(ticker)
            if current is None:
                continue
            is_kr   = ticker.endswith(".KS") or ticker.endswith(".KQ")
            fmt     = lambda x: f"{int(x):,}원" if is_kr else f"${x:,.2f}"
            rate    = (current - buy_price) / buy_price * 100
            invest  = buy_price * qty
            cur_val = current * qty
            profit  = cur_val - invest

            items.append({
                "종목":     name,
                "수량":     f"{qty:.0f}주",
                "매수가":   fmt(buy_price),
                "현재가":   fmt(current),
                "수익률":   f"{rate:+.2f}%",
                "투자금액": fmt(invest),
                "평가금액": fmt(cur_val),
                "손익":     fmt(profit),
                "_rate":    rate,
                "_invest":  invest,
                "_cur_val": cur_val,
            })
        except:
            pass
    return items


if __name__ == "__main__":
    init_portfolio_db()
    # 테스트
    print(add_portfolio("삼성전자", 10, 204000))
    print(add_portfolio("엔비디아", 5, 182.08))
    print()
    print(get_portfolio_status())
