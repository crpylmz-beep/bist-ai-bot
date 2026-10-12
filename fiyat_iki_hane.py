from pathlib import Path
import shutil

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

yedek = Path("bist_bot_fiyat_format_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

degisimler = {
'''            "karar_giris_alt": karar_giris_alt,
            "karar_giris_ust": karar_giris_ust,
            "karar_hedef": karar_hedef,
            "karar_stop": karar_stop,
''':
'''            "karar_giris_alt": round(karar_giris_alt, 2),
            "karar_giris_ust": round(karar_giris_ust, 2),
            "karar_hedef": round(karar_hedef, 2),
            "karar_stop": round(karar_stop, 2),
''',

'''            "yarin_alim_alt": yarin_alim_alt,
            "yarin_alim_ust": yarin_alim_ust,
            "yarin_kar_al": yarin_kar_al,
''':
'''            "yarin_alim_alt": round(yarin_alim_alt, 2),
            "yarin_alim_ust": round(yarin_alim_ust, 2),
            "yarin_kar_al": round(yarin_kar_al, 2),
''',

'''            "yarin_stop": yarin_stop,
''':
'''            "yarin_stop": round(yarin_stop, 2),
'''
}

for eski, yeni in degisimler.items():
    if eski in s:
        s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("FIYAT / HEDEF / STOP DEGERLERI 2 HANEYE YUVARLANDI")
