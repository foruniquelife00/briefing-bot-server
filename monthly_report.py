import anthropic
import sqlite3
import yfinance as yf
import requests
import config
from datetime import datetime, timezone, timedelta
from sender import send_all

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """당신은 시장 정보와 시스템 운영 현황을 설명하는 브리핑 분석가입니다.
사실, 데이터, 시장 배경, 위험요인을 정리합니다.
종목 추천, 매매 지시, 비중 조정, 헤지 상품 편입, 자산배분 지침을 제공하지 않습니다.
시그널봇의 검증 상태와 위험 게이트를 존중하며 이를 우회하지 않습니다."""


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

    # 시그널봇 운영상태 (읽기 전용 단방향 — §5). 실패 시 '확인 불가' 문자열.
    try:
        from signal_status import format_signal_status
        signal_status = format_signal_status()
    except Exception as e:
        signal_status = f"시그널 시스템 운영상태 데이터 확인 불가 ({type(e).__name__})"

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

## 🔒 시그널 시스템 운영 현황 (사실 데이터 — 임의 추정 금지)
{signal_status}

## 📝 월간 리포트 형식
1. 📌 {perf.get('month', '지난달')} 한줄 총평 (사실 요약)
2. 📊 시장 분석 (지난달 주요 흐름 3~4줄)
3. 📈 기록된 종목 성과 분석
   - 잘된 점
   - 아쉬운 점
   - 데이터상 관찰된 특징 (개선 '지시'가 아니라 관찰 사실로 기술)
4. 💼 월간 수익률 기록 요약
5. 🔍 이번 달 주요 변수 및 위험요인
6. 🧭 다음 달 시장 관찰 포인트
   - 주요 일정
   - 시장 위험요인
   - 환율·금리·원자재 확인 항목
   - 변동성 확대 시 유의사항
7. 🔒 시그널 시스템 운영 현황
   (위 '시그널 시스템 운영 현황' 데이터를 그대로 정리. 없으면 '확인 불가'로 표기)
8. 💬 브리핑 한마디 (사실 기반 마무리)

## ⛔ 반드시 지킬 것 (역할 경계)
- 종목 추천, 매수·매도 지시, 목표가·손절가 제시 금지
- 비중 조정안, 현금 비중 확대·축소 지시 금지
- 인버스·레버리지·헤지 상품 편입 제안 금지
- 분할매수 트리거, 자산배분 지침 금지
- 환율·금리는 '설명'까지만. "환율 오르면 비중 줄여라" 같은 지시 금지
- 시그널 시스템은 G3 paper-only(가상 검증)이며 실전 매매가 아님을 전제로 서술"""

    message = client.messages.create(
        model=getattr(config, "CLAUDE_MODEL", "claude-sonnet-4-6"),
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    briefing = message.content[0].text
    month    = perf.get("month", "지난달")
    header   = f"📅 {month} 월간 투자 성과 리포트\n{today}\n{'━' * 22}\n\n"
    return header + briefing


def send_monthly_report():
    """
    월간 리포트 발송 — 발송 전 역할 경계 검사 (§7).
    검사 실패 시 Telegram 발송 금지, status=blocked_role_boundary 기록.
    """
    print("월간 리포트 생성 중...")
    try:
        msg   = generate_monthly_report()
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m")

        # ── 발송 전 안전 검사 (§7) ──
        from role_boundary import check_role_boundary, ensure_disclaimer
        chk = check_role_boundary(msg)
        if not chk["ok"]:
            reason = "; ".join(f"{v['type']}: {v['evidence']}" for v in chk["violations"])
            _log_blocked(today, msg, reason)
            print(f"⛔ 발송 차단 (blocked_role_boundary) — 위반 {len(chk['violations'])}건")
            for v in chk["violations"]:
                print(f"   · {v['type']}: {v['evidence']}")
            return {"status": "blocked_role_boundary", "violations": chk["violations"]}

        msg = ensure_disclaimer(msg)                      # 면책 문구 (§8)
        result = send_all(msg, subject=f"📅 {today} 월간 리포트")
        print(f"텔레그램: {'✅' if result['telegram'] else '❌'}")
        print(f"이메일:   {'✅' if result['email'] else '❌'}")
        return {"status": "sent", **result}
    except Exception as e:
        print(f"월간 리포트 오류: {e}")
        return {"status": "error", "error": str(e)}


def _log_blocked(month: str, original: str, reason: str):
    """차단 시 원문·사유를 내부 로그에 보존 (§7)"""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "role_boundary_blocked.log")
    ts = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n[{ts}] month={month}\n"
                f"status=blocked_role_boundary\nfailure_reason={reason}\n"
                f"{'-'*70}\n{original}\n")


if __name__ == "__main__":
    send_monthly_report()
