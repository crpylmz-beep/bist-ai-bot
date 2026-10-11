import json
import time
import borsapy as bp


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

        # Yeni chart session
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

        # Sembolü çöz
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

        # 300 adet 5 dakikalik mum iste
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
# 10 HISSELIK TEST
# =========================================================

semboller = [
    "THYAO",
    "SKTAS",
    "TATGD",
    "TRENJ",
    "GLYHO",
    "POLHO",
    "MACKO",
    "TRCAS",
    "ANGEN",
    "DERIM",
]

s = MultiSessionStream()

baslangic = time.time()

print("Baglaniyor...")
s.connect()

print()
print("10 hisse ayri session ile abone ediliyor...")

for sembol in semboller:
    print("Abone:", sembol)
    s.subscribe_multi(sembol, "5m")

print()
print("Veriler bekleniyor...")

time.sleep(8)

print()
print("SONUCLAR")
print("=" * 60)

basarili = 0

for sembol in semboller:
    mumlar = s.get_candles(sembol, "5m")

    if mumlar:
        basarili += 1
        son = mumlar[-1]

        print(
            sembol,
            "| Mum:", len(mumlar),
            "| Son:", son["close"],
            "| Zaman:", son["time"],
        )
    else:
        print(
            sembol,
            "| Mum: 0",
            "| VERI GELMEDI"
        )

print("=" * 60)

print()
print("Basarili:", basarili, "/", len(semboller))
print(
    "Toplam sure:",
    round(time.time() - baslangic, 1),
    "sn"
)

s.disconnect()