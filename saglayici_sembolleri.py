"""Canonical BIST provider symbol; no inferred ticker aliases or investment filters."""
import re


def bist_symbol(value):
    text=str(value).strip().upper()
    if text.startswith('BIST:'):text=text[5:]
    for suffix in ('.IS','.E'):
        if text.endswith(suffix):text=text[:-len(suffix)];break
    if not re.fullmatch(r'[A-Z0-9]{2,12}',text):
        raise ValueError('Geçersiz BIST sağlayıcı sembolü')
    return text
