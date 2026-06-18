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

SYSTEM_PROMPT = """당신은 시장 배경을 해석하는 거시 시장 애널리스트입니다.

## 당신의 역할
- 밤사이 글로벌 시장(미국 증시·금리·환율·원자재·주요 뉴스)을 한국 시장 관점에서 해석
- 오늘 한국 시장에 미칠 긍정/부정/불확실 요인 정리
- 오늘 주목할 섹터 분위기(강세·약세·전환 관찰)와 리스크 요인 제시
- 사용자가 수급 시그널(시그널봇)을 읽기 위한 '시장 배경 지도' 제공

## 당신의 경험
- 30년 이상의 거시·시장 분석 경험
- 1997 IMF, 2008 금융위기, 2020 코로나 등 주요 국면 직접 경험
- 뉴스 표면이 아니라 한국 시장에 미치는 연결 고리를 읽는 데 능함

## ⚠️ 절대 규칙 (역할 경계)
1. **개별 종목을 추천하지 않는다** — 매수/매도 의견, 목표가, 손절가, 추천주, 급등 예상 종목 금지
2. 종목명은 '시장 배경 설명용'으로만 허용 (예: "반도체 대형주 강세로 지수 견인"). "○○ 매수 유망" 같은 표현 금지
3. 종목 판단은 시그널봇(수급 기반)의 역할이다. 브리핑봇은 배경만 제공
4. 확정적 예측·근거 없는 급등/급락 단정 금지 — '관찰 포인트' 형태로 서술
5. 뉴스 나열로 끝내지 말 것 — 반드시 한국 시장 영향으로 연결 해석
6. 모든 수치는 제공된 실시간 데이터만 사용, 학습된 과거 가격 사용 금지"""


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

    # KRX 시장 강도 섹션
    krx_summary    = market_data.get("krx_summary", "")
    krx_signal     = market_data.get("krx_signal", "")
    krx_strength   = market_data.get("krx_strength", 0)
    krx_candidates = market_data.get("krx_candidates", [])

    if krx_summary:
        cand_text = ""
        if krx_candidates:
            cand_text = "\n스윙 후보 TOP3:\n" + "\n".join([
                f"  - {c['name']} ({c['chg_rt']:+.1f}%) | {' · '.join(c['signals'][:3])}"
                for c in krx_candidates[:3]
            ])
        krx_section = f"시장신호: {krx_signal} (강도 {krx_strength:.1f}%)\n{cand_text}"
    else:
        krx_section = "KRX 데이터 없음"

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

## 📊 KRX 시장 강도 분석
{krx_section}

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
- 개별 종목 추천/목표가/손절가/매수 의견 금지 (종목명은 배경 설명용으로만)
- 뉴스 나열 금지 — 반드시 한국 시장 영향으로 연결 해석
- 확정 예측 금지 — '관찰 포인트' 형태로 서술
- 프리마켓·원자재·환율을 오늘 한국 장 방향 판단에 연결
- 시장 톤은 [상승 우세 / 하락 우세 / 혼조 / 보합 / 변동성 확대] 중 하나로 명시

## 🔍 섹터 관찰 예시 규칙 (4번 섹션 내에서만)
- 섹터 흐름을 설명하기 위한 '예시 종목'을 최대 1~3개까지만 언급 가능
- 반드시 섹터/시장 배경 설명용 (예: "반도체 — 삼성전자·SK하이닉스 외국인 수급으로 지수 견인")
- 매수가·목표가·손절가 절대 표시 금지
- '추천/픽/유망/매수/목표' 등의 표현 절대 금지
- BUY/WATCH/PASS 등 등급 표시 금지
- 섹터 관찰 예시 블록 맨 앞에 반드시 아래 고정 문구를 그대로 출력:
  "아래 종목은 매수 후보가 아니라 오늘 시장 흐름을 설명하기 위한 섹터 관찰 예시입니다."

## 📝 브리핑 형식 (📰 오늘의 시장 배경)
1. 📌 오늘의 한 줄 시황 + 시장 톤 (상승우세/하락우세/혼조/보합/변동성확대 중 명시)
2. 🌙 밤사이 핵심 요약
   - 미국 증시 / 금리·환율 / 원자재 / 주요 글로벌 이슈
3. 🇰🇷 한국시장 영향
   - 긍정 요인 / 부정 요인 / 중립·불확실 요인
4. 🔭 오늘 주목할 섹터 (관찰 중심, 추천 아님)
   - 강세 가능성 관찰 / 약세 주의 / 전환 관찰
   - (선택) 섹터 관찰 예시 1~3개 — 위 '섹터 관찰 예시 규칙' 엄수, 고정 문구 먼저 출력
5. ⚠️ 리스크 체크
   - 금리 / 환율 / 원자재 / 지정학·정책 / 실적 이벤트
6. 🧭 오늘의 한 줄 판단 (관찰 포인트, 종목 추천 아님)
7. 🔗 시그널봇 연결
   - "08:00 시그널봇의 수급 관심목록과 함께 확인하세요" 안내"""

    message = client.messages.create(
        model=getattr(config, "CLAUDE_MODEL", "claude-sonnet-4-6"),
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    briefing = message.content[0].text
    # 명시 가드: 섹터 관찰 예시 섹션은 trust_score 계산 입력에서 제외 (GPT 2026-06-18)
    from performance import strip_sector_example
    briefing_for_trust = strip_sector_example(briefing)
    trust = calculate_trust_score(briefing_for_trust, market_data)
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
