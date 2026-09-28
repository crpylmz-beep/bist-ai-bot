import os
import borsapy as bp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

TOKEN = os.getenv("BOT_TOKEN")
print("TOKEN DURUMU:", bool(TOKEN), "UZUNLUK:", len(TOKEN) if TOKEN else 0)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📈 Hisse Özeti", callback_data="ozet")],
        [InlineKeyboardButton("📡 Sinyaller", callback_data="sinyal")]
    ]

    await update.message.reply_text(
        "🤖 BIST AI TERMINAL\n\nBir işlem seç:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ozet":
        context.user_data["hisse_bekleniyor"] = True
        context.user_data["mod"] = "ozet"

        await query.message.reply_text(
            "📈 HİSSE ÖZETİ\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: PSGYO"
        )

    elif query.data == "sinyal":
        context.user_data["hisse_bekleniyor"] = True
        context.user_data["mod"] = "sinyal"

        await query.message.reply_text(
            "📡 GELİŞMİŞ SİNYAL ANALİZİ\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: PSGYO"
        )


async def hisse_oku(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("hisse_bekleniyor"):
        return

    sembol = update.message.text.strip().upper()
    mod = context.user_data.get("mod")

    try:
        hisse = bp.Ticker(sembol)
        veri = hisse.history(period="3mo")

        if veri is None or veri.empty or len(veri) < 50:
            await update.message.reply_text(
                "❌ Bu hisse için yeterli veri bulunamadı."
            )
            return

        son = veri.iloc[-1]

        kapanis = float(son["Close"])
        onceki = float(veri.iloc[-2]["Close"])

        degisim = ((kapanis - onceki) / onceki) * 100

        # SMA
        sma20 = veri["Close"].rolling(20).mean().iloc[-1]
        sma50 = veri["Close"].rolling(50).mean().iloc[-1]

        # Hacim
        hacim = float(son["Volume"])
        hacim20 = veri["Volume"].rolling(20).mean().iloc[-1]

        hacim_orani = (hacim / hacim20) * 100 if hacim20 > 0 else 0

        # RSI 14
        delta = veri["Close"].diff()

        kazanc = delta.clip(lower=0)
        kayip = -delta.clip(upper=0)

        ort_kazanc = kazanc.rolling(14).mean()
        ort_kayip = kayip.rolling(14).mean()

        rs = ort_kazanc / ort_kayip
        rsi = 100 - (100 / (1 + rs))

        rsi_son = float(rsi.iloc[-1])

        # MACD
        ema12 = veri["Close"].ewm(span=12, adjust=False).mean()
        ema26 = veri["Close"].ewm(span=26, adjust=False).mean()

        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()

        macd_son = float(macd.iloc[-1])
        macd_signal_son = float(macd_signal.iloc[-1])

        # Önceki MACD değerleri
        macd_onceki = float(macd.iloc[-2])
        signal_onceki = float(macd_signal.iloc[-2])

        macd_yukseliyor = macd_son > macd_onceki

        # MACD kesişimi
        macd_al_kesisim = (
            macd_onceki <= signal_onceki
            and macd_son > macd_signal_son
        )

        macd_sat_kesisim = (
            macd_onceki >= signal_onceki
            and macd_son < macd_signal_son
        )

        if mod == "ozet":

            mesaj = (
                f"📊 {sembol} HİSSE ÖZETİ\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Son Fiyat: {kapanis:.2f} TL\n"
                f"📈 Günlük Değişim: {degisim:+.2f}%\n"
                f"🔺 Günlük Yüksek: {float(son['High']):.2f}\n"
                f"🔻 Günlük Düşük: {float(son['Low']):.2f}\n"
                f"🔵 Açılış: {float(son['Open']):.2f}\n"
                f"📦 Hacim: {hacim:,.0f}\n\n"
                f"📊 TEKNİK\n"
                f"20 Günlük Ortalama: {sma20:.2f}\n"
                f"50 Günlük Ortalama: {sma50:.2f}\n"
                f"RSI(14): {rsi_son:.2f}\n"
                f"MACD: {macd_son:.4f}\n"
                f"MACD Sinyal: {macd_signal_son:.4f}\n"
            )

        else:

            puan = 50
            nedenler = []

            # SMA20
            if kapanis > sma20:
                puan += 10
                nedenler.append("Fiyat SMA20 üzerinde")

            else:
                puan -= 10
                nedenler.append("Fiyat SMA20 altında")

            # SMA50
            if kapanis > sma50:
                puan += 10
                nedenler.append("Fiyat SMA50 üzerinde")

            else:
                puan -= 10
                nedenler.append("Fiyat SMA50 altında")

            # RSI
            if 50 <= rsi_son < 70:
                puan += 10
                nedenler.append("RSI pozitif bölgede")

            elif rsi_son >= 70:
                puan -= 5
                nedenler.append("RSI aşırı alım bölgesinde")

            elif rsi_son < 30:
                puan += 5
                nedenler.append("RSI aşırı satım bölgesinde")

            else:
                nedenler.append("RSI nötr bölgede")

            # MACD
            if macd_son > macd_signal_son:
                puan += 10
                nedenler.append("MACD sinyal çizgisinin üzerinde")

            else:
                puan -= 10
                nedenler.append("MACD sinyal çizgisinin altında")

            # MACD kesişimi
            if macd_al_kesisim:
                puan += 10
                nedenler.append("MACD yukarı kesişim yaptı")

            elif macd_sat_kesisim:
                puan -= 10
                nedenler.append("MACD aşağı kesişim yaptı")

            # MACD momentum
            if macd_yukseliyor:
                puan += 5
                nedenler.append("MACD yükseliyor")

            else:
                puan -= 5
                nedenler.append("MACD düşüyor")

            # Hacim
            if hacim > hacim20:
                puan += 10
                nedenler.append("Hacim 20G ortalamasının üzerinde")

            else:
                puan -= 5
                nedenler.append("Hacim 20G ortalamasının altında")

            # Günlük momentum
            if degisim > 0:
                puan += 5
                nedenler.append("Günlük momentum pozitif")

            elif degisim < 0:
                puan -= 5
                nedenler.append("Günlük momentum negatif")

            # Puan sınırı
            puan = max(0, min(100, puan))

            # Sinyal
            if rsi_son < 25 and macd_yukseliyor:
                sinyal = "🟠 AŞIRI SATIM / TEPKİ ADAYI"

            elif puan >= 70:
                sinyal = "🟢 AL ADAYI"

            elif puan <= 35:
                sinyal = "🔴 SAT ADAYI"

            else:
                sinyal = "🟡 BEKLE"

            # Risk durumu
            if rsi_son < 30:
                risk = "⚠️ RSI aşırı satım: sert tepki veya devam eden düşüş görülebilir."

            elif rsi_son > 70:
                risk = "⚠️ RSI aşırı alım bölgesinde."

            else:
                risk = "ℹ️ RSI aşırı satım/alım bölgesinde değil."

            mesaj = (
                f"📡 {sembol} GELİŞMİŞ SİNYAL\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Fiyat: {kapanis:.2f} TL\n"
                f"📈 Günlük: {degisim:+.2f}%\n\n"

                f"📊 GÖSTERGELER\n"
                f"RSI(14): {rsi_son:.2f}\n"
                f"SMA20: {sma20:.2f}\n"
                f"SMA50: {sma50:.2f}\n"
                f"MACD: {macd_son:.4f}\n"
                f"MACD Sinyal: {macd_signal_son:.4f}\n\n"

                f"📦 HACİM\n"
                f"Mevcut: {hacim:,.0f}\n"
                f"20G Ortalama: {hacim20:,.0f}\n"
                f"Hacim Oranı: %{hacim_orani:.1f}\n\n"

                f"🎯 SİNYAL\n"
                f"{sinyal}\n\n"

                f"⭐ TEKNİK PUAN: {puan}/100\n\n"

                f"🔎 GEREKÇELER\n"
            )

            for neden in nedenler:
                mesaj += f"• {neden}\n"

            mesaj += (
                f"\n{risk}\n\n"
                "⚠️ Bu sistem teknik göstergelerden "
                "algoritmik aday üretir. Kesin al/sat sonucu veya "
                "yatırım tavsiyesi değildir."
            )

        await update.message.reply_text(mesaj)

    except Exception as e:
        await update.message.reply_text(
            f"❌ Hata:\n{e}"
        )

    context.user_data["hisse_bekleniyor"] = False
    context.user_data["mod"] = None


app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buton))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, hisse_oku))

print("BIST AI Terminal çalışıyor...")

app.run_polling()
