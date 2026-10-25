"""Deterministic KR/US equity-session notice; independent of LLM output."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from market_calendar import session, adjacent_session, latest_completed_session, now_kst, KST


def _state(day, market):
    try:
        return session(day, market)
    except (OSError, ValueError, TypeError, KeyError):
        return {'status': 'UNKNOWN'}


def _line(label, day, market):
    state = _state(day, market)
    prefix = f'{label} {day}'
    if state['status'] == 'UNKNOWN':
        return prefix + ' — 확인 불가 · 달력/특별 운영시간 확인 필요'
    if state['status'] == 'CLOSED':
        kind = '주말 휴장' if datetime.fromisoformat(day).weekday() >= 5 else '휴장'
        try:
            upcoming = adjacent_session(day, 1, market)
            confirmed = _state(upcoming, market)['status'] == 'OPEN_SESSION'
            suffix = f' · 다음 거래일 {upcoming}' if confirmed else ' · 다음 거래일 운영시간 확인 필요'
        except (OSError, ValueError, TypeError, KeyError):
            suffix = ' · 다음 거래일 확인 필요'
        return prefix + ' — ' + kind + suffix
    try:
        opened = datetime.fromisoformat(state['open']).astimezone(KST)
        closed = datetime.fromisoformat(state['close']).astimezone(KST)
        duration = closed - opened
        normal_duration = timedelta(hours=6, minutes=30)
        special = ' · 단축장' if duration < normal_duration else ''
        return (prefix + ' — 거래일' + special
                + f' · 한국시간 {opened:%m/%d %H:%M}~{closed:%m/%d %H:%M}')
    except (ValueError, TypeError, KeyError):
        return prefix + ' — 운영시간 확인 불가'


def build_market_notice(now=None):
    now = now or now_kst()
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    korean_day = now.astimezone(KST).date().isoformat()
    us_day = now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    lines = ['📅 국장·미장 운영 안내 (정규장)',
             _line('🇰🇷 한국', korean_day, 'XKRX'),
             _line('🇺🇸 미국 현지일', us_day, 'XNYS')]
    # Korean morning is still the prior US date. Announce the coming US session too.
    if us_day != korean_day:
        lines.append(_line('🇺🇸 다가오는 미국 현지일', korean_day, 'XNYS'))
    try:
        latest = latest_completed_session(now, 'XNYS')
        lines.append(f'미국 최근 완료 거래일(달력 기준): {latest}')
    except (OSError, ValueError, TypeError, KeyError):
        lines.append('미국 최근 완료 거래일: 확인 불가')
    lines.append('휴장일에는 새 정규장 등락이 없습니다. 시세는 실제 기준일을 확인하며, 선물·가상자산 일정은 별도입니다.')
    return '\n'.join(lines)
