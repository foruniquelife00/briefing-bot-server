import streamlit as st
import sqlite3
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
from datetime import datetime, timezone, timedelta
import sys
sys.path.append("/root/briefing-bot")
from watchlist import STOCK_MAP, load_watchlist
from eco_calendar import get_this_week_events

st.set_page_config(page_title="투자 브리핑 대시보드", page_icon="📊", layout="wide")

st.markdown("""
<style>
.block-container{padding-top:0.5rem;padding-bottom:0}
div[data-testid="metric-container"]{padding:3px 6px}
div[data-testid="metric-container"] label{font-size:11px!important}
div[data-testid="metric-container"] div{font-size:15px!important}
h3{font-size:15px!important;margin:2px 0!important}
.stExpander{margin:1px 0}
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

hc1, hc2 = st.columns([5,1])
with hc1:
    st.markdown("### 📊 투자 브리핑 대시보드")
    st.caption(f"업데이트: {now.strftime('%Y.%m.%d %H:%M')} KST")
with hc2:
    if st.button("🔄 전체갱신"):
        st.cache_data.clear()
        st.rerun()

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🌍 시장현황","📋 워치리스트","📰 브리핑히스토리",
    "📐 신뢰도트렌드","💼 포트폴리오","⭐ 성과추적","🔬 백테스팅","🏠 부동산"
])

@st.cache_data(ttl=300)
def get_indices():
    tickers = {"S&P500":"^GSPC","NASDAQ":"^IXIC","DOW":"^DJI","니케이":"^N225","코스피":"^KS11","코스닥":"^KQ11"}
    result = {}
    for name, ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            prev = t.fast_info.regular_market_previous_close
            rate = (price - prev) / prev * 100
            result[name] = {"price": price, "rate": rate}
        except:
            result[name] = {"price": 0, "rate": 0}
    return result

@st.cache_data(ttl=300)
def get_macro():
    data = {}
    try:
        data["usd"] = yf.Ticker("USDKRW=X").fast_info.last_price
        data["vix"] = yf.Ticker("^VIX").fast_info.last_price
        data["us10y"] = yf.Ticker("^TNX").fast_info.last_price
        res = requests.get("https://api.alternative.me/fng/", timeout=5)
        fgi = res.json()
        data["fgi"] = int(fgi["data"][0]["value"])
        data["fgi_label"] = fgi["data"][0]["value_classification"]
    except:
        pass
    return data

@st.cache_data(ttl=300)
def get_commodity():
    tickers = {"WTI유":"CL=F","금":"GC=F","은":"SI=F","브렌트":"BZ=F"}
    result = {}
    for name, ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            prev = t.fast_info.regular_market_previous_close
            rate = (price - prev) / prev * 100
            result[name] = {"price": price, "rate": rate}
        except:
            pass
    return result

@st.cache_data(ttl=180)
def get_wl_prices():
    watchlist = load_watchlist()
    rows = []
    for name in watchlist:
        ticker = STOCK_MAP.get(name)
        if not ticker:
            continue
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = info.last_price
            prev = info.regular_market_previous_close
            rate = (price - prev) / prev * 100
            high52 = info.year_high
            low52 = info.year_low
            is_kr = ticker.endswith((".KS",".KQ"))
            fmt = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
            pos52 = (price-low52)/(high52-low52)*100 if high52 != low52 else 50
            rows.append({
                "종목": name, "현재가": fmt(price), "등락률": f"{rate:+.2f}%",
                "52주고": fmt(high52), "52주저": fmt(low52), "위치": f"{pos52:.0f}%",
                "_rate": rate, "_pos52": pos52
            })
        except:
            pass
    return rows

# ── 탭1: 시장현황 ─────────────────────────────────
with tab1:
    t1h, t1r = st.columns([5,1])
    with t1r:
        if st.button("🔄 갱신", key="t1r"):
            st.cache_data.clear(); st.rerun()

    indices = get_indices()
    cols = st.columns(6)
    for i, (name, d) in enumerate(indices.items()):
        with cols[i]:
            st.metric(name, f"{d['price']:,.2f}",
                f"{'▲' if d['rate']>=0 else '▼'} {d['rate']:+.2f}%")

    st.divider()
    left, right = st.columns([3,2])

    with left:
        chart_sel = st.selectbox("차트", ["^GSPC","^IXIC","^KS11","^KQ11"],
            format_func=lambda x: {"^GSPC":"S&P500","^IXIC":"NASDAQ","^KS11":"코스피","^KQ11":"코스닥"}.get(x,x),
            key="t1chart")
        try:
            hist = yf.Ticker(chart_sel).history(period="1mo")
            fig = go.Figure(go.Candlestick(
                x=hist.index, open=hist["Open"], high=hist["High"],
                low=hist["Low"], close=hist["Close"],
                increasing_line_color="#68d391", decreasing_line_color="#fc8181"))
            fig.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis_rangeslider_visible=False,
                xaxis=dict(gridcolor="#2d3748"), yaxis=dict(gridcolor="#2d3748"))
            st.plotly_chart(fig, use_container_width=True)
        except:
            st.info("차트 로딩 중...")

        macro = get_macro()
        mc1,mc2,mc3,mc4 = st.columns(4)
        mc1.metric("원/달러", f"{macro.get('usd',0):,.0f}원")
        mc2.metric("VIX", f"{macro.get('vix',0):.1f}")
        mc3.metric("미10년물", f"{macro.get('us10y',0):.2f}%")
        fgi = macro.get("fgi", 0)
        fgi_icon = "🟢" if fgi>50 else "🔴" if fgi<25 else "🟡"
        mc4.metric("공포탐욕", f"{fgi_icon}{fgi}", macro.get("fgi_label",""))

    with right:
        st.markdown("**🌅 프리마켓**")
        pre_tickers = {"엔비디아":"NVDA","애플":"AAPL","테슬라":"TSLA","MS":"MSFT"}
        pc = st.columns(4)
        for i, (name, ticker) in enumerate(pre_tickers.items()):
            try:
                info = yf.Ticker(ticker).info
                pre = info.get("preMarketPrice")
                reg = info.get("regularMarketPrice")
                if pre and reg:
                    rate = (pre-reg)/reg*100
                    with pc[i]:
                        st.metric(name, f"${pre:.1f}", f"{rate:+.1f}%")
            except:
                pass

        st.divider()
        st.markdown("**🛢️ 원자재**")
        com = get_commodity()
        cc = st.columns(4)
        for i, (name, d) in enumerate(com.items()):
            with cc[i]:
                st.metric(name, f"${d['price']:.1f}", f"{d['rate']:+.1f}%")

        st.divider()
        st.markdown("**📅 경제 캘린더**")
        try:
            cal = get_this_week_events()
            st.text(cal[:300] if cal else "데이터 없음")
        except:
            st.caption("로딩 중...")

# ── 탭2: 워치리스트 ───────────────────────────────
with tab2:
    wh1, wh2 = st.columns([5,1])
    with wh2:
        if st.button("🔄 갱신", key="t2r"):
            st.cache_data.clear(); st.rerun()

    from ai_watchlist import load_ai_watchlist_full
    ai_data = load_ai_watchlist_full()
    ai_stocks = ai_data.get("stocks", [])

    st.markdown("### 🤖 AI 선정 워치리스트")
    ah1, ah2 = st.columns([4,1])
    with ah1:
        if ai_data.get("weekly_theme"):
            st.caption(f"📌 {ai_data['weekly_theme']}")
        if ai_data.get("risk_warning"):
            st.caption(f"⚠️ {ai_data['risk_warning']}")
    with ah2:
        st.caption(f"갱신: {ai_data.get('updated_at','')}")
        if st.button("🔄 AI갱신", key="ai_ref"):
            with st.spinner("갱신 중..."):
                from ai_watchlist import update_ai_watchlist
                update_ai_watchlist()
                st.cache_data.clear(); st.rerun()

    ff1, ff2 = st.columns(2)
    with ff1:
        style_f = st.selectbox("스타일", ["전체","모멘텀","안정","역발상","성장","배당"], key="ai_sf")
    with ff2:
        sec_list = sorted(set([s.get("sector","기타") for s in ai_stocks if isinstance(s,dict)]))
        sec_f = st.selectbox("섹터", ["전체"]+sec_list, key="ai_sec")

    filtered = [s for s in ai_stocks if isinstance(s,dict)
        and (style_f=="전체" or s.get("style")==style_f)
        and (sec_f=="전체" or s.get("sector")==sec_f)]

    imap = {"모멘텀":"🔴","성장":"🟠","역발상":"🟣","안정":"🟢","배당":"🔵"}
    if filtered:
        cols5 = st.columns(5)
        for i, s in enumerate(filtered[:5]):
            with cols5[i]:
                name = s.get("name","")
                sector = s.get("sector","")
                style = s.get("style","")
                reason = s.get("reason","")[:18]
                icon = imap.get(style,"⚪")
                st.markdown(
                    f"<div style='background:#1e2a3a;border-radius:6px;padding:5px;font-size:12px'>"
                    f"<b>{name}</b><br>"
                    f"<span style='color:#90cdf4'>{sector} {icon}</span><br>"
                    f"<span style='color:#cbd5e0;font-size:11px'>{reason}</span>"
                    f"</div>",
                    unsafe_allow_html=True)

        if len(filtered) > 5:
            with st.expander(f"나머지 {len(filtered)-5}개"):
                rest_items = []
                for s in filtered[5:]:
                    if isinstance(s,dict):
                        nm = s.get("name","")
                        tk = STOCK_MAP.get(nm,"").replace(".KS","").replace(".KQ","")
                        rest_items.append(f"{nm}({tk})")
                st.caption(" · ".join(rest_items))

    st.divider()

    with st.expander("📊 상승/하락 TOP3 & 전체 시세", expanded=False):
        sort_by = st.selectbox("정렬", ["등락률↑","등락률↓","종목명"], key="wl_sort")
        wl_data = get_wl_prices()
        if wl_data:
            if sort_by=="등락률↑":   wl_data.sort(key=lambda x: x["_rate"], reverse=True)
            elif sort_by=="등락률↓": wl_data.sort(key=lambda x: x["_rate"])
            else:                     wl_data.sort(key=lambda x: x["종목"])
            uc, dc = st.columns(2)
            with uc:
                st.caption("🚀 상승 TOP3")
                for r in wl_data[:3]:
                    st.success(f"{r['종목']}: {r['현재가']} ({r['등락률']})")
            with dc:
                st.caption("📉 하락 TOP3")
                for r in sorted(wl_data, key=lambda x: x["_rate"])[:3]:
                    st.error(f"{r['종목']}: {r['현재가']} ({r['등락률']})")
            st.dataframe(pd.DataFrame(wl_data).drop(columns=["_rate","_pos52"]),
                use_container_width=True, hide_index=True, height=250)

    with st.expander("⚙️ 워치리스트 관리", expanded=False):
        ca, cb = st.columns(2)
        with ca:
            ns = st.text_input("추가할 종목", key="wl_add")
            if st.button("➕ 추가", key="wl_add_btn"):
                if ns:
                    from watchlist import add_stock
                    r = add_stock(ns.strip())
                    st.success(r) if "✅" in r else st.error(r)
                    st.cache_data.clear()
        with cb:
            ds = st.text_input("삭제할 종목", key="wl_del")
            if st.button("➖ 삭제", key="wl_del_btn"):
                if ds:
                    from watchlist import remove_stock
                    r = remove_stock(ds.strip())
                    st.success(r) if "✅" in r else st.error(r)
                    st.cache_data.clear()

# ── 탭3: 브리핑 히스토리 ─────────────────────────
with tab3:
    t3h, t3r = st.columns([5,1])
    with t3r:
        if st.button("🔄 갱신", key="t3r"):
            st.cache_data.clear(); st.rerun()
    try:
        conn = sqlite3.connect("/root/briefing-bot/performance.db")
        recs = pd.read_sql(
            "SELECT date, stock_name, ticker, buy_price, target_price, stop_loss FROM recommendations ORDER BY date DESC LIMIT 30",
            conn)
        conn.close()
        if recs.empty:
            st.info("브리핑 기록 없음")
        else:
            dates = recs["date"].unique().tolist()
            sel = st.selectbox("날짜", dates, key="t3date")
            row = recs[recs["date"]==sel].iloc[0]
            is_kr = row["ticker"].endswith((".KS",".KQ"))
            fmt = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
            try:
                cur = yf.Ticker(row["ticker"]).fast_info.last_price
                rate = (cur - row["buy_price"]) / row["buy_price"] * 100
                cur_str = fmt(cur); rate_str = f"{rate:+.2f}%"
            except:
                cur_str = rate_str = "N/A"
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("종목", row["stock_name"])
            c2.metric("매수가", fmt(row["buy_price"]))
            c3.metric("현재가", cur_str, rate_str)
            c4.metric("목표가", fmt(row["target_price"]))
            st.caption(f"손절가: {fmt(row['stop_loss'])}")
    except Exception as e:
        st.error(f"오류: {e}")

# ── 탭4: 신뢰도 트렌드 ───────────────────────────
with tab4:
    t4h, t4r = st.columns([5,1])
    with t4r:
        if st.button("🔄 갱신", key="t4r"):
            st.cache_data.clear(); st.rerun()
    try:
        conn = sqlite3.connect("/root/briefing-bot/performance.db")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        hist_df = pd.read_sql(
            "SELECT date, weekday, trust_score, recommended, fgi_score, kospi, sp500 FROM briefing_history ORDER BY date ASC",
            conn) if "briefing_history" in tables else pd.DataFrame()
        bt_df = pd.read_sql(
            "SELECT run_date, win_rate, avg_rate FROM backtest_summary ORDER BY run_date ASC",
            conn) if "backtest_summary" in tables else pd.DataFrame()
        conn.close()

        if hist_df.empty:
            st.info("데이터 누적 중...")
        else:
            avg_t = hist_df["trust_score"].mean()
            max_t = hist_df["trust_score"].max()
            min_t = hist_df["trust_score"].min()
            trend = hist_df["trust_score"].iloc[-1] - hist_df["trust_score"].iloc[0] if len(hist_df)>1 else 0
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("평균", f"{avg_t:.0f}/100")
            c2.metric("최고", f"{max_t}/100")
            c3.metric("최저", f"{min_t}/100")
            c4.metric("트렌드", f"{trend:+.0f}점")

            lc, rc = st.columns(2)
            with lc:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=hist_df["date"], y=hist_df["trust_score"],
                    mode="lines+markers", line=dict(color="#63b3ed",width=2)))
                fig.add_hline(y=80, line_dash="dash", line_color="#68d391", annotation_text="우수")
                fig.add_hline(y=60, line_dash="dash", line_color="#f6e05e", annotation_text="양호")
                fig.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(range=[0,100],gridcolor="#2d3748"),
                    xaxis=dict(gridcolor="#2d3748"), title="신뢰도 추이")
                st.plotly_chart(fig, use_container_width=True)
            with rc:
                def grade(s):
                    return "🟢 우수" if s>=80 else "🟡 양호" if s>=60 else "🔴 주의"
                hist_df["등급"] = hist_df["trust_score"].apply(grade)
                gc = hist_df["등급"].value_counts()
                fig2 = px.pie(values=gc.values, names=gc.index, title="등급 분포",
                    color_discrete_map={"🟢 우수":"#68d391","🟡 양호":"#f6e05e","🔴 주의":"#fc8181"})
                fig2.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0), paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig2, use_container_width=True)

            st.dataframe(
                hist_df[["date","weekday","trust_score","등급","recommended","fgi_score"]].sort_values("date",ascending=False),
                use_container_width=True, hide_index=True, height=180)
    except Exception as e:
        st.error(f"오류: {e}")

# ── 탭5: 포트폴리오 ──────────────────────────────
with tab5:
    t5h, t5r = st.columns([5,1])
    with t5r:
        if st.button("🔄 갱신", key="t5r"):
            st.cache_data.clear(); st.rerun()

    with st.expander("⚙️ 종목 추가/삭제", expanded=False):
        pa, pb, pc_, pd_ = st.columns([2,1,2,1])
        with pa:
            pname = st.text_input("종목명", key="pf_nm", placeholder="삼성전자")
        with pb:
            pqty = st.number_input("수량", min_value=0.0, value=1.0, step=1.0, key="pf_qty")
        with pc_:
            pprice = st.number_input("매수가", min_value=0.0, value=0.0, step=100.0, key="pf_price")
        with pd_:
            st.write("")
            st.write("")
            if st.button("➕ 추가", key="pf_add"):
                if pname and pprice > 0:
                    from portfolio import add_portfolio
                    r = add_portfolio(pname.strip(), pqty, pprice)
                    st.success(r) if "✅" in r else st.error(r)
                    st.cache_data.clear(); st.rerun()

        pe, pf_ = st.columns([3,1])
        with pe:
            del_nm = st.text_input("삭제할 종목", key="pf_del")
        with pf_:
            st.write("")
            st.write("")
            if st.button("➖ 삭제", key="pf_del_btn"):
                if del_nm:
                    from portfolio import remove_portfolio
                    r = remove_portfolio(del_nm.strip())
                    st.success(r) if "✅" in r else st.error(r)
                    st.cache_data.clear(); st.rerun()

    @st.cache_data(ttl=180)
    def get_pf():
        from portfolio import get_portfolio_data
        return get_portfolio_data()

    pf = get_pf()
    if not pf:
        st.info("포트폴리오가 비어있어요. 위에서 추가해보세요!")
    else:
        ti = sum(d["_invest"] for d in pf)
        tc = sum(d["_cur_val"] for d in pf)
        tp = tc - ti
        tr = (tc-ti)/ti*100
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("총 투자", f"{int(ti):,}원")
        c2.metric("평가액",  f"{int(tc):,}원")
        c3.metric("수익률",  f"{tr:+.2f}%")
        c4.metric("손익",    f"{int(tp):+,}원")

        lc, rc = st.columns(2)
        with lc:
            df = pd.DataFrame(pf)
            fig = px.bar(df, x="종목", y="_rate", color="_rate",
                color_continuous_scale=["#fc8181","#68d391"],
                labels={"_rate":"수익률(%)"}, title="종목별 수익률")
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(height=220, margin=dict(l=0,r=0,t=20,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        with rc:
            fig2 = px.pie(df, values="_cur_val", names="종목", title="포트폴리오 비중")
            fig2.update_layout(height=220, margin=dict(l=0,r=0,t=20,b=0), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(pd.DataFrame(pf).drop(columns=["_rate","_invest","_cur_val"]),
            use_container_width=True, hide_index=True, height=200)

# ── 탭6: 성과 추적 ────────────────────────────────
with tab6:
    t6h, t6r = st.columns([5,1])
    with t6r:
        if st.button("🔄 갱신", key="t6r"):
            st.cache_data.clear(); st.rerun()
    try:
        conn = sqlite3.connect("/root/briefing-bot/performance.db")
        df = pd.read_sql(
            "SELECT date, stock_name, ticker, buy_price, target_price, stop_loss FROM recommendations ORDER BY date DESC LIMIT 30",
            conn)
        conn.close()
        if df.empty:
            st.info("추천 종목 기록 없음")
        else:
            @st.cache_data(ttl=300)
            def get_prices_t6(tickers):
                prices = {}
                for t in tickers:
                    try: prices[t] = yf.Ticker(t).fast_info.last_price
                    except: prices[t] = None
                return prices

            prices = get_prices_t6(tuple(df["ticker"].unique()))
            rows = []
            for _, row in df.iterrows():
                cur = prices.get(row["ticker"])
                if cur is None: continue
                rate = (cur - row["buy_price"]) / row["buy_price"] * 100
                is_kr = row["ticker"].endswith((".KS",".KQ"))
                fmt = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
                if cur >= row["target_price"]: status = "🎯 목표"
                elif cur <= row["stop_loss"]: status = "🛑 손절"
                elif rate >= 0: status = "✅ 수익"
                else: status = "⚠️ 손실"
                rows.append({"날짜":row["date"],"종목":row["stock_name"],"매수가":fmt(row["buy_price"]),
                    "현재가":fmt(cur),"수익률":f"{rate:+.2f}%","목표가":fmt(row["target_price"]),
                    "손절가":fmt(row["stop_loss"]),"상태":status,"_rate":rate})

            if rows:
                avg = sum(r["_rate"] for r in rows)/len(rows)
                wins = sum(1 for r in rows if r["_rate"]>0)
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("평균 수익률", f"{avg:+.2f}%")
                c2.metric("승률", f"{wins/len(rows)*100:.0f}%")
                c3.metric("총 추천", f"{len(rows)}건")
                c4.metric("목표 달성", f"{sum(1 for r in rows if '목표' in r['상태'])}건")

                cdf = pd.DataFrame(rows)
                fig = px.bar(cdf, x="날짜", y="_rate", color="_rate",
                    color_continuous_scale=["#fc8181","#68d391"], title="수익률")
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                fig.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(cdf.drop(columns=["_rate"]),
                    use_container_width=True, hide_index=True, height=200)
    except Exception as e:
        st.error(f"오류: {e}")

# ── 탭7: 백테스팅 ────────────────────────────────
with tab7:
    t7h, t7r = st.columns([5,1])
    with t7r:
        if st.button("🔄 갱신", key="t7r"):
            st.cache_data.clear(); st.rerun()

    if st.button("🔬 백테스팅 실행"):
        with st.spinner("분석 중..."):
            from backtest import run_backtest, save_backtest_to_db
            bt = run_backtest()
            save_backtest_to_db(bt)
            st.session_state["bt"] = bt

    bt = st.session_state.get("bt")
    if not bt:
        from backtest import run_backtest
        bt = run_backtest()
        st.session_state["bt"] = bt

    if "error" in bt:
        st.info(bt["error"])
    else:
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("총 추천",     f"{bt['total']}건")
        c2.metric("평균 수익률", f"{bt['avg_rate']:+.2f}%")
        c3.metric("승률",        f"{bt['win_rate']:.0f}%")
        c4.metric("목표 달성",   f"{bt['target_hits']}건")
        c5.metric("손절 발생",   f"{bt['stop_hits']}건")

        lc, rc = st.columns(2)
        with lc:
            df = pd.DataFrame(bt["results"])
            fig = px.bar(df, x="date", y="rate", color="rate",
                color_continuous_scale=["#fc8181","#68d391"], title="수익률")
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        with rc:
            oc = pd.DataFrame(bt["results"])["outcome"].value_counts()
            fig2 = px.pie(values=oc.values, names=oc.index, title="결과 분포",
                color_discrete_map={"목표달성":"#68d391","수익중":"#63b3ed","손실중":"#fc8181","손절":"#fc4141"})
            fig2.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(pd.DataFrame([{
            "날짜":r["date"],"종목":r["name"],"매수가":r["buy_str"],
            "현재가":r["current_str"],"수익률":f"{r['rate']:+.2f}%",
            "결과":f"{r['outcome_icon']} {r['outcome']}","보유일":f"{r['hold_days']}일"
        } for r in bt["results"]]), use_container_width=True, hide_index=True, height=200)

# ── 탭8: 부동산 ──────────────────────────────────
with tab8:
    t8h, t8r = st.columns([5,1])
    with t8r:
        if st.button("🔄 갱신", key="t8r"):
            st.cache_data.clear(); st.rerun()

    metro_codes = {
        "서울": ["11110","11140","11170","11200","11215","11230","11260","11290","11305","11320","11350","11380","11410","11440","11470","11500","11530","11545","11560","11590","11620","11650","11680","11710","11740"],
        "부산": ["26110","26140","26170","26200","26230","26260","26290","26320","26350","26380","26410","26440","26470","26500","26530"],
        "대구": ["27110","27140","27170","27200","27230","27260","27290","27710"],
        "대전": ["30110","30140","30170","30200","30230"],
        "울산": ["31110","31140","31170","31200","31710"],
    }
    try:
        conn = sqlite3.connect("/root/realestate-bot/realestate.db")
        sel = st.selectbox("광역시", list(metro_codes.keys()), key="re_sel")
        codes = metro_codes[sel]
        ph = ",".join("?"*len(codes))

        lc, rc = st.columns(2)
        with lc:
            top10 = pd.read_sql(f"""
                SELECT apt_name, dong, area, floor, deal_amount, deal_date, is_high
                FROM trades WHERE lawd_cd IN ({ph})
                ORDER BY deal_amount DESC LIMIT 10
            """, conn, params=codes)
            if not top10.empty:
                avg = top10["deal_amount"].mean()
                st.metric(f"{sel} Top10 평균", f"{int(avg//10000)}억 {int(avg%10000):,}만원")
                top10["거래금액"] = top10["deal_amount"].apply(
                    lambda x: f"{x//10000}억 {x%10000:,}만원" if x>=10000 else f"{x:,}만원")
                top10["신고가"] = top10["is_high"].apply(lambda x: "🔥" if x else "")
                st.dataframe(top10[["apt_name","dong","area","floor","거래금액","deal_date","신고가"]].rename(
                    columns={"apt_name":"아파트","dong":"동","area":"면적","floor":"층","deal_date":"거래일"}),
                    use_container_width=True, hide_index=True, height=300)
        with rc:
            monthly = pd.read_sql(f"""
                SELECT substr(deal_date,1,7) as month, AVG(deal_amount) as avg_price
                FROM trades WHERE lawd_cd IN ({ph})
                GROUP BY month ORDER BY month DESC LIMIT 12
            """, conn, params=codes)
            if not monthly.empty:
                monthly = monthly.iloc[::-1]
                fig = px.bar(monthly, x="month", y="avg_price", title=f"{sel} 월별 평균",
                    color="avg_price", color_continuous_scale=["#3B8BD4","#E8593C"])
                fig.update_layout(height=300, margin=dict(l=0,r=0,t=20,b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)
        conn.close()
    except Exception as e:
        st.error(f"부동산 오류: {e}")
