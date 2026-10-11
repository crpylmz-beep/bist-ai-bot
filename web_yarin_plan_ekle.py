from pathlib import Path

p = Path("webapp/index.html")
s = p.read_text(encoding="utf-8")

eski1 = '''    const riskGetiri =
        hisse.risk_getiri ??
        "-";

    const tip ='''

yeni1 = '''    const riskGetiri =
        hisse.risk_getiri ??
        "-";

    const yarinAlimAlt = hisse.yarin_alim_alt ?? "-";
    const yarinAlimUst = hisse.yarin_alim_ust ?? "-";
    const yarinKarAl = hisse.yarin_kar_al ?? "-";
    const yarinStop = hisse.yarin_stop ?? "-";
    const yarinKirilim = hisse.yarin_kirilim ?? "-";
    const yarinKirilimHedef = hisse.yarin_kirilim_hedef ?? "-";
    const kirilimDurum = hisse.hacimli_kirilim_durum ?? "BEKLENIYOR";

    const fiyatYaz = (deger) => {
        const n = Number(deger);
        return Number.isFinite(n) ? n.toFixed(2) + " TL" : "-";
    };

    let kirilimYazi = "⚪ HACİMLİ KIRILIM BEKLENİYOR";

    if(kirilimDurum === "GERCEKLESTI"){
        kirilimYazi = "🟢 HACİMLİ KIRILIM GERÇEKLEŞTİ";
    }
    else if(kirilimDurum === "HACIM_ZAYIF"){
        kirilimYazi = "🟡 FİYAT KIRDI — HACİM TEYİDİ ZAYIF";
    }

    const tip ='''

if eski1 not in s:
    raise SystemExit("HATA: Degisken ekleme noktasi bulunamadi.")

s = s.replace(eski1, yeni1, 1)

eski2 = '''        <div class="detail-card">

            <b>🎯 İşlem Bölgeleri</b>

            <div class="detail-grid" style="margin-top:12px">

                ${detayKutu("Giriş Alt", girisAlt)}

                ${detayKutu("Giriş Üst", girisUst)}

                ${detayKutu("Hedef 1", hedef1)}

                ${detayKutu("Hedef 2", hedef2)}

                ${detayKutu("Stop", stop)}

                ${detayKutu("Destek", destek)}

                ${detayKutu("Direnç", direnc)}

            </div>

        </div>'''

yeni2 = '''        <div class="detail-card">

            <b>📅 YARIN İÇİN</b>

            <div class="detail-grid" style="margin-top:12px">

                ${detayKutu(
                    "🟢 Alım Bölgesi",
                    fiyatYaz(yarinAlimAlt) + " - " + fiyatYaz(yarinAlimUst)
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

            </div>

        </div>

        <div class="detail-card">

            <b>📈 ORTA / UZUN VADE</b>

            <div class="detail-grid" style="margin-top:12px">

                ${detayKutu(
                    "🟢 Alım Bölgesi",
                    fiyatYaz(girisAlt) + " - " + fiyatYaz(girisUst)
                )}

                ${detayKutu("🎯 Hedef 1", fiyatYaz(hedef1))}

                ${detayKutu("🎯 Hedef 2", fiyatYaz(hedef2))}

                ${detayKutu("🛑 Stop-Loss", fiyatYaz(stop))}

                ${detayKutu("🟡 Destek", fiyatYaz(destek))}

                ${detayKutu("🔴 Direnç", fiyatYaz(direnc))}

                ${detayKutu("⚖️ Risk/Getiri", riskGetiri)}

            </div>

        </div>'''

if eski2 not in s:
    raise SystemExit("HATA: Islem bolgeleri blogu bulunamadi.")

s = s.replace(eski2, yeni2, 1)

p.write_text(s, encoding="utf-8")

print("WEB YARIN PLANI VE HACIMLI KIRILIM EKRANI EKLENDI")