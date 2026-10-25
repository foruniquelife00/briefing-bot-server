"""Compact, dated holiday briefing; no domestic candidates or performance grading."""
from datetime import datetime,timedelta,timezone
from html import escape
import logging
from market_calendar import session,adjacent_session,latest_completed_session,now_kst,CalendarUnavailable

def build_nontrading_brief(now=None, ticker_factory=None):
    now=now or now_kst();day=now.date().isoformat();state=session(day)
    from market_notice import build_market_notice
    lines=[build_market_notice(now), '', f'📰 한국 증시 휴장 안내 | {day}' if state['status']=='CLOSED' else f'📰 거래일 확인 보류 | {day}']
    try:
        lines.append(f'최근 국내 거래일: {adjacent_session(day,-1)} · 다음 거래일: {adjacent_session(day,1)}')
    except CalendarUnavailable:lines.append('다음 거래일: 달력 갱신 필요')
    lines.append('국내 당일 관심목록·급등락·장마감 채점은 진행하지 않습니다.')
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory=yf.Ticker
    lines += ['', '미국 증시 — 확인된 최근 거래일 기준']
    try:expected=latest_completed_session(now,'XNYS')
    except (OSError,ValueError,TypeError,KeyError):expected=None
    for name,code in [('S&amp;P 500','^GSPC'),('나스닥','^IXIC'),('다우','^DJI')]:
        try:
            if expected is None:raise ValueError('US calendar unavailable')
            t=ticker_factory(code)
            h=t.history(start=(datetime.fromisoformat(expected)-timedelta(days=12)).date().isoformat(),
                        end=(datetime.fromisoformat(expected)+timedelta(days=1)).date().isoformat(),auto_adjust=False)
            close=h['Close'].dropna()
            if len(close)<2 or close.index[-1].strftime('%Y-%m-%d')!=expected:raise ValueError('stale quote')
            rate=(float(close.iloc[-1])/float(close.iloc[-2])-1)*100
            lines.append(f'· {name}: {rate:+.2f}% ({expected} 종가)')
        except Exception:
            lines.append(f'· {name}: 최신 거래일 시세 확인 불가')
    lines += ['', '최근 국제 뉴스 — 원문 제목']
    headlines=[]
    try:
        for item in ticker_factory('SPY').get_news(count=10):
            content=item.get('content') or item
            published=content.get('pubDate')
            at=datetime.fromisoformat(published.replace('Z','+00:00')) if published else datetime.fromtimestamp(content['providerPublishTime'],timezone.utc)
            if at.tzinfo is None or not timedelta(0)<=now-at<=timedelta(hours=36):continue
            title=content.get('title','').strip()
            provider=content.get('provider') or {}
            publisher=provider.get('displayName') or content.get('publisher') or 'Yahoo Finance'
            if title:headlines.append(f'· {escape(title[:180])} — {escape(publisher)} ({at.astimezone(now.tzinfo):%m-%d %H:%M} KST)')
            if len(headlines)==3:break
    except Exception:pass
    lines += headlines or ['· 발행 시각이 확인되는 최신 기사를 확보하지 못했습니다.']
    lines += ['', '해외 변동을 휴장 중 국내 주가의 당일 움직임으로 해석하지 않습니다.']
    return '\n'.join(lines)

def run_nontrading_brief():
    import config,sqlite3,fcntl
    from pathlib import Path
    import delivery_status as DS
    from sender import send_telegram
    # OS lock survives concurrent timer/manual entry; delivered-day state survives restart.
    with Path(config.DB_PATH).with_suffix('.holiday.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        DS.init_delivery_log()
        with sqlite3.connect(config.DB_PATH) as c:
            row=c.execute('SELECT telegram_ok FROM briefing_delivery_log WHERE run_date=? AND kind=?',
                          (now_kst().date().isoformat(),'daily')).fetchone()
        if row and row[0]:
            logging.info('Holiday brief already delivered; skip duplicate')
            return
        text=build_nontrading_brief()
        ok=bool(send_telegram(text))
        DS.record(kind='daily',generated_ok=1,send_attempted=1,telegram_ok=int(ok),
                  final_delivery_status=DS.SENT_FULL if ok else DS.FAILED_DELIVERY,
                  detail='nontrading_brief: no domestic session evaluation')
        if not ok:raise RuntimeError('nontrading_brief_delivery_failed')
