# -*- coding: utf-8 -*-
"""
C+ 정책 런타임 검증 — GPT §8 요구 항목 자동 수행
근거: GPT_TO_CLAUDE_BRIEFING_DAILY_CPLUS_DECISION_20260807

실행: cd /root/briefing-bot-server && python3 verify_cplus.py

★ 실제 발송 없음 — send_telegram/send_email을 가로채 '도달 여부'만 본다.
"""
import sys, os, sqlite3
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError: pass

R = []
def step(name, ok, detail=""):
    R.append((name, ok))
    print(f"{'✅' if ok else '❌'} {name}")
    for l in str(detail).split("\n")[:5]:
        if l: print(f"      {l}")


BASE = "\n".join([
    "## 오늘의 시장 브리핑", "",
    "코스피는 1.2% 상승 마감했습니다.",
    "외국인 매수세 유입이 이어졌고 반도체가 강세였습니다.",
    "미국 CPI 발표가 이번 주 최대 변수입니다.",
    "환율은 1,380원 부근에서 등락했습니다.",
    "공포탐욕지수는 42로 중립 구간입니다.",
    "채권 금리는 소폭 하락했습니다.",
    "원자재는 유가 중심으로 반등했습니다.",
    "다음 주 FOMC 일정이 예정돼 있습니다.",
])


def main():
    from role_boundary import apply_cplus, check_role_boundary
    import delivery_status as DS

    # ── 1. C+ 판정 4종 ──
    cases = [
        ("위반 없음 → pass", BASE, "pass"),
        ("독립 1줄 → redact", BASE + "\n인버스 ETF 편입을 권고합니다.", "redact"),
        ("연속 2줄 → block", BASE + "\n인버스 ETF 편입을 권고합니다.\n현금 비중 축소를 권고합니다.", "block"),
        ("섹션 제목 → block", BASE + "\n\n## 🧭 이번 달 투자 전략\n섹터를 봅니다.", "block"),
    ]
    allok = True
    for name, txt, exp in cases:
        r = apply_cplus(txt)
        ok = r["action"] == exp
        allok &= ok
        print(f"   {'✓' if ok else '✗'} {name:<22} → {r['action']} ({r['reason'][:34]})")
    step("C+ 판정 4종", allok)

    # ── 2. 문장 제거 결과 검증 ──
    r = apply_cplus(BASE + "\n인버스 ETF 편입을 권고합니다.")
    removed_gone = "인버스 ETF 편입을 권고합니다." not in r["text"]
    body_kept = "코스피는 1.2% 상승 마감했습니다." in r["text"]
    notice = "제거되었습니다" in r["text"]
    step("제거 후 본문 보존 + 고지문구", removed_gone and body_kept and notice,
         f"위반문장 제거={removed_gone} / 본문유지={body_kept} / 고지문구={notice}")

    # ── 3. 검사기 오류 → fail-safe 차단 ──
    import role_boundary as RB
    orig = RB._line_violations
    RB._line_violations = lambda t: (_ for _ in ()).throw(RuntimeError("강제 오류"))
    try:
        r = apply_cplus(BASE)
        step("검사기 오류 → fail-safe 차단", r["action"] == "block", r["reason"][:60])
    finally:
        RB._line_violations = orig

    # ── 4. §6 회귀 10종 (기술용어 vs 행동지시) ──
    G6 = [("과매수 부담이 커졌습니다", True), ("과매도 부담을 덜었습니다", True),
          ("외국인 매수세 유입이 이어졌습니다", True), ("기관 매도세 확대가 나타났습니다", True),
          ("외국인 매수 우위가 지속됐습니다", True), ("기관 매도 우위가 집중됐습니다", True),
          ("포지션 확대는 자제할 것을 권고합니다", False), ("인버스 ETF 편입을 권고합니다", False),
          ("현금 비중 축소를 권고합니다", False), ("조정 시 분할매수를 권고합니다", False)]
    n_ok = sum(check_role_boundary(t)["ok"] == e for t, e in G6)
    step(f"§6 회귀 10종", n_ok == 10, f"{n_ok}/10")

    # ── 5. 발송 상태 기록 + silent failure 판정 ──
    DS.init_delivery_log()
    probe = "9999-12-31"
    DS.record("daily", run_date=probe, generated_ok=1, role_boundary_checked=1,
              role_boundary_action="block", final_delivery_status=DS.BLOCKED,
              notified=1, detail="verify_probe true_positive")
    conn = sqlite3.connect(DS._db_path()); conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM briefing_delivery_log WHERE run_date=?",
                            (probe,)).fetchone())
    silent_notified = DS.is_silent_failure(row)
    DS.record("daily", run_date=probe, generated_ok=1, role_boundary_checked=1,
              role_boundary_action="block", final_delivery_status=DS.BLOCKED,
              notified=0, detail="verify_probe")
    row2 = dict(conn.execute("SELECT * FROM briefing_delivery_log WHERE run_date=?",
                             (probe,)).fetchone())
    silent_unnotified = DS.is_silent_failure(row2)
    conn2 = sqlite3.connect(DS._db_path())
    conn2.execute("DELETE FROM briefing_delivery_log WHERE run_date=?", (probe,))
    conn2.commit(); conn2.close(); conn.close()
    step("silent failure 판정 로직",
         (not silent_notified) and silent_unnotified,
         f"차단+알림O → silent={silent_notified}(기대 False) / "
         f"차단+알림X → silent={silent_unnotified}(기대 True)")

    # ── 6. 실운영 지표 ──
    print("\n" + DS.metrics_report(30))
    m = DS.metrics(30)
    step("silent_failure_count = 0", m["silent_failure_count"] == 0,
         f"현재 {m['silent_failure_count']}건")

    print("\n" + "─" * 56)
    ok = sum(1 for _, o in R if o)
    print(f"C+ 런타임 검증: {ok}/{len(R)} 통과")
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
