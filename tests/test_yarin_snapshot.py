"""Snapshot persistence checks: no live network or repository-data writes."""
import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import bist_bot as bot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / 'yarin_top10.json'
        self.archive = self.root / 'yarin_top10_arsiv'
        self.live = self.root / 'yarin_top10_canli.json'
        self.now = datetime(2026, 10, 6, 19, 0, tzinfo=ZoneInfo('Europe/Istanbul'))
        self.sample = {
            'sembol': 'THYAO', 'fiyat': 290.5, 'yarin_ai_karar': 'AL',
            'ai_yarin_alim_alt': 289, 'ai_yarin_alim_ust': 291,
            'ai_yarin_hedef': 300, 'ai_yarin_stop': 284,
            'yarin_kirilim': 295, 'haber_puani': 2, 'makro_puani': -1,
            'nedenler': ['Hacim teyidi'], 'rsi': 55,
        }
        for key, value in {
            'YARIN_TOP10_FILE': str(self.current),
            'YARIN_TOP10_ARSIV_DIR': str(self.archive),
            'YARIN_TOP10_CANLI_FILE': str(self.live),
            '__file__': str(self.root / 'bist_bot.py'),
        }.items():
            self.enterContext(patch.object(bot, key, value))
        self.clock = self.enterContext(patch.object(bot, 'datetime', wraps=datetime))
        self.clock.now.side_effect = lambda tz=None: self.now.astimezone(tz) if tz else self.now.replace(tzinfo=None)
        def ranking(rows, **kwargs):
            for row in rows:row.update(ham_puan=80,final_puan=80,shadow_puan=80,kalibrasyon_duzeltmesi=0,calibration_version='BASE',shadow_version='BASE')
            return [(80,a) for a in rows]
        self.rank = self.enterContext(patch.object(bot, 'yarin_top10_listesi', side_effect=ranking))
        self.enterContext(patch.object(bot, 'yarin_potansiyel_hesapla', return_value=80))

    def save(self, sample=None):
        return bot.yarin_top10_kilitli_kaydet([copy.deepcopy(sample or self.sample)], 805)

    def test_snapshot_fields_and_same_day_no_overwrite(self):
        first = self.save()
        path = self.archive / '2026-10-06.json'
        original = path.read_bytes()
        current_stat = self.current.stat().st_mtime_ns
        prediction = first['top10'][0]['tahmin']
        self.assertEqual(prediction['fiyat'], 290.5)
        self.assertEqual(prediction['skor'], 80)
        self.assertEqual(prediction['karar'], 'AL')
        self.assertEqual((prediction['alim_alt'], prediction['alim_ust'], prediction['hedef'], prediction['stop']), (289, 291, 300, 284))
        self.assertEqual(prediction['makro_puani'], -1)
        self.assertEqual(prediction['kriter_ozeti']['nedenler'], ['Hacim teyidi'])
        self.assertTrue(prediction['tahmin_zamani'].endswith('+03:00'))
        changed = dict(self.sample, fiyat=999, ai_yarin_hedef=2000)
        self.assertEqual(self.save(changed), first)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.current.stat().st_mtime_ns, current_stat)
        self.assertEqual(self.rank.call_count, 1)

    def test_next_day_keeps_previous_archive(self):
        self.save()
        old = (self.archive / '2026-10-06.json').read_bytes()
        self.now += timedelta(days=1)
        new = self.save(dict(self.sample, fiyat=305))
        self.assertEqual(new['analiz_tarihi'], '2026-10-07')
        self.assertEqual((self.archive / '2026-10-06.json').read_bytes(), old)
        self.assertEqual(bot.yarin_top10_kilitli_oku(), new)

    def test_legacy_same_day_is_preserved_without_reranking(self):
        legacy = {
            'analiz_tarihi': '2026-10-06', 'olusturma_zamani': '2026-10-06 18:30:00',
            'kilitli': True, 'top10': [dict(self.sample, yarin_top10_puani=70)],
        }
        self.current.write_text(json.dumps(legacy))
        migrated = self.save(dict(self.sample, fiyat=999))
        self.rank.assert_not_called()
        for key, value in legacy['top10'][0].items():
            self.assertEqual(migrated['top10'][0][key], value)
        self.assertIsNone(migrated['tahmin_zamani'])
        self.assertEqual(migrated['zaman_kaynagi'], 'LEGACY_BELIRSIZ')

    def test_concurrent_writers_share_first_prediction(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda price: self.save(dict(self.sample, fiyat=price)), [290, 300, 310, 320]))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.rank.call_count, 1)
        self.assertEqual(json.loads((self.archive / '2026-10-06.json').read_text()), results[0])

    def test_previous_day_legacy_is_archived_before_new_prediction(self):
        legacy = {
            'analiz_tarihi': '2026-10-05', 'olusturma_zamani': '2026-10-05 19:02:49',
            'kilitli': True, 'top10': [dict(self.sample, fiyat=280)],
        }
        self.current.write_text(json.dumps(legacy))
        self.save()
        old = json.loads((self.archive / '2026-10-05.json').read_text())
        self.assertEqual(old['top10'][0]['fiyat'], 280)
        self.assertEqual(old['olusturma_zamani'], legacy['olusturma_zamani'])
        self.assertTrue((self.archive / '2026-10-06.json').exists())

    def test_broken_archive_cannot_be_replaced_by_live_results(self):
        self.save()
        path = self.archive / '2026-10-06.json'
        path.write_text('{broken')
        current = self.current.read_bytes()
        self.assertIsNone(self.save(dict(self.sample, fiyat=999)))
        self.assertEqual(path.read_text(), '{broken')
        self.assertEqual(self.current.read_bytes(), current)

    def test_atomic_failure_leaves_previous_json_intact(self):
        self.current.write_text('{"old": true}')
        with self.assertRaises(ValueError):
            bot.json_atomik_yaz(str(self.current), {'price': float('nan')})
        self.assertEqual(self.current.read_text(), '{"old": true}')
        self.assertFalse(list(self.root.glob('.snapshot-*.tmp')))
        with self.assertRaises(FileExistsError):
            bot.json_atomik_yaz(str(self.current), {'new': True}, overwrite=False)
        self.assertEqual(self.current.read_text(), '{"old": true}')

    def test_retry_after_current_write_failure_reuses_archive(self):
        writer = bot.json_atomik_yaz
        def fail_current(path, data, overwrite=True):
            if path == str(self.current):
                raise OSError('simulated current-file failure')
            return writer(path, data, overwrite)
        with patch.object(bot, 'json_atomik_yaz', side_effect=fail_current):
            self.assertIsNone(self.save())
        archive = (self.archive / '2026-10-06.json').read_bytes()
        recovered = self.save(dict(self.sample, fiyat=999))
        self.assertEqual(recovered['top10'][0]['fiyat'], 290.5)
        self.assertEqual((self.archive / '2026-10-06.json').read_bytes(), archive)

    def test_broken_existing_record_is_not_overwritten(self):
        self.current.write_text('{broken')
        self.assertIsNone(self.save())
        self.assertEqual(self.current.read_text(), '{broken')
        self.rank.assert_not_called()

    def history(self):
        return pd.DataFrame({
            'High': [999, 500, 110, 108], 'Low': [1, 2, 90, 95],
            'Close': [100, 100, 105, 105],
        }, index=pd.to_datetime(['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08']))

    def performance_fixture(self, **changes):
        sample = dict(self.sample, fiyat=100, ai_yarin_hedef=110, ai_yarin_stop=90)
        sample.update(changes)
        snapshot = self.save(sample)
        self.now += timedelta(days=2)
        return snapshot, snapshot['top10'][0]

    def test_performance_uses_frozen_price_and_only_later_days(self):
        snapshot, stock = self.performance_fixture()
        result = bot.yarin_tahmin_performansi(stock, snapshot, 105, self.history())
        self.assertEqual(result['simdi_yuzde'], 5)
        self.assertEqual(result['en_yuksek_yuzde'], 10)
        self.assertEqual(result['en_dusuk_yuzde'], -10)
        self.assertTrue(result['hedefe_ulasti'])  # equality counts
        self.assertTrue(result['stop_oldu'])

    def test_uncrossed_target_and_stop_are_false(self):
        snapshot, stock = self.performance_fixture(ai_yarin_hedef=111, ai_yarin_stop=89)
        result = bot.yarin_tahmin_performansi(stock, snapshot, 99, self.history())
        self.assertEqual(result['simdi_yuzde'], -1)
        self.assertFalse(result['hedefe_ulasti'])
        self.assertFalse(result['stop_oldu'])

    def test_missing_legacy_time_and_zero_base_stay_unknown(self):
        snapshot, stock = self.performance_fixture()
        stock['tahmin']['tahmin_zamani'] = None
        result = bot.yarin_tahmin_performansi(stock, snapshot, 105, self.history())
        self.assertEqual(result['simdi_yuzde'], 5)
        self.assertIsNone(result['en_yuksek_yuzde'])
        self.assertIsNone(result['hedefe_ulasti'])
        stock['tahmin']['fiyat'] = 0
        self.assertIsNone(bot.yarin_tahmin_performansi(stock, snapshot, 105, self.history())['simdi_yuzde'])

    def test_short_history_cannot_claim_full_extremes_or_no_hit(self):
        snapshot, stock = self.performance_fixture(ai_yarin_hedef=120, ai_yarin_stop=80)
        result = bot.yarin_tahmin_performansi(stock, snapshot, 105, self.history().iloc[-1:])
        self.assertIsNone(result['en_yuksek_yuzde'])
        self.assertIsNone(result['en_dusuk_yuzde'])
        self.assertIsNone(result['hedefe_ulasti'])
        self.assertIsNone(result['stop_oldu'])

    def test_live_updates_keep_snapshot_and_use_archive_as_authority(self):
        snapshot, _ = self.performance_fixture()
        archive_path = self.archive / '2026-10-06.json'
        original = archive_path.read_bytes()
        # A modified compatibility file must not change the performance base.
        alias = copy.deepcopy(snapshot)
        alias['top10'][0]['tahmin']['fiyat'] = 999
        self.current.write_text(json.dumps(alias))
        current = self.current.read_bytes()
        analysis = dict(self.sample, fiyat=105, degisim=2, puan=75, karar='IZLE')
        bot.yarin_top10_canli_guncelle(analysis, self.history())
        live = json.loads(self.live.read_text())['top10'][0]
        self.assertEqual(live['canli']['fiyat'], 105)
        self.assertEqual(live['performans']['simdi_yuzde'], 5)
        self.assertTrue(live['canli']['updated_at'].endswith('+03:00'))
        bot.yarin_top10_canli_guncelle(dict(analysis, fiyat=106), self.history())
        self.assertEqual(json.loads(self.live.read_text())['top10'][0]['performans']['simdi_yuzde'], 6)
        self.assertEqual(archive_path.read_bytes(), original)
        self.assertEqual(self.current.read_bytes(), current)

    def test_pre_prediction_data_is_not_published_as_live(self):
        self.performance_fixture()
        bot.yarin_top10_canli_guncelle(self.sample, self.history().iloc[:2])
        self.assertFalse(self.live.exists())

    def test_observed_hits_survive_later_incomplete_history(self):
        self.performance_fixture()
        analysis = dict(self.sample, fiyat=105)
        bot.yarin_top10_canli_guncelle(analysis, self.history())
        bot.yarin_top10_canli_guncelle(analysis, self.history().iloc[-1:])
        result = json.loads(self.live.read_text())['top10'][0]['performans']
        self.assertTrue(result['hedefe_ulasti'])
        self.assertTrue(result['stop_oldu'])

    def test_intraday_scan_only_updates_separate_live_record(self):
        self.save()
        frozen = self.current.read_bytes()
        archive_path = self.archive / '2026-10-06.json'
        archive = archive_path.read_bytes()
        self.now += timedelta(days=2)
        bot.yarin_top10_canli_guncelle(dict(self.sample, fiyat=305), self.history())
        saved_live = json.loads(self.live.read_text())['top10'][0]
        data = pd.DataFrame({'Close': [300.]})
        stubs = {
            'bist_hisseleri_getir': ['THYAO'], 'gun_ici_gecersiz_oku': set(),
            'gun_ici_stream_verileri_getir': ({'THYAO': data}, []),
            'gun_ici_analiz_hesapla': {'sembol': 'THYAO', 'gun_ici_puan': 70},
            'ilk_hacimli_kirilim_bul': ('10:30:00', 'GERCEKLESTI'),
        }
        for name, result in stubs.items():
            self.enterContext(patch.object(bot, name, return_value=result))
        self.enterContext(patch.object(bot, 'gun_ici_sinyal_durumlarini_guncelle', side_effect=lambda rows: rows))
        for name in ['ai_sinyal_sonuc_guncelle', 'ai_ogrenme_kaydet', 'ai_ogrenme_ozeti_yaz', 'ai_ogrenilmis_agirliklari_hesapla', 'gun_ici_gecersiz_yaz']:
            self.enterContext(patch.object(bot, name))
        top10, _, _ = bot.gun_ici_top10_tara()
        self.assertEqual(len(top10), 1)
        live = json.loads(self.live.read_text())
        self.assertEqual(live['top10'][0]['ilk_hacimli_kirilim_saati'], '10:30:00')
        self.assertTrue(live['updated_at'].endswith('+03:00'))
        self.assertEqual(live['top10'][0]['canli'], saved_live['canli'])
        self.assertEqual(live['top10'][0]['performans'], saved_live['performans'])
        bot.gun_ici_top10_tara()
        self.assertEqual(self.current.read_bytes(), frozen)
        self.assertEqual(archive_path.read_bytes(), archive)


if __name__ == '__main__':
    unittest.main()
