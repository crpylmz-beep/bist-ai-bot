p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

baslangic = s.find('    elif query.data == "top10":')
bitis = s.find(
    "# =========================================================\n# HİSSE OKU",
    baslangic
)

if baslangic == -1 or bitis == -1:
    raise SystemExit("TOP10 BUTON BLOGU BULUNAMADI")

yeni = '''    elif query.data == "top10":

        try:

            mesaj = yarin_top10_mesaji()

            parcalar = mesaj_parcala_gonder(
                update,
                mesaj
            )

            for parca in parcalar:

                await query.message.reply_text(
                    parca
                )

        except Exception as e:

            await query.message.reply_text(
                f"❌ TOP 10 liste hatası:\\n{e}"
            )


'''

s = s[:baslangic] + yeni + s[bitis:]

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 BUTONU KILITLI LISTEYE BAGLANDI")