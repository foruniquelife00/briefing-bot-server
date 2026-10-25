"""Mixed clauses must not let a market description exempt a reader direction."""
import unittest
from role_boundary import apply_cplus, check_role_boundary

FACT = "- SOXL -13% / SOXS +13%의 극단적 방향성은 단기 반도체 비중 축소 심리를 반영"
PAD = "금리와 기업 발표에 대한 시장 정보입니다.\n" * 20


class SentimentScopeTests(unittest.TestCase):
    def assert_blocked_or_redacted(self, text):
        self.assertFalse(check_role_boundary(text)["ok"])
        result = apply_cplus(PAD + text)
        self.assertIn(result["action"], ("redact", "block"))
        if result["action"] == "redact":
            self.assertNotIn(text, result["text"])

    def test_terminal_description_remains_allowed(self):
        self.assertTrue(check_role_boundary(FACT)["ok"])
        self.assertEqual(apply_cplus(PAD + FACT)["action"], "pass")

    def test_prior_instruction_is_not_exempted_by_terminal_description(self):
        for prefix in ("반도체 비중 축소해 주세요; ",
                       "반도체 비중 축소가 적절합니다; ",
                       "현금 비중 확대; "):
            with self.subTest(prefix=prefix):
                self.assert_blocked_or_redacted(prefix + FACT)

    def test_observation_does_not_exempt_a_following_reader_direction(self):
        self.assert_blocked_or_redacted(
            "외국인 매수 확대가 관측됐습니다; 지금 비중을 축소하세요")

    def test_disclaimer_does_not_exempt_a_following_reader_direction(self):
        self.assert_blocked_or_redacted(
            "매매 지시는 제공하지 않습니다; 지금 비중을 축소하세요")

    def test_direction_does_not_inherit_a_later_observation(self):
        self.assert_blocked_or_redacted(
            "지금 비중을 축소하세요; 외국인 매수 확대가 관측됐습니다")

    def test_supply_observation_without_direction_remains_allowed(self):
        text = "외국인 매수 확대가 관측됐습니다"
        self.assertTrue(check_role_boundary(text)["ok"])
        self.assertEqual(apply_cplus(PAD + text)["action"], "pass")

    def test_normative_direction_does_not_inherit_explanation_or_disclaimer(self):
        for text in (
            "외국인 매수 확대가 관측됐습니다; 지금 비중을 축소해야 합니다",
            "매매 지시는 제공하지 않습니다; 지금 매수해야 합니다",
            "배경을 설명합니다; 지금 비중을 축소하는 것이 바람직합니다",
        ):
            with self.subTest(text=text):
                self.assert_blocked_or_redacted(text)

    def test_clause_exemptions_do_not_cover_normative_adjustments(self):
        facts = ("외국인 매수 확대가 관측됐습니다", "매매 지시는 제공하지 않습니다",
                 "배경을 설명합니다")
        directions = ("현금 비중 확대가 적절합니다", "현금 비중 확대가 유리합니다",
                      "지금 비중을 축소해야 합니다")
        for fact in facts:
            for direction in directions:
                for text in (fact + "; " + direction, direction + "; " + fact):
                    with self.subTest(text=text):
                        self.assert_blocked_or_redacted(text)
        self.assert_blocked_or_redacted(
            "외국인 매수 확대가 관측됐으며 현금 비중 확대가 적절합니다")


if __name__ == "__main__":
    unittest.main()
