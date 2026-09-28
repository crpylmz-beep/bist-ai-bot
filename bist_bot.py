import os
import borsapy as bp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

TOKEN = os.environ.get("BOT_TOKEN")

print(
    "TOKEN DURUMU:",
    bool(TOKEN),
    "UZUNLUK:",
    len(TOKEN) if TOKEN else 0
)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("📈 Hisse Özeti", callback_data="ozet")],
        [InlineKeyboardButton("📡 Sinyaller", callback_data="sinyal")],
        [InlineKeyboardButton("🔥 Agresif Hisse Bulucu", callback_data="agresif")]
    ]

    await update.message.reply_text(
        "🤖 BIST AI TERMINAL\n\n"
        "Bir işlem seç:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# BUTONLAR
# =========================================================

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

    elif query.data == "agresif":

        await agresif_tarama(update, context)


# =========================================================
# BIST GENELİ AGRESİF HİSSE TARAMASI
# =========================================================

async def agresif_tarama(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mesaj_gonder = update.callback_query.message

    await mesaj_gonder.reply_text(
        "🔥 BIST GENELİ AGRESİF TARAMA BAŞLIYOR...\n\n"
        "📊 BIST şirketleri otomatik olarak alınıyor.\n"
        "🔎 Teknik göstergeler hesaplanıyor.\n"
        "⏳ Çok sayıda hisse taranacağı için biraz sürebilir..."
    )

    try:

        # -------------------------------------------------
        # BIST ŞİRKET LİSTESİNİ OTOMATİK AL
        # -------------------------------------------------

        sirketler = bp.companies()

        if sirketler is None or sirketler.empty:

            await mesaj_gonder.reply_text(
                "❌ BIST şirket listesi alınamadı."
            )

            return

        # Ticker sütununu bul
        if "ticker" in sirketler.columns:

            hisseler = (
                sirketler["ticker"]
                .dropna()
                .astype(str)
                .str.upper()
                .str.strip()
                .tolist()
            )

        elif "symbol" in sirketler.columns:

            hisseler = (
                sirketler["symbol"]
                .dropna()
                .astype(str)
                .str.upper()
                .str.strip()
                .tolist()
            )

        else:

            await mesaj_gonder.reply_text(
                "❌ BIST şirket listesindeki hisse kodu sütunu bulunamadı."
            )

            return

        # Tekrarları kaldır
        hisseler = list(dict.fromkeys(hisseler))

        toplam_hisse = len(hisseler)

        await mesaj_gonder.reply_text(
            f"📊 BIST GENELİ TARAMA\n\n"
            f"🔎 Bulunan hisse: {toplam_hisse}\n"
            f"⏳ Teknik analiz başlıyor..."
        )

        adaylar = []

        taranan = 0

        # -------------------------------------------------
        # TÜM BIST HİSSELERİNİ TARA
        # -------------------------------------------------

        for sembol in hisseler:

            taranan += 1

            try:

                hisse = bp.Ticker(sembol)

                veri = hisse.history(period="3mo")

                if veri is None or veri.empty:
                    continue

                if len(veri) < 60:
                    continue

                # Gerekli sütunlar yoksa geç
                gerekli = [
                    "Close",
                    "High",
                    "Low",
                    "Volume"
                ]

                if not all(
                    sutun in veri.columns
                    for sutun in gerekli
                ):
                    continue

                # -------------------------------------------------
                # FİYAT
                # -------------------------------------------------

                kapanis = float(
                    veri["Close"].iloc[-1]
                )

                onceki = float(
                    veri["Close"].iloc[-2]
                )

                if kapanis <= 0 or onceki <= 0:
                    continue

                gunluk_degisim = (
                    (kapanis - onceki) / onceki
                ) * 100

                # -------------------------------------------------
                # SMA
                # -------------------------------------------------

                sma20 = float(
                    veri["Close"]
                    .rolling(20)
                    .mean()
                    .iloc[-1]
                )

                sma50 = float(
                    veri["Close"]
                    .rolling(50)
                    .mean()
                    .iloc[-1]
                )

                if sma20 <= 0 or sma50 <= 0:
                    continue

                # -------------------------------------------------
                # RSI
                # -------------------------------------------------

                delta = veri["Close"].diff()

                kazanc = delta.clip(lower=0)
                kayip = -delta.clip(upper=0)

                ort_kazanc = (
                    kazanc
                    .rolling(14)
                    .mean()
                )

                ort_kayip = (
                    kayip
                    .rolling(14)
                    .mean()
                )

                rs = ort_kazanc / ort_kayip

                rsi = 100 - (
                    100 / (1 + rs)
                )

                rsi_son = float(
                    rsi.iloc[-1]
                )

                if rsi_son != rsi_son:
                    continue

                # -------------------------------------------------
                # MACD
                # -------------------------------------------------

                ema12 = (
                    veri["Close"]
                    .ewm(
                        span=12,
                        adjust=False
                    )
                    .mean()
                )

                ema26 = (
                    veri["Close"]
                    .ewm(
                        span=26,
                        adjust=False
                    )
                    .mean()
                )

                macd = ema12 - ema26

                macd_signal = (
                    macd
                    .ewm(
                        span=9,
                        adjust=False
                    )
                    .mean()
                )

                macd_son = float(
                    macd.iloc[-1]
                )

                macd_onceki = float(
                    macd.iloc[-2]
                )

                macd_signal_son = float(
                    macd_signal.iloc[-1]
                )

                macd_signal_onceki = float(
                    macd_signal.iloc[-2]
                )

                macd_yukseliyor = (
                    macd_son > macd_onceki
                )

                macd_ustunde = (
                    macd_son > macd_signal_son
                )

                macd_al_kesisim = (
                    macd_onceki
                    <= macd_signal_onceki
                    and
                    macd_son
                    > macd_signal_son
                )

                # -------------------------------------------------
                # HACİM
                # -------------------------------------------------

                hacim = float(
                    veri["Volume"].iloc[-1]
                )

                hacim20 = float(
                    veri["Volume"]
                    .rolling(20)
                    .mean()
                    .iloc[-1]
                )

                if hacim20 <= 0:
                    continue

                hacim_orani = (
                    hacim / hacim20
                ) * 100

                # -------------------------------------------------
                # DESTEK / DİRENÇ
                # -------------------------------------------------

                son20 = veri.tail(20)

                destek = float(
                    son20["Low"].min()
                )

                direnc = float(
                    son20["High"].max()
                )

                if destek <= 0 or direnc <= 0:
                    continue

                # -------------------------------------------------
                # TEKNİK PUAN
                # -------------------------------------------------

                puan = 0

                nedenler = []

                # RSI
                if 25 <= rsi_son < 30:

                    puan += 20

                    nedenler.append(
                        "RSI aşırı satıma yakın"
                    )

                elif 30 <= rsi_son < 40:

                    puan += 15

                    nedenler.append(
                        "RSI düşük bölgede"
                    )

                elif 40 <= rsi_son < 55:

                    puan += 8

                    nedenler.append(
                        "RSI dengeli"
                    )

                elif rsi_son < 25:

                    puan += 10

                    nedenler.append(
                        "RSI aşırı satım"
                    )

                # MACD yükselişi
                if macd_yukseliyor:

                    puan += 15

                    nedenler.append(
                        "MACD yükseliyor"
                    )

                # MACD sinyal üstü
                if macd_ustunde:

                    puan += 15

                    nedenler.append(
                        "MACD sinyal üzerinde"
                    )

                # MACD yukarı kesişim
                if macd_al_kesisim:

                    puan += 15

                    nedenler.append(
                        "MACD yukarı kesişim"
                    )

                # Hacim
                if hacim_orani >= 200:

                    puan += 20

                    nedenler.append(
                        "Hacim çok güçlü"
                    )

                elif hacim_orani >= 150:

                    puan += 15

                    nedenler.append(
                        "Hacim güçlü"
                    )

                elif hacim_orani >= 120:

                    puan += 10

                    nedenler.append(
                        "Hacim ortalamanın üzerinde"
                    )

                elif hacim_orani >= 100:

                    puan += 5

                # SMA20
                if kapanis > sma20:

                    puan += 8

                    nedenler.append(
                        "Fiyat SMA20 üzerinde"
                    )

                else:

                    puan -= 5

                # SMA50
                if kapanis > sma50:

                    puan += 7

                    nedenler.append(
                        "Fiyat SMA50 üzerinde"
                    )

                else:

                    puan -= 5

                # Günlük momentum
                if gunluk_degisim > 0:

                    puan += 5

                    nedenler.append(
                        "Günlük momentum pozitif"
                    )

                # Destekten uzaklık
                destek_uzaklik = (
                    (kapanis - destek)
                    / destek
                ) * 100

                if 0 <= destek_uzaklik <= 5:

                    puan += 5

                    nedenler.append(
                        "Fiyat desteğe yakın"
                    )

                # -------------------------------------------------
                # PUANI 0-100 ARASINA SINIRLA
                # -------------------------------------------------

                puan = max(
                    0,
                    min(100, puan)
                )

                # -------------------------------------------------
                # AGRESİF ADAY KRİTERİ
                # -------------------------------------------------

                agresif = False

                if puan >= 45:

                    agresif = True

                # Çok yüksek hacimli ve RSI düşük hisseler
                if (
                    hacim_orani >= 150
                    and rsi_son < 35
                    and macd_yukseliyor
                ):

                    agresif = True

                # MACD yukarı kesişim + hacim
                if (
                    macd_al_kesisim
                    and hacim_orani >= 120
                ):

                    agresif = True

                if not agresif:
                    continue

                # -------------------------------------------------
                # ALIM / HEDEF / STOP
                # -------------------------------------------------

                al_alt = destek * 0.99
                al_ust = destek * 1.03

                hedef1 = kapanis + (
                    (direnc - kapanis) * 0.50
                )

                hedef2 = direnc

                stop = destek * 0.97

                # -------------------------------------------------
                # ADAYI KAYDET
                # -------------------------------------------------

                adaylar.append(
                    {
                        "sembol": sembol,
                        "puan": puan,
                        "fiyat": kapanis,
                        "rsi": rsi_son,
                        "hacim": hacim_orani,
                        "sma20": sma20,
                        "sma50": sma50,
                        "degisim": gunluk_degisim,
                        "macd_yukseliyor": macd_yukseliyor,
                        "macd_ustunde": macd_ustunde,
                        "macd_kesisim": macd_al_kesisim,
                        "destek": destek,
                        "direnc": direnc,
                        "al_alt": al_alt,
                        "al_ust": al_ust,
                        "hedef1": hedef1,
                        "hedef2": hedef2,
                        "stop": stop,
                        "nedenler": nedenler
                    }
                )

            except Exception:
                continue

        # -------------------------------------------------
        # PUANA GÖRE SIRALA
        # -------------------------------------------------

        adaylar.sort(
            key=lambda x: (
                x["puan"],
                x["hacim"]
            ),
            reverse=True
        )

        # -------------------------------------------------
        # SONUÇ
        # -------------------------------------------------

        if not adaylar:

            await mesaj_gonder.reply_text(
                "🔎 BIST GENELİ TARAMA TAMAMLANDI.\n\n"
                f"📊 Taranan hisse: {taranan}\n"
                "🔥 Uygun agresif aday bulunamadı."
            )

            return

        en_iyi = adaylar[:10]

        mesaj = (
            "🔥 BIST GENELİ AGRESİF TARAMA\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📊 Taranan: {taranan} hisse\n"
            f"🔥 Agresif aday: {len(adaylar)}\n"
            "🏆 En yüksek teknik puanlı 10 hisse:\n\n"
        )

        # -------------------------------------------------
        # EN İYİ 10
        # -------------------------------------------------

        for sira, aday in enumerate(
            en_iyi,
            1
        ):

            sembol = aday["sembol"]
            puan = aday["puan"]
            fiyat = aday["fiyat"]
            rsi = aday["rsi"]
            hacim = aday["hacim"]
            degisim = aday["degisim"]

            if aday["macd_kesisim"]:

                macd_durum = "🟢 Yukarı kesişim"

            elif aday["macd_yukseliyor"]:

                macd_durum = "🟢 Yükseliyor"

            elif aday["macd_ustunde"]:

                macd_durum = "🟡 Sinyal üstü"

            else:

                macd_durum = "🔴 Zayıf"

            mesaj += (
                f"{sira}. 🔥 {sembol}\n"
                f"⭐ Teknik Güven Puanı: {puan}/100\n"
                f"💰 Fiyat: {fiyat:.2f} TL\n"
                f"📈 Günlük: {degisim:+.2f}%\n"
                f"RSI: {rsi:.2f}\n"
                f"📦 Hacim: %{hacim:.1f}\n"
                f"📊 MACD: {macd_durum}\n"
                f"📉 SMA20: "
                f"{'ÜZERİNDE' if fiyat > aday['sma20'] else 'ALTINDA'}\n"
                f"📉 SMA50: "
                f"{'ÜZERİNDE' if fiyat > aday['sma50'] else 'ALTINDA'}\n"
                f"🎯 Destek: {aday['destek']:.2f} TL\n"
                f"🚧 Direnç: {aday['direnc']:.2f} TL\n"
                f"💰 Alım bölgesi: "
                f"{aday['al_alt']:.2f} - "
                f"{aday['al_ust']:.2f} TL\n"
                f"🎯 Hedef 1: {aday['hedef1']:.2f} TL\n"
                f"🎯 Hedef 2: {aday['hedef2']:.2f} TL\n"
                f"🛑 Stop: {aday['stop']:.2f} TL\n"
            )

            if aday["nedenler"]:

                mesaj += "🔎 Nedenler:\n"

                for neden in aday["nedenler"][:4]:

                    mesaj += f"• {neden}\n"

            mesaj += "\n"

        mesaj += (
            "━━━━━━━━━━━━━━\n"
            "⚠️ Sıralama teknik göstergelerin "
            "algoritmik puanlamasına göredir.\n"
            "⚠️ 'Teknik Güven Puanı' kesin yükseliş "
            "veya kazanç garantisi değildir.\n"
            "⚠️ Yatırım tavsiyesi değildir."
        )

        await mesaj_gonder.reply_text(
            mesaj
        )

    except Exception as e:

        await mesaj_gonder.reply_text(
            f"❌ Agresif tarama hatası:\n{e}"
        )


# =========================================================
# HİSSE OKUMA
# =========================================================

async def hisse_oku(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get(
        "hisse_bekleniyor"
    ):
        return

    sembol = (
        update.message.text
        .strip()
        .upper()
    )

    mod = context.user_data.get(
        "mod"
    )

    try:

        hisse = bp.Ticker(sembol)

        veri = hisse.history(
            period="3mo"
        )

        if veri is None or veri.empty or len(veri) < 50:

            await update.message.reply_text(
                "❌ Bu hisse için yeterli veri bulunamadı."
            )

            return

        son = veri.iloc[-1]

        kapanis = float(
            son["Close"]
        )

        onceki = float(
            veri.iloc[-2]["Close"]
        )

        degisim = (
            (kapanis - onceki)
            / onceki
        ) * 100

        # -------------------------------------------------
        # SMA
        # -------------------------------------------------

        sma20 = (
            veri["Close"]
            .rolling(20)
            .mean()
            .iloc[-1]
        )

        sma50 = (
            veri["Close"]
            .rolling(50)
            .mean()
            .iloc[-1]
        )

        # -------------------------------------------------
        # HACİM
        # -------------------------------------------------

        hacim = float(
            son["Volume"]
        )

        hacim20 = (
            veri["Volume"]
            .rolling(20)
            .mean()
            .iloc[-1]
        )

        hacim_orani = (
            (hacim / hacim20) * 100
            if hacim20 > 0
            else 0
        )

        # -------------------------------------------------
        # RSI
        # -------------------------------------------------

        delta = veri["Close"].diff()

        kazanc = delta.clip(
            lower=0
        )

        kayip = -delta.clip(
            upper=0
        )

        ort_kazanc = (
            kazanc
            .rolling(14)
            .mean()
        )

        ort_kayip = (
            kayip
            .rolling(14)
            .mean()
        )

        rs = (
            ort_kazanc
            / ort_kayip
        )

        rsi = 100 - (
            100 / (1 + rs)
        )

        rsi_son = float(
            rsi.iloc[-1]
        )

        # -------------------------------------------------
        # MACD
        # -------------------------------------------------

        ema12 = (
            veri["Close"]
            .ewm(
                span=12,
                adjust=False
            )
            .mean()
        )

        ema26 = (
            veri["Close"]
            .ewm(
                span=26,
                adjust=False
            )
            .mean()
        )

        macd = ema12 - ema26

        macd_signal = (
            macd
            .ewm(
                span=9,
                adjust=False
            )
            .mean()
        )

        macd_son = float(
            macd.iloc[-1]
        )

        macd_signal_son = float(
            macd_signal.iloc[-1]
        )

        macd_onceki = float(
            macd.iloc[-2]
        )

        signal_onceki = float(
            macd_signal.iloc[-2]
        )

        macd_yukseliyor = (
            macd_son > macd_onceki
        )

        # -------------------------------------------------
        # DESTEK / DİRENÇ
        # -------------------------------------------------

        son_20 = veri.tail(20)

        destek = float(
            son_20["Low"].min()
        )

        direnc = float(
            son_20["High"].max()
        )

        # AL bölgesi
        al_alt = destek * 0.99
        al_ust = destek * 1.03

        # Hedefler
        hedef1 = kapanis + (
            (direnc - kapanis) * 0.50
        )

        hedef2 = direnc

        # Stop
        risk_seviyesi = (
            destek * 0.97
        )

        # SAT bölgesi
        sat_alt = direnc * 0.97
        sat_ust = direnc

        # -------------------------------------------------
        # MACD KESİŞİM
        # -------------------------------------------------

        macd_al_kesisim = (
            macd_onceki <= signal_onceki
            and
            macd_son > macd_signal_son
        )

        macd_sat_kesisim = (
            macd_onceki >= signal_onceki
            and
            macd_son < macd_signal_son
        )

        # =================================================
        # HİSSE ÖZETİ
        # =================================================

        if mod == "ozet":

            mesaj = (
                f"📊 {sembol} HİSSE ÖZETİ\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Son Fiyat: "
                f"{kapanis:.2f} TL\n"
                f"📈 Günlük Değişim: "
                f"{degisim:+.2f}%\n"
                f"🔺 Günlük Yüksek: "
                f"{float(son['High']):.2f}\n"
                f"🔻 Günlük Düşük: "
                f"{float(son['Low']):.2f}\n"
                f"🔵 Açılış: "
                f"{float(son['Open']):.2f}\n"
                f"📦 Hacim: "
                f"{hacim:,.0f}\n\n"
                f"📊 TEKNİK\n"
                f"20 Günlük Ortalama: "
                f"{sma20:.2f}\n"
                f"50 Günlük Ortalama: "
                f"{sma50:.2f}\n"
                f"RSI(14): "
                f"{rsi_son:.2f}\n"
                f"MACD: "
                f"{macd_son:.4f}\n"
                f"MACD Sinyal: "
                f"{macd_signal_son:.4f}\n"
            )

        # =================================================
        # GELİŞMİŞ SİNYAL
        # =================================================

        else:

            puan = 50

            nedenler = []

            # SMA20
            if kapanis > sma20:

                puan += 10

                nedenler.append(
                    "Fiyat SMA20 üzerinde"
                )

            else:

                puan -= 10

                nedenler.append(
                    "Fiyat SMA20 altında"
                )

            # SMA50
            if kapanis > sma50:

                puan += 10

                nedenler.append(
                    "Fiyat SMA50 üzerinde"
                )

            else:

                puan -= 10

                nedenler.append(
                    "Fiyat SMA50 altında"
                )

            # RSI
            if 50 <= rsi_son < 70:

                puan += 10

                nedenler.append(
                    "RSI pozitif bölgede"
                )

            elif rsi_son >= 70:

                puan -= 5

                nedenler.append(
                    "RSI aşırı alım bölgesinde"
                )

            elif rsi_son < 30:

                puan += 5

                nedenler.append(
                    "RSI aşırı satım bölgesinde"
                )

            else:

                nedenler.append(
                    "RSI nötr bölgede"
                )

            # MACD
            if macd_son > macd_signal_son:

                puan += 10

                nedenler.append(
                    "MACD sinyal çizgisinin üzerinde"
                )

            else:

                puan -= 10

                nedenler.append(
                    "MACD sinyal çizgisinin altında"
                )

            # MACD kesişimi
            if macd_al_kesisim:

                puan += 10

                nedenler.append(
                    "MACD yukarı kesişim yaptı"
                )

            elif macd_sat_kesisim:

                puan -= 10

                nedenler.append(
                    "MACD aşağı kesişim yaptı"
                )

            # MACD momentum
            if macd_yukseliyor:

                puan += 5

                nedenler.append(
                    "MACD yükseliyor"
                )

            else:

                puan -= 5

                nedenler.append(
                    "MACD düşüyor"
                )

            # Hacim
            if hacim > hacim20:

                puan += 10

                nedenler.append(
                    "Hacim 20G ortalamasının üzerinde"
                )

            else:

                puan -= 5

                nedenler.append(
                    "Hacim 20G ortalamasının altında"
                )

            # Günlük momentum
            if degisim > 0:

                puan += 5

                nedenler.append(
                    "Günlük momentum pozitif"
                )

            elif degisim < 0:

                puan -= 5

                nedenler.append(
                    "Günlük momentum negatif"
                )

            # Puan sınırı
            puan = max(
                0,
                min(100, puan)
            )

            # Sinyal
            if (
                rsi_son < 25
                and macd_yukseliyor
            ):

                sinyal = (
                    "🟠 AŞIRI SATIM / "
                    "TEPKİ ADAYI"
                )

            elif (
                rsi_son < 25
                and puan <= 35
            ):

                sinyal = (
                    "🟠 AŞIRI SATIM / "
                    "RİSKLİ BÖLGE"
                )

            elif puan >= 70:

                sinyal = "🟢 AL ADAYI"

            elif puan <= 35:

                sinyal = (
                    "🔴 SAT / "
                    "RİSK AZALT ADAYI"
                )

            else:

                sinyal = "🟡 BEKLE"

            # Risk
            if rsi_son < 30:

                risk = (
                    "⚠️ RSI aşırı satım: "
                    "sert tepki veya devam eden "
                    "düşüş görülebilir."
                )

            elif rsi_son > 70:

                risk = (
                    "⚠️ RSI aşırı alım bölgesinde."
                )

            else:

                risk = (
                    "ℹ️ RSI aşırı satım/alım "
                    "bölgesinde değil."
                )

            mesaj = (
                f"📡 {sembol} GELİŞMİŞ SİNYAL\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Fiyat: "
                f"{kapanis:.2f} TL\n"
                f"📈 Günlük: "
                f"{degisim:+.2f}%\n\n"

                f"📊 GÖSTERGELER\n"
                f"RSI(14): "
                f"{rsi_son:.2f}\n"
                f"SMA20: "
                f"{sma20:.2f}\n"
                f"SMA50: "
                f"{sma50:.2f}\n"
                f"MACD: "
                f"{macd_son:.4f}\n"
                f"MACD Sinyal: "
                f"{macd_signal_son:.4f}\n\n"

                f"📦 HACİM\n"
                f"Mevcut: "
                f"{hacim:,.0f}\n"
                f"20G Ortalama: "
                f"{hacim20:,.0f}\n"
                f"Hacim Oranı: "
                f"%{hacim_orani:.1f}\n\n"

                f"🎯 SİNYAL\n"
                f"{sinyal}\n\n"

                f"⭐ TEKNİK PUAN: "
                f"{puan}/100\n\n"

                f"💰 ALIM BÖLGESİ\n"
                f"{al_alt:.2f} - "
                f"{al_ust:.2f} TL\n\n"

                f"🔴 SATIŞ BÖLGESİ\n"
                f"{sat_alt:.2f} - "
                f"{sat_ust:.2f} TL\n\n"

                f"🎯 HEDEFLER\n"
                f"1. Hedef: "
                f"{hedef1:.2f} TL\n"
                f"2. Hedef: "
                f"{hedef2:.2f} TL\n\n"

                f"🛑 RİSK / STOP\n"
                f"{risk_seviyesi:.2f} TL\n\n"

                f"🔎 GEREKÇELER\n"
            )

            for neden in nedenler:

                mesaj += (
                    f"• {neden}\n"
                )

            mesaj += (
                f"\n{risk}\n\n"
                "⚠️ Bu sistem teknik "
                "göstergelerden algoritmik "
                "aday üretir. Kesin al/sat "
                "sonucu veya yatırım tavsiyesi değildir."
            )

        await update.message.reply_text(
            mesaj
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Hata:\n{e}"
        )

    context.user_data[
        "hisse_bekleniyor"
    ] = False

    context.user_data[
        "mod"
    ] = None


# =========================================================
# TELEGRAM UYGULAMASI
# =========================================================

app = (
    Application
    .builder()
    .token(TOKEN)
    .build()
)

app.add_handler(
    CommandHandler(
        "start",
        start
    )
)

app.add_handler(
    CallbackQueryHandler(
        buton
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        hisse_oku
    )
)

print(
    "BIST AI Terminal çalışıyor..."
)

app.run_polling()
