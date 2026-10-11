from pathlib import Path

p = Path("webapp/index.html")
s = p.read_text(encoding="utf-8")

# ---------------------------------------------------------
# 1) GUN ICI DEGISKENLERI
# ---------------------------------------------------------

eski = '''    const kirilimDurum = hisse.hacimli_kirilim_durum ?? "BEKLENIYOR";

    const fiyatYaz = (deger) => {'''

yeni = '''    const kirilimDurum = hisse.hacimli_kirilim_durum ?? "BEKLENIYOR";

    const gunIciMi = oncekiSayfa === "gunici_top10";

    const gunIciAlimAlt =
        hisse.gun_ici_alim_alt ?? "-";

    const gunIciAlimUst =
        hisse.gun_ici_alim_ust ?? "-";

    const gunIciKarAl =
        hisse.gun_ici_kar_al ?? "-";

    const gunIciStop =
        hisse.gun_ici_stop ?? "-";

    const gunIciKirilim =
        hisse.gun_ici_hacimli_kirilim ?? "-";

    const gunIciKirilimHedef =
        hisse.gun_ici_kirilim_hedef ?? "-";

    const gunIciKirilimDurumu =
        hisse.gun_ici_kirilim_durumu ??
        "HACIMLI KIRILIM BEKLENIYOR";

    const fiyatYaz = (deger) => {'''

if eski not in s:
    raise SystemExit("GUN ICI DEGISKEN YERI BULUNAMADI")

s = s.replace(eski, yeni, 1)


# ---------------------------------------------------------
# 2) GUN ICI KIRILIM YAZISI
# ---------------------------------------------------------

eski = '''    const tip =
        hisse.sinyal ??'''

yeni = '''    let gunIciKirilimYazi =
        "⚪ HACİMLİ KIRILIM BEKLENİYOR";

    if(gunIciKirilimDurumu === "HACIMLI KIRILIM VAR"){
        gunIciKirilimYazi =
            "🟢 HACİMLİ KIRILIM GERÇEKLEŞTİ";
    }
    else if(
        gunIciKirilimDurumu ===
        "DIRENC KIRILDI - HACIM TEYIDI BEKLENIYOR"
    ){
        gunIciKirilimYazi =
            "🟡 DİRENÇ KIRILDI — HACİM TEYİDİ BEKLENİYOR";
    }

    const tip =
        hisse.sinyal ??'''

if eski not in s:
    raise SystemExit("KIRILIM YAZISI YERI BULUNAMADI")

s = s.replace(eski, yeni, 1)


# ---------------------------------------------------------
# 3) YARIN ICIN KARTININ USTUNE GUN ICI KARTI
# ---------------------------------------------------------

eski = '''        <div class="detail-card">

            <b>📅 YARIN İÇİN</b>'''

yeni = '''        ${
            gunIciMi
            ? `
        <div class="detail-card">

            <b>⚡ GÜN İÇİ</b>

            <div class="detail-grid" style="margin-top:12px">

                ${detayKutu(
                    "🟢 Alım Bölgesi",
                    fiyatYaz(gunIciAlimAlt) +
                    " - " +
                    fiyatYaz(gunIciAlimUst)
                )}

                ${detayKutu(
                    "🎯 Kısa Vade Kâr Al",
                    fiyatYaz(gunIciKarAl)
                )}

                ${detayKutu(
                    "🛑 Kısa Vade Stop",
                    fiyatYaz(gunIciStop)
                )}

                ${detayKutu(
                    "🚀 Hacimli Kırılım",
                    fiyatYaz(gunIciKirilim)
                )}

                ${detayKutu(
                    "🎯 Kırılım Sonrası Hedef",
                    fiyatYaz(gunIciKirilimHedef)
                )}

                ${detayKutu(
                    "📊 Kırılım Durumu",
                    gunIciKirilimYazi
                )}

            </div>

        </div>
            `
            : ""
        }

        <div class="detail-card">

            <b>📅 YARIN İÇİN</b>'''

if eski not in s:
    raise SystemExit("YARIN ICIN KARTI BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("WEB GUN ICI DETAY BOLUMU EKLENDI")