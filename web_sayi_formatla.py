from pathlib import Path

p = Path("webapp/index.html")
s = p.read_text(encoding="utf-8")

degisimler = {
'''                ${fiyat} TL''':
'''                ${Number.isFinite(Number(fiyat)) ? Number(fiyat).toFixed(2) : "-"} TL''',

'''                ${detayKutu("RSI", rsi)}''':
'''                ${detayKutu("RSI", Number.isFinite(Number(rsi)) ? Number(rsi).toFixed(1) : "-")}''',

'''                ${detayKutu("SMA20", sma20)}''':
'''                ${detayKutu("SMA20", Number.isFinite(Number(sma20)) ? Number(sma20).toFixed(2) : "-")}''',

'''                ${detayKutu("SMA50", sma50)}''':
'''                ${detayKutu("SMA50", Number.isFinite(Number(sma50)) ? Number(sma50).toFixed(2) : "-")}''',

'''                ${detayKutu("MACD", macd)}''':
'''                ${detayKutu("MACD", Number.isFinite(Number(macd)) ? Number(macd).toFixed(4) : "-")}''',

'''                ${detayKutu("Signal", signal)}''':
'''                ${detayKutu("Signal", Number.isFinite(Number(signal)) ? Number(signal).toFixed(4) : "-")}''',

'''                ${detayKutu("Hacim", hacim)}''':
'''                ${detayKutu("Hacim", Number.isFinite(Number(hacim)) ? "%" + Number(hacim).toFixed(1) : "-")}''',

'''                ${detayKutu("Risk/Getiri", riskGetiri)}''':
'''                ${detayKutu("Risk/Getiri", Number.isFinite(Number(riskGetiri)) ? Number(riskGetiri).toFixed(2) : "-")}'''
}

for eski, yeni in degisimler.items():
    if eski not in s:
        raise SystemExit("HATA: Bulunamadi -> " + eski.strip())
    s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("WEB SAYI FORMATLARI DUZELTILDI")