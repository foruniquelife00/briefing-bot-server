import sqlite3
import anthropic
import requests
import config
from datetime import datetime, timezone, timedelta

DB_PATH = config.DB_PATH
client  = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

KST = timezone(timedelta(hours=9))

# 이벤트 유형 정의
EVENT_TYPES = {
    "지정학":   {"icon": "⚔️",  "sectors": {"수혜": ["방산", "항공우주"], "타격": ["항공", "여행", "카지노"]}},
    "통화정책": {"icon": "🏦",  "sectors": {"수혜": ["금융", "배당주"],   "타격": ["성장주", "부동산"]}},
    "무역":     {"icon": "🚢",  "sectors": {"수혜": ["내수", "방산"],     "타격": ["수출", "반도체"]}},
    "환율":     {"icon": "💱",  "sectors": {"수혜": ["수출", "반도체"],   "타격": ["수입", "항공"]}},
    "에너지":   {"icon": "⛽",  "sectors": {"수혜": ["에너지", "화학"],   "타격": ["항공", "운송"]}},
    "국내정치": {"icon": "🏛️",  "sectors": {"수혜": ["방산"],             "타격": ["전반적 하락"]}},
    "자연재해": {"icon": "🌪️",  "sectors": {"수혜": ["건설", "보험"],     "타격": ["관광", "유통"]}},
}

# 과거 패턴 DB (수동 구축 + 자동 축적)
HISTORICAL_PATTERNS = [
    {"type": "지정학", "event": "북한 미사일 발사", "kospi_1d": -1.8, "kospi_3d": -0.5, "recovery_days": 3,  "count": 7},
    {"type": "지정학", "event": "중동 분쟁 확대",   "kospi_1d": -2.1, "kospi_3d": -1.2, "recovery_days": 7,  "count": 4},
    {"type": "통화정책","event": "미국 금리 인상",  "kospi_1d": -1.5, "kospi_3d": -2.0, "recovery_days": 14, "count": 12},
    {"type": "통화정책","event": "미국 금리 동결",  "kospi_1d": +0.8, "kospi_3d": +1.2, "recovery_days": 0,  "count": 8},
    {"type": "무역",    "event": "미중 관세 분쟁",  "kospi_1d": -2.5, "kospi_3d": -3.1, "recovery_days": 21, "count": 5},
    {"type": "무역",    "event": "트럼프 관세 폭탄","kospi_1d": -3.2, "kospi_3d": -4.0, "recovery_days": 14, "count": 3},
    {"type": "환율",    "event": "원달러 1400 돌파", "kospi_1d": -1.2, "kospi_3d": -0.8, "recovery_days": 7,  "count": 6},
    {"type": "국내정치","event": "계엄 선언",        "kospi_1d": -5.0, "kospi_3d": -2.0, "recovery_days": 10, "count": 1},
]


def init_event_db():
    """이벤트 DB 초기화"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at  TEXT NOT NULL,
            event_type   TEXT NOT NULL,
            event_title  TEXT NOT NULL,
            event_summary TEXT,
            severity     INTEGER DEFAULT 1,
            alert_sent   INTEGER DEFAULT 0,
            source       TEXT,
            created_at   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()


def get_latest_news() -> list:
    """최신 뉴스 수집"""
    import feedparser
    import calendar as cal_mod

    news_list = []
    sources = [
        ("https://rss.donga.com/total.xml",       "동아일보"),
        ("https://www.mk.co.kr/rss/30000001/",     "매일경제"),
        ("https://www.hankyung.com/feed/all-news", "한국경제"),
        ("https://rss.etnews.com/Section901.xml",  "전자신문"),
    ]

    now_ts = datetime.now(timezone.utc).timestamp()

    for url, source in sources:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                parsed = entry.get("published_parsed")
                if not parsed:
                    continue
                pub_ts    = cal_mod.timegm(parsed)
                age_hours = (now_ts - pub_ts) / 3600
                if age_hours <= 6:
                    news_list.append({
                        "title":  entry.get("title", ""),
                        "pub":    entry.get("published", ""),
                        "source": source,
                        "age_h":  round(age_hours, 1),
                    })
        except Exception as e:
            pass

    return sorted(news_list, key=lambda x: x.get("age_h", 99))[:20]

# 이벤트 감지 키워드 (Claude 호출 전 필터)
EVENT_KEYWORDS = [
    # 지정학
    "전쟁", "폭격", "미사일", "북한", "도발", "침공", "분쟁", "테러",
    "봉쇄", "호르무즈", "이란", "이스라엘", "우크라이나", "러시아",
    # 통화정책
    "금리 인상", "금리 인하", "긴급 금리", "연준", "FOMC", "기준금리",
    # 무역
    "관세", "무역전쟁", "수출 규제", "제재", "블랙리스트",
    # 환율
    "원달러 1500", "원화 급락", "환율 급등", "외환위기",
    # 국내정치
    "계엄", "탄핵", "긴급명령", "국가비상",
    # 시장충격
    "서킷브레이커", "폭락", "급락", "사이드카", "코스피 폭",
    # 에너지
    "유가 급등", "유가 폭등", "원유 공급",
]

def has_event_keyword(news_list: list) -> tuple:
    """키워드 필터 — True이면 Claude 호출, False이면 스킵"""
    matched = []
    for news in news_list:
        title = news.get("title", "")
        for kw in EVENT_KEYWORDS:
            if kw in title:
                matched.append((kw, title[:40]))
                break
    return len(matched) > 0, matched


def detect_event(news_list: list) -> dict:
    """Claude로 이벤트 감지 및 분류"""
    if not news_list:
        return {}

    news_text = "\n".join([f"- {n['title']}" for n in news_list])
    now       = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    prompt = f"""현재 시각: {now}

아래 최신 뉴스 헤드라인을 분석하여 한국 증시에 영향을 줄 수 있는 중요한 이벤트가 있으면 감지해주세요.

## 최신 뉴스
{news_text}

## 이벤트 유형
- 지정학: 전쟁·분쟁·테러·북한 도발
- 통화정책: 금리 결정·양적완화·긴축
- 무역: 관세·제재·무역협정
- 환율: 급격한 환율 변동
- 에너지: 유가 급등락·에너지 위기
- 국내정치: 정치적 불안·선거·정책 변화
- 자연재해: 대형 재해·사고

중요한 이벤트가 없으면 "없음"으로 답하세요.
있으면 아래 JSON 형식으로만 답하세요:

{{
  "detected": true,
  "type": "이벤트유형",
  "title": "이벤트 제목 (20자 이내)",
  "summary": "2~3줄 요약",
  "severity": 1~3 (1=관심, 2=주의, 3=경보),
  "affected_sectors": {{"수혜": ["섹터1"], "타격": ["섹터2"]}}
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text
        if "없음" in text or "detected" not in text:
            return {}

        import re, json
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"이벤트 감지 오류: {e}")
    return {}


def find_historical_pattern(event_type: str) -> dict:
    """과거 유사 패턴 검색"""
    patterns = [p for p in HISTORICAL_PATTERNS if p["type"] == event_type]
    if not patterns:
        return {}

    avg_1d  = sum(p["kospi_1d"]  for p in patterns) / len(patterns)
    avg_3d  = sum(p["kospi_3d"]  for p in patterns) / len(patterns)
    avg_rec = sum(p["recovery_days"] for p in patterns) / len(patterns)
    total   = sum(p["count"] for p in patterns)

    return {
        "count":         total,
        "avg_1d":        avg_1d,
        "avg_3d":        avg_3d,
        "recovery_days": avg_rec,
        "examples":      [p["event"] for p in patterns[:3]],
    }


def generate_action_plan(event: dict, pattern: dict) -> str:
    """대처 방안 생성"""
    event_type = event.get("type", "")
    info       = EVENT_TYPES.get(event_type, {})
    sectors    = event.get("affected_sectors", info.get("sectors", {}))
    icon       = info.get("icon", "🚨")
    severity   = event.get("severity", 1)
    sev_icon   = "🔴" if severity == 3 else "🟡" if severity == 2 else "🟠"

    lines = [
        f"\n{sev_icon} 긴급 이벤트 감지",
        "━" * 22,
        f"{icon} **{event.get('title', '')}**",
        f"유형: {event_type} | 심각도: {'경보' if severity==3 else '주의' if severity==2 else '관심'}",
        f"\n📋 요약\n{event.get('summary', '')}",
    ]

    # 과거 패턴
    if pattern:
        lines += [
            f"\n📊 과거 유사 패턴 ({pattern['count']}건 평균)",
            f"  당일 코스피: {pattern['avg_1d']:+.1f}%",
            f"  3일 후:      {pattern['avg_3d']:+.1f}%",
            f"  평균 회복:   {pattern['recovery_days']:.0f}일",
            f"  유사 사례:   {', '.join(pattern['examples'][:2])}",
        ]

    # 영향 섹터
    if sectors:
        lines.append("\n🎯 영향 섹터")
        if sectors.get("수혜"):
            lines.append(f"  📈 수혜: {', '.join(sectors['수혜'])}")
        if sectors.get("타격"):
            lines.append(f"  📉 타격: {', '.join(sectors['타격'])}")

    # 대처 방안
    lines += [
        "\n⚡ 대처 방안",
        "  1️⃣ 단기 (오늘): 수혜 섹터 관심 + 타격 섹터 비중 축소",
        "  2️⃣ 중기 (3일): 과매도 시 역발상 분할 매수",
        "  3️⃣ 보수적: 현금 비중 유지, 변동성 확대 관망",
        "━" * 22,
    ]

    return "\n".join(lines)


def save_event(event: dict, source: str = "뉴스"):
    """이벤트 DB 저장"""
    init_event_db()
    conn = sqlite3.connect(DB_PATH)

    # 최근 1시간 내 동일 이벤트 중복 방지
    one_hour_ago = (datetime.now(KST) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    existing = conn.execute("""
        SELECT id FROM events
        WHERE event_title = ? AND detected_at > ?
    """, (event.get("title",""), one_hour_ago)).fetchone()

    if existing:
        conn.close()
        return False

    conn.execute("""
        INSERT INTO events
            (detected_at, event_type, event_title, event_summary, severity, source)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        event.get("type", ""),
        event.get("title", ""),
        event.get("summary", ""),
        event.get("severity", 1),
        source,
    ))
    conn.commit()
    conn.close()
    return True


def run_event_detection():
    """이벤트 감지 + 알림 발송"""
    print("이벤트 감지 중...")
    init_event_db()

    # 뉴스 수집
    news = get_latest_news()
    if not news:
        print("뉴스 수집 실패")
        return

    print(f"뉴스 {len(news)}건 수집 완료")

    # 이벤트 감지
    event = detect_event(news)
    if not event or not event.get("detected"):
        print("감지된 이벤트 없음")
        return

    print(f"이벤트 감지: {event.get('title')} (심각도: {event.get('severity')})")

    # 심각도 1 이상만 알림
    if event.get("severity", 0) < 1:
        return

    # DB 저장 (중복 방지)
    if not save_event(event):
        print("중복 이벤트 - 알림 생략")
        return

    # 과거 패턴 검색
    pattern = find_historical_pattern(event.get("type", ""))

    # 대처 방안 생성
    alert_msg = generate_action_plan(event, pattern)
    print(alert_msg)

    # 카카오 발송 (이벤트 감지는 카카오만)
    try:
        from sender import send_kakao
        send_kakao(alert_msg)
        print("카카오 알림 발송 완료!")
    except Exception as e:
        print(f"알림 발송 오류: {e}")

    return event


if __name__ == "__main__":
    run_event_detection()
