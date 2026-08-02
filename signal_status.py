# -*- coding: utf-8 -*-
"""
시그널봇 운영상태 조회 — 읽기 전용 단방향 (§5)
근거: GPT_TO_CLAUDE_BRIEFING_BOT_ROLE_BOUNDARY_TASK_20260802 §5

브리핑봇이 시그널봇의 게이트 상태를 '인지'하되 절대 건드리지 않는다.
★ SELECT만 수행. 쓰기·재평가·gate 변경·paper 발행 요청 금지 (§5).
★ 읽기 실패 시 임의 추정 금지 — "확인 불가"로 표시한다.
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
SIGNAL_DB = os.environ.get("SIGNAL_DB_PATH", "/root/stock-signal/data/stock_signal.db")

FROZEN_ITEMS = (
    "v0.2 점수공식·가중치·BUY/WATCH / target+7%·stop-4%·D+5/D+10 / "
    "OBV 점수화·필터화 / 컨센서스 / 코스닥 확장 / G4 / 주문API / 자동매매 / 실전 매매 지시"
)
UNAVAILABLE = "시그널 시스템 운영상태 데이터 확인 불가"


def _q(conn, sql, params=()):
    try:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r and r[0] is not None else None
    except Exception:
        return None


def get_signal_status() -> dict:
    """읽기 전용 상태 요약. 실패 시 {'available': False}."""
    if not os.path.exists(SIGNAL_DB):
        return {"available": False, "reason": "DB 경로 없음"}
    try:
        # 읽기 전용 연결 (URI mode=ro) — 쓰기 자체를 물리적으로 차단
        conn = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True, timeout=5)
    except Exception as e:
        return {"available": False, "reason": f"연결 실패 {type(e).__name__}"}

    try:
        st = {
            "available": True,
            "signal_date": _q(conn, "SELECT MAX(date) FROM signals"),
            "g3_status": "G3 paper-only (가상 검증, 실전 아님)",
            "risk_level": _q(conn, "SELECT daily_shock FROM paper_recommendations "
                                   "ORDER BY signal_date DESC LIMIT 1"),
            "daily_shock": _q(conn, "SELECT daily_shock FROM paper_recommendations "
                                    "ORDER BY signal_date DESC LIMIT 1"),
            "live_sample_count": _q(conn, "SELECT COUNT(*) FROM paper_recommendations") or 0,
            "live_closed_count": _q(conn, "SELECT COUNT(*) FROM paper_recommendations "
                                          "WHERE status LIKE 'closed%'") or 0,
            "blocked_shadow_count": _q(conn, "SELECT COUNT(*) FROM blocked_shadow") or 0,
            "gate_block_count": _q(conn, "SELECT COUNT(*) FROM blocked_shadow "
                                         "WHERE blocked_reason IS NOT NULL") or 0,
            "latest_data_basis_date": _q(conn, "SELECT MAX(date) FROM stock_supply"),
            "frozen_items": FROZEN_ITEMS,
        }
        return st
    except Exception as e:
        return {"available": False, "reason": f"조회 실패 {type(e).__name__}"}
    finally:
        conn.close()


def format_signal_status() -> str:
    """월간 리포트 §7 삽입용 텍스트 (사실만, 지시 없음)"""
    s = get_signal_status()
    if not s.get("available"):
        return f"{UNAVAILABLE} ({s.get('reason', '')})"
    return (
        f"- 게이트: {s['g3_status']}\n"
        f"- 최신 신호일: {s.get('signal_date') or '-'} / "
        f"데이터 기준일: {s.get('latest_data_basis_date') or '-'}\n"
        f"- 페이퍼 표본: 전체 {s['live_sample_count']}건 (청산 완료 {s['live_closed_count']}건)\n"
        f"- blocked shadow 표본: {s['blocked_shadow_count']}건 "
        f"(gate 차단 {s['gate_block_count']}건)\n"
        f"- 최근 위험등급/당일충격: {s.get('risk_level') or '-'}\n"
        f"- 계속 동결: {s['frozen_items']}"
    )
