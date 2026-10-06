from pathlib import Path

p = Path("kap_canli.py")
s = p.read_text(encoding="utf-8")

if "def web_alarm_kaydet(" not in s:

    ek = r'''

WEB_ALARM_DOSYA = Path(
    "webapp/data/kap_alarmlar.json"
)


def web_alarm_kaydet(analiz, alarm):
    if not alarm.get("alarm"):
        return False

    WEB_ALARM_DOSYA.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        if WEB_ALARM_DOSYA.exists():
            veri = json.loads(
                WEB_ALARM_DOSYA.read_text(
                    encoding="utf-8"
                )
            )
        else:
            veri = {
                "guncelleme": None,
                "alarmlar": []
            }

    except Exception:
        veri = {
            "guncelleme": None,
            "alarmlar": []
        }

    kayit = {
        "id": hashlib.sha1(
            (
                str(analiz.get("sembol", ""))
                + "|"
                + str(analiz.get("baslik", ""))
            ).encode(
                "utf-8",
                errors="ignore"
            )
        ).hexdigest()[:16],

        "tarih": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "sembol": analiz.get(
            "sembol",
            "-"
        ),

        "baslik": analiz.get(
            "baslik",
            ""
        ),

        "etki_puani": analiz.get(
            "etki_puani",
            0
        ),

        "etki_sinifi": analiz.get(
            "etki_sinifi",
            "NOTR"
        ),

        "guven": analiz.get(
            "guven",
            0
        ),

        "onem": analiz.get(
            "onem",
            0
        ),

        "fiyatlandi_riski": analiz.get(
            "fiyatlandi_riski",
            "BILINMIYOR"
        ),

        "alarm_seviyesi": alarm.get(
            "seviye",
            "YOK"
        ),

        "mesaj": alarm.get(
            "mesaj",
            ""
        )
    }

    alarmlar = veri.get(
        "alarmlar",
        []
    )

    alarmlar = [
        x
        for x in alarmlar
        if x.get("id") != kayit["id"]
    ]

    alarmlar.insert(
        0,
        kayit
    )

    veri["alarmlar"] = alarmlar[:100]

    veri["guncelleme"] = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    WEB_ALARM_DOSYA.write_text(
        json.dumps(
            veri,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        "WEB KAP ALARMI KAYDEDILDI:",
        kayit["sembol"],
        kayit["alarm_seviyesi"]
    )

    return True
'''

    main_pos = s.find(
        '\nif __name__ == "__main__":'
    )

    if main_pos == -1:
        raise SystemExit(
            "MAIN BLOKU BULUNAMADI"
        )

    s = (
        s[:main_pos]
        + ek
        + s[main_pos:]
    )


eski = '''    if alarm.get("alarm"):
        print()
        print(
            alarm.get(
                "mesaj",
                ""
            )
        )
        print()
'''

yeni = '''    if alarm.get("alarm"):
        print()
        print(
            alarm.get(
                "mesaj",
                ""
            )
        )
        print()

        web_alarm_kaydet(
            analiz,
            alarm
        )
'''

if eski not in s:
    raise SystemExit(
        "ALARM BAGLANTI NOKTASI BULUNAMADI"
    )

s = s.replace(
    eski,
    yeni,
    1
)

p.write_text(
    s,
    encoding="utf-8"
)

print(
    "WEB KAP ALARM KAYDI EKLENDI"
)
