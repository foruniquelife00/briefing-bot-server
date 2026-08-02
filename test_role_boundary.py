# -*- coding: utf-8 -*-
"""역할 경계 검사기 테스트 — GPT §10 시나리오 10종"""
import sys
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError: pass
from role_boundary import check_role_boundary

# (시나리오, 본문, 기대: True=발송허용 / False=차단)
CASES = [
    ("시장·환율·금리 설명",
     "지난달 코스피는 3.2% 하락했습니다. 원/달러 환율은 1,380원까지 상승했고 "
     "미국 금리 동결이 확인됐습니다. 외국인 순매도가 이어졌습니다.", True),

    ("인버스 ETF 편입 제안",
     "변동성 확대에 대비해 인버스 ETF 편입을 권장합니다.", False),

    ("현금 비중 축소 지시",
     "공포탐욕지수가 30을 밑돌고 있어 현금 비중을 축소하고 분할매수에 나서야 합니다.", False),

    ("특정 종목 3개 추천",
     "⭐ 이번 달 주목 종목 3개\n삼성전자, SK하이닉스, 현대차를 추천합니다.", False),

    ("시그널봇 G3 상태 요약",
     "시그널 시스템은 G3 paper-only 상태이며 페이퍼 표본은 40건이 기록됐습니다. "
     "blocked shadow는 18건 집계됐습니다.", True),

    ("시그널봇 데이터 없음",
     "시그널 시스템 운영상태 데이터 확인 불가", True),

    ("위험등급 4 설명",
     "지난달 위험등급 4가 6거래일 관측됐습니다. 이는 변동성이 큰 국면이었음을 의미합니다.", True),

    ("위험등급 4에서 매도 지시",
     "위험등급 4 구간에서는 보유 주식을 매도하고 비중을 줄이시기 바랍니다.", False),

    ("환율 상승 + 외국인 매도 설명",
     "원/달러 환율 상승과 함께 외국인 순매도가 나타났습니다. "
     "환율 변동성이 커진 반도체 섹터에서 유출이 집계됐습니다.", True),

    ("환율에 따른 자산배분 변경",
     "환율이 상승하면 주식 비중을 축소하고 달러 자산을 확대하는 것이 바람직합니다.", False),
]

def main():
    print(f"{'시나리오':<28}{'기대':>6}{'실제':>6}  판정")
    print("─" * 60)
    passed = 0
    for name, text, expect_ok in CASES:
        r = check_role_boundary(text)
        ok = r["ok"]
        good = (ok == expect_ok)
        passed += good
        e = "허용" if expect_ok else "차단"
        a = "허용" if ok else "차단"
        mark = "✅" if good else "❌"
        print(f"{name:<28}{e:>6}{a:>6}  {mark}")
        if not good and r["violations"]:
            for v in r["violations"][:2]:
                print(f"    └ {v['type']}: {v['evidence'][:50]}")
        elif not good:
            print("    └ 위반 미탐지 (차단됐어야 함)")
    print("─" * 60)
    print(f"통과 {passed}/{len(CASES)}")
    return 0 if passed == len(CASES) else 1

if __name__ == "__main__":
    sys.exit(main())
