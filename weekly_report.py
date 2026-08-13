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
5. 비중 조정·현금 비중 확대/축소·자산배분 지침·헤지 상품 편입 제안 금지 (설명까지만)
시그널 시스템은 G3 paper-only(가상 검증)이며 실전 매매가 아니다."""


def _guard_or_block(msg: str, tag: str):
    """
    발송 전 역할 경계 검사 (GPT 20260802 §3 — 주간에도 월간과 동일 적용).
    통과 시 면책문구 부착한 본문 반환, 위반 시 None (발송 금지).
    """
    from role_boundary import check_role_boundary, ensure_disclaimer
    chk = check_role_boundary(msg)
    if not chk["ok"]:
        reason = "; ".join(f"{v['type']}: {v['evidence']}" for v in chk["violations"])
        _log_blocked(tag, msg, reason)
        print(f"⛔ 발송 차단 (blocked_role_boundary) — 위반 {len(chk['violations'])}건")
        for v in chk["violations"]:
            print(f"   · {v['type']}: {v['evidence']}")
        return None
    return ensure_disclaimer(msg)


def _log_blocked(tag: str, original: str, reason: str):
    """차단 원문·사유 보존 (§3)"""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "role_boundary_blocked.log")
    ts = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n[{ts}] tag={tag}\nstatus=blocked_role_boundary\n"
                f"failure_reason={reason}\n{'-'*70}\n{original}\n")


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

    # 시그널봇 운영상태 (읽기 전용 단방향 — GPT §5)
    try:
        from signal_status import format_signal_status
        signal_status = format_signal_status()
    except Exception as e:
        signal_status = f"시그널 시스템 운영상태 데이터 확인 불가 ({type(e).__name__})"

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
6. 🧭 이번 주 시장 관찰 포인트
   - 주요 경제 일정
   - 시장 위험요인
   - 환율·금리·원자재 확인 항목
7. ⚠️ 이번 주 리스크 요인
8. 🔒 시그널 시스템 운영 상태 (아래 데이터 그대로 정리, 없으면 '확인 불가')
{signal_status}
9. 💬 브리핑 한마디

## ⛔ 반드시 지킬 것 (역할 경계)
- 종목 추천, 매수·매도 지시, 목표가·손절가 제시 금지
- 비중 조정안, 현금 비중 확대·축소 지시 금지
- 인버스·레버리지·헤지 상품 편입 제안 금지
- 분할매수 트리거, 자산배분 지침 금지
- 환율·금리는 '설명'까지만 ("환율 오르면 비중 줄여라" 같은 지시 금지)
- 시그널 시스템은 G3 paper-only(가상 검증)이며 실전 매매가 아님"""

    message = client.messages.create(
        model=getattr(config, "CLAUDE_MODEL", "claude-sonnet-4-6"),
        max_tokens=6000,   # 4000도 부족해 §8 중간 절단 (2026-08-11 실측)
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
        msg   = generate_weekly_briefing()
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m.%d")
        gate  = _guard_or_block(msg, f"weekly_{today}")
        if gate is None:
            return {"status": "blocked_role_boundary"}
        # C+ §7 운영지표 — 주 1회 함께 발송 (verify 스크립트에서만 보이던 상태 해소)
        try:
            import delivery_status as _DS
            gate = gate + "\n\n" + "─" * 22 + "\n" + _DS.metrics_report(7)
        except Exception as _me:
            print(f"발송지표 첨부 실패(무영향): {_me}")
        result = send_all(gate, subject=f"📰 주간 뉴스레터 {today}")
        print(f"텔레그램: {'✅' if result['telegram'] else '❌'}")
        print(f"이메일:   {result.get('email_status', '?')}")
        return {"status": "sent", **result}
    except Exception as e:
        print(f"주간 뉴스레터 오류: {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    send_weekly_report()


FRIDAY_SYSTEM_PROMPT = """당신은 시장 배경을 해석하는 거시 시장 애널리스트입니다.
30년 이상 거시·시장 분석 경험. 매주 금요일 장 마감 후 주간 시장 결산과 다음 주 배경 전망을 작성합니다.
다음 주는 낙관·중립·비관 3가지 지수 시나리오를 확률과 함께 제시합니다.

## 절대 규칙 (역할 경계)
1. 개별 종목 추천/목표가/매수 의견 금지 (종목명은 시장 배경 설명용만)
2. 지수 시나리오·섹터 흐름·리스크는 OK, 개별 종목 매수 판단은 시그널봇 역할
3. 확정 예측 금지, 시나리오·관찰 포인트로 서술
4. 비중 조정·현금 비중 확대/축소·자산배분 지침·헤지 상품 편입 제안 금지 (설명까지만)
시그널 시스템은 G3 paper-only(가상 검증)이며 실전 매매가 아니다."""


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

    # 시그널봇 운영상태 (읽기 전용 단방향 — GPT §5)
    try:
        from signal_status import format_signal_status
        signal_status = format_signal_status()
    except Exception as e:
        signal_status = f"시그널 시스템 운영상태 데이터 확인 불가 ({type(e).__name__})"

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
8. 🧭 다음 주 시장 관찰 포인트
   - 주요 경제 일정
   - 시장 위험요인
   - 환율·금리·원자재 확인 항목
   - 변동성 확대 시 유의사항
9. 🔒 시그널 시스템 운영 상태 (아래 데이터 그대로 정리, 없으면 '확인 불가')
{signal_status}
10. ⚠️ 다음 주 주요 리스크
11. 💬 브리핑 한마디

## ⛔ 반드시 지킬 것 (역할 경계)
- 종목 추천, 매수·매도 지시, 목표가·손절가 제시 금지
- 비중 조정안, 현금 비중 확대·축소 지시 금지
- 인버스·레버리지·헤지 상품 편입 제안 금지
- 분할매수 트리거, 자산배분 지침 금지
- 환율·금리는 '설명'까지만 ("환율 오르면 비중 줄여라" 같은 지시 금지)
- 시그널 시스템은 G3 paper-only(가상 검증)이며 실전 매매가 아님"""

    message = client.messages.create(
        model=getattr(config, "CLAUDE_MODEL", "claude-sonnet-4-6"),
        max_tokens=6000,   # 4000도 부족해 §8 중간 절단 (2026-08-11 실측)
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
        msg   = generate_friday_briefing()
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m.%d")
        gate  = _guard_or_block(msg, f"friday_{today}")
        if gate is None:
            return {"status": "blocked_role_boundary"}
        result = send_all(gate, subject=f"📊 주간 결산 & 다음 주 전망 {today}")
        print(f"텔레그램: {'✅' if result['telegram'] else '❌'}")
        print(f"이메일:   {result.get('email_status', '?')}")
        return {"status": "sent", **result}
    except Exception as e:
        print(f"금요일 리포트 오류: {e}")
        return {"status": "error", "error": str(e)}
