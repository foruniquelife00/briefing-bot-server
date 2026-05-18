"""
KRX 데이터 기반 시장 강도 분석 + 스윙 추천 신호
매일 브리핑 전 실행 → analyzer.py에 컨텍스트 주입
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

def analyze_market(items_kospi: list, items_kosdaq: list) -> dict:
    """전종목 데이터로 시장 강도 분석"""

    def _analyze(items, mkt):
        up = sum(1 for x in items if float(x.get("FLUC_RT","0") or 0) > 0)
        dn = sum(1 for x in items if float(x.get("FLUC_RT","0") or 0) < 0)
        fl = sum(1 for x in items if float(x.get("FLUC_RT","0") or 0) == 0)
        total = len(items)
        strength = round(up / total * 100, 1) if total else 0

        # 등락률 기준 상위/하위
        sorted_up  = sorted(items, key=lambda x: float(x.get("FLUC_RT","0") or 0), reverse=True)
        sorted_dn  = sorted(items, key=lambda x: float(x.get("FLUC_RT","0") or 0))

        # 거래량 상위 (시가총액 대비)
        vol_ratio = []
        for x in items:
            mktcap = float(x.get("MKTCAP","0") or 0)
            vol    = float(x.get("ACC_TRDVOL","0") or 0)
            close  = float(x.get("TDD_CLSPRC","0") or 0)
            if mktcap > 0 and close > 0:
                vol_val = vol * close
                ratio   = vol_val / mktcap * 100
                vol_ratio.append({**x, "_vol_ratio": ratio})

        vol_ratio.sort(key=lambda x: x["_vol_ratio"], reverse=True)

        return {
            "market":   mkt,
            "total":    total,
            "up":       up,
            "down":     dn,
            "flat":     fl,
            "strength": strength,
            "top_up":   [{"name":x["ISU_NM"],"rate":x["FLUC_RT"],"vol":x["ACC_TRDVOL"]} for x in sorted_up[:5]],
            "top_dn":   [{"name":x["ISU_NM"],"rate":x["FLUC_RT"],"vol":x["ACC_TRDVOL"]} for x in sorted_dn[:5]],
            "vol_surge":[ {"name":x["ISU_NM"],"rate":x["FLUC_RT"],"ratio":round(x["_vol_ratio"],1)} for x in vol_ratio[:5]],
        }

    kospi  = _analyze(items_kospi,  "KOSPI")
    kosdaq = _analyze(items_kosdaq, "KOSDAQ")

    # 종합 시장 강도
    total_up = kospi["up"] + kosdaq["up"]
    total    = kospi["total"] + kosdaq["total"]
    overall  = round(total_up / total * 100, 1) if total else 0

    return {
        "overall_strength": overall,
        "kospi":   kospi,
        "kosdaq":  kosdaq,
        "signal":  "강세🟢" if overall >= 60 else "약세🔴" if overall <= 40 else "중립🟡",
    }


def get_swing_candidates(items_kospi: list, items_kosdaq: list, watchlist_codes: list = None) -> list:
    """스윙 트레이딩 후보 종목 선정"""
    all_items = items_kospi + items_kosdaq
    candidates = []

    for item in all_items:
        try:
            code   = item.get("ISU_CD","")
            name   = item.get("ISU_NM","")
            close  = float(item.get("TDD_CLSPRC","0") or 0)
            high   = float(item.get("TDD_HGPRC","0") or 0)
            low    = float(item.get("TDD_LWPRC","0") or 0)
            chg_rt = float(item.get("FLUC_RT","0") or 0)
            vol    = float(item.get("ACC_TRDVOL","0") or 0)
            mktcap = float(item.get("MKTCAP","0") or 0)
            open_  = float(item.get("TDD_OPNPRC","0") or 0)

            if close <= 0 or mktcap <= 0: continue

            score  = 0
            signals = []

            # 1. 상승 마감 (+1)
            if chg_rt > 2:
                score += 1
                signals.append(f"상승({chg_rt:+.1f}%)")

            # 2. 거래량 급증 - 시총 대비 (turnover ratio)
            turnover = (vol * close) / mktcap * 100
            if turnover > 3:
                score += 2
                signals.append(f"거래량급증({turnover:.1f}%)")
            elif turnover > 1.5:
                score += 1
                signals.append(f"거래량증가({turnover:.1f}%)")

            # 3. 양봉 (시가 대비 종가 상승)
            if open_ > 0 and close > open_:
                body = (close - open_) / open_ * 100
                if body > 1:
                    score += 1
                    signals.append(f"양봉({body:.1f}%)")

            # 4. 고가 근처 마감 (당일 고가의 95% 이상)
            if high > 0 and close >= high * 0.95:
                score += 1
                signals.append("고가근처마감")

            # 5. 워치리스트 종목 가중치
            if watchlist_codes and code in watchlist_codes:
                score += 1
                signals.append("워치리스트")

            # 6. 중소형주 필터 (시총 500억~5조)
            if 50_000_000_000 <= mktcap <= 5_000_000_000_000:
                score += 1

            if score >= 3:
                candidates.append({
                    "code":    code,
                    "name":    name,
                    "close":   int(close),
                    "chg_rt":  chg_rt,
                    "turnover": round(turnover, 1),
                    "mktcap":  int(mktcap),
                    "score":   score,
                    "signals": signals,
                    "market":  item.get("MKT_NM",""),
                })
        except: continue

    # 점수 순 정렬
    candidates.sort(key=lambda x: (x["score"], x["turnover"]), reverse=True)
    return candidates[:20]


def format_market_summary(analysis: dict, candidates: list) -> str:
    """브리핑용 시장 강도 요약 텍스트 생성"""
    k = analysis["kospi"]
    q = analysis["kosdaq"]

    lines = [
        f"📊 시장 강도: {analysis['signal']} (전체 {analysis['overall_strength']:.1f}%)",
        f"  KOSPI  상승 {k['up']} / 하락 {k['down']} / 보합 {k['flat']} (강도 {k['strength']}%)",
        f"  KOSDAQ 상승 {q['up']} / 하락 {q['down']} / 보합 {q['flat']} (강도 {q['strength']}%)",
        "",
        "🚀 KOSPI 상승 TOP5:",
    ]
    for x in k["top_up"]:
        lines.append(f"  {x['name']} {float(x['rate']):+.2f}%")

    lines.append("\n📉 KOSPI 하락 TOP5:")
    for x in k["top_dn"]:
        lines.append(f"  {x['name']} {float(x['rate']):+.2f}%")

    lines.append("\n💥 거래량 급증 TOP5 (시총 대비):")
    for x in k["vol_surge"]:
        lines.append(f"  {x['name']} {float(x['rate']):+.2f}% | 회전율 {x['ratio']}%")

    if candidates:
        lines.append(f"\n⭐ 스윙 후보 TOP5 (점수순):")
        for c in candidates[:5]:
            sig = " · ".join(c["signals"])
            lines.append(f"  {c['name']}({c['market']}) {float(c['chg_rt']):+.1f}% | {sig}")

    return "\n".join(lines)


def run_krx_analysis() -> dict:
    """메인 실행 함수 - 브리핑에서 호출"""
    from krx_collector import get_krx_daily_trade
    from watchlist import STOCK_MAP

    print("KRX 시장 분석 중...")
    kospi_data  = get_krx_daily_trade("kospi")
    kosdaq_data = get_krx_daily_trade("kosdaq")

    # get_krx_daily_trade는 {code: {...}} 형태 → ISU_CD 추가해서 리스트로 변환
    items_k = [{"ISU_CD": k, "ISU_NM": v.get("name",""), "MKT_NM": "KOSPI",
                "FLUC_RT": v.get("chg_rt","0"), "ACC_TRDVOL": v.get("volume","0"),
                "TDD_CLSPRC": v.get("close","0"), "TDD_OPNPRC": v.get("open","0"),
                "TDD_HGPRC": v.get("high","0"), "TDD_LWPRC": v.get("low","0"),
                "MKTCAP": v.get("mktcap","0"), "ACC_TRDVAL": v.get("value","0")}
               for k, v in kospi_data.items()]
    items_q = [{"ISU_CD": k, "ISU_NM": v.get("name",""), "MKT_NM": "KOSDAQ",
                "FLUC_RT": v.get("chg_rt","0"), "ACC_TRDVOL": v.get("volume","0"),
                "TDD_CLSPRC": v.get("close","0"), "TDD_OPNPRC": v.get("open","0"),
                "TDD_HGPRC": v.get("high","0"), "TDD_LWPRC": v.get("low","0"),
                "MKTCAP": v.get("mktcap","0"), "ACC_TRDVAL": v.get("value","0")}
               for k, v in kosdaq_data.items()]

    # 워치리스트 종목코드 수집
    wl_codes = []
    for name, ticker in STOCK_MAP.items():
        code = ticker.replace(".KS","").replace(".KQ","")
        wl_codes.append(code)

    analysis   = analyze_market(items_k, items_q)
    candidates = get_swing_candidates(items_k, items_q, wl_codes)
    summary    = format_market_summary(analysis, candidates)

    print(summary)

    return {
        "analysis":   analysis,
        "candidates": candidates,
        "summary":    summary,
    }


if __name__ == "__main__":
    result = run_krx_analysis()
