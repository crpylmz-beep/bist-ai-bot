import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import requests

from ekonomi_haberleri import EconomyNews,SOURCES
from haber_kaynak_politikasi import SourceRestrictions,restriction
from gorev_hatalari import TaskIssue


class NewsRestrictionsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':tmp.name,'BIST_RUNTIME_DIR':''}))
        self.policy=SourceRestrictions()

    def fetch(self,url):
        if 'ekonomim' in url:return b'User-agent: *\nDisallow: /'
        return b'User-agent: *\nAllow: /' if url.endswith('robots.txt') else b'<rss><channel/></rss>'

    def test_denial_not_retried_next_round_or_restart(self):
        fetch=Mock(side_effect=self.fetch)
        first=EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock())
        with self.assertRaises(TaskIssue):first.one_round()
        fetch.reset_mock()
        second=EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock())
        result=second.one_round()
        self.assertFalse(any('ekonomim' in c.args[0] for c in fetch.call_args_list))
        self.assertEqual(result['disabled'],1)
        rows=json.loads((self.root/'runtime/economy_news_health.json').read_text())['sources']
        self.assertEqual(rows['EKONOMIM']['status'],'DISABLED')
        self.assertEqual(rows['BLOOMBERG_HT']['status'],'OK')

    def test_previous_health_restriction_paused_before_request(self):
        self.policy.health_path.parent.mkdir(parents=True)
        self.policy.health_path.write_text(json.dumps({'sources':{'EKONOMIM':{'code':'HTTP_BLOCKED'}}}))
        fetch=Mock(side_effect=self.fetch)
        EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock()).one_round()
        self.assertFalse(any('ekonomim' in c.args[0] for c in fetch.call_args_list))

    def test_http_denials_include_auth_rate_limit_and_legal(self):
        for status in (401,402,403,429,451):
            response=requests.Response();response.status_code=status
            self.assertIsNotNone(restriction(requests.HTTPError(response=response)))
        response=requests.Response();response.status_code=503
        self.assertIsNone(restriction(requests.HTTPError(response=response)))
        self.assertIsNone(restriction(requests.ConnectionError()))

    def test_kap_accessible_continues_blocked_kap_not_retried(self):
        callback=Mock(return_value=3)
        self.assertEqual(self.policy.call('KAP',callback),3)
        response=requests.Response();response.status_code=403
        callback.side_effect=requests.HTTPError(response=response)
        with self.assertRaises(requests.HTTPError):self.policy.call('KAP',callback)
        callback.reset_mock()
        value=SourceRestrictions().call('KAP',callback)
        callback.assert_not_called();self.assertEqual(value['diagnostics']['skipped'],1)

    def test_changed_url_does_not_reactivate_and_state_bounded(self):
        self.policy.disable('EKONOMIM',{'code':'HTTP_BLOCKED'})
        before=self.policy.path.read_bytes()
        with patch.dict(os.environ,{'EKONOMIM_RSS_URL':'https://www.ekonomim.com/other'}):
            fetch=Mock(side_effect=self.fetch)
            EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock()).one_round()
        self.assertFalse(any('ekonomim' in c.args[0] for c in fetch.call_args_list))
        self.assertEqual(before,self.policy.path.read_bytes())
        self.assertLess(len(before),8192)

    def test_corrupt_policy_preserved_no_network(self):
        self.policy.path.parent.mkdir(parents=True)
        self.policy.path.write_text('UNIQUE INVALID CONTENT')
        fetch=Mock()
        with self.assertRaises(ValueError):EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock()).one_round()
        fetch.assert_not_called();self.assertEqual(self.policy.path.read_text(),'UNIQUE INVALID CONTENT')

    def test_transient_network_failure_retried_not_disabled(self):
        fetch=Mock(side_effect=requests.ConnectionError())
        collector=EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock())
        for _ in range(2):
            with self.assertRaises(TaskIssue):collector.one_round()
        self.assertEqual(fetch.call_count,6);self.assertEqual(self.policy.load(),{})

    def test_policy_write_failure_does_not_repeat_detected_denial_in_process(self):
        import errno
        response=requests.Response();response.status_code=403
        callback=Mock(side_effect=requests.HTTPError(response=response))
        with patch('haber_kaynak_politikasi.atomic_json',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaises(OSError):self.policy.call('KAP',callback)
        callback.reset_mock();self.policy.call('KAP',callback);callback.assert_not_called()

    def test_bad_rss_observation_does_not_stop_accessible_kap(self):
        self.policy.health_path.parent.mkdir(parents=True)
        self.policy.health_path.write_text('INVALID RSS OBSERVATION')
        callback=Mock(return_value=4)
        self.assertEqual(self.policy.call('KAP',callback),4)
        callback.assert_called_once()
