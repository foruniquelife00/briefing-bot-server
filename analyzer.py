import anthropic
import config
from datetime import datetime
from eco_calendar import get_this_week_events, get_us_news_sentiment, format_sentiment
from validator     import validate_briefing
from cross_verify   import verify_briefing
from briefing_store  import build_context_prompt, save_briefing
from trust_score    import calculate_trust_score, format_trust_report
from collector    import get_premarket_data, get_commodity_data

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """당신은 세계 최고 수준의 투자 애널리스트입니다.

## 당신의 경험
- 30년 이상의 실전 투자 경험
- 1997년 IMF, 2000년 닷컴버블, 2008년 금융위기, 2020년 코로나 직접 경험
- 전쟁, 계엄 선언, 트럼프 돌발 발언 등 예측 불가 변수 수십 차례 경험
- 극단적 공포 구간에서 역발상 매수로 수익 실현한 다수의 경험

## 투자 철학 (고유 공식)
1. 변동성 = 기회 — 공포탐욕지수 20 이하는 역발상 매수 신호
2. 3분할 원칙 — 단기(30%) + 중기(40%) + 장기(30%)
3. 헤지 필수 — 달러·금·채권 10~15% 항상 확보
4. 분기 10~20% 수익 목표
5. 손절 -7% 원칙 절대 준수

## 운용 기준
- 총 운용 자산: 5,000만원
- 포트폴리오: 국내 주식 + 미국 ETF + 달러/금/채권 + 단기 트레이딩

## ⚠️ 절대 규칙
1. 종목 가격·목표가·손절가는 반드시 [실시간 종목 데이터]에 있는 수치만 사용
2. 목표가 = 현재가 기준 +10~25% 범위로만 제시
3. 손절가 = 현재가 기준 -7% 이내로만 제시
4. [실시간 종목 데이터]에 없는 종목은 절대 추천 금지
5. 학습된 과거 가격 데이터는 절대 사용 금지"""


def build_stock_info(stocks: dict) -> str:
    lines = []
    for name, s in stocks.items():
        if s.get("price") == "N/A" or not s.get("raw_price"):
            continue
        lines.append(
            f"- {name} ({s['ticker']}): "
            f"현재가 {s['price']} ({s['rate']}) | "
            f"52주 {s['week52_low']}~{s['week52_high']} | "
            f"PER {s['per']}"
        )
    return "\n".join(lines)


def build_premarket_info(premarket: dict) -> str:
    lines = []
    for name, d in premarket.items():
        if d:
            lines.append(f"- {name}: {d['pre_price']} ({d['rate']}) | 전일 정규장: {d['reg_price']}")
    return "\n".join(lines) if lines else "프리마켓 데이터 없음"


def build_commodity_info(commodity: dict) -> str:
    lines = []
    for name, d in commodity.items():
        if d:
            lines.append(f"- {name}: {d['price']} ({d['rate']})")
    return "\n".join(lines) if lines else "원자재 데이터 없음"


def analyze(market_data: dict) -> str:
    today         = datetime.now().strftime("%Y년 %m월 %d일 (%a)")
    news          = "\n".join([f"- {n}" for n in market_data["news"]])
    stock_info    = build_stock_info(market_data.get("top_candidates", market_data.get("stocks", {})))
    calendar_str  = get_this_week_events()
    sentiment     = get_us_news_sentiment()
    sentiment_str = format_sentiment(sentiment)

    # 프리마켓 + 원자재
    premarket  = get_premarket_data()
    commodity  = get_commodity_data()
    pre_str    = build_premarket_info(premarket)
    com_str    = build_commodity_info(commodity)

    context = build_context_prompt(3)

    # 외국인 신호 추가
    try:
        from krx_collector import get_foreign_signal_summary
        foreign_signal = get_foreign_signal_summary()
    except:
        foreign_signal = ""

    # 앙상블 신호 추가
    try:
        from ensemble_signal import calculate_ensemble, format_ensemble_report, save_ensemble_to_db
        top_stocks = list(market_data.get("top_candidates", {}).items())[:3]
        ensemble_text = ""
        for name, data in top_stocks:
            ticker = data.get("ticker", "")
            if ticker:
                result = calculate_ensemble(name, ticker, "", market_data)
                save_ensemble_to_db(result)
                ensemble_text += format_ensemble_report(result)
    except Exception as e:
        ensemble_text = ""
        print(f"앙상블 신호 오류: {e}")
    prompt = f"""오늘은 {today}입니다. 아래 실시간 데이터를 바탕으로 투자 브리핑을 작성해주세요.

{context}

## 🌐 외국인 매매 신호
{foreign_signal}

## 🎯 앙상블 신호
{ensemble_text}

## 📊 주요 지수 (전일 종가)
- S&P 500:  {market_data['sp500']['value']}  ({market_data['sp500']['rate']})
- NASDAQ:   {market_data['nasdaq']['value']} ({market_data['nasdaq']['rate']})
- DOW:      {market_data['dow']['value']}    ({market_data['dow']['rate']})
- 니케이:   {market_data['nikkei']['value']} ({market_data['nikkei']['rate']})
- 코스피:   {market_data['kospi']['value']}  ({market_data['kospi']['rate']})
- 코스닥:   {market_data['kosdaq']['value']} ({market_data['kosdaq']['rate']})
- 원/달러:  {market_data['usd_krw']}원
- 공포탐욕지수: {market_data['fgi_score']} ({market_data['fgi_rating']})

## 🌅 미국 프리마켓 (장 시작 전 동향)
{pre_str}

## 🛢️ 원자재 실시간
{com_str}

## 📰 국내 주요 뉴스
{news}

## 🌐 글로벌 뉴스 감성
{sentiment_str}

## 📅 이번 주 경제 캘린더
{calendar_str}

## 📈 실시간 종목 데이터 (이 데이터만 사용할 것)
{stock_info}

## ⚠️ 작성 규칙
- 모든 가격 수치는 위 [실시간 종목 데이터]에서만 가져올 것
- 목표가 = 현재가 × (1 + 10~25%)
- 손절가 = 현재가 × 0.93 이상
- 위 목록에 없는 종목 추천 금지
- 학습된 과거 가격 절대 사용 금지
- 프리마켓 데이터를 오늘 장 방향 판단에 적극 활용

## 📝 브리핑 형식
1. 📌 오늘의 한줄 시황
2. 🌅 프리마켓 동향 (미국 장 방향 예측)
3. 🌍 글로벌 시장 분석 (3~4줄)
4. 🛢️ 원자재 동향 (유가·금이 시장에 미치는 영향)
5. 🇰🇷 국내 시장 분석 (3~4줄)
6. ⚠️ 오늘의 주요 리스크 (2~3줄)
7. 📅 오늘 주목할 경제 이벤트
8. 🧭 투자 전략 (단기/중기/장기 각 1~2줄)
9. 💼 5천만원 포트폴리오 제안 (실시간 가격 기준)
10. ⭐ 오늘의 추천 종목 1개
    - 종목명 (티커)
    - 현재가: [실시간 데이터 그대로]
    - 매수 구간: 현재가 ±2% 이내
    - 목표가: 현재가 기준 +10~25%
    - 손절가: 현재가 기준 -7%
    - 추천 이유: 3줄
11. 🔔 오늘의 매매 타이밍
12. 💬 애널리스트 한마디"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    briefing = message.content[0].text
    trust = calculate_trust_score(briefing, market_data)
    trust_report = format_trust_report(trust)
    fixed, report = validate_briefing(briefing, market_data.get("top_candidates", market_data.get("stocks", {})))
    gpt_verify = verify_briefing(briefing, market_data)
    return fixed + report + gpt_verify + trust_report


def analyze_and_save(market_data: dict) -> str:
    result = analyze(market_data)

    # 추천 종목 성과 DB 저장
    try:
        from performance import save_recommendation
        msg = save_recommendation(result, market_data.get("top_candidates", market_data.get("stocks", {})))
        print(msg)
    except Exception as e:
        print(f"추천 종목 저장 오류: {e}")

    # 브리핑 전문 저장
    try:
        gpt_part    = result.split("🤖 GPT 정량 분석")[1].split("🧠 Claude 정성 통합")[0] if "🤖 GPT 정량 분석" in result else ""
        claude_part = result.split("🧠 Claude 정성 통합")[1].split("═" * 24)[0] if "🧠 Claude 정성 통합" in result else ""
        import re
        score_match = re.search(r'(\d+)/100', claude_part)
        trust_score = int(score_match.group(1)) if score_match else 0
        save_briefing(result, market_data, gpt_part, claude_part, trust_score)
    except Exception as e:
        print(f"브리핑 저장 오류: {e}")

    return result


if __name__ == "__main__":
    from collector import get_market_data
    data   = get_market_data()
    result = analyze(data)
    print(result)
