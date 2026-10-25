"""Versioned offline exchange sessions; unknown coverage never means open."""
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
CALENDAR_PATH = Path(__file__).with_name('exchange_sessions.json')

class CalendarUnavailable(ValueError):
    pass

@lru_cache(maxsize=1)
def _load():
    data = json.loads(CALENDAR_PATH.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not data.get('markets'):
        raise CalendarUnavailable('invalid_calendar')
    return data

def now_kst():
    return datetime.now(KST)

def _market(market, day):
    try:
        data = _load()
        if not data['start'] <= day <= data['end']:
            raise CalendarUnavailable('calendar_out_of_range')
        return data, data['markets'][market]
    except (OSError, KeyError, ValueError) as exc:
        raise CalendarUnavailable(str(exc)) from exc

def session(day=None, market='XKRX'):
    day = str(day or now_kst().date())
    try:
        date.fromisoformat(day)
        data, exchange = _market(market, day)
        hours = exchange['sessions'].get(day)
        if day in exchange.get('hours_unconfirmed', []):
            return {'status':'UNKNOWN','date':day,'market':market,'reason':'session_hours_unconfirmed','version':data['version']}
        return {'status':'OPEN_SESSION' if hours else 'CLOSED', 'date':day, 'market':market,
                'open':hours[0] if hours else None,'close':hours[1] if hours else None,
                'version':data['version'],'valid_until':data['end']}
    except (CalendarUnavailable, ValueError) as exc:
        return {'status':'UNKNOWN','date':day,'market':market,'reason':str(exc)}

def is_session(day=None, market='XKRX'):
    return session(day,market)['status'] == 'OPEN_SESSION'

def is_open_now(now=None, market='XKRX'):
    now = now or now_kst()
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    try:
        exchange = _load()['markets'][market]
        day = now.astimezone(ZoneInfo(exchange['timezone'])).date().isoformat()
        s = session(day,market)
        return s['status']=='OPEN_SESSION' and datetime.fromisoformat(s['open']) <= now <= datetime.fromisoformat(s['close'])
    except (OSError,KeyError,ValueError):
        return False

def shift_session(day, count, market='XKRX'):
    _, exchange = _market(market,day)
    dates = sorted(exchange['sessions'])
    if day not in exchange['sessions']:
        raise CalendarUnavailable('origin_not_a_session')
    pos = bisect_left(dates,day) + count
    if not 0 <= pos < len(dates):
        raise CalendarUnavailable('target_out_of_range')
    return dates[pos]

def adjacent_session(day, direction, market='XKRX'):
    _, exchange = _market(market,day)
    dates = sorted(exchange['sessions'])
    pos = bisect_left(dates,day)-1 if direction<0 else bisect_right(dates,day)
    if not 0 <= pos < len(dates):
        raise CalendarUnavailable('adjacent_out_of_range')
    return dates[pos]

def latest_completed_session(now=None, market='XKRX'):
    now = now or now_kst()
    if now.tzinfo is None: raise ValueError('timezone_required')
    data=_load(); exchange=data['markets'][market]
    day=now.astimezone(ZoneInfo(exchange['timezone'])).date().isoformat()
    _market(market,day)
    for d in reversed(sorted(exchange['sessions'])):
        if d > day: continue
        s=session(d,market)
        if s['status']=='UNKNOWN': raise CalendarUnavailable('session_hours_unconfirmed')
        if datetime.fromisoformat(s['close']) <= now:return d
    raise CalendarUnavailable('no_completed_session')

def block_reason(day=None):
    state=session(day)
    if state['status']=='OPEN_SESSION': return None
    reason='skipped_market_closed' if state['status']=='CLOSED' else 'blocked_calendar_unknown'
    logging.getLogger(__name__).warning('%s: %s',reason,state)
    return reason
