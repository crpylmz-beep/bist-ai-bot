import base64
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from vapid_uret import generate, main, validate_subject


def decode(value):
    return base64.urlsafe_b64decode(value+'='*(-len(value)%4))


class VapidTests(unittest.TestCase):
    def test_key_format_and_matching_public_key(self):
        values=generate('user@example.com')
        private=decode(values['VAPID_PRIVATE_KEY'])
        public=decode(values['VAPID_PUBLIC_KEY'])
        self.assertEqual(len(private),32)
        self.assertEqual(len(public),65)
        self.assertEqual(public[0],4)
        derived=ec.derive_private_key(int.from_bytes(private,'big'),ec.SECP256R1())
        self.assertEqual(derived.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint),public)
        self.assertEqual(values['VAPID_SUBJECT'],'mailto:user@example.com')

    def test_fresh_keys(self):
        self.assertNotEqual(generate('user@example.com')['VAPID_PRIVATE_KEY'],generate('user@example.com')['VAPID_PRIVATE_KEY'])

    def test_valid_subjects(self):
        for value in ('mailto:user@example.com','https://example.com/contact'):
            self.assertEqual(validate_subject(value),value)

    def test_invalid_subjects(self):
        for value in ('','not-an-email','mailto:@','http://example.com','mailto:user@example.com\nsecret','https://user:password@example.com'):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_subject(value)

    def test_interactive_main_displays_three_values(self):
        capture=io.StringIO()
        with patch('builtins.input',return_value='user@example.com'),contextlib.redirect_stdout(capture):
            self.assertEqual(main([]),0)
        lines=capture.getvalue().splitlines()
        self.assertEqual(len([line for line in lines if line.startswith('VAPID_')]),3)

    def test_command_writes_no_files(self):
        script=Path(__file__).resolve().parents[1]/'vapid_uret.py'
        with tempfile.TemporaryDirectory() as directory:
            process=subprocess.run([sys.executable,str(script),'--subject','user@example.com'],cwd=directory,capture_output=True,text=True,check=True)
            self.assertEqual(len(list(Path(directory).iterdir())),0)
            self.assertIn('VAPID_SUBJECT=mailto:user@example.com',process.stdout)


if __name__=='__main__':unittest.main()
