# -*- coding: utf-8 -*-
"""
급등락 알림 발송 회귀 테스트 (2026-09-04)

검증 대상: alert.dispatch_alerts()의 '발송 성공 → 기록' 순서.

배경(고친 버그):
  mark_alerted()가 기록과 발송을 겸하면서
    ① 미정의 변수 `message` 참조 → NameError로 실제 발송 실패
    ② 그런데 save_alert_log()가 먼저 실행되어 '오늘 보냄'으로 기록 → 재시도 차단
    ③ 호출측은 "알림 발송" 로그를 출력 → 성공처럼 보임
  except가 NameError를 삼켜 조용히 미발송 상태였다.

★ 이 테스트의 핵심: 발송 실패 시 기록이 남지 않아야 한다.
  기록이 남으면 그날 재시도가 영구히 막히므로, 이것이 회귀의 급소다.

실행: cd /root/briefing-bot-server && python3 test_alert_dispatch.py
      (config.py 불필요 — sender를 주입하므로 텔레그램에 접속하지 않는다)
"""
import json
import os
import sys
import tempfile

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alert

FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


def with_temp_log(fn):
    """alert_log.json을 임시 파일로 격리해 실제 운영 로그를 건드리지 않는다."""
    orig = alert.ALERT_LOG_FILE
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    tmp.write("{}")
    tmp.close()
    alert.ALERT_LOG_FILE = tmp.name
    try:
        return fn()
    finally:
        alert.ALERT_LOG_FILE = orig
        os.unlink(tmp.name)


print("=" * 68)
print("ALERT_DISPATCH_REGRESSION")
print("=" * 68)

TODAY = "2026-09-04"
ALERTS = [("삼성전자", "msg-A"), ("SK하이닉스", "msg-B")]

# ── 1. 전부 발송 성공 → 전부 기록 ──
print("\n[1] 발송 성공 시 기록되는가")


def case_all_ok():
    calls = []
    res = alert.dispatch_alerts(
        ALERTS, TODAY, sender=lambda m: calls.append(m) or True)
    log = alert.load_alert_log()
    return calls, res, log


calls, res, log = with_temp_log(case_all_ok)
check("발송 함수가 2건 모두 호출됨", calls == ["msg-A", "msg-B"], str(calls))
check("결과 집계 sent=2 failed=0",
      res["sent"] == 2 and res["failed"] == 0, str(res))
check("2건 모두 기록됨",
      log.get("삼성전자") == TODAY and log.get("SK하이닉스") == TODAY, str(log))

# ── 2. ★ 발송 실패 → 기록되지 않아야 한다 (이번 버그의 급소) ──
print("\n[2] ★ 발송 실패 시 기록이 남지 않는가 (재시도 가능해야 함)")


def case_all_fail():
    try:
        alert.dispatch_alerts(ALERTS, TODAY, sender=lambda m: False)
        raised = None
    except RuntimeError as e:
        raised = str(e)
    return raised, alert.load_alert_log()


raised, log = with_temp_log(case_all_fail)
check("실패가 RuntimeError로 드러남 (조용히 넘어가지 않음)",
      raised is not None, raised or "예외 없음 — 조용한 실패!")
check("★ 실패한 2건이 기록되지 않음 (다음 주기 재시도 가능)",
      log == {}, f"기록됨: {log} — 재시도가 막힘!")

# ── 3. 부분 실패 → 성공분만 기록 ──
print("\n[3] 일부만 실패할 때 성공분만 기록되는가")


def case_partial():
    try:
        alert.dispatch_alerts(
            ALERTS, TODAY, sender=lambda m: m == "msg-A")   # A만 성공
        raised = None
    except RuntimeError as e:
        raised = str(e)
    return raised, alert.load_alert_log()


raised, log = with_temp_log(case_partial)
check("성공한 삼성전자는 기록됨", log.get("삼성전자") == TODAY, str(log))
check("★ 실패한 SK하이닉스는 미기록", "SK하이닉스" not in log, str(log))
check("부분 실패도 RuntimeError로 드러남", raised is not None, raised or "예외 없음")
check("에러 메시지에 실패 종목명 포함",
      raised is not None and "SK하이닉스" in raised, raised or "")

# ── 4. mark_alerted가 발송하지 않는가 (책임 분리) ──
print("\n[4] mark_alerted가 기록만 하는가 (발송 책임 제거 확인)")
import ast
import inspect
import textwrap


def code_without_docstring(fn) -> str:
    """
    함수의 '실행되는 코드'만 문자열로 돌려준다 — docstring·주석 제외.

    ★ 문자열 grep으로 검사하면 docstring에 적힌 버그 이력 설명('sender.send_telegram을
      쓴다' 같은 문장)까지 위반으로 잡히는 오탐이 난다. 실제로 이 테스트를 처음
      돌렸을 때 그 오탐이 발생했다.
      이 프로젝트는 검사기 오탐으로 3회 사고가 있었으므로(ROOT_CAUSE_ANALYSIS_20260811)
      AST로 실제 코드만 본다.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]                       # docstring 제거
    return "\n".join(ast.unparse(n) for n in body)


mark_code = code_without_docstring(alert.mark_alerted)
check("mark_alerted 실제 코드에 발송 호출 없음",
      "requests" not in mark_code and "send_telegram" not in mark_code,
      f"발송 코드 잔존: {mark_code[:80]}")
check("mark_alerted가 로그 기록만 수행",
      "save_alert_log" in mark_code, mark_code.replace("\n", " ")[:80])
check("alert.py 어디에도 자체 텔레그램 URL 없음",
      "api.telegram.org" not in inspect.getsource(alert),
      "자체 발송 경로가 남아 있음")

# ── 결과 ──
print("\n" + "=" * 68)
if FAIL:
    print(f"판정: FAIL — {len(FAIL)}건")
    for f in FAIL:
        print(f"  · {f}")
    print("=" * 68)
    sys.exit(1)
print("판정: ALERT_DISPATCH_REGRESSION_PASS")
print("  발송 성공 시에만 기록 / 실패는 미기록·재시도 가능 / 실패가 예외로 드러남")
print("=" * 68)
