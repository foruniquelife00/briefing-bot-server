from datetime import datetime,timedelta
from types import SimpleNamespace
from unittest.mock import patch,Mock
import unittest

import alert
from alert_quote_guard import validate_kr_quote,KST

TICKER='034020.KS'
def meta(at):
    return {'symbol':TICKER,'exchangeTimezoneName':'Asia/Seoul',
            'regularMarketTime':at.timestamp(),'regularMarketPrice':81700}


class GuardTests(unittest.TestCase):
    def test_exact_holiday_incident_rejected(self):
        at=datetime(2026,9,23,15,30,22,tzinfo=KST)
        for day in (24,25):
            with self.assertRaisesRegex(ValueError,'quote_not_from_today'):
                validate_kr_quote(TICKER,meta(at),81700,86500,now=datetime(2026,9,day,9,17,tzinfo=KST))

    def test_fresh_open_day_quote_accepted_and_delay_bounded(self):
        now=datetime(2026,9,23,10,tzinfo=KST)
        at=now-timedelta(minutes=15)
        self.assertEqual(validate_kr_quote(TICKER,meta(at),81700,86500,now=now),at)
        with self.assertRaisesRegex(ValueError,'stale_intraday_quote'):
            validate_kr_quote(TICKER,meta(now-timedelta(minutes=21)),81700,86500,now=now)

    def test_missing_future_wrong_symbol_or_price_fail_closed(self):
        now=datetime(2026,9,23,10,tzinfo=KST)
        variants=[{}, {**meta(now),'symbol':'005930.KS'},
                  {**meta(now),'regularMarketPrice':80000},
                  meta(now+timedelta(minutes=5)), {**meta(now),'regularMarketTime':True}]
        for value in variants:
            with self.assertRaises(ValueError):
                validate_kr_quote(TICKER,value,81700,86500,now=now)
        for previous in (0,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                validate_kr_quote(TICKER,meta(now),81700,previous,now=now)

    def exercise_scan(self, quote_at, now):
        stock=SimpleNamespace(fast_info=SimpleNamespace(last_price=81700,regular_market_previous_close=86500,
                                                       year_high=100000,year_low=60000),
                              get_history_metadata=Mock(return_value=meta(quote_at)))
        original=validate_kr_quote
        # Reproduce the faulty weekday-only scheduler admitting a holiday.
        with patch.object(alert,'is_market_hours',return_value=True), \
             patch.object(alert,'load_watchlist',return_value=['두산에너빌리티']), \
             patch.object(alert,'load_alert_settings',return_value={}), \
             patch.object(alert,'already_alerted',return_value=False), \
             patch.dict('sys.modules',{'ticker_verify':SimpleNamespace(unreliable_today=lambda:set())}), \
             patch.object(alert.yf,'Ticker',return_value=stock), \
             patch.object(alert,'validate_kr_quote',side_effect=lambda *args:original(*args,now=now)), \
             patch.object(alert,'dispatch_alerts') as send:
            alert.check_alerts()
            return send.call_args

    def test_real_scan_path_never_dispatches_holiday_stale_quote(self):
        self.assertIsNone(self.exercise_scan(datetime(2026,9,23,15,30,22,tzinfo=KST),
                                            datetime(2026,9,25,9,17,tzinfo=KST)))

    def test_real_scan_keeps_valid_alert_with_source_time(self):
        at=datetime(2026,9,23,10,tzinfo=KST)
        sent=self.exercise_scan(at,at+timedelta(minutes=1))
        self.assertIsNotNone(sent)
        self.assertIn('2026-09-23 10:00:00 KST',sent.args[0][0][1])
        self.assertIn('-5.55%',sent.args[0][0][1])

if __name__=='__main__':unittest.main()
