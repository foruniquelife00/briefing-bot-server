import streamlit as st
import sqlite3
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import re
from datetime import datetime, timezone, timedelta
import sys
import config
from watchlist import STOCK_MAP, load_watchlist
from eco_calendar import get_this_week_events

st.set_page_config(page_title="투자 브리핑 대시보드", page_icon="📊", layout="wide")

# ── 전체 스타일 (흰 배경, 진한 글씨, 컴팩트) ──
st.markdown("""
<style>
.block-container{padding-top:0.4rem;padding-bottom:0}
div[data-testid="metric-container"]{background:#f7fafc;border:1px solid #e2e8f0;border-radius:6px;padding:4px 10px}
div[data-testid="metric-container"] label{font-size:11px!important;color:#4a5568!important}
div[data-testid="metric-container"] div[data-testid="metric-value"]{font-size:13px!important;font-weight:700!important;color:#1a202c!important}
div[data-testid="metric-container"] div[data-testid="metric-delta"]{font-size:10px!important}
h1,h2,h3{font-size:14px!important;margin:2px 0!important;font-weight:700!important;color:#1a202c!important}
p,span,.stMarkdown{font-size:12px;color:#2d3748}
.stDataFrame{font-size:11px}
.stExpander summary p{font-size:12px!important;color:#2d3748!important}
.stSelectbox label,.stTextInput label,.stNumberInput label{font-size:11px!important;color:#4a5568!important}
button[data-testid="baseButton-secondary"]{font-size:11px!important;padding:2px 8px!important}
.stat-row{display:flex;gap:24px;background:#f7fafc;border:1px solid #e2e8f0;border-radius:6px;padding:6px 14px;margin-bottom:8px}
.stat-item-label{font-size:11px;color:#718096}
.stat-item-val{font-size:13px;font-weight:700;color:#1a202c}
.section-title{font-size:12px;font-weight:700;color:#1a202c;margin:6px 0 3px}
.info-box{background:#ebf8ff;border:1px solid #bee3f8;border-radius:6px;padding:7px 12px;font-size:12px;color:#2c5282;margin-bottom:8px}
.summary-pos{background:#f0fff4;border-left:3px solid #38a169;padding:5px 10px;border-radius:0 4px 4px 0;font-size:12px;color:#1a202c;margin:2px 0}
.summary-neu{background:#ebf8ff;border-left:3px solid #3182ce;padding:5px 10px;border-radius:0 4px 4px 0;font-size:12px;color:#1a202c;margin:2px 0}
.summary-neg{background:#fff5f5;border-left:3px solid #e53e3e;padding:5px 10px;border-radius:0 4px 4px 0;font-size:12px;color:#1a202c;margin:2px 0}
.summary-str{background:#fffff0;border-left:3px solid #d69e2e;padding:5px 10px;border-radius:0 4px 4px 0;font-size:12px;color:#1a202c;margin:2px 0}
.mini-card{border:2px solid #e2e8f0;border-radius:6px;padding:6px 8px;height:72px;background:#fff}
.briefing-text{font-size:14px;line-height:1.9;white-space:pre-wrap;color:#2d3748;padding:8px}
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

# ── 헤더 ──
hc1, hc2 = st.columns([8,1])
with hc1:
    st.markdown(f"**📊 투자 브리핑 대시보드** <span style='color:#718096;font-size:11px'>{now.strftime('%Y.%m.%d %H:%M')} KST</span>", unsafe_allow_html=True)
with hc2:
    if st.button("🔄 갱신"):
        st.cache_data.clear(); st.rerun()

tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
    "🌍 시장현황","🎯 오늘의 추천",
    "📰 브리핑봇","📊 시그널봇",
    "💼 포트폴리오","🐾 운영 원칙"
])

# ── 공통 함수 ──────────────────────────────────
@st.cache_data(ttl=300)
def get_indices():
    tickers = {"S&P500":"^GSPC","NASDAQ":"^IXIC","DOW":"^DJI","니케이":"^N225","코스피":"^KS11","코스닥":"^KQ11"}
    result = {}
    for name,ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            prev = t.fast_info.regular_market_previous_close
            result[name] = {"price":price,"rate":(price-prev)/prev*100}
        except:
            result[name] = {"price":0,"rate":0}
    return result

@st.cache_data(ttl=300)
def get_macro():
    data = {}
    try:
        data["usd"] = yf.Ticker("USDKRW=X").fast_info.last_price
        data["vix"] = yf.Ticker("^VIX").fast_info.last_price
        data["us10y"] = yf.Ticker("^TNX").fast_info.last_price
        res = requests.get("https://api.alternative.me/fng/",timeout=5)
        fgi = res.json()
        data["fgi"] = int(fgi["data"][0]["value"])
        data["fgi_label"] = fgi["data"][0]["value_classification"]
    except: pass
    return data

@st.cache_data(ttl=300)
def get_commodity():
    tickers = {"WTI":"CL=F","금":"GC=F","은":"SI=F","브렌트":"BZ=F"}
    result = {}
    for name,ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            prev = t.fast_info.regular_market_previous_close
            result[name] = {"price":price,"rate":(price-prev)/prev*100}
        except: pass
    return result

@st.cache_data(ttl=180)
def get_wl_prices():
    watchlist = load_watchlist()
    rows = []
    for name in watchlist:
        ticker = STOCK_MAP.get(name)
        if not ticker: continue
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = info.last_price
            prev = info.regular_market_previous_close
            rate = (price-prev)/prev*100
            high52 = info.year_high
            low52 = info.year_low
            is_kr = ticker.endswith((".KS",".KQ"))
            fmt = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
            pos52 = (price-low52)/(high52-low52)*100 if high52!=low52 else 50
            rows.append({"종목":name,"현재가":fmt(price),"등락률":f"{rate:+.2f}%",
                "52주고":fmt(high52),"52주저":fmt(low52),"위치":f"{pos52:.0f}%",
                "_rate":rate,"_pos52":pos52})
        except: pass
    return rows

@st.cache_data(ttl=1800)
def get_daily_summary():
    try:
        conn = sqlite3.connect(config.DB_PATH)
        today = datetime.now(KST).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT briefing_text FROM briefing_history WHERE date=? ORDER BY rowid DESC LIMIT 1",
            (today,)).fetchone()
        conn.close()
        if not row or not row[0]: return {}
        text = row[0]
        result = {}
        for pat,key in [
            (r'긍정[^:：\n]{0,10}[:：]\s*(.{15,80})','positive'),
            (r'중립[^:：\n]{0,10}[:：]\s*(.{15,80})','neutral'),
            (r'리스크[^:：\n]{0,10}[:：]\s*(.{15,80})','negative'),
            (r'전략[^:：\n]{0,10}[:：]\s*(.{15,80})','strategy'),
            (r'대응[^:：\n]{0,10}[:：]\s*(.{15,80})','strategy'),
        ]:
            m = re.search(pat, text)
            if m and key not in result:
                result[key] = m.group(1).strip()[:70]
        if not result:
            lines = [l.strip() for l in text.split('\n')
                if l.strip() and len(l.strip())>20
                and not l.strip().startswith('─')
                and not l.strip().startswith('═')
                and not l.strip().startswith('#')]
            if len(lines) >= 3:
                result = {"positive":lines[1][:70],"neutral":lines[2][:70],
                    "negative":lines[3][:70] if len(lines)>3 else ""}
        return result
    except: return {}

@st.cache_data(ttl=600)
def get_signal_bot_data():
    """stock-signal GitHub에서 오늘의 시그널 데이터 가져오기"""
    url = "https://raw.githubusercontent.com/foruniquelife00/stock-signal/main/exports/signals_for_dashboard.json"
    try:
        res = requests.get(url, timeout=8)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

# ════════════════════════════════════════════
# 탭1: 시장현황
# ════════════════════════════════════════════
with tab1:
    # 오늘 시황 요약 (최상단)
    summary = get_daily_summary()
    if summary:
        st.markdown("<div class='section-title'>📌 오늘의 시장 요약</div>", unsafe_allow_html=True)
        s1,s2,s3 = st.columns(3)
        with s1:
            st.markdown(f"<div class='summary-pos'>✅ <b>긍정</b><br>{summary.get('positive','')}</div>", unsafe_allow_html=True)
        with s2:
            st.markdown(f"<div class='summary-neu'>📊 <b>주목</b><br>{summary.get('neutral','')}</div>", unsafe_allow_html=True)
        with s3:
            st.markdown(f"<div class='summary-neg'>⚠️ <b>리스크</b><br>{summary.get('negative','')}</div>", unsafe_allow_html=True)
        if summary.get('strategy'):
            st.markdown(f"<div class='summary-str'>🧭 <b>대응전략</b> {summary['strategy']}</div>", unsafe_allow_html=True)

    st.divider()

    # 거시지표 (차트 위)
    macro = get_macro()
    fgi = macro.get("fgi",0)
    fgi_icon = "🟢" if fgi>50 else "🔴" if fgi<25 else "🟡"
    mi1,mi2,mi3,mi4 = st.columns(4)
    fgi_color = "#38a169" if fgi>50 else "#e53e3e" if fgi<25 else "#d69e2e"
    for col, label, val, sub in [
        (mi1, "💱 원/달러 환율", f"{macro.get('usd',0):,.0f}원", ""),
        (mi2, "📊 VIX 공포지수", f"{macro.get('vix',0):.1f}", "낮을수록 안정"),
        (mi3, "🏦 미국 10년물 금리", f"{macro.get('us10y',0):.2f}%", ""),
        (mi4, "😨 공포탐욕지수", f"{fgi_icon} {fgi}", macro.get('fgi_label','')),
    ]:
        with col:
            st.markdown(
                f"<div style='background:#f7fafc;border:1px solid #e2e8f0;border-radius:6px;padding:5px 10px'>"
                f"<div style='font-size:11px;color:#4a5568'>{label}</div>"
                f"<div style='font-size:14px;font-weight:700;color:#1a202c'>{val}</div>"
                f"<div style='font-size:10px;color:#718096'>{sub}</div>"
                f"</div>", unsafe_allow_html=True)

    st.divider()

    # 주요 지수
    indices = get_indices()
    cols6 = st.columns(6)
    for i,(name,d) in enumerate(indices.items()):
        with cols6[i]:
            color = "#c53030" if d["rate"]>=0 else "#2b6cb0"
            arrow = "▲" if d["rate"]>=0 else "▼"
            st.markdown(
                f"<div style='font-size:11px;color:#4a5568;font-weight:600'>{name}</div>"
                f"<div style='font-size:15px;font-weight:700;color:#1a202c'>{d['price']:,.2f}</div>"
                f"<div style='font-size:11px;color:{color}'>{arrow} {d['rate']:+.2f}%</div>",
                unsafe_allow_html=True)

    st.divider()

    left,right = st.columns([3,2])
    with left:
        chart_sel = st.selectbox("차트",["^GSPC","^IXIC","^KS11","^KQ11"],
            format_func=lambda x:{"^GSPC":"S&P500","^IXIC":"NASDAQ","^KS11":"코스피","^KQ11":"코스닥"}.get(x,x),
            key="t1chart")
        try:
            hist = yf.Ticker(chart_sel).history(period="1mo")
            fig = go.Figure(go.Candlestick(
                x=hist.index, open=hist["Open"], high=hist["High"],
                low=hist["Low"], close=hist["Close"],
                increasing_line_color="#38a169", decreasing_line_color="#e53e3e"))
            fig.update_layout(height=200, margin=dict(l=5,r=5,t=5,b=5),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#fafafa",
                xaxis_rangeslider_visible=False,
                xaxis=dict(gridcolor="#e2e8f0",tickfont=dict(size=10,color="#4a5568")),
                yaxis=dict(gridcolor="#e2e8f0",tickfont=dict(size=10,color="#4a5568")))
            st.plotly_chart(fig, use_container_width=True)
        except: st.info("차트 로딩 중...")

    with right:
        st.markdown("<div class='section-title'>🌅 프리마켓</div>", unsafe_allow_html=True)
        pre_tickers = {"엔비디아":"NVDA","애플":"AAPL","테슬라":"TSLA","MS":"MSFT"}
        pc = st.columns(4)
        for i,(name,ticker) in enumerate(pre_tickers.items()):
            try:
                info = yf.Ticker(ticker).info
                pre = info.get("preMarketPrice")
                reg = info.get("regularMarketPrice")
                if pre and reg:
                    rate = (pre-reg)/reg*100
                    color = "#c53030" if rate>=0 else "#2b6cb0"
                    with pc[i]:
                        st.markdown(
                            f"<div style='font-size:11px;color:#4a5568'>{name}</div>"
                            f"<div style='font-size:13px;font-weight:700;color:#1a202c'>${pre:.1f}</div>"
                            f"<div style='font-size:11px;color:{color}'>{rate:+.1f}%</div>",
                            unsafe_allow_html=True)
            except: pass

        st.markdown("<div class='section-title'>🛢️ 원자재</div>", unsafe_allow_html=True)
        com = get_commodity()
        cc = st.columns(4)
        for i,(name,d) in enumerate(com.items()):
            color = "#c53030" if d["rate"]>=0 else "#2b6cb0"
            with cc[i]:
                st.markdown(
                    f"<div style='font-size:11px;color:#4a5568'>{name}</div>"
                    f"<div style='font-size:13px;font-weight:700;color:#1a202c'>${d['price']:.1f}</div>"
                    f"<div style='font-size:11px;color:{color}'>{d['rate']:+.1f}%</div>",
                    unsafe_allow_html=True)

        st.markdown("<div class='section-title'>📅 경제 캘린더</div>", unsafe_allow_html=True)
        try:
            cal = get_this_week_events()
            st.markdown(f"<div style='font-size:12px;color:#2d3748;white-space:pre-wrap;line-height:1.6'>{cal[:280] if cal else '없음'}</div>", unsafe_allow_html=True)
        except: st.caption("로딩 중...")

# ════════════════════════════════════════════
# 탭2: 오늘의 추천 종목
# ════════════════════════════════════════════
with tab2:
    st.markdown("<div class='section-title'>🎯 오늘의 추천 종목</div>", unsafe_allow_html=True)
    st.caption(f"기준일: {now.strftime('%Y.%m.%d')}  |  브리핑봇과 시그널봇의 오늘 추천을 한눈에 비교합니다.")
    st.divider()

    briefcol, sigcol = st.columns(2)

    # ── 브리핑봇 오늘 추천 ──────────────────────────────
    with briefcol:
        st.markdown(
            "<div style='background:#ebf8ff;border:2px solid #3182ce;border-radius:8px;padding:6px 12px;margin-bottom:8px'>"
            "<span style='font-size:13px;font-weight:700;color:#2b6cb0'>📰 브리핑봇 오늘의 추천</span>"
            "<span style='font-size:11px;color:#4a5568;margin-left:8px'>AI 시장분석 기반</span>"
            "</div>", unsafe_allow_html=True)
        try:
            conn_b = sqlite3.connect(config.DB_PATH)
            today_str = now.strftime("%Y-%m-%d")
            b_row = conn_b.execute(
                "SELECT recommended, buy_price, briefing_text, trust_score FROM briefing_history"
                " WHERE date=? ORDER BY rowid DESC LIMIT 1",
                (today_str,)).fetchone()
            conn_b.close()
            if b_row and b_row[0]:
                rec_name   = b_row[0]
                buy_price  = b_row[1]
                brief_text = b_row[2] or ""
                trust_sc   = b_row[3] or 0
                is_kr = str(STOCK_MAP.get(rec_name, "")).endswith((".KS", ".KQ"))
                fmt_p = lambda x: f"{int(x):,}원" if (is_kr and x) else (f"${x:.2f}" if x else "-")
                target_p = stoploss_p = reason_t = ""
                for ln in brief_text.split("\n"):
                    ln = ln.strip()
                    if "목표가" in ln and ":" in ln:
                        target_p   = re.sub(r'.*?[：:]\s*', "", ln).strip()[:20]
                    elif "손절가" in ln and ":" in ln:
                        stoploss_p = re.sub(r'.*?[：:]\s*', "", ln).strip()[:20]
                    elif ("추천 이유" in ln or "선정 이유" in ln or "상승 근거" in ln) and ":" in ln:
                        reason_t   = re.sub(r'.*?[：:]\s*', "", ln).strip()[:80]
                trust_color = "#38a169" if trust_sc >= 70 else "#d69e2e" if trust_sc >= 50 else "#e53e3e"
                reason_html = (f"<div style='font-size:11px;color:#2d3748;margin-top:6px;"
                               f"background:#ebf8ff;border-radius:4px;padding:4px 8px'>💡 {reason_t}</div>"
                               if reason_t else "")
                st.markdown(
                    f"<div style='background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;padding:10px 14px;margin:4px 0'>"
                    f"<div style='font-size:17px;font-weight:700;color:#1a202c'>{rec_name}</div>"
                    f"<div style='font-size:11px;color:{trust_color};margin:2px 0'>신뢰도 {trust_sc}점</div>"
                    f"<div style='display:flex;gap:20px;margin-top:6px'>"
                    f"<div><div style='font-size:10px;color:#718096'>💹 매수가</div>"
                    f"<div style='font-size:13px;font-weight:700;color:#1a202c'>{fmt_p(buy_price)}</div></div>"
                    f"<div><div style='font-size:10px;color:#718096'>🎯 목표가</div>"
                    f"<div style='font-size:13px;font-weight:700;color:#38a169'>{target_p or '-'}</div></div>"
                    f"<div><div style='font-size:10px;color:#718096'>🛑 손절가</div>"
                    f"<div style='font-size:13px;font-weight:700;color:#e53e3e'>{stoploss_p or '-'}</div></div>"
                    f"</div>{reason_html}</div>", unsafe_allow_html=True)
            else:
                st.info("오늘 브리핑 데이터 없음\n매일 KST 09:30 자동 생성")
        except Exception as _e:
            st.error(f"브리핑봇 데이터 오류: {_e}")

    # ── 시그널봇 오늘 추천 ──────────────────────────────
    with sigcol:
        st.markdown(
            "<div style='background:#fff5f5;border:2px solid #fc8181;border-radius:8px;padding:6px 12px;margin-bottom:8px'>"
            "<span style='font-size:13px;font-weight:700;color:#c53030'>📊 시그널봇 오늘의 추천</span>"
            "<span style='font-size:11px;color:#4a5568;margin-left:8px'>KOSPI 200 수급 분석 기반</span>"
            "</div>", unsafe_allow_html=True)
        sig_data = get_signal_bot_data()
        if sig_data is None:
            st.info("시그널봇 데이터 로드 중...\n저녁 장 마감 후 자동 업데이트됩니다.")
        else:
            sig_date = sig_data.get("date", "")
            sig_time = sig_data.get("generated_at", "")
            signals  = sig_data.get("signals", [])
            st.caption(f"업데이트: {sig_time}  |  기준일: {sig_date}")
            if not signals:
                st.info("오늘 BUY/WATCH 시그널 없음")
            else:
                buy_sigs   = [s for s in signals if s.get("grade") == "BUY"]
                watch_sigs = [s for s in signals if s.get("grade") == "WATCH"]
                if buy_sigs:
                    st.markdown("<div style='font-size:11px;font-weight:700;color:#c53030;margin:4px 0'>🔴 BUY</div>", unsafe_allow_html=True)
                    for s in buy_sigs:
                        st.markdown(
                            f"<div style='background:#fff5f5;border:1px solid #feb2b2;border-radius:8px;padding:8px 12px;margin:4px 0'>"
                            f"<div style='font-size:14px;font-weight:700;color:#1a202c'>{s['name']}"
                            f" <span style='font-size:11px;color:#e53e3e'>BUY {s.get('score',0):.0f}점</span></div>"
                            f"<div style='display:flex;gap:16px;margin-top:4px'>"
                            f"<div><div style='font-size:10px;color:#718096'>💹 진입가</div>"
                            f"<div style='font-size:12px;font-weight:700;color:#1a202c'>{s.get('entry','-')}</div></div>"
                            f"<div><div style='font-size:10px;color:#718096'>🎯 목표가</div>"
                            f"<div style='font-size:12px;font-weight:700;color:#38a169'>{s.get('target','-')}</div></div>"
                            f"<div><div style='font-size:10px;color:#718096'>🛑 손절가</div>"
                            f"<div style='font-size:12px;font-weight:700;color:#e53e3e'>{s.get('stoploss','-')}</div></div>"
                            f"</div>"
                            f"<div style='font-size:11px;color:#2d3748;margin-top:4px'>💡 {s.get('reason','-')[:80]}</div>"
                            f"</div>", unsafe_allow_html=True)
                if watch_sigs:
                    st.markdown("<div style='font-size:11px;font-weight:700;color:#d69e2e;margin:6px 0 4px'>🟡 WATCH</div>", unsafe_allow_html=True)
                    for s in watch_sigs:
                        st.markdown(
                            f"<div style='background:#fffff0;border:1px solid #faf089;border-radius:6px;padding:6px 10px;margin:3px 0'>"
                            f"<div style='font-size:13px;font-weight:700;color:#1a202c'>{s['name']}"
                            f" <span style='font-size:11px;color:#d69e2e'>WATCH {s.get('score',0):.0f}점</span></div>"
                            f"<div style='font-size:11px;color:#2d3748;margin-top:2px'>💡 {s.get('reason','-')[:70]}</div>"
                            f"</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════
# 탭3: 브리핑봇 (AI 워치리스트 / 히스토리 / 신뢰도 / 성과)
# ════════════════════════════════════════════
with tab3:
    bt1, bt2, bt3, bt4 = st.tabs([
        "🤖 AI 워치리스트", "📰 브리핑히스토리",
        "📐 신뢰도트렌드", "📊 성과 & 검증"
    ])

with bt1:
    from ai_watchlist import load_ai_watchlist_full
    ai_data = load_ai_watchlist_full()
    ai_stocks = ai_data.get("stocks",[])

    # 헤더
    ah1,ah2,ah3 = st.columns([3,2,1])
    with ah1:
        st.markdown("<div style='font-size:13px;font-weight:700;color:#1a202c'>🤖 AI 선정 워치리스트</div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:11px;color:#4a5568;background:#f7fafc;border:1px solid #e2e8f0;border-radius:4px;padding:3px 8px;margin:2px 0'>"
            "📌 <b>선정기준</b>: 모멘텀(상승세·거래량) · 펀더멘털(실적·저평가) · 이벤트(정책·실적발표) · 기술적(52주 돌파·MACD)"
            "</div>", unsafe_allow_html=True)
        if ai_data.get("weekly_theme"):
            st.markdown(f"<div style='font-size:11px;color:#2b6cb0'>🗓️ {ai_data['weekly_theme']}</div>", unsafe_allow_html=True)
        if ai_data.get("risk_warning"):
            st.markdown(f"<div style='font-size:11px;color:#c53030'>⚠️ {ai_data['risk_warning']}</div>", unsafe_allow_html=True)
    with ah2:
        ff1,ff2 = st.columns(2)
        with ff1: style_f = st.selectbox("스타일",["전체","모멘텀","안정","역발상","성장","배당"],key="ai_sf")
        with ff2:
            sec_list = sorted(set([s.get("sector","기타") for s in ai_stocks if isinstance(s,dict)]))
            sec_f = st.selectbox("섹터",["전체"]+sec_list,key="ai_sec")
    with ah3:
        st.caption(f"갱신: {ai_data.get('updated_at','')[-5:]}")
        if st.button("🔄 AI갱신",key="ai_ref"):
            with st.spinner("~2분"):
                from ai_watchlist import update_ai_watchlist
                update_ai_watchlist()
                st.cache_data.clear(); st.rerun()

    filtered = [s for s in ai_stocks if isinstance(s,dict)
        and (style_f=="전체" or s.get("style")==style_f)
        and (sec_f=="전체" or s.get("sector")==sec_f)]

    bg_map = {"모멘텀":"#fff5f5","성장":"#fffaf0","역발상":"#faf5ff","안정":"#f0fff4","배당":"#ebf8ff"}
    bd_map = {"모멘텀":"#fc8181","성장":"#f6ad55","역발상":"#b794f4","안정":"#68d391","배당":"#63b3ed"}
    imap = {"모멘텀":"🔴","성장":"🟠","역발상":"🟣","안정":"🟢","배당":"🔵"}

    if filtered:
        cols5 = st.columns(5)
        for i,s in enumerate(filtered[:5]):
            with cols5[i]:
                name = s.get("name","")
                sector = s.get("sector","")
                style = s.get("style","")
                reason = s.get("reason","")[:22]
                icon = imap.get(style,"⚪")
                bg = bg_map.get(style,"#f7fafc")
                bd = bd_map.get(style,"#e2e8f0")
                st.markdown(
                    f"<div style='background:{bg};border:2px solid {bd};border-radius:6px;padding:6px 8px'>"
                    f"<div style='font-size:12px;font-weight:700;color:#1a202c;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{name}</div>"
                    f"<div style='color:#4a5568;font-size:10px;margin:2px 0'>{sector} {icon}</div>"
                    f"<div style='color:#2d3748;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{reason}</div>"
                    f"</div>", unsafe_allow_html=True)

        if len(filtered) > 5:
            with st.expander(f"나머지 {len(filtered)-5}개"):
                items = []
                for s in filtered[5:]:
                    if isinstance(s,dict):
                        nm = s.get("name","")
                        tk = STOCK_MAP.get(nm,"").replace(".KS","").replace(".KQ","")
                        items.append(f"{nm}({tk})")
                st.markdown(f"<div style='font-size:12px;color:#2d3748;font-weight:500'>{' · '.join(items)}</div>", unsafe_allow_html=True)

    st.divider()

    with st.expander("📊 상승/하락 TOP3 & 전체 시세", expanded=False):
        sort_by = st.selectbox("정렬",["등락률↑","등락률↓","종목명"],key="wl_sort")
        wl_data = get_wl_prices()
        if wl_data:
            if sort_by=="등락률↑": wl_data.sort(key=lambda x:x["_rate"],reverse=True)
            elif sort_by=="등락률↓": wl_data.sort(key=lambda x:x["_rate"])
            else: wl_data.sort(key=lambda x:x["종목"])
            uc,dc = st.columns(2)
            with uc:
                st.markdown("<div class='section-title'>🚀 상승 TOP3</div>", unsafe_allow_html=True)
                for r in wl_data[:3]: st.success(f"{r['종목']}: {r['현재가']} ({r['등락률']})")
            with dc:
                st.markdown("<div class='section-title'>📉 하락 TOP3</div>", unsafe_allow_html=True)
                for r in sorted(wl_data,key=lambda x:x["_rate"])[:3]: st.error(f"{r['종목']}: {r['현재가']} ({r['등락률']})")
            st.dataframe(pd.DataFrame(wl_data).drop(columns=["_rate","_pos52"]),
                use_container_width=True, hide_index=True, height=250)

    with st.expander("⚙️ 워치리스트 관리", expanded=False):
        ca,cb = st.columns(2)
        with ca:
            ns = st.text_input("추가할 종목",key="wl_add",placeholder="예: 삼성전자")
            if st.button("➕ 추가",key="wl_add_btn"):
                if ns:
                    from watchlist import add_stock
                    r = add_stock(ns.strip())
                    st.success(r) if "✅" in r else st.error(r)
                    st.cache_data.clear()
        with cb:
            ds = st.text_input("삭제할 종목",key="wl_del",placeholder="예: 카카오")
            if st.button("➖ 삭제",key="wl_del_btn"):
                if ds:
                    from watchlist import remove_stock
                    r = remove_stock(ds.strip())
                    st.success(r) if "✅" in r else st.error(r)
                    st.cache_data.clear()

with bt2:
    try:
        conn = sqlite3.connect(config.DB_PATH)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "briefing_history" in tables:
            hist = pd.read_sql(
                "SELECT date, weekday, trust_score, recommended, buy_price, briefing_text FROM briefing_history ORDER BY date DESC LIMIT 30",
                conn)
            conn.close()
            if hist.empty:
                st.info("브리핑 기록 없음")
            else:
                dates = hist["date"].unique().tolist()
                sel = st.selectbox("날짜",dates,key="t3date")
                row = hist[hist["date"]==sel].iloc[0]
                rec_name = row["recommended"] or "없음"
                is_kr_rec = str(STOCK_MAP.get(row["recommended"] or "","")).endswith((".KS",".KQ"))
                price_str = f"{int(row['buy_price']):,}원" if is_kr_rec and row["buy_price"] else f"${row['buy_price']:.2f}" if row["buy_price"] else "없음"
                trust_color = "#38a169" if row["trust_score"]>=70 else "#d69e2e" if row["trust_score"]>=50 else "#e53e3e"

                # 요약 한 줄
                st.markdown(
                    f"<div class='stat-row'>"
                    f"<div><span class='stat-item-label'>📅 요일 </span><span class='stat-item-val'>{row['weekday']}</span></div>"
                    f"<div><span class='stat-item-label'>⭐ 추천종목 </span><span style='font-size:13px;font-weight:700;color:#2b6cb0'>{rec_name}</span></div>"
                    f"<div><span class='stat-item-label'>💰 매수가 </span><span class='stat-item-val'>{price_str}</span></div>"
                    f"<div><span class='stat-item-label'>📐 신뢰도 </span><span style='font-size:13px;font-weight:700;color:{trust_color}'>{row['trust_score']}/100</span></div>"
                    f"</div>", unsafe_allow_html=True)

                if row["briefing_text"]:
                    text = row["briefing_text"]

                    # 추천 종목 상세
                    rec_info = {}
                    for l in text.split("\n"):
                        l = l.strip()
                        if "현재가" in l and ":" in l: rec_info["현재가"] = re.sub(r'.*?[：:]\s*',"",l).strip()[:15]
                        elif "목표가" in l and ":" in l: rec_info["목표가"] = re.sub(r'.*?[：:]\s*',"",l).strip()[:15]
                        elif "손절가" in l and ":" in l: rec_info["손절가"] = re.sub(r'.*?[：:]\s*',"",l).strip()[:15]
                        elif ("추천 이유" in l or "선정 이유" in l or "상승 근거" in l) and ":" in l:
                            rec_info["이유"] = re.sub(r'.*?[：:]\s*',"",l).strip()[:60]

                    if any(k in rec_info for k in ["현재가","목표가","손절가"]):
                        ri1,ri2,ri3 = st.columns(3)
                        for col,k,label in [(ri1,"현재가","💹 현재가"),(ri2,"목표가","🎯 목표가"),(ri3,"손절가","🛑 손절가")]:
                            with col:
                                st.markdown(
                                    f"<div style='font-size:11px;color:#4a5568'>{label}</div>"
                                    f"<div style='font-size:13px;font-weight:700;color:#1a202c'>{rec_info.get(k,'N/A')}</div>",
                                    unsafe_allow_html=True)
                        if rec_info.get("이유"):
                            st.markdown(f"<div style='font-size:12px;color:#2b6cb0;background:#ebf8ff;border-radius:4px;padding:4px 8px;margin:3px 0'>💡 {rec_info['이유']}</div>", unsafe_allow_html=True)

                    # 핵심 요약 3줄 (추천종목 연관 우선)
                    st.markdown("<div class='section-title'>📌 핵심 요약</div>", unsafe_allow_html=True)
                    rec_related, general = [], []
                    for line in text.split("\n"):
                        line = line.strip()
                        if len(line)<20 or line.startswith("─") or line.startswith("═") or line.startswith("#"): continue
                        clean = line.replace("**","").replace("##","").replace("#","").strip()
                        if rec_name != "없음" and rec_name in clean: rec_related.append(clean)
                        else: general.append(clean)

                    show_lines = (rec_related[:1] + general)[:3]
                    for line in show_lines:
                        st.markdown(f"<div class='summary-neu'>{line[:100]}</div>", unsafe_allow_html=True)

                    # 전문 보기
                    with st.expander("📄 브리핑 전문 보기"):
                        st.markdown(f"<div class='briefing-text'>{text[:4000]}</div>", unsafe_allow_html=True)
                else:
                    st.info("브리핑 내용 없음")
        else:
            conn.close()
            st.info("브리핑 히스토리 DB 없음")
    except Exception as e:
        st.error(f"오류: {e}")

with bt3:
    try:
        conn = sqlite3.connect(config.DB_PATH)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        hist_df = pd.read_sql(
            "SELECT date, weekday, trust_score, recommended, fgi_score, kospi, sp500 FROM briefing_history ORDER BY date ASC",
            conn) if "briefing_history" in tables else pd.DataFrame()
        conn.close()

        if hist_df.empty:
            st.info("브리핑 데이터가 아직 없어요.")
        else:
            avg_t = hist_df["trust_score"].mean()
            max_t = hist_df["trust_score"].max()
            min_t = hist_df["trust_score"].min()
            trend = hist_df["trust_score"].iloc[-1]-hist_df["trust_score"].iloc[0] if len(hist_df)>1 else 0
            trend_icon = "📈" if trend>0 else "📉" if trend<0 else "➡️"
            trend_color = "#38a169" if trend>0 else "#e53e3e" if trend<0 else "#718096"

            # 설명
            st.markdown(
                "<div class='info-box'>📐 <b>신뢰도 점수란?</b> AI 브리핑의 품질 지표입니다. "
                "수치 정확도(30점) + 과거 성과(30점) + AI 일치도(20점) + 손익비(20점) = 100점 만점. "
                "<b>80점↑ 우수🟢 / 60~79점 양호🟡 / 60점↓ 주의🔴</b></div>",
                unsafe_allow_html=True)

            # 요약 컴팩트
            st.markdown(
                f"<div class='stat-row'>"
                f"<div><span class='stat-item-label'>📊 전체 평균 </span><span class='stat-item-val'>{avg_t:.0f}점 / 100점</span></div>"
                f"<div><span class='stat-item-label'>🏆 최고 기록 </span><span style='font-size:13px;font-weight:700;color:#38a169'>{max_t}점</span></div>"
                f"<div><span class='stat-item-label'>📉 최저 기록 </span><span style='font-size:13px;font-weight:700;color:#e53e3e'>{min_t}점</span></div>"
                f"<div><span class='stat-item-label'>{trend_icon} 최초 대비 </span><span style='font-size:13px;font-weight:700;color:{trend_color}'>{trend:+.0f}점</span></div>"
                f"<div><span class='stat-item-label'>📋 총 브리핑 </span><span class='stat-item-val'>{len(hist_df)}회</span></div>"
                f"</div>", unsafe_allow_html=True)

            lc,rc = st.columns(2)
            with lc:
                st.markdown("<div class='section-title'>📈 신뢰도 추이</div>", unsafe_allow_html=True)
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=hist_df["date"], y=hist_df["trust_score"],
                    mode="lines+markers",
                    line=dict(color="#3182ce",width=2),
                    marker=dict(size=7,
                        color=hist_df["trust_score"],
                        colorscale=[[0,"#fc8181"],[0.6,"#f6e05e"],[0.8,"#68d391"],[1,"#38a169"]],
                        showscale=False),
                    text=hist_df["recommended"],
                    hovertemplate="<b>%{x}</b><br>신뢰도: %{y}점<br>추천: %{text}<extra></extra>"))
                fig.add_hline(y=80,line_dash="dash",line_color="#38a169",
                    annotation_text="우수(80)",annotation_font=dict(color="#38a169",size=10))
                fig.add_hline(y=60,line_dash="dash",line_color="#d69e2e",
                    annotation_text="양호(60)",annotation_font=dict(color="#d69e2e",size=10))
                fig.update_layout(height=220,margin=dict(l=5,r=5,t=5,b=5),
                    paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#fafafa",
                    yaxis=dict(range=[0,105],gridcolor="#e2e8f0",tickfont=dict(color="#4a5568",size=11)),
                    xaxis=dict(gridcolor="#e2e8f0",tickfont=dict(color="#4a5568",size=11)),
                    showlegend=False)
                st.plotly_chart(fig,use_container_width=True)

            with rc:
                st.markdown("<div class='section-title'>📊 등급 분포</div>", unsafe_allow_html=True)
                def grade(s): return "🟢 우수(80+)" if s>=80 else "🟡 양호(60~79)" if s>=60 else "🔴 주의(~59)"
                hist_df["등급"] = hist_df["trust_score"].apply(grade)
                gc = hist_df["등급"].value_counts()
                fig2 = px.pie(values=gc.values,names=gc.index,
                    color=gc.index,
                    color_discrete_map={"🟢 우수(80+)":"#68d391","🟡 양호(60~79)":"#f6e05e","🔴 주의(~59)":"#fc8181"})
                fig2.update_traces(textfont_size=12,textfont_color="#1a202c")
                fig2.update_layout(height=220,margin=dict(l=5,r=5,t=5,b=5),
                    paper_bgcolor="rgba(0,0,0,0)",
                    legend=dict(font=dict(size=11,color="#2d3748")))
                st.plotly_chart(fig2,use_container_width=True)

            st.markdown("<div class='section-title'>📋 브리핑 이력</div>", unsafe_allow_html=True)
            display_df = hist_df[["date","weekday","trust_score","등급","recommended","fgi_score"]].copy()
            display_df.columns = ["날짜","요일","신뢰도","등급","추천종목","공포탐욕"]
            st.dataframe(display_df.sort_values("날짜",ascending=False),
                use_container_width=True,hide_index=True,height=180)
    except Exception as e:
        st.error(f"신뢰도 트렌드 오류: {e}")

# ════════════════════════════════════════════
# 탭5: 포트폴리오
# ════════════════════════════════════════════
with tab5:
    # ════════════════════════════════════════════
    # 탭5: 포트폴리오
    # ════════════════════════════════════════════
    st.markdown("<div class='section-title'>⚙️ 종목 추가/삭제</div>", unsafe_allow_html=True)
    pa,pb,pc_,pd_ = st.columns([2,1,2,1])
    with pa:
        st.caption("종목명")
        pname = st.text_input("종목명",key="pf_nm",placeholder="삼성전자",label_visibility="collapsed")
    with pb:
        st.caption("수량")
        pqty = st.number_input("수량",min_value=0.0,value=1.0,step=1.0,key="pf_qty",label_visibility="collapsed")
    with pc_:
        st.caption("매수가")
        pprice = st.number_input("매수가",min_value=0.0,value=0.0,step=100.0,key="pf_price",label_visibility="collapsed")
    with pd_:
        st.caption(" ")
        if st.button("➕ 추가",key="pf_add",use_container_width=True):
            if pname and pprice>0:
                from portfolio import add_portfolio
                r = add_portfolio(pname.strip(),pqty,pprice)
                st.success(r) if "✅" in r else st.error(r)
                st.cache_data.clear(); st.rerun()

    try:
        conn2 = sqlite3.connect(config.DB_PATH)
        pf_names = [r[0] for r in conn2.execute("SELECT stock_name FROM portfolio ORDER BY stock_name").fetchall()]
        conn2.close()
    except: pf_names = []

    de1,de2 = st.columns([3,1])
    with de1:
        st.caption(f"삭제할 종목" + (f"  (보유: {', '.join(pf_names)})" if pf_names else ""))
        del_nm = st.text_input("삭제종목",value=pf_names[0] if pf_names else "",key="pf_del_txt",label_visibility="collapsed")
    with de2:
        st.caption(" ")
        if st.button("➖ 삭제",key="pf_del_btn",use_container_width=True):
            if del_nm:
                from portfolio import remove_portfolio
                r = remove_portfolio(del_nm.strip())
                st.success(r) if "✅" in r else st.error(r)
                st.cache_data.clear(); st.rerun()

    st.divider()

    @st.cache_data(ttl=180)
    def get_pf():
        from portfolio import get_portfolio_data
        return get_portfolio_data()

    pf = get_pf()
    if not pf:
        st.info("포트폴리오 비어있어요. 위에서 추가해보세요!")
    else:
        ti = sum(d["_invest"] for d in pf)
        tc = sum(d["_cur_val"] for d in pf)
        tp = tc-ti; tr = (tc-ti)/ti*100
        tr_color = "#38a169" if tr>=0 else "#e53e3e"

        st.markdown(
            f"<div class='stat-row'>"
            f"<div><span class='stat-item-label'>💰 총 투자 </span><span class='stat-item-val'>{int(ti):,}원</span></div>"
            f"<div><span class='stat-item-label'>📈 평가액 </span><span class='stat-item-val'>{int(tc):,}원</span></div>"
            f"<div><span class='stat-item-label'>💹 수익률 </span><span style='font-size:13px;font-weight:700;color:{tr_color}'>{tr:+.2f}%</span></div>"
            f"<div><span class='stat-item-label'>💵 손익 </span><span style='font-size:13px;font-weight:700;color:{tr_color}'>{int(tp):+,}원</span></div>"
            f"</div>", unsafe_allow_html=True)

        df = pd.DataFrame(pf)
        lc,rc = st.columns(2)
        with lc:
            st.markdown("<div class='section-title'>📊 종목별 수익률</div>", unsafe_allow_html=True)
            fig = px.bar(df,x="종목",y="_rate",color="_rate",
                color_continuous_scale=["#e53e3e","#38a169"],labels={"_rate":"수익률(%)"})
            fig.add_hline(y=0,line_dash="dash",line_color="#718096")
            fig.update_layout(height=200,margin=dict(l=5,r=5,t=5,b=5),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#fafafa",
                coloraxis_showscale=False,
                xaxis=dict(tickfont=dict(size=12,color="#2d3748")),
                yaxis=dict(tickfont=dict(size=11,color="#2d3748"),gridcolor="#e2e8f0"))
            st.plotly_chart(fig,use_container_width=True)
        with rc:
            st.markdown("<div class='section-title'>🥧 포트폴리오 비중</div>", unsafe_allow_html=True)
            fig2 = px.pie(df,values="_cur_val",names="종목")
            fig2.update_traces(textfont_size=12,textfont_color="#1a202c")
            fig2.update_layout(height=200,margin=dict(l=5,r=5,t=5,b=5),
                paper_bgcolor="rgba(0,0,0,0)",legend=dict(font=dict(size=12,color="#2d3748")))
            st.plotly_chart(fig2,use_container_width=True)

        st.markdown("<div class='section-title'>📋 보유 종목 상세</div>", unsafe_allow_html=True)
        st.dataframe(df.drop(columns=["_rate","_invest","_cur_val"]),
            use_container_width=True,hide_index=True,height=180)

with bt4:
    # ════════════════════════════════════════════
    # 브리핑봇 성과 & 검증
    # ════════════════════════════════════════════

    # 설명 박스
    st.markdown(
        "<div class='info-box'>"
        "📊 <b>성과 추적</b>: AI가 추천한 종목의 현재 수익률을 실시간으로 확인합니다. "
        "🔬 <b>백테스팅</b>: 과거 추천 종목이 목표가/손절가 기준으로 어떤 결과를 냈는지 검증합니다."
        "</div>", unsafe_allow_html=True)

    perf_tab, bt_tab = st.tabs(["📊 성과 추적", "🔬 백테스팅"])

    with perf_tab:
        try:
            conn = sqlite3.connect(config.DB_PATH)
            df = pd.read_sql(
                "SELECT date, stock_name, ticker, buy_price, target_price, stop_loss FROM recommendations ORDER BY date DESC LIMIT 30",
                conn)
            conn.close()
            if df.empty:
                st.info("추천 종목 기록 없음. 브리핑이 실행되면 자동으로 쌓입니다.")
            else:
                @st.cache_data(ttl=300)
                def get_prices_perf(tickers):
                    prices = {}
                    for t in tickers:
                        try: prices[t] = yf.Ticker(t).fast_info.last_price
                        except: prices[t] = None
                    return prices

                prices = get_prices_perf(tuple(df["ticker"].unique()))
                rows = []
                for _,row in df.iterrows():
                    cur = prices.get(row["ticker"])
                    if cur is None: continue
                    rate = (cur-row["buy_price"])/row["buy_price"]*100
                    is_kr = row["ticker"].endswith((".KS",".KQ"))
                    fmt = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
                    if cur>=row["target_price"]: status="🎯 목표"
                    elif cur<=row["stop_loss"]: status="🛑 손절"
                    elif rate>=0: status="✅ 수익"
                    else: status="⚠️ 손실"
                    rows.append({"날짜":row["date"],"종목":row["stock_name"],
                        "매수가":fmt(row["buy_price"]),"현재가":fmt(cur),
                        "수익률":f"{rate:+.2f}%","목표가":fmt(row["target_price"]),
                        "손절가":fmt(row["stop_loss"]),"상태":status,"_rate":rate})

                if rows:
                    avg = sum(r["_rate"] for r in rows)/len(rows)
                    wins = sum(1 for r in rows if r["_rate"]>0)
                    targets = sum(1 for r in rows if "목표" in r["상태"])
                    stops = sum(1 for r in rows if "손절" in r["상태"])
                    avg_color = "#38a169" if avg>=0 else "#e53e3e"

                    st.markdown(
                        f"<div class='stat-row'>"
                        f"<div><span class='stat-item-label'>📊 평균 수익률 </span><span style='font-size:13px;font-weight:700;color:{avg_color}'>{avg:+.2f}%</span></div>"
                        f"<div><span class='stat-item-label'>🎯 승률 </span><span class='stat-item-val'>{wins/len(rows)*100:.0f}%</span></div>"
                        f"<div><span class='stat-item-label'>📋 총 추천 </span><span class='stat-item-val'>{len(rows)}건</span></div>"
                        f"<div><span class='stat-item-label'>🏆 목표달성 </span><span style='font-size:13px;font-weight:700;color:#38a169'>{targets}건</span></div>"
                        f"<div><span class='stat-item-label'>🛑 손절발생 </span><span style='font-size:13px;font-weight:700;color:#e53e3e'>{stops}건</span></div>"
                        f"</div>", unsafe_allow_html=True)

                    cdf = pd.DataFrame(rows)
                    st.markdown("<div class='section-title'>📈 수익률 추이</div>", unsafe_allow_html=True)
                    fig = px.bar(cdf,x="날짜",y="_rate",color="_rate",
                        color_continuous_scale=["#e53e3e","#38a169"],labels={"_rate":"수익률(%)"})
                    fig.add_hline(y=0,line_dash="dash",line_color="#718096")
                    fig.update_layout(height=200,margin=dict(l=5,r=5,t=5,b=5),
                        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#fafafa",
                        coloraxis_showscale=False,
                        xaxis=dict(tickfont=dict(size=11,color="#2d3748")),
                        yaxis=dict(tickfont=dict(size=11,color="#2d3748"),gridcolor="#e2e8f0"))
                    st.plotly_chart(fig,use_container_width=True)
                    st.dataframe(cdf.drop(columns=["_rate"]),use_container_width=True,hide_index=True,height=200)
        except Exception as e: st.error(f"오류: {e}")

    with bt_tab:
        if st.button("🔬 백테스팅 실행"):
            with st.spinner("분석 중..."):
                from backtest import run_backtest, save_backtest_to_db
                bt = run_backtest(); save_backtest_to_db(bt)
                st.session_state["bt"] = bt

        bt = st.session_state.get("bt")
        if not bt:
            try:
                from backtest import run_backtest
                bt = run_backtest()
                st.session_state["bt"] = bt
            except Exception as _e:
                bt = {"error": f"백테스팅 데이터 없음 (첫 브리핑 실행 후 사용 가능)"}
                st.session_state["bt"] = bt

        if "error" in bt:
            st.info(bt["error"])
        else:
            avg_color = "#38a169" if bt["avg_rate"]>=0 else "#e53e3e"
            st.markdown(
                f"<div class='stat-row'>"
                f"<div><span class='stat-item-label'>📋 대상 </span><span class='stat-item-val'>{bt['total']}건</span></div>"
                f"<div><span class='stat-item-label'>📊 평균 수익률 </span><span style='font-size:13px;font-weight:700;color:{avg_color}'>{bt['avg_rate']:+.2f}%</span></div>"
                f"<div><span class='stat-item-label'>🎯 승률 </span><span class='stat-item-val'>{bt['win_rate']:.0f}%</span></div>"
                f"<div><span class='stat-item-label'>🏆 목표달성 </span><span style='font-size:13px;font-weight:700;color:#38a169'>{bt['target_hits']}건</span></div>"
                f"<div><span class='stat-item-label'>🛑 손절발생 </span><span style='font-size:13px;font-weight:700;color:#e53e3e'>{bt['stop_hits']}건</span></div>"
                f"</div>", unsafe_allow_html=True)

            lc,rc = st.columns(2)
            with lc:
                st.markdown("<div class='section-title'>📈 백테스팅 수익률</div>", unsafe_allow_html=True)
                df = pd.DataFrame(bt["results"])
                fig = px.bar(df,x="date",y="rate",color="rate",
                    color_continuous_scale=["#e53e3e","#38a169"],labels={"rate":"수익률(%)"})
                fig.add_hline(y=0,line_dash="dash",line_color="#718096")
                fig.update_layout(height=220,margin=dict(l=5,r=5,t=5,b=5),
                    paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#fafafa",
                    coloraxis_showscale=False,
                    xaxis=dict(tickfont=dict(size=11,color="#2d3748")),
                    yaxis=dict(tickfont=dict(size=11,color="#2d3748"),gridcolor="#e2e8f0"))
                st.plotly_chart(fig,use_container_width=True)
            with rc:
                st.markdown("<div class='section-title'>🥧 결과 분포</div>", unsafe_allow_html=True)
                oc = pd.DataFrame(bt["results"])["outcome"].value_counts()
                fig2 = px.pie(values=oc.values,names=oc.index,color=oc.index,
                    color_discrete_map={"목표달성":"#68d391","수익중":"#63b3ed","손실중":"#fc8181","손절":"#e53e3e"})
                fig2.update_traces(textfont_size=12,textfont_color="#1a202c")
                fig2.update_layout(height=220,margin=dict(l=5,r=5,t=5,b=5),
                    paper_bgcolor="rgba(0,0,0,0)",legend=dict(font=dict(size=11,color="#2d3748")))
                st.plotly_chart(fig2,use_container_width=True)

            st.dataframe(pd.DataFrame([{
                "날짜":r["date"],"종목":r["name"],"매수가":r["buy_str"],
                "현재가":r["current_str"],"수익률":f"{r['rate']:+.2f}%",
                "결과":f"{r['outcome_icon']} {r['outcome']}","보유일":f"{r['hold_days']}일"
            } for r in bt["results"]]),use_container_width=True,hide_index=True,height=200)

with tab4:
    # ════════════════════════════════════════════
    # 탭4: 시그널봇
    # ════════════════════════════════════════════
    st.header("📊 시그널봇")
    st.caption("KOSPI 200 종목의 기관·외국인 수급을 기반으로 관심 종목을 탐지하는 수급 기반 알리미입니다.")

    st.info(
        "스톡시그널봇은 주가를 예언하는 도구가 아니라, "
        "기관·외국인의 실제 매수 흐름을 점수화해 BUY / WATCH / 관심PASS 후보를 분류하는 관찰 도구입니다."
    )

    st.subheader("핵심 역할")
    st.markdown(
        """
        - KOSPI 200 종목 중 수급이 개선되는 종목 탐지
        - 기관·외국인 순매수, 수급가속, 장기 연속매수 흐름 분석
        - 차트, OBV, 실적 발표 이벤트, DART 공시 플래그로 해석 보강
        - D+1 / D+3 / D+5 / D+10 / D+20 수익률 검증
        - 텔레그램으로 카드형 시그널 발송
        """
    )

    st.subheader("현재 운영 상태")
    st.table(
        {
            "항목": [
                "대상 종목",
                "현재 버전",
                "시그널 등급",
                "검증 구조",
                "텔레그램 헤더",
                "점수 체계",
            ],
            "내용": [
                "KOSPI 200",
                "v0.3.1",
                "BUY / WATCH / 관심PASS / PASS",
                "D+1 / D+3 / D+5 / D+10 / D+20",
                "📊 [시그널봇]",
                "v0.2 점수 체계 동결 유지",
            ],
        }
    )

    st.subheader("점수 구조")
    st.markdown(
        """
        총점은 100점 만점 구조입니다.

        | 항목 | 점수 |
        |------|------|
        | 원자재 점수 | 20점 |
        | 수급파워 점수 | 30점 |
        | 수급가속 점수 (단기 12 + long_flow 8) | 20점 |
        | 기술적 점수 | 20점 |
        | 패시브 감점 | 최대 -10점 |
        """
    )

    st.subheader("보조 해석 장치")
    st.markdown(
        """
        - **OBV**: 수급 신호가 거래량 흐름과 맞는지 확인
        - **실적 발표 이벤트**: 30일 이내 실적 발표 예정 여부 표시
        - **DART 공시 플래그**: 공급계약, 수주, 자사주취득, 실적전망 등 의미 있는 공시 감지
        - **extreme_market_day**: KOSPI 급등락이 큰 날은 일반 검증과 분리
        """
    )

    st.warning(
        "스톡시그널봇은 투자 추천이나 수익 보장 도구가 아닙니다. "
        "검증 리포트는 학습과 관찰용이며, 충분한 데이터가 쌓이기 전까지 점수 공식은 변경하지 않습니다."
    )

with tab6:
    # ════════════════════════════════════════════
    # 탭6: 운영 원칙
    # ════════════════════════════════════════════
    st.header("🐾 운영 원칙")
    st.caption("브리핑봇과 스톡시그널봇의 역할과 사용 원칙을 정리합니다.")

    st.subheader("📰 브리핑봇")
    st.markdown(
        """
        브리핑봇은 시장 주요 뉴스와 이벤트를 요약해 텔레그램으로 전달하는 정보 도구입니다.

        - 국내외 주요 시장 뉴스 요약
        - 경제 일정 확인
        - 시장 분위기 파악
        - 투자 판단 전 배경 정보 제공
        - 텔레그램 헤더: 📰 [브리핑봇]
        """
    )

    st.subheader("📊 스톡시그널봇")
    st.markdown(
        """
        스톡시그널봇은 KOSPI 200 종목의 기관·외국인 수급을 분석해
        관심 종목을 탐지하고 검증하는 수급 기반 관찰 도구입니다.

        - 수급파워, 단기수급가속, long_flow_score 분석
        - 차트, OBV, 실적 발표 이벤트, DART 공시 플래그로 해석 보강
        - BUY / WATCH / 관심PASS 분류
        - D+N 수익률 검증
        - 텔레그램 헤더: 📊 [시그널봇]
        """
    )

    st.subheader("공통 주의사항")
    st.markdown(
        """
        - 이 시스템은 투자 추천이나 수익 보장 도구가 아닙니다.
        - 매수·매도 결정은 사용자가 최종 판단해야 합니다.
        - 매일 검증 리포트는 학습과 관찰용입니다.
        - D+1, D+3, D+5 같은 단기 결과만으로 공식이나 필터를 바꾸지 않습니다.
        - 충분한 데이터와 반복 패턴이 확인될 때만 시스템 변경을 검토합니다.
        """
    )

    st.success("현재 운영 원칙: KOSPI 200 중심 운용, v0.2 점수 체계 유지, 코스닥 확장 보류")
