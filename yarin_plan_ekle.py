from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''        # Yarin icin dar, dinamik alim bolgesi
        yarin_alim_alt = max(
            0.01,
            fiyat - atr14 * 0.35
        )

        yarin_alim_ust = max(
            yarin_alim_alt,
            fiyat + atr14 * 0.10
        )

        # Ilk kisa vadeli kar alma seviyesi kirilimdan bagimsizdir.
        yarin_kar_al = fiyat + atr14 * 0.50

        # Kisa vadeli stop
        yarin_stop = max(
            0.01,
            fiyat - atr14 * 0.55
        )
'''

yeni = '''        # Yarin icin daha kontrollu dinamik alim bolgesi.
        # ATR kullanilir ancak cok oynak hisselerde bolgenin
        # gereksiz yere genislemesi sinirlandirilir.
        alim_alt_mesafe = min(
            atr14 * 0.23,
            fiyat * 0.022
        )

        alim_ust_mesafe = min(
            atr14 * 0.03,
            fiyat * 0.004
        )

        yarin_alim_alt = max(
            0.01,
            fiyat - alim_alt_mesafe
        )

        yarin_alim_ust = max(
            yarin_alim_alt,
            fiyat + alim_ust_mesafe
        )

        # Ilk kisa vadeli kar alma seviyesi kirilimdan bagimsizdir.
        yarin_kar_al = fiyat + atr14 * 0.50

        # Kisa vadeli stop.
        # ATR ile hesaplanir fakat asiri genis stop engellenir.
        stop_mesafe = min(
            atr14 * 0.50,
            fiyat * 0.046
        )

        yarin_stop = max(
            0.01,
            fiyat - stop_mesafe
        )
'''

if eski not in s:
    raise SystemExit(
        "HATA: Alim/stop blogu bulunamadi. Dosya degistirilmedi."
    )

s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("YARIN ALIM BOLGESI VE STOP INCE AYARI TAMAMLANDI")