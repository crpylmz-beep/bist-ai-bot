p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

baslangic = s.find("def yarin_top10_mesaji(")
bitis = s.find(
    "# =========================================================\n# START MENÜ",
    baslangic
)

if baslangic == -1 or bitis == -1:
    raise SystemExit("YARIN TOP10 MESAJ BLOGU BULUNAMADI")

yeni = '''def yarin_top10_mesaji(sonuclar=None, toplam=None):

    kilitli = yarin_top10_kilitli_oku()

    if not kilitli:
        return (
            "🏆 YARIN İÇİN TOP 10\\n"
            "━━━━━━━━━━━━━━\\n\\n"
            "❌ Kilitli Yarın TOP10 listesi henüz oluşturulmadı.\\n\\n"
            "📌 Liste piyasa kapanışı sonrası oluşturulup "
            "ertesi işlem seansı için sabitlenir."
        )

    top10 = kilitli.get("top10", [])
    toplam_hisse = kilitli.get("toplam_hisse", 0)
    teknik_aday = kilitli.get("teknik_aday", 0)
    olusturma = kilitli.get("olusturma_zamani", "-")

    mesaj = (
        "🏆 YARIN İÇİN TOP 10\\n"
        "━━━━━━━━━━━━━━\\n\\n"
        f"🔒 Kilitli liste: {olusturma}\\n"
        f"🔎 Taranan hisse: {toplam_hisse}\\n"
        f"📊 Teknik aday: {teknik_aday}\\n\\n"
    )

    if not top10:
        mesaj += "❌ Yeterli teknik aday bulunamadı."
        return mesaj

    for i, a in enumerate(top10, 1):

        skor = int(
            guvenli_float(
                a.get("yarin_top10_puani")
            )
        )

        mesaj += (
            f"🏅 {i}. {a.get('sembol', '-')} — {skor}/100\\n"
            f"   💰 {guvenli_float(a.get('fiyat')):.2f} TL "
            f"({guvenli_float(a.get('degisim')):+.2f}%)\\n"
            f"   RSI {guvenli_float(a.get('rsi')):.1f} | "
            f"Hacim %{guvenli_float(a.get('hacim_orani')):.0f}\\n"
            f"   MACD: "
            f"{'Pozitif' if guvenli_float(a.get('macd')) > guvenli_float(a.get('signal')) else 'Negatif'}\\n"
            f"   Destek {guvenli_float(a.get('destek')):.2f} | "
            f"Direnç {guvenli_float(a.get('direnc')):.2f}\\n"
            f"   Hedef1 {guvenli_float(a.get('hedef1')):.2f} | "
            f"Stop {guvenli_float(a.get('stop')):.2f}\\n\\n"
        )

    mesaj += (
        "━━━━━━━━━━━━━━\\n"
        "🔒 Bu liste oluşturulduğu seans kapanışındaki "
        "verilerle sabitlenmiştir.\\n\\n"
        "⚠️ Algoritmik teknik potansiyeldir; "
        "yükseliş garantisi veya yatırım tavsiyesi değildir."
    )

    return mesaj


'''

s = s[:baslangic] + yeni + s[bitis:]

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 MESAJI KILITLI LISTEYE BAGLANDI")