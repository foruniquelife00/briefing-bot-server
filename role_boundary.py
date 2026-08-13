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
# ★ '담' 단독은 금지 — "부담", "담당", "부담과" 등에 걸려 정상 해설을 차단한다
#   (2026-08-05 실측: "과매수 부담과…" 가 매수 지시로 오인되어 브리핑 발송 차단)
DIRECTIVE = (
    r"(권장|권고|추천|해야|하라|하자|하시|바랍니다|필요합니다|"
    r"유리합니다|바람직|검토하|고려하|늘리|줄이|확대|축소|편입|"
    r"담아|담는|담을|담자|비중을)"
)

# ── 3. 금지 행위 × 지시형 조합 (의미 기반) ───────────────────
BANNED_PATTERNS = [
    # 매수/매도 지시
    #   (?<!과) — '과매수/과매도'는 기술적 지표 용어
    #   (?!세)  — '매수세/매도세'는 수급 사실 용어 ("매도세 확대"는 지시가 아니라 관측)
    (rf"(?<!과)(매수|매도|사는|파는|진입|청산)(?!세)\s*\S{{0,6}}\s*{DIRECTIVE}",
     "매수·매도 지시"),
    # 비중·현금 조절
    (rf"(비중|현금|포지션)\s*\S{{0,8}}\s*(확대|축소|늘리|줄이|조정|조절)", "비중·현금 조정 지시"),
    # 인버스·레버리지·헤지 상품 편입
    # ★ '담' 단독 금지 — "환헤지 부담"의 '담'에 걸려 시장 해설이 차단됐다 (2026-08-13 실측)
    #   DIRECTIVE에서는 8/5에 뺐으나 이 패턴에 하드코딩돼 남아 있었다 (수평전개 누락)
    (rf"(인버스|레버리지|곱버스|풋|헤지)\s*\S{{0,10}}\s*(편입|매수|담아|담는|담을|활용|{DIRECTIVE})",
     "인버스·레버리지·헤지 편입 제안"),
    # 분할매수 트리거
    (r"(분할\s*매수|물타기|추가\s*매수)\s*\S{0,8}\s*(트리거|시점|전략|권|하)", "분할매수 지시"),
    # 목표가·손절가 제시
    (r"(목표가|목표\s*주가|손절가|손절\s*라인)\s*[:은는]?\s*[\d,]+", "목표가·손절가 제시"),
    # 종목 추천 — '종목/주식' 단어가 있는 형태
    (rf"(종목|주식)\s*\S{{0,6}}\s*(추천|주목|담아|담는|담을|편입)\s*\S{{0,4}}\s*(합니다|드립니다|권|하세요)",
     "종목 추천"),
    # 종목 추천 — 종목명이 직접 나오는 형태 ("삼성전자와 SK하이닉스를 추천합니다")
    # 종목명을 열거할 수 없으므로 '추천 행위 표현' 자체를 탐지. 설명 맥락은 예외로 걸러짐.
    (r"(추천|매수\s*의견|비중\s*확대\s*의견)\s*(합니다|드립니다|드려요|해\s*드립|입니다|종목)",
     "종목 추천"),
    (r"(를|을|이|가)\s*(추천|주목|매수|편입)\s*(합니다|드립니다|하세요|하시)", "종목 추천"),
    # "우량주를 담아야 합니다" — 목적격 + 담기 표현 (DIRECTIVE '담' 축소로 생긴 미탐 보완)
    (r"(를|을)\s*(담아|담는|담을|담자)\s*\S{0,4}\s*"
     r"(합니다|하세요|하시|바랍니다|권합니다|두시|야|죠|됩니다)",
     "매수·매도 지시"),
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

# ── 4b. 부정·금지·동결 맥락 (필수 예외) ──────────────────────
#    2026-08-02 실제 생성물에서 발견: 면책 문구와 동결 항목 설명이 차단됐다.
#    "종목 추천, 매매 지시, 비중 조정을 포함하지 않습니다" ← 이것 자체가 걸림.
#    금지 행위를 '하지 않는다'고 밝히는 문장은 위반이 아니라 오히려 준수 표현이다.
NEGATION = [
    "않습니다", "않음", "않는다", "않으며", "않고", "없습니다", "없음", "아닙니다",
    "아니라", "아니며", "금지", "동결", "제외", "무관", "불가", "미수집", "미제공",
    "제공하지", "포함하지", "생성하지", "지양", "삼가", "배제",
]

# ── 4c. 데이터 라벨 예외 ─────────────────────────────────────
#    "추천 종목 성과", "추천 종목 평균 수익률" 등은 과거 기록의 지표명이지 추천 행위가 아니다.
DATA_LABEL = [
    "성과", "수익률", "데이터", "기록", "표본", "건수", "통계", "집계", "미수집", "없음",
]

DISCLAIMER = (
    "본 리포트는 시장 정보와 시스템 운영 현황을 설명합니다.\n"
    "종목 추천, 매매 지시 또는 자산배분 지침을 제공하지 않습니다."
)


def _is_explanatory(sentence: str) -> bool:
    """설명·사실 기술 맥락인지 (지시가 아닌지)"""
    return any(w in sentence for w in EXPLANATORY)


def _is_negated(sentence: str) -> bool:
    """금지·부정·동결을 밝히는 문장인지 (준수 표현 — 위반 아님)"""
    return any(w in sentence for w in NEGATION)


def _is_data_label(sentence: str) -> bool:
    """'추천 종목 성과' 처럼 과거 기록의 지표명인지 (추천 행위 아님)"""
    return any(w in sentence for w in DATA_LABEL)


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
            # 부정·동결 선언이거나 데이터 라벨이면 섹션 위반이 아니다
            if _is_negated(s) or _is_data_label(s):
                continue
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
        # 사실 기술 / 금지·동결 선언 / 데이터 라벨은 위반이 아니다
        if _is_explanatory(s) or _is_negated(s):
            continue
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


# ══════════════════════════════════════════════════════════════
# C+ 하이브리드 정책 (GPT_TO_CLAUDE_BRIEFING_DAILY_CPLUS_DECISION_20260807 §2)
# ══════════════════════════════════════════════════════════════
#   1) 독립된 위반 1~2줄 + 제거 후 문맥 유지  → 해당 줄만 제거하고 발송
#   2) 섹션제목/전략블록/연속줄 위반, 3줄 이상 → 전체 차단
#   3) 검사기 자체 오류                        → fail-safe 전체 차단
#
# ★ 문장이 아니라 '줄' 단위로 다룬다.
#   브리핑 본문은 마크다운 불릿/표 형태라 줄이 의미 단위이고,
#   줄 단위 제거가 원문 복원과 문맥 보존에 가장 안전하다.

REDACT_NOTICE = (
    "역할 경계 검사에서 매매지시성 문장 일부가 제거되었습니다.\n"
    "시장 정보 본문은 그대로 제공되며, 종목 추천·매매 지시는 제공하지 않습니다."
)

MAX_REDACT_LINES = 2          # 이보다 많으면 전체 차단 (§2-2 '3문장 이상')


def _line_violations(text: str):
    """줄 단위 위반 탐지 → [(줄번호, 유형, 원문, is_section)]"""
    out = []
    for i, line in enumerate(text.split("\n")):
        s = line.strip()
        if len(s) < 6:
            continue
        if _is_explanatory(s) or _is_negated(s):
            continue

        # 섹션 제목 위반 (구조 위반 — 제거로 해결 안 됨)
        is_title = len(s) <= 40 and (
            re.match(r"^[\d#\-•*🧭⭐📌📊💼🔍💬]", s) or s.endswith(":"))
        if is_title and not _is_data_label(s):
            for b in BANNED_SECTIONS:
                if b in s:
                    out.append((i, "금지 섹션", s, True))
                    break
            if out and out[-1][0] == i:
                continue

        for pat, label in BANNED_PATTERNS:
            if re.search(pat, s):
                out.append((i, label, s, False))
                break
    return out


def apply_cplus(text: str) -> dict:
    """
    C+ 판정. 반환:
      action : "pass" | "redact" | "block"
      text   : 발송할 본문 (redact면 제거·고지 반영본)
      removed: 제거된 줄 [(유형, 원문)]
      violations / hard : 탐지 결과
      reason : 판정 사유 (로그·알림용)
    """
    try:
        vio = _line_violations(text)
    except Exception as e:                      # §2-3 검사기 오류 → fail-safe 차단
        return {"action": "block", "text": text, "removed": [], "violations": [],
                "hard": [], "reason": f"검사기 오류(fail-safe 차단): {type(e).__name__}: {e}"}

    if not vio:
        return {"action": "pass", "text": text, "removed": [], "violations": [],
                "hard": [], "reason": "위반 없음"}

    viols = [{"type": t, "evidence": s[:70]} for _, t, s, _ in vio]
    hard = [v for v in viols if v["type"] in HARD_BLOCK_TYPES]

    # ── 전체 차단 조건 (§2-2) ──
    if any(is_title for *_, is_title in vio):
        return {"action": "block", "text": text, "removed": [], "violations": viols,
                "hard": hard, "reason": "섹션 제목/전략 블록 위반 — 제거로 해결 불가"}
    if len(vio) > MAX_REDACT_LINES:
        return {"action": "block", "text": text, "removed": [], "violations": viols,
                "hard": hard, "reason": f"다중 위반 {len(vio)}건 (>{MAX_REDACT_LINES}) — 문맥 보존 불가"}
    idxs = sorted(i for i, *_ in vio)
    if len(idxs) >= 2 and any(b - a == 1 for a, b in zip(idxs, idxs[1:])):
        return {"action": "block", "text": text, "removed": [], "violations": viols,
                "hard": hard, "reason": "연속 줄 위반 — 제거 시 문맥 불완전"}

    # ── 문장 제거 후 발송 (§2-1) ──
    lines = text.split("\n")
    removed = [(t, s) for _, t, s, _ in vio]
    kept = [l for i, l in enumerate(lines) if i not in set(idxs)]
    body = "\n".join(kept).rstrip()

    # 제거 후 본문이 지나치게 줄면 문맥 유지 실패로 본다
    if len(body) < len(text) * 0.6 or len(body) < 200:
        return {"action": "block", "text": text, "removed": [], "violations": viols,
                "hard": hard, "reason": "제거 후 본문 과소 — 문맥 유지 실패"}

    body = f"{body}\n\n{'─'*22}\n{REDACT_NOTICE}"
    return {"action": "redact", "text": body, "removed": removed, "violations": viols,
            "hard": hard, "reason": f"독립 위반 {len(vio)}줄 제거 후 발송"}
