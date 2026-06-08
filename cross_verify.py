from openai import OpenAI
import anthropic
import config

# OpenAI 키가 config에 없거나 비어도 import가 죽지 않도록 안전 처리
_openai_key = getattr(config, "OPENAI_API_KEY", "") or ""
openai_client = OpenAI(api_key=_openai_key) if _openai_key else None
claude_client = anthropic.Anthropic(api_key=getattr(config, "ANTHROPIC_API_KEY", "") or "")

# ── GPT 역할: 정량 분석 ──────────────────────────
GPT_SYSTEM = """당신은 정량적 데이터 분석 전문가입니다.
감정이나 스토리 없이 오직 숫자와 통계로만 시장을 분석합니다.

분석 원칙:
1. 모든 판단은 수치 근거 필수
2. 지수·환율·원자재 상관관계 분석
3. 공포탐욕지수 통계적 해석
4. 추천 종목 밸류에이션 수치 검토
5. 리스크/리워드 비율 계산

출력 형식:
- 수치 기반 시장 상태 점수 (0~100)
- 핵심 정량 지표 3가지
- 추천 종목 밸류에이션 판단
- 리스크/리워드 비율
- 한줄 정량 결론"""

# ── Claude 역할: 정성 분석 + 전략 통합 ──────────
CLAUDE_SYNTHESIS_SYSTEM = """당신은 30년 경력의 투자 전략가입니다.
정량 분석 결과를 바탕으로 정성적 판단과 실전 전략을 추가합니다.

역할:
1. GPT의 정량 분석을 해석하고 맥락 부여
2. 지정학·심리·모멘텀 등 비정형 변수 반영
3. 최종 투자 판단 및 실행 전략 제시
4. 정량과 정성이 충돌할 경우 이유 설명
5. 신뢰도 점수 부여 (0~100)"""


def gpt_quantitative_analysis(market_data: dict) -> str:
    """GPT — 정량 데이터 분석"""
    try:
        sp500   = market_data.get("sp500",  {}).get("value", "N/A")
        sp500r  = market_data.get("sp500",  {}).get("rate",  "N/A")
        nasdaq  = market_data.get("nasdaq", {}).get("value", "N/A")
        nasdaqr = market_data.get("nasdaq", {}).get("rate",  "N/A")
        kospi   = market_data.get("kospi",  {}).get("value", "N/A")
        kospir  = market_data.get("kospi",  {}).get("rate",  "N/A")
        kosdaq  = market_data.get("kosdaq", {}).get("value", "N/A")
        kosdaqr = market_data.get("kosdaq", {}).get("rate",  "N/A")
        usd_krw = market_data.get("usd_krw", "N/A")
        fgi     = market_data.get("fgi_score", "N/A")

        # 워치리스트 상위 종목 데이터
        stocks = market_data.get("top_candidates", {})
        stock_lines = []
        for name, s in list(stocks.items())[:10]:
            if s.get("raw_price"):
                stock_lines.append(
                    f"- {name}: {s['price']} ({s['rate']}) "
                    f"| 52주 위치: {s.get('week52_low','N/A')}~{s.get('week52_high','N/A')} "
                    f"| PER: {s.get('per','N/A')}"
                )
        stock_str = "\n".join(stock_lines) if stock_lines else "데이터 없음"

        prompt = f"""아래 시장 데이터를 정량적으로 분석해주세요.

## 시장 데이터
- S&P500: {sp500} ({sp500r})
- NASDAQ: {nasdaq} ({nasdaqr})
- 코스피: {kospi} ({kospir})
- 코스닥: {kosdaq} ({kosdaqr})
- 원/달러: {usd_krw}원
- 공포탐욕지수: {fgi}

## 주요 종목 데이터
{stock_str}

정량 분석 결과를 아래 형식으로 출력해주세요:
1. 시장 상태 점수: X/100
2. 핵심 정량 지표 3가지 (수치 포함)
3. 추천 종목 밸류에이션 판단
4. 리스크/리워드 비율
5. 한줄 정량 결론"""

        if openai_client is None:
            return "GPT 정량 분석 비활성 (OPENAI_API_KEY 미설정)"
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": GPT_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=600,
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"GPT 정량 분석 오류: {e}")
        return "GPT 분석 실패"


def claude_synthesis(briefing: str, gpt_analysis: str, market_data: dict) -> str:
    """Claude — 정성 분석 + 최종 통합"""
    try:
        prompt = f"""아래는 오늘의 투자 브리핑과 GPT 정량 분석 결과입니다.
GPT 분석을 참고하여 최종 종합 검증을 작성해주세요.

## 오늘의 브리핑 (요약)
{briefing[:1500]}

## GPT 정량 분석 결과
{gpt_analysis}

## 요청
GPT 정량 분석과 브리핑을 비교하여:
1. 📊 정량·정성 일치 여부
2. ⚡ 충돌 포인트 (있다면)
3. 🎯 최종 신뢰도 점수 (0~100)
4. 💡 보완 필요 사항 1~2가지
5. ✅ 최종 한줄 종합 의견

간결하게 5줄 이내로 작성해주세요."""

        message = claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return message.content[0].text

    except Exception as e:
        print(f"Claude 통합 분석 오류: {e}")
        return "Claude 통합 분석 실패"


def verify_briefing(briefing: str, market_data: dict) -> str:
    """GPT 정량 분석 → Claude 정성 통합 → 최종 검증 리포트"""
    try:
        print("  GPT 정량 분석 중...")
        gpt_result = gpt_quantitative_analysis(market_data)

        print("  Claude 정성 통합 중...")
        claude_result = claude_synthesis(briefing, gpt_result, market_data)

        report = f"""

📊 AI 교차검증 리포트
{'═' * 24}

🤖 GPT 정량 분석
{'─' * 24}
{gpt_result}

🧠 Claude 정성 통합
{'─' * 24}
{claude_result}
{'═' * 24}"""

        return report

    except Exception as e:
        print(f"교차검증 오류: {e}")
        return ""


if __name__ == "__main__":
    from collector import get_market_data
    print("시장 데이터 수집 중...")
    data = get_market_data()

    test_briefing = """
📌 오늘의 한줄 시황
코스피 강보합, 반도체 중심 외국인 순매수 지속
⭐ 추천 종목: SK하이닉스
현재가: 1,006,500원 | 목표가: 1,157,475원 | 손절가: 936,045원
추천 이유: HBM 수요 급증, AI 인프라 투자 확대
"""
    print("교차검증 중...")
    result = verify_briefing(test_briefing, data)
    print(result)
