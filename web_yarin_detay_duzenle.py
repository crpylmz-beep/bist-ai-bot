p = "webapp/index.html"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

# 1) Yarin detay degiskenlerine Satim Bolgesi ve ilk kirilim saatini ekle
eski1 = '''    const yarinAlimAlt = hisse.yarin_alim_alt ?? "-";
    const yarinAlimUst = hisse.yarin_alim_ust ?? "-";
    const yarinKarAl = hisse.yarin_kar_al ?? "-";
    const yarinStop = hisse.yarin_stop ?? "-";
    const yarinKirilim = hisse.yarin_kirilim ?? "-";
    const yarinKirilimHedef = hisse.yarin_kirilim_hedef ?? "-";
    const kirilimDurum = hisse.hacimli_kirilim_durum ?? "BEKLENIYOR";
'''

yeni1 = '''    const yarinAlimAlt = hisse.yarin_alim_alt ?? "-";
    const yarinAlimUst = hisse.yarin_alim_ust ?? "-";
    const yarinSatimAlt = hisse.yarin_satim_alt ?? "-";
    const yarinSatimUst = hisse.yarin_satim_ust ?? "-";
    const yarinKarAl = hisse.yarin_kar_al ?? "-";
    const yarinStop = hisse.yarin_stop ?? "-";
    const yarinKirilim = hisse.yarin_kirilim ?? "-";
    const yarinKirilimHedef = hisse.yarin_kirilim_hedef ?? "-";
    const kirilimDurum = hisse.hacimli_kirilim_durum ?? "BEKLENIYOR";
    const ilkHacimliKirilimSaati =
        hisse.ilk_hacimli_kirilim_saati ?? "-";

    const yarinTop10Detayi =
        oncekiSayfa === "top10";
'''

if eski1 not in s:
    raise SystemExit("YARIN DEGISKEN BLOGU BULUNAMADI")

s = s.replace(eski1, yeni1, 1)

# 2) Yarin detay kartini yenile
baslangic = s.find('        <div class="detail-card">', s.find('<b>📅 YARIN İÇİN</b>') - 100)
bitis = s.find('        <div class="detail-card">', s.find('<b>📈 ORTA / UZUN VADE</b>') - 100)

if baslangic == -1 or bitis == -1:
    raise SystemExit("YARIN DETAY KARTI BULUNAMADI")

yeni_kart = '''        <div class="detail-card">

            ${
                yarinTop10Detayi
                ? ""
                : "<b>📅 YARIN İÇİN</b>"
            }

            <div class="detail-grid" style="margin-top:12px">

                ${detayKutu(
                    "🟢 Alım Bölgesi",
                    fiyatYaz(yarinAlimAlt) + " - " + fiyatYaz(yarinAlimUst)
                )}

                ${detayKutu(
                    "🔴 Satım Bölgesi",
                    fiyatYaz(yarinSatimAlt) + " - " + fiyatYaz(yarinSatimUst)
                )}

                ${detayKutu(
                    "🎯 Kısa Vade Kâr Al",
                    fiyatYaz(yarinKarAl)
                )}

                ${detayKutu(
                    "🛑 Kısa Vade Stop",
                    fiyatYaz(yarinStop)
                )}

                ${detayKutu(
                    "🚀 Hacimli Kırılım",
                    fiyatYaz(yarinKirilim)
                )}

                ${detayKutu(
                    "🎯 Kırılım Sonrası Hedef",
                    fiyatYaz(yarinKirilimHedef)
                )}

                ${detayKutu(
                    "📊 Kırılım Durumu",
                    kirilimYazi
                )}

                ${detayKutu(
                    "🕐 İlk Hacimli Kırılım",
                    ilkHacimliKirilimSaati
                )}

            </div>

        </div>

'''

s = s[:baslangic] + yeni_kart + s[bitis:]

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 DETAY EKRANI DUZENLENDI")