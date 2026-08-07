# -*- coding: utf-8 -*-
"""
역할경계 런타임 검증 — GPT §2 7단계 자동 수행
근거: GPT_TO_CLAUDE_BRIEFING_RUNTIME_WEEKLY_FIX_20260802 §2

실행: cd /root/briefing-bot-server && python3 verify_runtime.py

★ 실제 텔레그램/이메일 발송은 하지 않는다.
   send_all을 가로채 '호출됐는지'만 기록해 차단 여부를 검증한다.
   (운영 채널에 테스트 메시지를 뿌리지 않기 위함 — 발송 경로 도달 여부가 검증 대상)
"""
import sys, os, subprocess
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError: pass

RESULTS = []


def step(n, name, ok, detail=""):
    RESULTS.append((n, name, ok, detail))
    print(f"{'✅' if ok else '❌'} [{n}] {name}")
    if detail:
        for line in str(detail).split("\n")[:6]:
            print(f"      {line}")


def main():
    # ── 1. git pull 및 적용 commit 확인 ──
    try:
        head = subprocess.check_output(["git", "log", "--oneline", "-1"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"],
                                        text=True, stderr=subprocess.DEVNULL).strip()
        step(1, "적용 commit 확인", True,
             f"{head}\n작업트리: {'clean' if not dirty else '변경 있음 — ' + dirty[:80]}")
    except Exception as e:
        step(1, "적용 commit 확인", False, str(e))

    # ── 7. signal DB 읽기 전용 (먼저 확인 — 생성 시 사용되므로) ──
    try:
        from signal_status import get_signal_status, format_signal_status, SIGNAL_DB
        st = get_signal_status()
        import sqlite3
        wrote = False
        try:
            c = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True)
            c.execute("CREATE TABLE _verify_probe (a INT)")
            wrote = True                      # 여기 오면 쓰기가 된 것 = 실패
            c.close()
        except sqlite3.OperationalError as oe:
            ro_msg = str(oe)
        step(7, "signal DB 읽기 전용", (not wrote),
             f"쓰기 시도 → {ro_msg if not wrote else '⚠ 쓰기 성공(위험)'}\n"
             f"조회 가능: {st.get('available')} / 신호일 {st.get('signal_date')}")
    except Exception as e:
        step(7, "signal DB 읽기 전용", False, str(e))

    # ── 2·3. 월간 리포트 시험 생성 + 정상 발송 허용 확인 ──
    try:
        from monthly_report import generate_monthly_report
        from role_boundary import check_role_boundary
        msg = generate_monthly_report()
        step(2, "월간 리포트 시험 생성", bool(msg and len(msg) > 500),
             f"길이 {len(msg)}자 / §7 운영현황 포함: "
             f"{'예' if '시그널' in msg and ('G3' in msg or '확인 불가' in msg) else '아니오'}")
        chk = check_role_boundary(msg)
        step(3, "정상 리포트 발송 허용", chk["ok"],
             "위반 0건" if chk["ok"] else
             "; ".join(f"{v['type']}: {v['evidence'][:40]}" for v in chk["violations"]))
    except Exception as e:
        step(2, "월간 리포트 시험 생성", False, str(e))
        step(3, "정상 리포트 발송 허용", False, "생성 실패로 미검증")
        msg = ""

    # ── 4·5·6. 금지 문구 주입 → 발송 차단 + 상태·로그 확인 ──
    # send_all을 가로채 실제 발송 없이 '도달 여부'만 본다.
    try:
        import monthly_report as MR
        called = {"hit": False}

        def _fake_send_all(message, subject=None):
            called["hit"] = True              # 여기 도달 = 차단 실패
            return {"telegram": True, "email": True}

        banned = ("\n\n## 🧭 이번 달 투자 전략\n"
                  "- 인버스 ETF 편입을 권장합니다.\n"
                  "- 현금 비중을 축소하시기 바랍니다.\n"
                  "- 삼성전자와 SK하이닉스를 추천합니다.\n")
        tainted = (msg or "테스트 본문입니다.") + banned

        orig_gen, orig_send = MR.generate_monthly_report, MR.send_all
        MR.generate_monthly_report = lambda: tainted
        MR.send_all = _fake_send_all
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "role_boundary_blocked.log")
        before = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        try:
            res = MR.send_monthly_report()
        finally:
            MR.generate_monthly_report, MR.send_all = orig_gen, orig_send

        step(4, "금지 문구 주입 생성", True, "인버스 편입/현금 축소/종목 추천 3종 삽입")
        step(5, "Telegram·이메일 발송 차단", (not called["hit"]),
             "send_all 미호출 — 발송 경로 도달 없음" if not called["hit"]
             else "⚠ send_all이 호출됨 (차단 실패)")
        status = (res or {}).get("status")
        after = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        step(6, "blocked_role_boundary 상태·로그",
             status == "blocked_role_boundary" and after > before,
             f"status={status} / 로그 {after - before}바이트 기록")
    except Exception as e:
        step(4, "금지 문구 주입 생성", False, str(e))
        step(5, "Telegram·이메일 발송 차단", False, "미검증")
        step(6, "blocked_role_boundary 상태·로그", False, "미검증")

    # ── 요약 ──
    print("\n" + "─" * 56)
    ok = sum(1 for *_, o, _ in RESULTS if o)
    print(f"GPT §2 7단계: {ok}/{len(RESULTS)} 통과")
    for n, name, o, _ in sorted(RESULTS):
        print(f"  {n}. {name}: {'OK' if o else 'FAIL'}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
