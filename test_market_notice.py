import ast, importlib.util, sys, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace, ModuleType

ROOT=Path(__file__).resolve().parent
CODE_ROOT=ROOT/'patch' if (ROOT/'patch').is_dir() else ROOT
sys.path.insert(0,str(CODE_ROOT))
if CODE_ROOT != ROOT:
    sys.path.insert(1,str(ROOT.parents[1]))
from market_calendar import KST
from market_notice import build_market_notice


class MarketNoticeTests(unittest.TestCase):
    def test_kr_closed_us_open(self):
        text=build_market_notice(datetime(2026,9,25,6,50,tzinfo=KST))
        self.assertIn('한국 2026-09-25 — 휴장',text)
        self.assertIn('미국 현지일 2026-09-24 — 거래일',text)
        self.assertIn('다가오는 미국 현지일 2026-09-25 — 거래일',text)
        self.assertIn('다음 거래일 2026-09-28',text)

    def test_us_holiday_announced_before_and_after(self):
        before=build_market_notice(datetime(2026,9,7,6,50,tzinfo=KST))
        after=build_market_notice(datetime(2026,9,8,6,50,tzinfo=KST))
        self.assertIn('다가오는 미국 현지일 2026-09-07 — 휴장',before)
        self.assertIn('미국 현지일 2026-09-07 — 휴장',after)
        self.assertIn('한국 2026-09-08 — 거래일',after)
        self.assertIn('미국 최근 완료 거래일(달력 기준): 2026-09-04',after)

    def test_both_closed_and_shortened_us_session(self):
        text=build_market_notice(datetime(2026,12,25,6,50,tzinfo=KST))
        self.assertIn('한국 2026-12-25 — 휴장',text)
        self.assertIn('다가오는 미국 현지일 2026-12-25 — 휴장',text)
        self.assertIn('미국 현지일 2026-12-24 — 거래일 · 단축장',text)

    def test_dst_times_and_dates_are_explicit(self):
        summer=build_market_notice(datetime(2026,9,8,6,50,tzinfo=KST))
        winter=build_market_notice(datetime(2026,12,24,6,50,tzinfo=KST))
        self.assertIn('09/08 22:30~09/09 05:00',summer)
        self.assertIn('12/23 23:30~12/24 06:00',winter)

    def test_unknown_or_corrupt_calendar_does_not_claim_open(self):
        text=build_market_notice(datetime(2027,1,4,6,50,tzinfo=KST))
        self.assertIn('확인 불가',text)
        self.assertNotIn('— 거래일',text)
        with patch('market_notice.session',side_effect=ValueError('broken')):
            self.assertNotIn('— 거래일',build_market_notice(datetime(2026,9,8,6,50,tzinfo=KST)))

    def test_nontrading_message_contains_both_markets_even_without_quotes(self):
        spec=importlib.util.spec_from_file_location('notice_holiday',CODE_ROOT/'nontrading_brief.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        factory=Mock(side_effect=RuntimeError('offline'))
        text=module.build_nontrading_brief(datetime(2026,9,25,6,50,tzinfo=KST),factory)
        self.assertEqual(text.count('📅 국장·미장 운영 안내'),1)
        self.assertIn('미국 현지일 2026-09-24',text)
        self.assertIn('최신 거래일 시세 확인 불가',text)

    def test_regular_briefing_prepends_notice_after_role_redaction(self):
        tree=ast.parse((CODE_ROOT/'bot.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_briefing')
        modules={}
        for name in ['collector','analyzer','sender','role_boundary','delivery_status']:
            modules[name]=ModuleType(name)
        modules['collector'].get_market_data=lambda:{}
        modules['analyzer'].analyze_and_save=lambda data:'LLM body'
        sent=[]
        modules['sender'].send_telegram=lambda text:sent.append(text) or True
        modules['sender'].send_email=lambda *args:None
        modules['role_boundary'].apply_cplus=lambda text:{'action':'redact','text':'SAFE BODY','removed':[], 'violations':[]}
        modules['role_boundary'].audit_only=lambda *args:None
        ds=modules['delivery_status'];ds.record=Mock();ds.SENT_REDACTED='sent_redacted';ds.FAILED_GEN='failed_gen'
        class Clock:
            @classmethod
            def now(cls,*args):return datetime(2026,9,8,6,50,tzinfo=KST)
        import logging
        from datetime import timezone,timedelta
        env={'datetime':Clock,'timezone':timezone,'timedelta':timedelta,'logging':logging}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'bot.py','exec'),env)
        with patch.dict(sys.modules,modules),patch('market_calendar.is_session',return_value=True),patch('market_notice.now_kst',return_value=Clock.now()):
            env['run_briefing']()
        self.assertTrue(sent[-1].startswith('📅 국장·미장 운영 안내'))
        self.assertTrue(sent[-1].endswith('SAFE BODY'))
        self.assertIn('\n\nSAFE BODY',sent[-1])
        self.assertIn('미국 현지일 2026-09-07 — 휴장',sent[-1])
        self.assertEqual(sent[-1].count('📅 국장·미장 운영 안내'),1)


if __name__=='__main__':unittest.main(verbosity=2)
