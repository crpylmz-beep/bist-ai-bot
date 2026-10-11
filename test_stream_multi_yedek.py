import json
import time
import borsapy as bp


class MultiTradingViewStream(bp.TradingViewStream):

    def __init__(self):
        super().__init__()
        self._multi_map = {}

    def _send_chart_subscribe(self, symbol, interval, exchange="BIST"):
        tv_interval = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "1d": "1D",
        }.get(interval, interval)

        tv_symbol = f"{exchange}:{symbol}"

        self._chart_series_counter += 1
        n = self._chart_series_counter

        resolve_id = f"ser_{n}"
        price_id = f"$prices_{n}"
        series_index = f"s{n}"

        self._chart_series_map[price_id] = (symbol, interval)
        self._multi_map[price_id] = (symbol, interval)

        symbol_config = json.dumps({
            "symbol": tv_symbol,
            "adjustment": "splits",
            "session": "regular",
        })

        self._send(
            self._create_message(
                "resolve_symbol",
                [
                    self._chart_session,
                    resolve_id,
                    f"={symbol_config}",
                ],
            )
        )

        self._send(
            self._create_message(
                "create_series",
                [
                    self._chart_session,
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

        data = params[1]

        if not isinstance(data, dict):
            return

        for series_key, series_data in data.items():

            if series_key not in self._multi_map:
                continue

            symbol, interval = self._multi_map[series_key]

            candles = []

            if isinstance(series_data, dict):
                bars = series_data.get("s", series_data.get("st", []))

                if isinstance(bars, list):
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
                                    "volume": float(v[5])
                                    if len(v) >= 6 and v[5]
                                    else 0,
                                })

            if candles:
                self._update_chart_data(
                    symbol,
                    interval,
                    candles
                )


s = MultiTradingViewStream()

baslangic = time.time()

print("Baglaniyor...")
s.connect()

print("THYAO ve SKTAS abone ediliyor...")

s.subscribe_chart("THYAO", "5m")
s.subscribe_chart("SKTAS", "5m")

time.sleep(6)

thyao = s.get_candles("THYAO", "5m")
sktas = s.get_candles("SKTAS", "5m")

print()
print("THYAO mum:", len(thyao))
print("SKTAS mum:", len(sktas))
print("Sure:", round(time.time() - baslangic, 1), "sn")

if thyao:
    print("THYAO SON:", thyao[-1])

if sktas:
    print("SKTAS SON:", sktas[-1])

s.disconnect()