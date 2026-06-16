# -*- coding: utf-8 -*-
"""
토스증권 Open API 현재가 헬퍼 (대시보드 종목 시세용)

- 개별 종목(국내/미국/ETF) 현재가를 토스에서 복수 1콜로 조회 (yfinance 대비 ~33배 빠름)
- OAuth 토큰 캐싱 (만료 전 재사용)
- 토스 실패/키 없음 시 yfinance 자동 fallback → 대시보드 안 깨짐
- 지수(KOSPI/S&P 등)는 토스 미지원 → yfinance 그대로 (이 헬퍼는 개별 종목만)

점수 계산·검증과 무관한 표시 레이어 (GPT 동결과 무관).
"""
import time
import requests
import config

_TOKEN_URL  = "https://openapi.tossinvest.com/oauth2/token"
_PRICES_URL = "https://openapi.tossinvest.com/api/v1/prices"

_token_cache = {"token": None, "expires_at": 0}


def _get_token() -> str | None:
    """토큰 캐싱 — 만료 60초 전까지 재사용. 키 없거나 실패 시 None."""
    cid = getattr(config, "TOSS_CLIENT_ID", "") or ""
    sec = getattr(config, "TOSS_CLIENT_SECRET", "") or ""
    if not cid or not sec:
        return None
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    try:
        r = requests.post(_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": cid, "client_secret": sec,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        _token_cache["token"] = j["access_token"]
        _token_cache["expires_at"] = now + int(j.get("expires_in", 3600))
        return _token_cache["token"]
    except Exception:
        return None


def _to_toss_symbol(ticker: str) -> str:
    """yfinance식 티커(.KS/.KQ)를 토스용 6자리로. 미국은 그대로."""
    return ticker.replace(".KS", "").replace(".KQ", "")


def get_prices(tickers: list[str]) -> dict:
    """
    종목 현재가 {원본_ticker: price}. 토스 우선, 실패분만 yfinance fallback.
    tickers: yfinance식 (예: "005930.KS", "AAPL") 그대로 받아도 됨.
    """
    if not tickers:
        return {}

    result: dict[str, float] = {}
    toss_map = {_to_toss_symbol(t): t for t in tickers}   # 토스심볼 → 원본

    # ── 1차: 토스 복수 1콜 ──
    token = _get_token()
    if token:
        try:
            syms = ",".join(toss_map.keys())
            r = requests.get(_PRICES_URL, params={"symbols": syms},
                             headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                rows = data.get("result", data if isinstance(data, list) else [])
                for x in rows:
                    sym = str(x.get("symbol", ""))
                    orig = toss_map.get(sym) or toss_map.get(sym.zfill(6))
                    lp = x.get("lastPrice")
                    if orig and lp not in (None, ""):
                        try:
                            result[orig] = float(lp)
                        except Exception:
                            pass
        except Exception:
            pass

    # ── 2차: 토스로 못 채운 것만 yfinance fallback ──
    missing = [t for t in tickers if t not in result]
    if missing:
        try:
            import yfinance as yf
            for t in missing:
                try:
                    p = yf.Ticker(t).fast_info.last_price
                    if p:
                        result[t] = float(p)
                except Exception:
                    continue
        except Exception:
            pass

    return result


def get_price(ticker: str) -> float | None:
    """단일 종목 현재가."""
    return get_prices([ticker]).get(ticker)
