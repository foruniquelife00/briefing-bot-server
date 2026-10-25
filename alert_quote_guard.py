"""Reject old Korean quotes before creating an intraday price alert.

This guard does not claim to be a complete exchange holiday calendar.
Even if the scheduler mistakes a weekday holiday for an open market,
last-session prices must never become today's price-movement message.
"""
from datetime import datetime, timedelta, timezone
from math import isfinite

KST = timezone(timedelta(hours=9))
MAX_QUOTE_AGE = timedelta(minutes=20)


def validate_kr_quote(ticker, metadata, price, previous_close, *, now=None):
    now = now or datetime.now(KST)
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    now = now.astimezone(KST)
    if metadata.get('symbol') != ticker or metadata.get('exchangeTimezoneName') != 'Asia/Seoul':
        raise ValueError('quote_identity_unconfirmed')
    try:
        timestamp = metadata['regularMarketTime']
        values = (price, previous_close, metadata['regularMarketPrice'], timestamp)
        if any(isinstance(v, bool) or not isfinite(float(v)) or float(v) <= 0 for v in values):
            raise ValueError('invalid_quote_value')
        quote_at = datetime.fromtimestamp(float(timestamp), KST)
        if abs(float(price) - float(metadata['regularMarketPrice'])) > 0.5:
            raise ValueError('quote_price_time_mismatch')
    except (KeyError, TypeError, OverflowError, OSError) as exc:
        raise ValueError('quote_time_or_value_missing') from exc
    if quote_at.date() != now.date():
        raise ValueError('quote_not_from_today')
    if quote_at > now + timedelta(seconds=60):
        raise ValueError('future_quote')
    if now - quote_at > MAX_QUOTE_AGE:
        raise ValueError('stale_intraday_quote')
    return quote_at
