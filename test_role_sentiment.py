import unittest
from role_boundary import apply_cplus,check_role_boundary
FACT='- SOXL -13% / SOXS +13%의 극단적 방향성은 단기 반도체 비중 축소 심리를 반영'
PAD='금리와 기업 발표에 대한 시장 정보입니다.\n'*20

class SentimentTests(unittest.TestCase):
    def test_reported_sentence_passes_both_guards(self):
        self.assertTrue(check_role_boundary(FACT)['ok'])
        self.assertEqual(apply_cplus(PAD+FACT)['action'],'pass')

    def test_sentiment_clause_does_not_allow_actual_direction(self):
        for command in ('비중을 축소하세요','비중 축소를 권고합니다','비중 축소가 필요합니다',
                        '지금 매수하세요','현금 비중을 줄이시기 바랍니다'):
            text=command+'; '+FACT
            self.assertFalse(check_role_boundary(text)['ok'],command)
            self.assertNotEqual(apply_cplus(PAD+text)['action'],'pass',command)

    def test_directive_endings_stay_blocked(self):
        for ending in ('해야 합니다','하세요','하라','하는 것이 바람직합니다'):
            text='반도체 비중 축소 심리를 반영'+ending
            self.assertFalse(check_role_boundary(text)['ok'])
            self.assertNotEqual(apply_cplus(PAD+text)['action'],'pass')

    def test_prohibited_section_remains_blocked(self):
        text='# 비중 조정안\n'+FACT
        self.assertFalse(check_role_boundary(text)['ok'])
        self.assertEqual(apply_cplus(PAD+text)['action'],'block')

    def test_ordinary_weight_directive_stays_blocked(self):
        self.assertFalse(check_role_boundary('반도체 비중 축소를 권장합니다')['ok'])

    def test_unrelated_asset_allocation_and_inverse_advice_stay_blocked(self):
        for text in ('인버스 ETF 편입을 권장합니다','주식 비중을 축소하고 달러 자산을 확대하세요'):
            self.assertFalse(check_role_boundary(text)['ok'])

if __name__=='__main__': unittest.main()
