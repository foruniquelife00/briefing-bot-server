import re

def validate_and_fix(briefing_text: str, stocks: dict) -> tuple:
    errors = []
    fixed  = briefing_text

    price_map = {}
    for name, s in stocks.items():
        if s.get("raw_price"):
            price_map[name] = s["raw_price"]

    found_stock = None
    for name in price_map:
        if name in briefing_text:
            found_stock = name
            break

    if not found_stock:
        errors.append("추천 종목을 워치리스트에서 찾을 수 없음")
        return fixed, errors

    current_price = price_map[found_stock]
    is_kr = found_stock not in ["QQQ", "TQQQ", "SPY", "GLD", "TLT"]

    target_min   = current_price * 1.10
    target_max   = current_price * 1.25
    stoploss_min = current_price * 0.93

    def fmt(val):
        if is_kr:
            return f"{int(val):,}원"
        else:
            return f"${val:,.2f}"

    # 목표가 검증 — 숫자만 추출 (단위 제외)
    target_pattern   = r'(목표가[:\s]*)([0-9,]+(?:\.[0-9]+)?)(원|\$)?'
    stoploss_pattern = r'(손절가[:\s]*)([0-9,]+(?:\.[0-9]+)?)(원|\$)?'

    target_match = re.search(target_pattern, briefing_text)
    if target_match:
        target_val = float(target_match.group(2).replace(",", ""))
        if not (target_min <= target_val <= target_max):
            errors.append(
                f"목표가 오류: {fmt(target_val)} "
                f"(정상 범위: {fmt(target_min)}~{fmt(target_max)})"
            )
            correct_target = fmt(current_price * 1.15)
            fixed = re.sub(
                target_pattern,
                lambda m: f"{m.group(1)}{correct_target}",
                fixed
            )
            errors.append(f"목표가 자동 수정 → {correct_target}")

    stoploss_match = re.search(stoploss_pattern, briefing_text)
    if stoploss_match:
        stoploss_val = float(stoploss_match.group(2).replace(",", ""))
        if stoploss_val < stoploss_min:
            errors.append(
                f"손절가 오류: {fmt(stoploss_val)} "
                f"(정상 범위: {fmt(stoploss_min)} 이상)"
            )
            correct_stop = fmt(current_price * 0.93)
            fixed = re.sub(
                stoploss_pattern,
                lambda m: f"{m.group(1)}{correct_stop}",
                fixed
            )
            errors.append(f"손절가 자동 수정 → {correct_stop}")

    if not errors:
        errors.append("✅ 가격 검증 통과")

    return fixed, errors


def validate_briefing(briefing_text: str, stocks: dict) -> tuple:
    fixed, errors = validate_and_fix(briefing_text, stocks)

    report_lines = ["", "─" * 22, "🔍 브리핑 검증 결과"]
    for e in errors:
        if "✅" in e:
            report_lines.append(f"  {e}")
        elif "자동 수정" in e:
            report_lines.append(f"  🔧 {e}")
        else:
            report_lines.append(f"  ⚠️ {e}")
    report_lines.append("─" * 22)

    return fixed, "\n".join(report_lines)


if __name__ == "__main__":
    test_text = """
⭐ 오늘의 추천 종목
SK하이닉스 (000660.KS)
현재가: 916,000원
목표가: 250,000원
손절가: 200,000원
추천 이유: HBM 수요 급증
"""
    test_stocks = {
        "SK하이닉스": {"raw_price": 916000, "price": "916,000원", "rate": "+2.1%"}
    }
    fixed, report = validate_briefing(test_text, test_stocks)
    print("=== 수정본 ===")
    print(fixed)
    print("=== 검증 리포트 ===")
    print(report)
