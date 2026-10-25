"""Offline regression tests: python -m unittest discover -s tests -p test_market_calendar.py."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import market_calendar as cal


class MarketCalendarTests(unittest.TestCase):
    def test_confirmed_2026_weekday_closures(self):
        holidays = [
            '01-01', '02-16', '02-17', '02-18', '03-02', '05-01',
            '05-05', '05-25', '06-03', '07-17', '08-17', '09-24',
            '09-25', '10-05', '10-09', '12-25', '12-31',
        ]
        for day in holidays:
            with self.subTest(day=day):
                self.assertEqual(cal.session('2026-' + day)['status'], 'CLOSED')
        self.assertTrue(cal.is_session('2026-09-28'))

    def test_holidays_are_excluded_from_return_horizon(self):
        for start, target in [('2026-09-23', '2026-09-28'),
                              ('2026-08-14', '2026-08-18'),
                              ('2026-07-16', '2026-07-20')]:
            self.assertEqual(cal.shift_session(start, 1), target)
        with self.assertRaises(cal.CalendarUnavailable):
            cal.shift_session('2026-09-25', 1)

    def test_kr_holiday_does_not_close_us_exchange(self):
        self.assertFalse(cal.is_session('2026-09-25', 'XKRX'))
        self.assertTrue(cal.is_session('2026-09-25', 'XNYS'))

    def test_delayed_open_and_intraday_bounds(self):
        self.assertFalse(cal.is_open_now(datetime(2026, 1, 2, 9, 30, tzinfo=cal.KST)))
        self.assertTrue(cal.is_open_now(datetime(2026, 1, 2, 10, 1, tzinfo=cal.KST)))
        self.assertFalse(cal.is_open_now(datetime(2026, 9, 28, 15, 31, tzinfo=cal.KST)))
        self.assertFalse(cal.is_open_now(datetime(2026, 9, 25, 10, tzinfo=cal.KST)))

    def test_unconfirmed_hours_and_expired_coverage_fail_closed(self):
        next_year = (datetime.fromisoformat(cal._load()['end']) + timedelta(days=1)).date().isoformat()
        for day in ['2026-11-19', next_year]:
            self.assertEqual(cal.session(day)['status'], 'UNKNOWN')
            self.assertFalse(cal.is_session(day))
        with patch.object(cal, '_load', side_effect=ValueError('invalid JSON')):
            self.assertEqual(cal.session('2026-09-28')['status'], 'UNKNOWN')
            self.assertFalse(cal.is_open_now(datetime(2026, 9, 28, 10, tzinfo=cal.KST)))

    def test_us_last_completed_session_uses_market_timezone(self):
        self.assertEqual(cal.latest_completed_session(datetime(2026, 9, 25, 7, tzinfo=cal.KST), 'XNYS'), '2026-09-24')
        self.assertEqual(cal.latest_completed_session(datetime(2026, 9, 25, 7, tzinfo=cal.KST), 'XKRX'), '2026-09-23')


if __name__ == '__main__':
    unittest.main()
