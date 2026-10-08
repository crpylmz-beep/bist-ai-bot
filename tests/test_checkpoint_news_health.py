import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from datetime import datetime,timezone
from email.utils import format_datetime

from disk_resumable import ResumableProof, MAX_BYTES
from ekonomi_haberleri import EconomyNews,SOURCES
from veri_yollari import DataPaths
from ana_motor import health_snapshot,istanbul_now
from gorev_hatalari import TaskIssue


class CheckpointHealthTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':tmp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':tmp.name,'BIST_RUNTIME_DIR':''}))

    def test_variable_metadata_byte_eviction_no_payload_deleted(self):
        unique=self.location.runtime/'.user-unique.tmp';unique.write_text('KEEP UNIQUE')
        session=ResumableProof(self.location)
        session.data['files']={str(i):{'completed':i<50,'touched':i,'metadata':{'hash':'x'*3000},'offset':i} for i in range(100)}
        session.dirty=True
        self.assertTrue(session.save())
        self.assertLessEqual(session.path.stat().st_size,MAX_BYTES)
        self.assertIn('99',session.data['files'])
        self.assertEqual(unique.read_text(),'KEEP UNIQUE')
        reopened=ResumableProof(self.location)
        self.assertEqual(reopened.data,session.data)
        self.assertLess(len(session.data['files']),100)
        reopened.close();session.close()

    def test_unfit_entry_preserves_previous_checkpoint(self):
        session=ResumableProof(self.location);session.dirty=True;session.save();before=session.path.read_bytes()
        session.data['files']={'only':{'completed':False,'metadata':'x'*MAX_BYTES}};session.dirty=True
        self.assertFalse(session.save())
        self.assertEqual(session.path.read_bytes(),before)
        session.dirty=False;session.close()

    def test_retained_progress_exactly_restored(self):
        session=ResumableProof(self.location)
        progress={'completed':False,'touched':1000,'parser':{'offset':23456},'count':78,'metadata':{},'recovery':{'added':3}}
        session.data['files']={str(i):{'completed':True,'metadata':'x'*4000,'touched':i} for i in range(100)}
        session.data['files']['active']=copy.deepcopy(progress);session.dirty=True;session.close()
        reopened=ResumableProof(self.location)
        self.assertEqual(reopened.data['files']['active'],progress);reopened.close()

    def test_rss_sources_separate_failures_and_success(self):
        def fetch(url):
            if 'ekonomim' in url:raise ConnectionError()
            if url.endswith('robots.txt'):return b'User-agent: *\nAllow: /'
            if 'bloomberg' in url:return b'<invalid'
            return b'<rss><channel/></rss>'
        collector=EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock())
        with self.assertRaises(TaskIssue):collector.one_round()
        value=json.loads((self.location.runtime/'economy_news_health.json').read_text())
        rows=value['sources'];self.assertEqual(len(rows),3)
        self.assertEqual(rows['EKONOMIM']['code'],'NETWORK_CONNECTION')
        self.assertEqual(rows['BLOOMBERG_HT']['code'],'SOURCE_INVALID_FEED')
        self.assertEqual(rows['ENSONHABER_EKONOMI']['status'],'OK')
        self.assertLess(len(json.dumps(value)),8192)
        (self.location.runtime/'ana_motor_durum.json').write_text(json.dumps({'updated_at':istanbul_now().isoformat(),'motor_durumu':'RUNNING'}))
        self.assertEqual(health_snapshot(self.location.runtime)['news_sources'],rows)

    def test_universe_failure_sources_not_claimed_available(self):
        collector=EconomyNews(lambda:[],Mock(),Mock(),Mock())
        with self.assertRaises(TaskIssue):collector.one_round()
        rows=json.loads((self.location.runtime/'economy_news_health.json').read_text())['sources']
        self.assertTrue(all(row['status']=='BLOCKED' and row['code']=='EMPTY_UNIVERSE' for row in rows.values()))

    def test_deferred_checkpoint_not_reported_as_success(self):
        from disk_forensik import inspect_atomic_temps
        from ana_motor import worker_lock
        with patch.object(ResumableProof,'save',return_value=False),worker_lock(self.location.runtime):
            result=inspect_atomic_temps(self.location,cleanup=True,resumable=True)
        self.assertTrue(result['checkpoint_deferred'])
        self.assertGreater(result['errors'],0)
        self.assertEqual(result['removed'],0)
