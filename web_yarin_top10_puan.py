p = "webapp/index.html"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

eski = '''    const tepkiSayfasi = sayfaTipi === "GUCLU_TEPKI" || sayfaTipi === "TEPKI_TOP10";
    const puan = tepkiSayfasi ? Number(hisse.tepki_puani || 0) : puanGetir(hisse);
    const puanEtiketi = tepkiSayfasi ? "Tepki" : "AI";
'''

yeni = '''    const tepkiSayfasi =
        sayfaTipi === "GUCLU_TEPKI" ||
        sayfaTipi === "TEPKI_TOP10";

    const yarinTop10Sayfasi =
        sayfaTipi === "YARIN_TOP10";

    const puan = yarinTop10Sayfasi
        ? Number(hisse.yarin_top10_puani || 0)
        : tepkiSayfasi
            ? Number(hisse.tepki_puani || 0)
            : puanGetir(hisse);

    const puanEtiketi = yarinTop10Sayfasi
        ? "Yarın"
        : tepkiSayfasi
            ? "Tepki"
            : "AI";
'''

if eski not in s:
    raise SystemExit("HISSE SATIRI PUAN BLOGU BULUNAMADI")

s = s.replace(eski, yeni, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 GERCEK PUANI WEBE BAGLANDI")