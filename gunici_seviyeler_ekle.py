from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''        puan = max(
            0,
            min(100, puan)
        )

        return {
'''

yeni = '''        puan = max(
            0,
            min(100, puan)
        )

        # -------------------------------------------------
        # GUN ICI ISLEM SEVIYELERI
        # -------------------------------------------------

        gun_aralik = max(
            gun_yuksek - gun_dusuk,
            fiyat * 0.005
        )

        # Alim bolgesi:
        # mevcut fiyat etrafinda kontrollu geri cekilme alani.
        alim_alt = max(
            gun_dusuk,
            fiyat - (gun_aralik * 0.18)
        )

        alim_ust = fiyat

        # Kisa vadeli kar al:
        # gun ici yuksek ve volatilite birlikte dikkate alinir.
        kar_al = max(
            gun_yuksek,
            fiyat + (gun_aralik * 0.35)
        )

        # Stop:
        # alim bolgesinin ve gun ici yapinin altinda.
        stop = max(
            0,
            alim_alt - (gun_aralik * 0.22)
        )

        # Hacimli kirilim seviyesi.
        hacimli_kirilim_seviyesi = max(
            yakin_direnc,
            gun_yuksek
        )

        # Kirilim sonrasi ilk hedef.
        kirilim_sonrasi_hedef = (
            hacimli_kirilim_seviyesi
            + (gun_aralik * 0.45)
        )

        if hacimli_kirilim:
            kirilim_durumu = "HACIMLI KIRILIM VAR"
        elif kirilim:
            kirilim_durumu = "DIRENC KIRILDI - HACIM TEYIDI BEKLENIYOR"
        else:
            kirilim_durumu = "HACIMLI KIRILIM BEKLENIYOR"

        return {
'''

if eski not in s:
    raise SystemExit("EKLENECEK YER BULUNAMADI")

s = s.replace(eski, yeni, 1)

eski2 = '''            "hacimli_kirilim": bool(hacimli_kirilim),
            "nedenler": nedenler,
'''

yeni2 = '''            "hacimli_kirilim": bool(hacimli_kirilim),
            "gun_ici_alim_alt": round(alim_alt, 2),
            "gun_ici_alim_ust": round(alim_ust, 2),
            "gun_ici_kar_al": round(kar_al, 2),
            "gun_ici_stop": round(stop, 2),
            "gun_ici_hacimli_kirilim": round(hacimli_kirilim_seviyesi, 2),
            "gun_ici_kirilim_hedef": round(kirilim_sonrasi_hedef, 2),
            "gun_ici_kirilim_durumu": kirilim_durumu,
            "nedenler": nedenler,
'''

if eski2 not in s:
    raise SystemExit("SONUC ALANI BULUNAMADI")

s = s.replace(eski2, yeni2, 1)

p.write_text(s, encoding="utf-8")

print("GUN ICI ALIM HEDEF STOP SEVIYELERI EKLENDI")