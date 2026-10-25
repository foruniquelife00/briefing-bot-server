"""Archive original rows before correcting session dates / excluding closed-day reviews.

Use on a consistent SQLite backup first. No market-data network calls here.
"""
import argparse,json,sqlite3,math
import logging
from datetime import datetime,timezone
from pathlib import Path
from market_calendar import session,shift_session,CalendarUnavailable,now_kst

VERSION='calendar-repair-20260925-v2'
VALUE_COLUMNS=['check_price','kospi_check','return_pct','kospi_return_pct','excess_return_pct','extreme_market_day']

def connect(path):
    c=sqlite3.connect(path,timeout=30);c.row_factory=sqlite3.Row
    return c

def archive(c,table,row):
    c.execute('''CREATE TABLE IF NOT EXISTS calendar_repair_archive(
      repair_version TEXT,source_table TEXT,source_rowid INTEGER,original_json TEXT,archived_at TEXT,
      PRIMARY KEY(repair_version,source_table,source_rowid))''')
    c.execute('INSERT OR IGNORE INTO calendar_repair_archive VALUES(?,?,?,?,?)',
              (VERSION,table,row['_rowid'],json.dumps(dict(row),ensure_ascii=False),datetime.now(timezone.utc).isoformat()))

def repair_signal(path,apply=False):
    c=connect(path);c.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
    results={'rescheduled':0,'previously_filled_reset':0,'invalid_origin':0,'unknown_calendar':0,'examples':[]}
    try:
        for row in c.execute('SELECT rowid _rowid,* FROM signal_returns').fetchall():
            try:expected=shift_session(row['signal_date'],int(row['d_plus']))
            except CalendarUnavailable:
                state=session(row['signal_date'])['status']
                status='invalid_calendar_origin' if state=='CLOSED' else 'calendar_unknown'
                if row['result_status']==status:continue
                results['invalid_origin' if state=='CLOSED' else 'unknown_calendar']+=1
                expected=row['check_date']
            else:
                if expected==row['check_date']:continue
                status='pending';results['rescheduled']+=1
            if row['result_status']=='filled':results['previously_filled_reset']+=1
            if len(results['examples'])<5:results['examples'].append({'signal_date':row['signal_date'],'d_plus':row['d_plus'],'old':row['check_date'],'new':expected,'old_status':row['result_status'],'new_status':status})
            if apply:
                archive(c,'signal_returns',row)
                clear=','.join(n+'=NULL' for n in VALUE_COLUMNS)
                c.execute(f'UPDATE signal_returns SET check_date=?,result_status=?,{clear} WHERE rowid=?',(expected,status,row['_rowid']))
        if apply:c.commit()
        else:c.rollback()
    except Exception:c.rollback();raise
    finally:c.close()
    return results

def repair_briefing(path,apply=False):
    c=connect(path);c.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
    count=0;days=[]
    try:
        for row in c.execute('SELECT rowid _rowid,* FROM briefing_history').fetchall():
            if session(row['date'])['status']!='CLOSED':continue
            if row['direction_result']=='excluded_market_closed':continue
            if all(row[k] is None for k in ['actual_kospi_return','actual_kosdaq_return','direction_result','sector_result','usefulness_grade']):continue
            count+=1;days.append(row['date'])
            if apply:
                archive(c,'briefing_history',row)
                c.execute('''UPDATE briefing_history SET actual_kospi_return=NULL,actual_kosdaq_return=NULL,
                  direction_result='excluded_market_closed',sector_result='excluded_market_closed',
                  usefulness_grade=NULL,review_note=? WHERE rowid=?''',
                  ('휴장일 복기 제외. 원본은 calendar_repair_archive에 보존. '+VERSION,row['_rowid']))
        if apply:c.commit()
        else:c.rollback()
    except Exception:c.rollback();raise
    finally:c.close()
    return {'reviews_excluded':count,'dates':sorted(set(days))}

def ensure_calendar_repair(path,kind):
    """One-time application migration, run by the service's existing DB owner.

    Existing file ownership stays unchanged; original rows are archived transactionally.
    """
    if not Path(path).is_file():raise RuntimeError('calendar_migration_database_missing')
    with connect(path) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS calendar_migrations(
          version TEXT PRIMARY KEY,kind TEXT,completed_at TEXT,result_json TEXT)''')
        if c.execute('SELECT 1 FROM calendar_migrations WHERE version=?',(VERSION,)).fetchone():
            return apply_return_backfill(path) if kind=='signal' else None
    if kind=='signal':result=repair_signal(str(path),True)
    elif kind=='briefing':result=repair_briefing(str(path),True)
    else:raise ValueError('unsupported_calendar_migration')
    with connect(path) as c:
        c.execute('INSERT OR IGNORE INTO calendar_migrations VALUES(?,?,?,?)',
                  (VERSION,kind,datetime.now(timezone.utc).isoformat(),json.dumps(result,ensure_ascii=False)))
    logging.getLogger(__name__).info('Calendar migration complete: %s',result)
    return result

def apply_return_backfill(path):
    """Apply a dated benchmark/price plan after exact identity and session checks."""
    plan_path=Path(path).with_name('calendar_backfill_plan.json')
    if not plan_path.exists():return None
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    if plan.get('version') not in {'calendar-backfill-20260925-v1','calendar-backfill-20260925-v2'}:raise ValueError('unknown_backfill_version')
    c=connect(path);c.execute('BEGIN IMMEDIATE');filled=0;skipped=0
    try:
        if c.execute('SELECT 1 FROM calendar_migrations WHERE version=?',(plan['version'],)).fetchone():
            c.rollback();return None
        for item in plan['rows']:
            row=c.execute('SELECT rowid _rowid,* FROM signal_returns WHERE rowid=?',(item['rid'],)).fetchone()
            if row is None or row['result_status']!='pending' or any(row[k]!=item[k] for k in ['ticker','signal_date','d_plus','check_date','base_price','kospi_base']):
                skipped+=1;continue
            expected=shift_session(row['signal_date'],int(row['d_plus']))
            if row['check_date']!=expected or not is_session_for_backfill(expected):raise ValueError('backfill_wrong_session')
            if expected>now_kst().date().isoformat():raise ValueError('backfill_future_session')
            values=item['values']
            if len(values)!=6 or not all(math.isfinite(float(v)) for v in values):raise ValueError('invalid_backfill_value')
            price=c.execute('SELECT close FROM moving_averages WHERE ticker=? AND date=?',(row['ticker'],expected)).fetchone()
            if price is None or round(price[0])!=values[0]:raise ValueError('price_source_changed')
            if min(float(row['base_price']),float(row['kospi_base']),values[0],values[1])<=0:raise ValueError('invalid_base')
            ret=(price[0]/row['base_price']-1)*100;kr=(values[1]/row['kospi_base']-1)*100
            if abs(round(ret,2)-values[2])>0.01 or abs(round(kr,2)-values[3])>0.02:raise ValueError('backfill_calculation_mismatch')
            # Preserve the corrected pending row independently from its original legacy row.
            c.execute('INSERT OR IGNORE INTO calendar_repair_archive VALUES(?,?,?,?,?)',
                      (plan['version'],'signal_returns',row['_rowid'],json.dumps(dict(row),ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
            assignments=','.join(k+'=?' for k in VALUE_COLUMNS)
            c.execute(f"UPDATE signal_returns SET {assignments},result_status='filled' WHERE rowid=?",tuple(values)+(row['_rowid'],))
            filled+=1
        result={'filled':filled,'skipped_changed':skipped,'source':plan['source'],'captured_at':plan['captured_at']}
        c.execute('INSERT INTO calendar_migrations VALUES(?,?,?,?)',(plan['version'],'signal_backfill',datetime.now(timezone.utc).isoformat(),json.dumps(result)))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
    logging.getLogger(__name__).info('Calendar exact-session backfill complete: %s',result)
    return result

def is_session_for_backfill(day):
    return session(day)['status']=='OPEN_SESSION'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--signal');p.add_argument('--briefing');p.add_argument('--apply',action='store_true');a=p.parse_args()
    result={}
    if a.signal:result['signal']=repair_signal(a.signal,a.apply)
    if a.briefing:result['briefing']=repair_briefing(a.briefing,a.apply)
    print(json.dumps(result,ensure_ascii=False,indent=2))
