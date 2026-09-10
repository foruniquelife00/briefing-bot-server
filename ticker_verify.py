# -*- coding: utf-8 -*-
"""
티커 해석 검증 — yfinance 가 '그 종목'을 돌려주는지 독립 소스로 확인한다.

── 왜 필요한가 (2026-09-10 사고) ──────────────────────────────
  에코프로비엠(247540)은 코스닥인데 watchlist 가 247540.KS(코스피)로
  매핑하고 있었다. yfinance 는 오류를 내지 않고 **전혀 다른 종목 가격**을 준다.
      247540.KS  last=194,000   (실제 에코프로비엠 118,700)
  등락률이 +68.84% 로 계산돼 임계 ±5% 를 매일 넘었고, 알림이 반복 발송됐다.

★ alert.py 의 ±30%(가격제한폭) 가드만으로는 부족하다.
  오늘은 prev 가 우연히 옳아서 걸렸을 뿐이다. yfinance 가 last·prev 를
  **둘 다 다른 종목 값**으로 주면 등락률이 정상 범위로 나와 가드를 통과한다.
  → 티커가 그 종목을 가리키는지 **독립 소스(FDR)로 직접 확인**해야 한다.

★ 소스 교체가 아니라 교차 검증인 이유
  티커가 틀리면 네이버든 토스든 어느 API를 써도 틀린 값이 온다.
  이번 사고는 소스 품질 문제가 아니라 **식별자 문제**였다.

의존성 없음 — FinanceDataReader 는 브리핑봇 python3 에 이미 설치돼 있다.
"""
import json
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "ticker_verify_cache.json")

TOLERANCE = 0.01     # 1% — 같은 종목이면 종가가 일치해야 한다
LOOKBACK = 3         # 최근 3거래일 중 하나와 맞으면 통과(장중/장후 경계 흡수)


def _load_cache() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c: dict):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:
        pass          # 캐시는 편의일 뿐 — 실패해도 검증 자체는 계속된다


def fdr_recent_closes(code: str, n: int = LOOKBACK) -> list:
    """FDR 에서 최근 n거래일 종가. 실패 시 빈 리스트."""
    try:
        import FinanceDataReader as fdr
        start = (datetime.now(KST) - timedelta(days=20)).strftime("%Y-%m-%d")
        d = fdr.DataReader(code, start)
        if d is None or d.empty or "Close" not in d.columns:
            return []
        return [float(x) for x in d["Close"].dropna().tail(n)]
    except Exception:
        return []


def verify_ticker(ticker: str, yf_prev: float = None, yf_last: float = None) -> dict:
    """
    ticker 예: '247540.KQ'. 국내(.KS/.KQ)가 아니면 검증 대상이 아니다.

    반환 {'checked': bool, 'ok': bool, 'reason': str, ...}
      checked=False → 판단하지 않았다(해외종목·FDR 실패). 호출측은 통과시킨다.
      ok=False      → yfinance 가 다른 종목을 주고 있다. 알림을 보내면 안 된다.
    """
    out = {"ticker": ticker, "checked": False, "ok": True, "reason": ""}
    if not ticker or not ticker.endswith((".KS", ".KQ")):
        out["reason"] = "국내 종목 아님 — 검증 대상 외"
        return out
    code = ticker.split(".")[0]

    closes = fdr_recent_closes(code)
    if not closes:
        # ★ FDR 이 죽었다고 알림을 막지 않는다. 판단 불가일 뿐이다.
        out["reason"] = "FDR 조회 실패 — 판단 보류"
        return out
    out["checked"] = True
    out["fdr_closes"] = [round(c, 1) for c in closes]

    # yfinance 값 중 하나라도 FDR 최근 종가와 일치하면 같은 종목으로 본다
    cands = [v for v in (yf_prev, yf_last) if v]
    if not cands:
        out["reason"] = "yfinance 값 없음 — 판단 보류"
        out["checked"] = False
        return out
    for v in cands:
        for c in closes:
            if c > 0 and abs(v - c) / c <= TOLERANCE:
                out["reason"] = f"FDR 종가 {c:,.0f} 와 일치"
                return out

    out["ok"] = False
    out["reason"] = (f"yfinance {cands} 가 FDR 최근종가 "
                     f"{[f'{c:,.0f}' for c in closes]} 어느 것과도 불일치 "
                     f"— 티커가 다른 종목을 가리킬 가능성")
    return out


def verify_all(verbose: bool = True) -> list:
    """워치리스트 전체를 훑어 잘못 매핑된 티커 목록을 반환한다."""
    import yfinance as yf
    from watchlist import load_watchlist, STOCK_MAP

    bad = []
    names = load_watchlist()
    if verbose:
        print(f"티커 해석 검증 — {len(names)}종목")
        print(f"{'종목':<20}{'매핑':<12}{'판정':<8}사유")
    for name in names:
        t = STOCK_MAP.get(name)
        if not t or not t.endswith((".KS", ".KQ")):
            continue
        try:
            fi = yf.Ticker(t).fast_info
            prev, last = fi.regular_market_previous_close, fi.last_price
        except Exception as e:
            prev = last = None
        r = verify_ticker(t, prev, last)
        if r["checked"] and not r["ok"]:
            bad.append((name, t, r["reason"]))
        if verbose:
            mark = "OK" if r["ok"] else "*** 오류"
            if not r["checked"]:
                mark = "보류"
            print(f"{name:<20}{t:<12}{mark:<8}{r['reason'][:60]}")
    if verbose:
        print()
        print(f"잘못 매핑된 티커: {len(bad)}건")
        for n, t, why in bad:
            print(f"  · {n} ({t}) — {why}")
    return bad


def unreliable_today() -> set:
    """
    오늘 신뢰할 수 없다고 판정된 티커 집합 (하루 1회만 계산해 캐시).
    alert.py 가 매 알림마다 FDR 을 때리지 않도록 한다.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    c = _load_cache()
    if c.get("date") == today:
        return set(c.get("unreliable", []))
    try:
        bad = verify_all(verbose=False)
    except Exception as e:
        print(f"  [티커검증] 실패(알림은 계속): {e}")
        return set()
    s = sorted({t for _, t, _ in bad})
    _save_cache({"date": today, "unreliable": s})
    if s:
        print(f"  [티커검증] ★ 신뢰 불가 티커 {len(s)}건: {', '.join(s)}")
    return set(s)


if __name__ == "__main__":
    verify_all()
