import json
import time
import borsapy as bp
import bist_bot


class MultiSessionStream(bp.TradingViewStream):

    def __init__(self):
        super().__init__()
        self._multi_sessions = {}

    def subscribe_multi(self, symbol, interval="5m", exchange="BIST"):
        tv_interval = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "1d": "1D",
        }.get(interval, interval)

        session_id = self._generate_session_id("cs")
        self._multi_sessions[session_id] = (symbol, interval)

        if symbol not in self._chart_data:
            self._chart_data[symbol] = {}

        self._chart_data[symbol][interval] = []

        self._send(
            self._create_message(
                "chart_create_session",
                [session_id],
            )
        )

        resolve_id = "ser_1"
        price_id = "$prices"
        series_index = "s1"

        symbol_config = json.dumps({
            "symbol": f"{exchange}:{symbol}",
            "adjustment": "splits",
            "session": "regular",
        })

        self._send(
            self._create_message(
                "resolve_symbol",
                [
                    session_id,
                    resolve_id,
                    f"={symbol_config}",
                ],
            )
        )

        self._send(
            self._create_message(
                "create_series",
                [
                    session_id,
                    price_id,
                    series_index,
                    resolve_id,
                    tv_interval,
                    300,
                ],
            )
        )

    def _handle_chart_data(self, params):
        if len(params) < 2:
            return

        session_id = params[0]
        data = params[1]

        if session_id not in self._multi_sessions:
            return

        symbol, interval = self._multi_sessions[session_id]

        if not isinstance(data, dict):
            return

        candles = []

        for series_key, series_data in data.items():

            if not isinstance(series_data, dict):
                continue

            bars = series_data.get(
                "s",
                series_data.get("st", [])
            )

            if not isinstance(bars, list):
                continue

            for bar in bars:
                if isinstance(bar, dict) and "v" in bar:
                    v = bar["v"]

                    if len(v) >= 5:
                        candles.append({
                            "time": int(v[0]),
                            "open": float(v[1]),
                            "high": float(v[2]),
                            "low": float(v[3]),
                            "close": float(v[4]),
                            "volume": (
                                float(v[5])
                                if len(v) >= 6 and v[5]
                                else 0
                            ),
                        })

        if candles:
            self._update_chart_data(
                symbol,
                interval,
                candles
            )


# =========================================================
# TUM BIST - 100'ER HISSELIK PAKET TESTI
# =========================================================

tum_semboller = bist_bot.bist_hisseleri_getir()
bilinen_gecersiz = bist_bot.gun_ici_gecersiz_oku()

semboller = [
    sembol
    for sembol in tum_semboller
    if sembol not in bilinen_gecersiz
]

PAKET_BOYUTU = 100

paketler = [
    semboller[i:i + PAKET_BOYUTU]
    for i in range(0, len(semboller), PAKET_BOYUTU)
]

print("Toplam BIST sembolu:", len(tum_semboller))
print("Onbellekte gecersiz:", len(bilinen_gecersiz))
print("Taranacak:", len(semboller))
print("Paket sayisi:", len(paketler))
print()

genel_baslangic = time.time()

tum_veriler = {}
tum_basarisiz = []

for paket_no, paket in enumerate(paketler, 1):

    print()
    print("=" * 70)
    print(
        f"PAKET {paket_no}/{len(paketler)} "
        f"- {len(paket)} HISSE"
    )
    print("=" * 70)

    s = MultiSessionStream()

    paket_baslangic = time.time()

    print("Baglaniyor...")
    s.connect()

    print("Abonelikler gonderiliyor...")

    for sembol in paket:
        s.subscribe_multi(sembol, "5m")

    print("Veriler bekleniyor...")
    time.sleep(10)

    paket_basarili = 0
    paket_basarisiz = []

    for sembol in paket:

        mumlar = s.get_candles(sembol, "5m")

        if mumlar:
            paket_basarili += 1
            tum_veriler[sembol] = mumlar
        else:
            paket_basarisiz.append(sembol)
            tum_basarisiz.append(sembol)

    print(
        "Paket sonucu:",
        paket_basarili,
        "/",
        len(paket)
    )

    if paket_basarisiz:
        print(
            "Veri gelmeyen:",
            paket_basarisiz
        )

    print(
        "Paket suresi:",
        round(time.time() - paket_baslangic, 1),
        "sn"
    )

    s.disconnect()

    # Sunucuyu paketler arasinda biraz dinlendir
    time.sleep(1)


print()
print("=" * 70)
print("GENEL SONUC")
print("=" * 70)

print("Taranan:", len(semboller))
print("Basarili:", len(tum_veriler))
print("Basarisiz:", len(tum_basarisiz))

if tum_basarisiz:
    print("Basarisiz semboller:")
    print(tum_basarisiz)

print(
    "TOPLAM SURE:",
    round(time.time() - genel_baslangic, 1),
    "sn"
)

print()
print("ORNEK SON VERILER")
print("=" * 70)

for sembol in list(tum_veriler.keys())[:10]:
    son = tum_veriler[sembol][-1]

    print(
        sembol,
        "| Mum:", len(tum_veriler[sembol]),
        "| Son:", son["close"],
        "| Zaman:", son["time"]
    )