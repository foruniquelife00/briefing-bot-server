import sqlite3
import yfinance as yf
import re
from datetime import datetime, timezone, timedelta
import config

DB_PATH = config.DB_PATH


def calc_sharpe_ratio(returns: list) -> float:
    """샤프 비율 계산 (무위험수익률 연 3.5% 가정)"""
    if len(returns) < 2:
        return 0.0
    import statistics
    risk_free_daily = 0.035 / 252
    excess = [r - risk_free_daily for r in returns]
    avg    = sum(excess) / len(excess)
    std    = statistics.stdev(excess) if len(excess) > 1 else 0.001
    return round((avg / std) * (252 ** 0.5), 2) if std > 0 else 0.0


def calc_profit_factor(returns: list) -> float:
    """프로핏 팩터 계산"""
    gains  = sum(r for r in returns if r > 0)
    losses = abs(sum(r for r in returns if r < 0))
    return round(gains / losses, 2) if losses > 0 else gains


def calc_max_drawdown(returns: list) -> float:
    """최대 낙폭(MDD) 계산"""
    if not returns:
        return 0.0
    peak     = 0
    max_dd   = 0
    cumulative = 0
    for r in returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


def get_historical_returns() -> list:
    """과거 추천 종목 수익률 목록"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT ticker, buy_price, target_price, stop_loss
        FROM recommendations
        ORDER BY date ASC
    """).fetchall()
    conn.close()

    returns = []
    for row in rows:
        ticker, buy_price, target, stop = row
        try:
            current = yf.Ticker(ticker).fast_info.last_price
            rate    = (current - buy_price) / buy_price
            returns.append(rate)
        except:
            pass
    return returns


def calc_data_accuracy(briefing_text: str, market_data: dict) -> int:
    """수치 정확도 점수 (0~30점)"""
    score = 30
    deduct = 0

    # 코스피 수치 확인
    kospi_actual = market_data.get("kospi", {}).get("value", "")
    if kospi_actual and kospi_actual != "N/A":
        kospi_match = re.search(r'코스피.*?([\d,]+\.?\d*)', briefing_text)
        if kospi_match:
            briefing_val = float(kospi_match.group(1).replace(",", ""))
            actual_val   = float(kospi_actual.replace(",", ""))
            diff_pct     = abs(briefing_val - actual_val) / actual_val * 100
            if diff_pct > 5:
                deduct += 10

    # 목표가 범위 확인
    price_match  = re.search(r'현재가[:\s]*\$?([\d,]+)', briefing_text)
    target_match = re.search(r'목표가[:\s]*\$?([\d,]+)', briefing_text)
    if price_match and target_match:
        price  = float(price_match.group(1).replace(",", ""))
        target = float(target_match.group(1).replace(",", ""))
        rate   = (target - price) / price * 100
        if rate < 5 or rate > 30:
            deduct += 10

    return max(0, score - deduct)


def calc_historical_score(returns: list) -> int:
    """과거 성과 점수 (0~30점)"""
    if not returns:
        return 15  # 데이터 없으면 중간값

    wins     = sum(1 for r in returns if r > 0)
    win_rate = wins / len(returns)
    sharpe   = calc_sharpe_ratio(returns)
    mdd      = calc_max_drawdown(returns)
    pf       = calc_profit_factor(returns)

    score = 0

    # 승률 기여 (0~10점)
    score += min(10, int(win_rate * 10))

    # 샤프 비율 기여 (0~10점)
    if sharpe >= 2.0:
        score += 10
    elif sharpe >= 1.0:
        score += 7
    elif sharpe >= 0:
        score += 4
    else:
        score += 0

    # MDD 기여 (0~10점)
    if mdd <= 5:
        score += 10
    elif mdd <= 15:
        score += 7
    elif mdd <= 25:
        score += 4
    else:
        score += 0

    return min(30, score)


def calc_ai_consistency(gpt_analysis: str, claude_verify: str) -> int:
    """GPT·Claude 일치도 점수 (0~20점)"""
    if not gpt_analysis or not claude_verify:
        return 10  # 데이터 없으면 중간값

    score = 20

    # 충돌 키워드 감지
    conflict_keywords = ["충돌", "불일치", "차이", "반면", "다르게", "괴리"]
    for kw in conflict_keywords:
        if kw in claude_verify:
            score -= 4
            break

    # 긍정 키워드
    agree_keywords = ["일치", "동의", "부합", "확인", "지지"]
    for kw in agree_keywords:
        if kw in claude_verify:
            score = min(20, score + 2)
            break

    return max(0, score)


def calc_risk_reward_score(briefing_text: str) -> int:
    """손익비 점수 (0~20점)"""
    try:
        price_match  = re.search(r'현재가[:\s]*\$?([\d,]+)', briefing_text)
        target_match = re.search(r'목표가[:\s]*\$?([\d,]+)', briefing_text)
        stop_match   = re.search(r'손절가[:\s]*\$?([\d,]+)', briefing_text)

        if price_match and target_match and stop_match:
            price  = float(price_match.group(1).replace(",", ""))
            target = float(target_match.group(1).replace(",", ""))
            stop   = float(stop_match.group(1).replace(",", ""))

            reward = (target - price) / price * 100
            risk   = (price - stop)  / price * 100

            if risk > 0:
                rr_ratio = reward / risk
                if rr_ratio >= 3.0:
                    return 20
                elif rr_ratio >= 2.0:
                    return 15
                elif rr_ratio >= 1.5:
                    return 10
                else:
                    return 5
    except:
        pass
    return 10  # 계산 불가 시 중간값


def calculate_trust_score(
    briefing_text: str,
    market_data:   dict,
    gpt_analysis:  str = "",
    claude_verify: str = "",
) -> dict:
    """
    종합 신뢰도 점수 계산
    총점 100점:
      - 수치 정확도:    30점
      - 과거 성과:      30점
      - AI 일치도:      20점
      - 손익비:         20점
    """
    returns = get_historical_returns()

    s1 = calc_data_accuracy(briefing_text, market_data)
    s2 = calc_historical_score(returns)
    s3 = calc_ai_consistency(gpt_analysis, claude_verify)
    s4 = calc_risk_reward_score(briefing_text)

    total  = s1 + s2 + s3 + s4
    sharpe = calc_sharpe_ratio(returns)
    mdd    = calc_max_drawdown(returns)
    pf     = calc_profit_factor(returns)
    wins   = sum(1 for r in returns if r > 0)
    wr     = wins / len(returns) * 100 if returns else 0

    return {
        "total":          total,
        "data_accuracy":  s1,
        "historical":     s2,
        "ai_consistency": s3,
        "risk_reward":    s4,
        "sharpe":         sharpe,
        "mdd":            mdd,
        "profit_factor":  pf,
        "win_rate":       round(wr, 1),
        "sample_count":   len(returns),
    }


def format_trust_report(score: dict) -> str:
    """신뢰도 리포트 텍스트"""
    total = score["total"]
    grade = "🟢 우수" if total >= 80 else "🟡 양호" if total >= 60 else "🔴 주의"

    return (
        f"\n📐 객관적 신뢰도 점수\n"
        f"{'─' * 22}\n"
        f"종합 점수: {total}/100 {grade}\n"
        f"  수치 정확도:  {score['data_accuracy']}/30\n"
        f"  과거 성과:    {score['historical']}/30\n"
        f"  AI 일치도:    {score['ai_consistency']}/20\n"
        f"  손익비:       {score['risk_reward']}/20\n"
        f"─ 성과 지표 ─\n"
        f"  샤프 비율:    {score['sharpe']}\n"
        f"  최대 낙폭:    {score['mdd']}%\n"
        f"  프로핏 팩터:  {score['profit_factor']}\n"
        f"  승률:         {score['win_rate']}% ({score['sample_count']}건)\n"
        f"{'─' * 22}"
    )


if __name__ == "__main__":
    from collector import get_market_data
    data = get_market_data()

    test_briefing = """
⭐ 오늘의 추천 종목
SOXL (SOXL)
현재가: $71.98
목표가: $86.38
손절가: $66.94
"""
    score = calculate_trust_score(test_briefing, data)
    print(format_trust_report(score))
