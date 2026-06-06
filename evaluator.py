# -*- coding: utf-8 -*-
"""
브리핑봇 장마감 복기 (GPT 2026-06-06 결정)

아침 브리핑의 시장 톤/섹터 언급이 실제 시장과 맞았는지 평가.
- 방향성 적중: market_view vs 실제 KOSPI 종가
- 섹터 적중: 언급 섹터 종목 평균수익 vs KOSPI
- 유용성: 체크리스트 자동 판정

결과는 briefing_history에 기록 + 복기 텍스트 반환.
초기 단계: DB/로그 기록만, 텔레그램 자동 발송 안 함.
점수 공식 변경 근거로 사용하지 않음 (학습/관찰용).
"""
import sqlite3
import config
from datetime import datetime, timezone, timedelta

DB_PATH = config.DB_PATH
KST = timezone(timedelta(hours=9))

# 방향성 판정 임계 (GPT 2-1)
DIR_THRESHOLD = 0.3   # %


def _kospi_kosdaq_return():
    """오늘 KOSPI/KOSDAQ 등락률 (FDR)"""
    import FinanceDataReader as fdr
    start = (datetime.now(KST) - timedelta(days=10)).strftime("%Y-%m-%d")
    end   = datetime.now(KST).strftime("%Y-%m-%d")
    out = {}
    for key, code in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            df = fdr.DataReader(code, start, end)
            v = df["Close"].dropna()
            out[key] = round((v.iloc[-1] - v.iloc[-2]) / v.iloc[-2] * 100, 2) if len(v) >= 2 else None
        except Exception:
            out[key] = None
    return out


def _judge_direction(view: str, kospi_ret: float) -> str:
    """시장 톤 vs 실제 KOSPI → hit/partial/miss/neutral"""
    if view is None or kospi_ret is None or view == "":
        return "neutral"
    t = DIR_THRESHOLD
    if "상승" in view:
        return "hit" if kospi_ret >= t else ("partial" if kospi_ret > -t else "miss")
    if "하락" in view:
        return "hit" if kospi_ret <= -t else ("partial" if kospi_ret < t else "miss")
    # 혼조/보합/변동성
    return "hit" if abs(kospi_ret) <= 0.5 else "partial"


def _sector_tickers(keyword: str) -> list[str]:
    """섹터 키워드 → 구성 종목 (sector_map 부분매칭)"""
    try:
        from sector_map import SECTOR_MAP
    except Exception:
        return []
    return [tk for tk, sec in SECTOR_MAP.items() if keyword in sec][:6]


def _judge_sectors(sectors_csv: str, kospi_ret: float) -> tuple[str, list]:
    """언급 섹터(강세 관찰 가정) 평균수익 vs KOSPI → hit/partial/miss/pending"""
    if not sectors_csv or kospi_ret is None:
        return "pending", []
    import FinanceDataReader as fdr
    start = (datetime.now(KST) - timedelta(days=10)).strftime("%Y-%m-%d")
    end   = datetime.now(KST).strftime("%Y-%m-%d")

    details = []
    for kw in sectors_csv.split(","):
        kw = kw.strip()
        if not kw:
            continue
        tks = _sector_tickers(kw)
        rets = []
        for tk in tks:
            try:
                df = fdr.DataReader(tk, start, end)
                v = df["Close"].dropna()
                if len(v) >= 2:
                    rets.append((v.iloc[-1] - v.iloc[-2]) / v.iloc[-2] * 100)
            except Exception:
                pass
        if rets:
            avg = sum(rets) / len(rets)
            excess = avg - kospi_ret
            verdict = "hit" if excess > 0.2 else ("partial" if excess > -0.5 else "miss")
            details.append({"sector": kw, "avg": round(avg, 2),
                            "excess": round(excess, 2), "verdict": verdict, "n": len(rets)})

    if not details:
        return "pending", []
    hits = sum(1 for d in details if d["verdict"] == "hit")
    ratio = hits / len(details)
    overall = "hit" if ratio >= 0.6 else ("partial" if ratio >= 0.3 else "miss")
    return overall, details


def _judge_usefulness(text: str) -> tuple[str, dict]:
    """유용성 체크리스트 (GPT 2-3)"""
    checks = {
        "has_korea_impact":  any(k in text for k in ["한국시장 영향", "긍정 요인", "부정 요인", "국내 시장"]),
        "has_sector_view":   "섹터" in text,
        "has_risk_check":    "리스크" in text,
        "has_signalbot_link": "시그널봇" in text,
        "not_too_short":     len(text) >= 500,
        "no_stock_reco":     not any(k in text for k in ["추천 종목", "매수 유망", "목표가", "손절가"]),
    }
    score = sum(checks.values())
    grade = "good" if score >= 5 else ("normal" if score >= 3 else "poor")
    return grade, checks


def evaluate_briefing(date: str = None) -> str:
    """오늘(또는 지정일) 브리핑 복기 → DB 기록 + 복기 텍스트 반환"""
    if date is None:
        date = datetime.now(KST).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT briefing_text, market_view, mentioned_sectors "
        "FROM briefing_history WHERE date=? ORDER BY id DESC LIMIT 1", (date,)
    ).fetchone()
    if not row:
        conn.close()
        return f"[복기] {date} 브리핑 없음 — 건너뜀"

    text, view, sectors = row[0] or "", row[1] or "", row[2] or ""

    idx = _kospi_kosdaq_return()
    kospi_ret, kosdaq_ret = idx.get("kospi"), idx.get("kosdaq")

    dir_result = _judge_direction(view, kospi_ret)
    sec_result, sec_details = _judge_sectors(sectors, kospi_ret)
    use_grade, use_checks = _judge_usefulness(text)

    # 복기 텍스트
    L = [
        "📰 [브리핑봇] 오늘 브리핑 복기",
        f"기준일: {date}",
        "",
        "1. 시장 방향 판단",
        f"  예상 톤: {view or '미표기'}",
        f"  실제: KOSPI {kospi_ret:+.2f}% / KOSDAQ {kosdaq_ret:+.2f}%" if kospi_ret is not None and kosdaq_ret is not None else "  실제: 데이터 미수신",
        f"  결과: {_kr(dir_result)}",
        "",
        "2. 언급 섹터 결과",
    ]
    if sec_details:
        for d in sec_details:
            L.append(f"  {d['sector']}: {d['avg']:+.2f}% (KOSPI 대비 {d['excess']:+.2f}%p) → {_kr(d['verdict'])}")
        L.append(f"  종합: {_kr(sec_result)}")
    else:
        L.append("  언급 섹터 없음/평가 보류")
    L += [
        "",
        f"3. 유용성: {use_grade.upper()}",
        f"  체크: " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in use_checks.items()),
    ]
    review_text = "\n".join(L)

    # DB 기록
    conn.execute("""
        UPDATE briefing_history
        SET actual_kospi_return=?, actual_kosdaq_return=?,
            direction_result=?, sector_result=?, usefulness_grade=?, review_note=?
        WHERE date=?
    """, (kospi_ret, kosdaq_ret, dir_result, sec_result, use_grade, review_text, date))
    conn.commit()
    conn.close()

    return review_text


def _kr(r: str) -> str:
    return {"hit": "적중", "partial": "부분 적중", "miss": "실패",
            "neutral": "중립", "pending": "보류"}.get(r, r)


if __name__ == "__main__":
    print(evaluate_briefing())
