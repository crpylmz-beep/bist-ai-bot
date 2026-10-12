import base64
import os
import unittest
from unittest.mock import patch
from vapid_uret import generate
from push_bildirim_motoru import normalize_public_key, public_config


class PublicKeyTests(unittest.TestCase):
    def setUp(self):
        self.values=generate('user@example.com')
        self.key=self.values['VAPID_PUBLIC_KEY']

    def test_generator_is_65_byte_uncompressed_curve_point(self):
        self.assertEqual(normalize_public_key(self.key),self.key)
        raw=base64.urlsafe_b64decode(self.key+'=')
        self.assertEqual(len(raw),65);self.assertEqual(raw[0],4)

    def test_copy_format_and_padding_preserve_same_key(self):
        for key in (self.key+'=', ' "'+self.key+'" ', 'VAPID_PUBLIC_KEY='+self.key, self.key[:20]+'\n'+self.key[20:],self.key.replace('-','+').replace('_','/')):
            self.assertEqual(normalize_public_key(key),self.key)

    def test_bad_base64_empty_wrong_length_or_prefix(self):
        for key in ('','%%%','a','eA',base64.urlsafe_b64encode(bytes(65)).decode()):
            with self.subTest(key=key),self.assertRaises(ValueError):normalize_public_key(key)

    def test_off_curve_point_rejected(self):
        invalid=base64.urlsafe_b64encode(b'\x04'+bytes(64)).decode()
        with self.assertRaises(ValueError):normalize_public_key(invalid)

    def test_api_normalizes_only_public_key_never_changes_private(self):
        with patch.dict(os.environ,{**self.values,'VAPID_PUBLIC_KEY':'"'+self.key+'"'}):
            result=public_config()
            self.assertTrue(result['configured']);self.assertEqual(result['public_key'],self.key)
            self.assertEqual(os.environ['VAPID_PRIVATE_KEY'],self.values['VAPID_PRIVATE_KEY'])
            self.assertNotIn('VAPID_PRIVATE_KEY',result)

    def test_invalid_or_missing_public_recovered_without_private_rotation(self):
        for value in ('', 'bad', self.values['VAPID_PRIVATE_KEY']):
            with patch.dict(os.environ,{**self.values,'VAPID_PUBLIC_KEY':value}):
                result=public_config()
                self.assertEqual(result['public_key'],self.key)
                self.assertTrue(result['public_key_recovered'])
                self.assertTrue(result['configured'])
                self.assertEqual(os.environ['VAPID_PRIVATE_KEY'],self.values['VAPID_PRIVATE_KEY'])

    def test_bad_key_api_is_safe_without_exception_or_secret(self):
        with patch.dict(os.environ,{**self.values,'VAPID_PUBLIC_KEY':'bad','VAPID_PRIVATE_KEY':'invalid'}):
            result=public_config()
            self.assertFalse(result['configured']);self.assertTrue(result['public_key_error'])
            self.assertEqual(result['public_key'],'')


if __name__=='__main__':unittest.main()
