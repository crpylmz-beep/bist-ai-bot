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

        # Her hisse icin ayri chart session
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
# 50 HISSELIK GERCEK BIST TESTI
# =========================================================

tum_semboller = bist_bot.bist_hisseleri_getir()

# Daha once gecersiz oldugunu bildigimiz sembolleri atla
bilinen_gecersiz = bist_bot.gun_ici_gecersiz_oku()

gecerli_adaylar = [
    sembol
    for sembol in tum_semboller
    if sembol not in bilinen_gecersiz
]

semboller = gecerli_adaylar[:100]

print("Toplam BIST sembolu:", len(tum_semboller))
print("Onbellekte gecersiz:", len(bilinen_gecersiz))
print("Test edilecek:", len(semboller))
print()

s = MultiSessionStream()

baslangic = time.time()

print("Baglaniyor...")
s.connect()

print()
print("50 hisse ayri session ile abone ediliyor...")

for no, sembol in enumerate(semboller, 1):
    print(no, sembol)
    s.subscribe_multi(sembol, "5m")

print()
print("Veriler bekleniyor...")

time.sleep(10)

print()
print("SONUCLAR")
print("=" * 70)

basarili = 0
basarisiz = []

for no, sembol in enumerate(semboller, 1):

    mumlar = s.get_candles(sembol, "5m")

    if mumlar:
        basarili += 1
        son = mumlar[-1]

        print(
            no,
            sembol,
            "| Mum:", len(mumlar),
            "| Son:", son["close"],
            "| Zaman:", son["time"],
        )

    else:
        basarisiz.append(sembol)

        print(
            no,
            sembol,
            "| Mum: 0",
            "| VERI GELMEDI"
        )

print("=" * 70)

print()
print("Basarili:", basarili, "/", len(semboller))
print("Basarisiz:", len(basarisiz))

if basarisiz:
    print("Basarisiz semboller:", basarisiz)

print(
    "Toplam sure:",
    round(time.time() - baslangic, 1),
    "sn"
)

s.disconnect()