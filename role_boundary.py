# -*- coding: utf-8 -*-
"""
역할 경계 안전 검사기 — 발송 전 매매지시 차단
근거: GPT_TO_CLAUDE_BRIEFING_BOT_ROLE_BOUNDARY_TASK_20260802 §7

브리핑봇은 '시장 정보·해설'만 제공한다. 매매 지시·비중 조정·종목 추천·
헤지 상품 편입은 생성되어서는 안 되며, 프롬프트 수정만으로는 재발을 못 막는다.
따라서 발송 직전에 구조·의미를 함께 검사해 위반 시 발송을 차단한다.

★ 단순 금지어 매칭이 아니다 (§7 명시):
   - 금지어가 '설명 맥락'에 쓰이면 통과시킨다 (예: "인버스 ETF로 몰렸다"는 사실 기술)
   - '지시 맥락'일 때만 차단한다 (예: "인버스 ETF를 편입하라/편입 권장")
   - 섹션 제목 자체가 금지 영역이면 즉시 차단 (예: "비중 조정안")
"""
import re

# ── 1. 금지 섹션 제목 (구조 검사) ─────────────────────────────
BANNED_SECTIONS = [
    "비중 조정", "비중조정", "헤지 전략", "헤지전략", "주목 종목", "주목종목",
    "추천 종목", "추천종목", "매수 종목", "매도 종목", "포트폴리오 조정",
    "자산 배분", "자산배분", "투자 전략",
]

# ── 2. 지시형 어미 (의미 검사의 핵심) ────────────────────────
#    사실 기술과 지시를 가르는 신호. 이 어미가 붙어야 '지시'로 본다.
DIRECTIVE = (
    r"(권장|권고|추천|해야|하라|하자|하시|바랍니다|필요합니다|"
    r"유리합니다|바람직|검토하|고려하|늘리|줄이|확대|축소|편입|담|비중을)"
)

# ── 3. 금지 행위 × 지시형 조합 (의미 기반) ───────────────────
BANNED_PATTERNS = [
    # 매수/매도 지시
    (rf"(매수|매도|사는|파는|진입|청산)\s*\S{{0,6}}\s*{DIRECTIVE}", "매수·매도 지시"),
    # 비중·현금 조절
    (rf"(비중|현금|포지션)\s*\S{{0,8}}\s*(확대|축소|늘리|줄이|조정|조절)", "비중·현금 조정 지시"),
    # 인버스·레버리지·헤지 상품 편입
    (rf"(인버스|레버리지|곱버스|풋|헤지)\s*\S{{0,10}}\s*(편입|매수|담|활용|{DIRECTIVE})",
     "인버스·레버리지·헤지 편입 제안"),
    # 분할매수 트리거
    (r"(분할\s*매수|물타기|추가\s*매수)\s*\S{0,8}\s*(트리거|시점|전략|권|하)", "분할매수 지시"),
    # 목표가·손절가 제시
    (r"(목표가|목표\s*주가|손절가|손절\s*라인)\s*[:은는]?\s*[\d,]+", "목표가·손절가 제시"),
    # 종목 추천 — '종목/주식' 단어가 있는 형태
    (rf"(종목|주식)\s*\S{{0,6}}\s*(추천|주목|담|편입)\s*\S{{0,4}}\s*(합니다|드립니다|권|하세요)",
     "종목 추천"),
    # 종목 추천 — 종목명이 직접 나오는 형태 ("삼성전자와 SK하이닉스를 추천합니다")
    # 종목명을 열거할 수 없으므로 '추천 행위 표현' 자체를 탐지. 설명 맥락은 예외로 걸러짐.
    (r"(추천|매수\s*의견|비중\s*확대\s*의견)\s*(합니다|드립니다|드려요|해\s*드립|입니다|종목)",
     "종목 추천"),
    (r"(를|을|이|가)\s*(추천|주목|매수|편입)\s*(합니다|드립니다|하세요|하시)", "종목 추천"),
    # 환율 연동 자산배분 (§6)
    (rf"(환율|원/달러|달러)\s*\S{{0,10}}\s*(상승|하락|강세|약세)\s*\S{{0,12}}\s*"
     rf"(비중|자산|주식|편입|{DIRECTIVE})", "환율 연동 자산배분 지시"),
]

# ── 4. 설명 맥락 예외 (오탐 방지) ────────────────────────────
#    이 표현이 같은 문장에 있으면 '사실 기술'로 보고 통과.
EXPLANATORY = [
    "나타났", "보였", "기록했", "집계", "관측", "유입", "유출", "몰렸", "늘었", "줄었",
    "였습니다", "했습니다", "입니다만", "통계", "지난달", "전월", "전년", "추이",
    "설명", "의미합니다", "뜻합니다", "배경", "원인", "때문",
]

DISCLAIMER = (
    "본 리포트는 시장 정보와 시스템 운영 현황을 설명합니다.\n"
    "종목 추천, 매매 지시 또는 자산배분 지침을 제공하지 않습니다."
)


def _is_explanatory(sentence: str) -> bool:
    """설명·사실 기술 맥락인지 (지시가 아닌지)"""
    return any(w in sentence for w in EXPLANATORY)


def check_role_boundary(text: str) -> dict:
    """
    반환: {"ok": bool, "violations": [{"type","evidence"}], "checked": int}
    ok=False면 발송 금지 (§7).
    """
    violations = []

    # (1) 구조 검사 — 금지 섹션 제목
    for line in text.split("\n"):
        s = line.strip()
        # 제목 형태만 (번호·이모지·불릿으로 시작하거나 짧은 줄)
        if len(s) <= 40 and (re.match(r"^[\d#\-•*🧭⭐📌📊💼🔍💬]", s) or s.endswith(":")):
            for b in BANNED_SECTIONS:
                if b in s:
                    violations.append({"type": "금지 섹션", "evidence": s[:60]})
                    break

    # (2) 의미 검사 — 문장 단위, 설명 맥락은 제외
    sentences = re.split(r"[.!?\n]", text)
    for sent in sentences:
        s = sent.strip()
        if len(s) < 6:
            continue
        if _is_explanatory(s):
            continue                     # 사실 기술은 허용
        for pat, label in BANNED_PATTERNS:
            if re.search(pat, s):
                violations.append({"type": label, "evidence": s[:70]})
                break

    # 중복 제거
    seen, uniq = set(), []
    for v in violations:
        k = (v["type"], v["evidence"])
        if k not in seen:
            seen.add(k); uniq.append(v)

    return {"ok": len(uniq) == 0, "violations": uniq, "checked": len(sentences)}


# ── audit-only 모드 (§4 일간 브리핑) ────────────────────────
# 5거래일간 '기록만' 하고 발송은 유지한다. 다만 아래 HARD 유형은 audit 기간에도 즉시 차단.
HARD_BLOCK_TYPES = {
    "매수·매도 지시",
    "인버스·레버리지·헤지 편입 제안",
    "비중·현금 조정 지시",
    "목표가·손절가 제시",
    "종목 추천",
    "환율 연동 자산배분 지시",
}


def audit_only(text: str, tag: str, log_path: str = None) -> dict:
    """
    일간 브리핑용 — 검사 결과를 기록하되 발송은 막지 않는다 (§4 1단계).
    반환: {"send_ok": bool, "violations": [...]}
      send_ok=False는 HARD_BLOCK_TYPES에 해당하는 명백한 위반일 때만.
    """
    import os
    from datetime import datetime, timezone, timedelta
    r = check_role_boundary(text)
    hard = [v for v in r["violations"] if v["type"] in HARD_BLOCK_TYPES]

    if r["violations"]:
        path = log_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "role_boundary_audit.log")
        ts = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n[{ts}] tag={tag} mode=audit-only "
                    f"violations={len(r['violations'])} hard={len(hard)}\n")
            for v in r["violations"]:
                mark = "HARD" if v["type"] in HARD_BLOCK_TYPES else "soft"
                f.write(f"  [{mark}] {v['type']}: {v['evidence']}\n")
    return {"send_ok": len(hard) == 0, "violations": r["violations"], "hard": hard}


def ensure_disclaimer(text: str) -> str:
    """고정 면책 문구 부착 (§8)"""
    if DISCLAIMER.split("\n")[0] in text:
        return text
    return f"{text}\n\n{'─'*22}\n{DISCLAIMER}"
