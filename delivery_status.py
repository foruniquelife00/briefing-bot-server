# -*- coding: utf-8 -*-
"""
발송 판정 구조 — 'briefing_history 있음 = 성공' 폐기
근거: GPT_TO_CLAUDE_BRIEFING_DAILY_CPLUS_DECISION_20260807 §3, §7

★ briefing_history는 '생성 성공' 증거일 뿐 '발송 성공' 증거가 아니다.
  2026-08-05 사고: 차단으로 미발송인데 history 기록이 남아 systemd가 SUCCESS 판정.
  → 발송 단계별 상태를 별도 테이블에 남기고, 그것으로 성공을 판정한다.

목표 지표: silent_failure_count = 0 (§7)
  silent failure = 발송 실패·차단인데 아무도 모르는 상태
                 = (미발송) AND (알림도 못 감)
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def _db_path() -> str:
    """config는 서버에만 있으므로 지연 로드. 없으면 환경변수/로컬 폴백(테스트용)."""
    try:
        import config
        return config.DB_PATH
    except Exception:
        return os.environ.get("BRIEFING_DB_PATH",
                              os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "briefing.db"))

# final_delivery_status 허용값 (§3)
SENT_FULL = "sent_full"
SENT_REDACTED = "sent_redacted"
BLOCKED = "blocked_role_boundary"
FAILED_GEN = "failed_generation"
FAILED_DELIVERY = "failed_delivery"


def init_delivery_log():
    conn = sqlite3.connect(_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS briefing_delivery_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,                  -- KST 기준 발송일
            created_at TEXT,
            kind TEXT,                      -- daily / weekly / friday / monthly
            generated_ok INTEGER DEFAULT 0,
            role_boundary_checked INTEGER DEFAULT 0,
            role_boundary_action TEXT,      -- pass / redact / block / error
            redacted_count INTEGER DEFAULT 0,
            violation_types TEXT,
            send_attempted INTEGER DEFAULT 0,
            telegram_ok INTEGER DEFAULT 0,
            telegram_message_id INTEGER,
            email_ok INTEGER DEFAULT 0,
            notified INTEGER DEFAULT 0,     -- 차단·실패를 사용자에게 알렸는가
            final_delivery_status TEXT,
            detail TEXT,
            UNIQUE (run_date, kind)
        )""")
    conn.commit()
    conn.close()


def record(kind: str, **kw):
    """발송 시도 결과 기록 (같은 날 같은 종류는 덮어씀)"""
    init_delivery_log()
    now = datetime.now(KST)
    row = {
        "run_date": kw.pop("run_date", now.strftime("%Y-%m-%d")),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S KST"),
        "kind": kind,
        "generated_ok": 0, "role_boundary_checked": 0, "role_boundary_action": None,
        "redacted_count": 0, "violation_types": None, "send_attempted": 0,
        "telegram_ok": 0, "telegram_message_id": None, "email_ok": 0,
        "notified": 0, "final_delivery_status": None, "detail": None,
    }
    row.update({k: v for k, v in kw.items() if k in row})
    cols = ",".join(row)
    ph = ",".join("?" * len(row))
    conn = sqlite3.connect(_db_path())
    conn.execute(f"INSERT OR REPLACE INTO briefing_delivery_log ({cols}) VALUES ({ph})",
                 tuple(row.values()))
    conn.commit()
    conn.close()
    return row["final_delivery_status"]


def is_silent_failure(row: dict) -> bool:
    """
    silent failure 정의 (§7 목표=0):
      최종 상태가 '발송됨'이 아닌데, 사용자에게 알림도 가지 않은 경우.
      차단이어도 알림이 갔으면 silent가 아니다 (사용자가 인지 가능).
    """
    delivered = row.get("final_delivery_status") in (SENT_FULL, SENT_REDACTED)
    return (not delivered) and (not row.get("notified"))


def metrics(days: int = 30) -> dict:
    """운영 지표 (§7)"""
    init_delivery_log()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM briefing_delivery_log WHERE run_date >= ? ORDER BY run_date", (cutoff,))]
    conn.close()

    m = {
        "generated_count": sum(r["generated_ok"] for r in rows),
        "sent_full_count": sum(r["final_delivery_status"] == SENT_FULL for r in rows),
        "sent_redacted_count": sum(r["final_delivery_status"] == SENT_REDACTED for r in rows),
        "blocked_count": sum(r["final_delivery_status"] == BLOCKED for r in rows),
        "delivery_failure_count": sum(r["final_delivery_status"] == FAILED_DELIVERY for r in rows),
        "silent_failure_count": sum(is_silent_failure(r) for r in rows),
        # 오탐/정탐은 사람이 판정해야 하므로 detail에 태그를 남긴 것만 집계
        "false_positive_count": sum("false_positive" in (r["detail"] or "") for r in rows),
        "true_positive_count": sum("true_positive" in (r["detail"] or "") for r in rows),
        "rows": len(rows), "days": days,
    }
    return m


def metrics_report(days: int = 30) -> str:
    m = metrics(days)
    L = [f"📊 브리핑 발송 지표 (최근 {days}일, {m['rows']}건)",
         f"  생성 {m['generated_count']} / 전체발송 {m['sent_full_count']} / "
         f"부분발송 {m['sent_redacted_count']} / 차단 {m['blocked_count']}",
         f"  발송실패 {m['delivery_failure_count']}",
         f"  ★ silent failure {m['silent_failure_count']} (목표 0)"]
    if m["false_positive_count"] or m["true_positive_count"]:
        L.append(f"  오탐 {m['false_positive_count']} / 정탐 {m['true_positive_count']} (수동 태깅분)")
    if m["silent_failure_count"] > 0:
        L.append("  ⚠ silent failure 발생 — 미발송인데 알림도 못 간 건이 있습니다")
    return "\n".join(L)
