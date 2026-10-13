"""One-off safe refresh of public stock rows from verified closing-scan checkpoint."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from veri_yollari import paths
from kullanici_kayitlari import atomic_json

def main():
    day=datetime.now(ZoneInfo('Europe/Istanbul')).date().isoformat()
    checkpoint=paths().runtime/'pozitif_kapanis_tarama.json'
    if not checkpoint.is_file():
        raise SystemExit('Kapanış kontrol noktası yok; mevcut dosya değiştirilmedi.')
    data=json.loads(checkpoint.read_text(encoding='utf-8'))
    if data.get('date')!=day:
        raise SystemExit('Bugüne ait kapanış kontrol noktası yok; mevcut dosya değiştirilmedi.')
    rows=data.get('rows')
    if not isinstance(rows,dict) or not rows:
        raise SystemExit('Kapanış kayıtları boş; mevcut dosya değiştirilmedi.')
    from ai_karar_motoru import stamp
    valid={}
    for stock,row in rows.items():
        if not isinstance(row,dict) or row.get('sembol')!=stock:
            continue
        observed=stamp((row.get('teknik_gostergeler') or {}).get('data_time'))
        if observed and observed.date().isoformat()==day:
            valid[stock]=row
    if not valid:
        raise SystemExit('Doğrulanmış güncel kapanış kaydı yok; mevcut dosya değiştirilmedi.')
    import bist_bot
    target=Path(bist_bot.DATA_FILE)
    previous=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    merged={r['sembol']:r for r in previous.get('hisseler',[])
            if isinstance(r,dict) and r.get('sembol')}
    for stock,row in valid.items():
        row['canli_guncelleme']=datetime.now(ZoneInfo('Europe/Istanbul')).isoformat()
        merged[stock]=row
    bist_bot.web_verisi_kaydet(list(merged.values()),data.get('symbols'))
    print(f'Kapanış verileri ana ekrana aktarıldı: {len(valid)} hisse. Diğer kayıtlar korundu.')

if __name__=='__main__':
    main()
