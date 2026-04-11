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

st.set_page_config(
    page_title="투자 브리핑 대시보드",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
<style>
.up   { color: #68d391; font-weight: 700; }
.down { color: #fc8181; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

st.title("📊 투자 브리핑 대시보드")
st.caption(f"마지막 업데이트: {now.strftime('%Y.%m.%d %H:%M')} KST")

# ── 탭 구성 (사고 흐름 순서) ─────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🌍 시장 현황",
    "📋 워치리스트",
    "📰 브리핑 히스토리",
    "📐 신뢰도 트렌드",
    "💼 포트폴리오",
    "⭐ 성과 추적",
    "🔬 백테스팅",
    "🏠 부동산",
])

# ── 공통 데이터 캐시 ─────────────────────────────
@st.cache_data(ttl=300)
def get_indices():
    tickers = {
        "S&P 500": "^GSPC", "NASDAQ": "^IXIC",
        "DOW": "^DJI", "니케이": "^N225",
        "코스피": "^KS11", "코스닥": "^KQ11",
    }
    results = {}
    for name, ticker in tickers.items():
        try:
            t     = yf.Ticker(ticker)
            price = t.fast_info.last_price
            prev  = t.fast_info.regular_market_previous_close
            rate  = (price - prev) / prev * 100
            results[name] = {"price": price, "rate": rate}
        except:
            results[name] = {"price": 0, "rate": 0}
    return results

@st.cache_data(ttl=300)
def get_premarket():
    targets = {
        "S&P500 선물": "^GSPC", "나스닥 선물": "^IXIC",
        "엔비디아": "NVDA", "애플": "AAPL", "테슬라": "TSLA",
    }
    results = {}
    for name, ticker in targets.items():
        try:
            info = yf.Ticker(ticker).info
            pre  = info.get("preMarketPrice")
            reg  = info.get("regularMarketPrice")
            chg  = info.get("preMarketChangePercent")
            if pre and reg:
                rate = chg * 100 if chg else (pre - reg) / reg * 100
                results[name] = {"pre": pre, "reg": reg, "rate": rate}
        except:
            pass
    return results

@st.cache_data(ttl=300)
def get_commodity():
    targets = {"WTI유가": "CL=F", "브렌트유": "BZ=F", "금": "GC=F", "은": "SI=F"}
    results = {}
    for name, ticker in targets.items():
        try:
            t     = yf.Ticker(ticker)
            price = t.fast_info.last_price
            prev  = t.fast_info.regular_market_previous_close
            rate  = (price - prev) / prev * 100
            results[name] = {"price": price, "rate": rate}
        except:
            pass
    return results

@st.cache_data(ttl=180)
def get_wl_prices():
    watchlist = load_watchlist()
    rows = []
    for name in watchlist:
        ticker = STOCK_MAP.get(name)
        if not ticker:
            continue
        try:
            t      = yf.Ticker(ticker)
            info   = t.fast_info
            price  = info.last_price
            prev   = info.regular_market_previous_close
            rate   = (price - prev) / prev * 100
            high52 = info.year_high
            low52  = info.year_low
            is_kr  = ticker.endswith(".KS") or ticker.endswith(".KQ")
            fmt    = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
            pos52  = (price - low52) / (high52 - low52) * 100 if high52 != low52 else 50
            rows.append({
                "종목": name, "현재가": fmt(price),
                "등락률": f"{rate:+.2f}%",
                "52주 고가": fmt(high52), "52주 저가": fmt(low52),
                "52주 위치": f"{pos52:.0f}%",
                "_rate": rate, "_pos52": pos52,
            })
        except:
            pass
    return rows


# ── 탭1: 시장 현황 ────────────────────────────────
with tab1:
    indices = get_indices()
    st.subheader("주요 지수")
    cols = st.columns(6)
    for i, (name, data) in enumerate(indices.items()):
        with cols[i]:
            st.metric(
                label=name,
                value=f"{data['price']:,.2f}",
                delta=f"{'▲' if data['rate'] >= 0 else '▼'} {data['rate']:+.2f}%",
            )

    st.divider()

    # 캔들 차트
    st.subheader("지수 추이 (1개월)")
    chart_ticker = st.selectbox("차트 종목", ["^GSPC","^IXIC","^KS11","^KQ11","^N225"],
        format_func=lambda x: {"^GSPC":"S&P 500","^IXIC":"NASDAQ",
                                "^KS11":"코스피","^KQ11":"코스닥","^N225":"니케이"}.get(x,x))
    try:
        hist = yf.Ticker(chart_ticker).history(period="1mo")
        fig  = go.Figure(go.Candlestick(
            x=hist.index,
            open=hist["Open"], high=hist["High"],
            low=hist["Low"],   close=hist["Close"],
            increasing_line_color="#68d391",
            decreasing_line_color="#fc8181",
        ))
        fig.update_layout(height=350, margin=dict(l=0,r=0,t=0,b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis_rangeslider_visible=False,
            xaxis=dict(gridcolor="#2d3748"), yaxis=dict(gridcolor="#2d3748"))
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"차트 오류: {e}")

    st.divider()
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("환율 · 공포탐욕")
        try:
            usd = yf.Ticker("USDKRW=X").fast_info.last_price
            st.metric("원/달러", f"{usd:,.2f}원")
        except:
            st.metric("원/달러", "N/A")
        try:
            res    = requests.get("https://api.alternative.me/fng/", timeout=5)
            fgi    = res.json()
            score  = int(fgi["data"][0]["value"])
            rating = fgi["data"][0]["value_classification"]
            icon   = "🟢" if score > 50 else "🔴" if score < 25 else "🟡"
            st.metric("공포탐욕지수", f"{icon} {score}", delta=rating)
        except:
            st.metric("공포탐욕지수", "N/A")

    with col2:
        st.subheader("🌅 프리마켓")
        pre = get_premarket()
        for name, d in pre.items():
            st.metric(name, f"${d['pre']:,.2f}",
                delta=f"{'▲' if d['rate'] >= 0 else '▼'} {d['rate']:+.2f}%")

    with col3:
        st.subheader("🛢️ 원자재")
        com = get_commodity()
        for name, d in com.items():
            st.metric(name, f"${d['price']:,.2f}",
                delta=f"{'▲' if d['rate'] >= 0 else '▼'} {d['rate']:+.2f}%")

    st.divider()
    st.subheader("📅 이번 주 경제 캘린더")
    st.text(get_this_week_events())


# ── 탭2: 워치리스트 ───────────────────────────────
with tab2:
    st.subheader("워치리스트 실시간 시세")

    # 종목 추가/삭제 UI
    with st.expander("⚙️ 워치리스트 관리", expanded=False):
        col_a, col_b, col_c = st.columns([2,1,1])
        with col_a:
            new_stock = st.text_input("종목명 입력", placeholder="예: 삼성전자")
        with col_b:
            if st.button("➕ 추가"):
                if new_stock:
                    from watchlist import add_stock
                    result = add_stock(new_stock.strip())
                    if "✅" in result:
                        st.success(result)
                        st.cache_data.clear()
                    else:
                        st.error(result)
        with col_c:
            del_stock = st.text_input("삭제할 종목명", placeholder="예: 카카오")
            if st.button("➖ 삭제"):
                if del_stock:
                    from watchlist import remove_stock
                    result = remove_stock(del_stock.strip())
                    if "✅" in result:
                        st.success(result)
                        st.cache_data.clear()
                    else:
                        st.error(result)

        # AI 워치리스트 현황
        st.divider()
        from ai_watchlist import load_ai_watchlist_full, load_user_watchlist
        ai_data   = load_ai_watchlist_full()
        ai_list   = [s["name"] if isinstance(s, dict) else s for s in ai_data.get("stocks", [])]
        user_list = load_user_watchlist()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🤖 AI 선정",   f"{len(ai_list)}개")
        c2.metric("👤 개인 목록", f"{len(user_list)}개")
        c3.metric("📊 통합",      f"{len(ai_list)+len(user_list)}개")
        c4.metric("🔄 업데이트",  ai_data.get("updated_at", "미갱신"))

        if ai_data.get("weekly_theme"):
            st.info(f"📌 이번 주 테마: {ai_data['weekly_theme']}")

        if ai_data.get("sector_focus"):
            st.caption(f"주목 섹터: {' · '.join(ai_data['sector_focus'])}")

        if ai_data.get("risk_warning"):
            st.warning(f"⚠️ {ai_data['risk_warning']}")

        # 종목별 태그 표시
        if ai_data.get("stocks"):
            st.divider()
            st.markdown("**🤖 AI 선정 종목**")

            col_f1, col_f2 = st.columns([2,1])
            with col_f1:
                style_filter = st.selectbox(
                    "스타일 필터",
                    ["전체", "모멘텀", "안정", "역발상", "성장", "배당"],
                    key="ai_style_filter"
                )
            with col_f2:
                sector_list = list(set([
                    s.get("sector","기타") for s in ai_data["stocks"]
                    if isinstance(s, dict)
                ]))
                sector_filter = st.selectbox(
                    "섹터 필터",
                    ["전체"] + sorted(sector_list),
                    key="ai_sector_filter"
                )

            filtered = [
                s for s in ai_data["stocks"]
                if isinstance(s, dict)
                and (style_filter == "전체" or s.get("style") == style_filter)
                and (sector_filter == "전체" or s.get("sector") == sector_filter)
            ]

            # TOP5 상세 표시
            st.markdown(f"**TOP 5 상세** (총 {len(filtered)}개)")
            for i, s in enumerate(filtered[:5]):
                name   = s.get("name", "")
                sector = s.get("sector", "기타")
                style  = s.get("style", "")
                reason = s.get("reason", "")

                style_color = {
                    "모멘텀": "🔴", "성장": "🟠", "역발상": "🟣",
                    "안정": "🟢", "배당": "🔵"
                }.get(style, "⚪")

                with st.container(border=True):
                    c1, c2, c3 = st.columns([3,2,4])
                    with c1:
                        st.markdown(f"### {i+1}. {name}")
                    with c2:
                        st.markdown(f"`{sector}`")
                        st.markdown(f"{style_color} **{style}**")
                    with c3:
                        st.markdown(f"💡 {reason}")

            # 나머지 종목 간략 표시
            if len(filtered) > 5:
                st.divider()
                st.markdown("**나머지 종목**")
                from watchlist import STOCK_MAP
                rest_text = "  ".join([
                    f"{s.get('name','')} `{STOCK_MAP.get(s.get('name',''), '')}`"
                    for s in filtered[5:]
                    if isinstance(s, dict)
                ])
                st.markdown(rest_text)
    with col2:
        sort_by = st.selectbox("정렬", ["등락률↑","등락률↓","종목명"])

    wl_data = get_wl_prices()
    if wl_data:
        if sort_by == "등락률↑":
            wl_data.sort(key=lambda x: x["_rate"], reverse=True)
        elif sort_by == "등락률↓":
            wl_data.sort(key=lambda x: x["_rate"])
        else:
            wl_data.sort(key=lambda x: x["종목"])

        top3 = wl_data[:3]
        bot3 = sorted(wl_data, key=lambda x: x["_rate"])[:3]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**🚀 상승 TOP 3**")
            for r in top3:
                st.success(f"{r['종목']}: {r['현재가']} ({r['등락률']})")
        with c2:
            st.markdown("**📉 하락 TOP 3**")
            for r in bot3:
                st.error(f"{r['종목']}: {r['현재가']} ({r['등락률']})")

        st.divider()
        st.dataframe(
            pd.DataFrame(wl_data).drop(columns=["_rate","_pos52"]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("워치리스트가 비어있어요.")


# ── 탭3: 브리핑 히스토리 ─────────────────────────
with tab3:
    st.subheader("📰 브리핑 히스토리")
    try:
        conn = sqlite3.connect("/root/briefing-bot/performance.db")
        recs = pd.read_sql("""
            SELECT date, stock_name, ticker, buy_price, target_price, stop_loss, created_at
            FROM recommendations ORDER BY date DESC LIMIT 50
        """, conn)
        conn.close()

        if recs.empty:
            st.info("브리핑 기록이 없어요.")
        else:
            dates = recs["date"].unique().tolist()
            selected_date = st.selectbox("날짜 선택", dates)
            row = recs[recs["date"] == selected_date].iloc[0]
            is_kr = row["ticker"].endswith(".KS") or row["ticker"].endswith(".KQ")
            fmt   = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"

            try:
                current = yf.Ticker(row["ticker"]).fast_info.last_price
                rate    = (current - row["buy_price"]) / row["buy_price"] * 100
                current_str = fmt(current)
                rate_str    = f"{rate:+.2f}%"
            except:
                current_str = "N/A"
                rate_str    = "N/A"

            st.markdown(f"### {selected_date} 추천 종목")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("종목",   row["stock_name"])
            c2.metric("매수가", fmt(row["buy_price"]))
            c3.metric("현재가", current_str, delta=rate_str)
            c4.metric("목표가", fmt(row["target_price"]))
            st.markdown(f"**손절가:** {fmt(row['stop_loss'])} | **기록 시각:** {row['created_at']}")
    except Exception as e:
        st.error(f"히스토리 오류: {e}")


# ── 탭4: 신뢰도 트렌드 ───────────────────────────
with tab4:
    st.subheader("📐 신뢰도 트렌드 분석")
    try:
        conn = sqlite3.connect("/root/briefing-bot/performance.db")
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]

        hist_df = pd.read_sql("""
            SELECT date, weekday, trust_score, recommended,
                   buy_price, fgi_score, kospi, sp500, usd_krw
            FROM briefing_history ORDER BY date ASC
        """, conn) if "briefing_history" in tables else pd.DataFrame()

        bt_df = pd.read_sql("""
            SELECT run_date, win_rate, avg_rate
            FROM backtest_summary ORDER BY run_date ASC
        """, conn) if "backtest_summary" in tables else pd.DataFrame()

        conn.close()

        if hist_df.empty:
            st.info("아직 브리핑 데이터가 없어요. 내일 09:30 브리핑 후 확인해보세요!")
        else:
            avg_trust = hist_df["trust_score"].mean()
            max_trust = hist_df["trust_score"].max()
            min_trust = hist_df["trust_score"].min()
            trend     = hist_df["trust_score"].iloc[-1] - hist_df["trust_score"].iloc[0] if len(hist_df) > 1 else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("평균 신뢰도", f"{avg_trust:.0f}/100")
            c2.metric("최고 신뢰도", f"{max_trust}/100")
            c3.metric("최저 신뢰도", f"{min_trust}/100")
            c4.metric("트렌드", f"{trend:+.0f}점",
                delta="↑ 개선" if trend > 0 else "↓ 하락" if trend < 0 else "→ 유지")

            st.divider()
            col1, col2 = st.columns(2)

            with col1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=hist_df["date"], y=hist_df["trust_score"],
                    mode="lines+markers", name="신뢰도",
                    line=dict(color="#63b3ed", width=2),
                    marker=dict(size=8),
                ))
                fig.add_hline(y=80, line_dash="dash", line_color="#68d391",
                    annotation_text="우수(80)")
                fig.add_hline(y=60, line_dash="dash", line_color="#f6e05e",
                    annotation_text="양호(60)")
                fig.update_layout(
                    title="일별 신뢰도 추이", height=300,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(gridcolor="#2d3748"),
                    yaxis=dict(gridcolor="#2d3748", range=[0,100]),
                    margin=dict(l=0,r=0,t=30,b=0),
                )
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                def grade(s):
                    if s >= 80: return "🟢 우수"
                    elif s >= 60: return "🟡 양호"
                    else: return "🔴 주의"
                hist_df["등급"] = hist_df["trust_score"].apply(grade)
                grade_counts = hist_df["등급"].value_counts()
                fig2 = px.pie(
                    values=grade_counts.values, names=grade_counts.index,
                    title="신뢰도 등급 분포",
                    color_discrete_map={
                        "🟢 우수": "#68d391",
                        "🟡 양호": "#f6e05e",
                        "🔴 주의": "#fc8181",
                    }
                )
                fig2.update_layout(height=300,
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig2, use_container_width=True)

            st.divider()
            col1, col2 = st.columns(2)

            with col1:
                if len(hist_df) > 2:
                    fig3 = px.scatter(
                        hist_df, x="fgi_score", y="trust_score",
                        title="공포탐욕 vs 신뢰도",
                        labels={"fgi_score":"공포탐욕지수","trust_score":"신뢰도"},
                        trendline="ols",
                        color="trust_score",
                        color_continuous_scale=["#fc8181","#68d391"],
                    )
                    fig3.update_layout(height=280,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        coloraxis_showscale=False,
                        margin=dict(l=0,r=0,t=30,b=0))
                    st.plotly_chart(fig3, use_container_width=True)
                else:
                    st.info("상관관계 분석은 3일 이상 데이터 필요")

            with col2:
                if not bt_df.empty:
                    fig4 = go.Figure()
                    fig4.add_trace(go.Scatter(
                        x=bt_df["run_date"], y=bt_df["win_rate"],
                        mode="lines+markers", name="승률(%)",
                        line=dict(color="#68d391"),
                    ))
                    fig4.add_trace(go.Scatter(
                        x=bt_df["run_date"], y=bt_df["avg_rate"],
                        mode="lines+markers", name="평균수익률(%)",
                        line=dict(color="#63b3ed"),
                    ))
                    fig4.update_layout(title="승률·수익률 추이", height=280,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=0,r=0,t=30,b=0))
                    st.plotly_chart(fig4, use_container_width=True)
                else:
                    st.info("백테스팅 데이터 누적 중...")

            st.divider()
            st.subheader("브리핑 히스토리")
            display_df = hist_df[[
                "date","weekday","trust_score","등급",
                "recommended","fgi_score","kospi","sp500"
            ]].rename(columns={
                "date":"날짜","weekday":"요일","trust_score":"신뢰도",
                "recommended":"추천종목","fgi_score":"공포탐욕",
                "kospi":"코스피","sp500":"S&P500",
            })
            st.dataframe(display_df.sort_values("날짜", ascending=False),
                use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"신뢰도 트렌드 오류: {e}")


# ── 탭5: 포트폴리오 ──────────────────────────────
with tab5:
    st.subheader("💼 포트폴리오 트래커")

    @st.cache_data(ttl=180)
    def get_pf_data():
        from portfolio import get_portfolio_data
        return get_portfolio_data()

    pf_data = get_pf_data()
    if not pf_data:
        st.info("포트폴리오가 비어있어요.\n텔레그램: /포트폴리오추가 종목명 수량 매수가")
    else:
        total_invest = sum(d["_invest"]  for d in pf_data)
        total_cur    = sum(d["_cur_val"] for d in pf_data)
        total_profit = total_cur - total_invest
        total_rate   = (total_cur - total_invest) / total_invest * 100

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투자금액", f"{int(total_invest):,}원")
        c2.metric("현재 평가액", f"{int(total_cur):,}원")
        c3.metric("총 수익률",   f"{total_rate:+.2f}%")
        c4.metric("총 손익",     f"{int(total_profit):+,}원")

        st.divider()
        col1, col2 = st.columns(2)

        with col1:
            df = pd.DataFrame(pf_data)
            fig = px.bar(df, x="종목", y="_rate",
                color="_rate",
                color_continuous_scale=["#fc8181","#68d391"],
                title="종목별 수익률",
                labels={"종목":"종목","_rate":"수익률(%)"},
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(height=300,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                coloraxis_showscale=False, margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig2 = px.pie(df, values="_cur_val", names="종목", title="포트폴리오 비중")
            fig2.update_layout(height=300,
                paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig2, use_container_width=True)

        st.divider()
        st.dataframe(
            pd.DataFrame(pf_data).drop(columns=["_rate","_invest","_cur_val"]),
            use_container_width=True, hide_index=True,
        )
        st.caption("텔레그램: /포트폴리오추가 종목명 수량 매수가 | /포트폴리오삭제 종목명")


# ── 탭6: 성과 추적 ────────────────────────────────
with tab6:
    st.subheader("추천 종목 성과 추적")
    try:
        conn = sqlite3.connect("/root/briefing-bot/performance.db")
        df   = pd.read_sql("""
            SELECT date, stock_name, ticker, buy_price, target_price, stop_loss
            FROM recommendations ORDER BY date DESC LIMIT 30
        """, conn)
        conn.close()

        if df.empty:
            st.info("아직 추천 종목 기록이 없어요.")
        else:
            @st.cache_data(ttl=300)
            def get_prices(tickers):
                prices = {}
                for t in tickers:
                    try:
                        prices[t] = yf.Ticker(t).fast_info.last_price
                    except:
                        prices[t] = None
                return prices

            prices = get_prices(tuple(df["ticker"].unique()))
            rows   = []
            for _, row in df.iterrows():
                current = prices.get(row["ticker"])
                if current is None:
                    continue
                rate  = (current - row["buy_price"]) / row["buy_price"] * 100
                is_kr = row["ticker"].endswith(".KS") or row["ticker"].endswith(".KQ")
                fmt   = lambda x: f"{int(x):,}원" if is_kr else f"${x:.2f}"
                if current >= row["target_price"]:   status = "🎯 목표 달성"
                elif current <= row["stop_loss"]:    status = "🛑 손절 터치"
                elif rate >= 0:                       status = "✅ 수익 중"
                else:                                 status = "⚠️ 손실 중"
                rows.append({
                    "날짜": row["date"], "종목": row["stock_name"],
                    "매수가": fmt(row["buy_price"]), "현재가": fmt(current),
                    "수익률": f"{rate:+.2f}%", "목표가": fmt(row["target_price"]),
                    "손절가": fmt(row["stop_loss"]), "상태": status, "_rate": rate,
                })

            if rows:
                avg_rate = sum(r["_rate"] for r in rows) / len(rows)
                wins     = sum(1 for r in rows if r["_rate"] > 0)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("평균 수익률", f"{avg_rate:+.2f}%")
                c2.metric("승률",        f"{wins/len(rows)*100:.0f}%")
                c3.metric("총 추천",     f"{len(rows)}건")
                c4.metric("목표 달성",   f"{sum(1 for r in rows if '목표' in r['상태'])}건")

                chart_df = pd.DataFrame(rows)
                fig = px.bar(chart_df, x="날짜", y="_rate", color="_rate",
                    color_continuous_scale=["#fc8181","#68d391"],
                    labels={"_rate":"수익률(%)"},
                    title="일별 추천 종목 수익률")
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                fig.update_layout(height=300,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False, margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(pd.DataFrame(rows).drop(columns=["_rate"]),
                    use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")


# ── 탭7: 백테스팅 ────────────────────────────────
with tab7:
    st.subheader("🔬 백테스팅 분석")
    if st.button("🔄 백테스팅 실행"):
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
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("총 추천",     f"{bt['total']}건")
        c2.metric("평균 수익률", f"{bt['avg_rate']:+.2f}%")
        c3.metric("승률",        f"{bt['win_rate']:.0f}%")
        c4.metric("목표 달성",   f"{bt['target_hits']}건")
        c5.metric("손절 발생",   f"{bt['stop_hits']}건")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            df = pd.DataFrame(bt["results"])
            fig = px.bar(df, x="date", y="rate", color="rate",
                color_continuous_scale=["#fc8181","#68d391"],
                title="날짜별 수익률",
                labels={"date":"날짜","rate":"수익률(%)"},
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(height=300,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                coloraxis_showscale=False, margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            outcome_counts = pd.DataFrame(bt["results"])["outcome"].value_counts()
            fig2 = px.pie(values=outcome_counts.values, names=outcome_counts.index,
                title="결과 분포",
                color_discrete_map={
                    "목표달성":"#68d391","수익중":"#63b3ed",
                    "손실중":"#fc8181","손절":"#fc4141",
                })
            fig2.update_layout(height=300,
                paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig2, use_container_width=True)

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("🇰🇷 국내 평균", f"{bt['kr_avg']:+.2f}%", f"{bt['kr_count']}건")
        c2.metric("🇺🇸 해외 평균", f"{bt['us_avg']:+.2f}%", f"{bt['us_count']}건")
        c3.metric("평균 보유",      f"{bt['avg_hold']:.0f}일")

        st.dataframe(pd.DataFrame([{
            "날짜": r["date"], "종목": r["name"],
            "매수가": r["buy_str"], "현재가": r["current_str"],
            "수익률": f"{r['rate']:+.2f}%", "목표가": r["target_str"],
            "손절가": r["stop_str"], "결과": f"{r['outcome_icon']} {r['outcome']}",
            "보유일": f"{r['hold_days']}일",
        } for r in bt["results"]]), use_container_width=True, hide_index=True)


# ── 탭8: 부동산 ──────────────────────────────────
with tab8:
    st.subheader("🏠 부동산 실거래가")
    metro_codes = {
        "서울": ["11110","11140","11170","11200","11215","11230","11260","11290",
                "11305","11320","11350","11380","11410","11440","11470","11500",
                "11530","11545","11560","11590","11620","11650","11680","11710","11740"],
        "부산": ["26110","26140","26170","26200","26230","26260","26290","26320",
                "26350","26380","26410","26440","26470","26500","26530"],
        "대구": ["27110","27140","27170","27200","27230","27260","27290","27710"],
        "대전": ["30110","30140","30170","30200","30230"],
        "울산": ["31110","31140","31170","31200","31710"],
    }
    try:
        conn     = sqlite3.connect("/root/realestate-bot/realestate.db")
        selected = st.selectbox("광역시 선택", list(metro_codes.keys()))
        codes    = metro_codes[selected]
        ph       = ",".join("?" * len(codes))

        col1, col2 = st.columns(2)
        with col1:
            top10 = pd.read_sql(f"""
                SELECT apt_name, dong, area, floor, deal_amount, deal_date, is_high
                FROM trades WHERE lawd_cd IN ({ph})
                ORDER BY deal_amount DESC LIMIT 10
            """, conn, params=codes)
            if not top10.empty:
                avg = top10["deal_amount"].mean()
                st.metric(f"{selected} Top10 평균",
                    f"{int(avg//10000)}억 {int(avg%10000):,}만원")
                top10["거래금액"] = top10["deal_amount"].apply(
                    lambda x: f"{x//10000}억 {x%10000:,}만원" if x >= 10000 else f"{x:,}만원")
                top10["신고가"] = top10["is_high"].apply(lambda x: "🔥" if x else "")
                st.dataframe(
                    top10[["apt_name","dong","area","floor","거래금액","deal_date","신고가"]]
                    .rename(columns={"apt_name":"아파트","dong":"동",
                                    "area":"면적(㎡)","floor":"층","deal_date":"거래일"}),
                    use_container_width=True, hide_index=True)

        with col2:
            monthly = pd.read_sql(f"""
                SELECT substr(deal_date,1,7) as month,
                       AVG(deal_amount) as avg_price, COUNT(*) as cnt
                FROM trades WHERE lawd_cd IN ({ph})
                GROUP BY month ORDER BY month DESC LIMIT 12
            """, conn, params=codes)
            if not monthly.empty:
                monthly = monthly.iloc[::-1]
                fig = px.bar(monthly, x="month", y="avg_price",
                    title=f"{selected} 월별 평균 거래가",
                    labels={"month":"월","avg_price":"평균가(만원)"},
                    color="avg_price",
                    color_continuous_scale=["#3B8BD4","#E8593C"])
                fig.update_layout(height=350,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False, margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig, use_container_width=True)
        conn.close()
    except Exception as e:
        st.error(f"부동산 DB 오류: {e}")
