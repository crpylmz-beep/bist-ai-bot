from pathlib import Path

p = Path("webapp/index.html")
s = p.read_text(encoding="utf-8")

# -------------------------------------------------
# 1) ANA SAYFAYA KAP ALARM BUTONU
# -------------------------------------------------

if 'onclick="showKapAlarms()"' not in s:

    hedef = '''        <button class="action-btn" onclick="showSearch()">'''

    yeni = '''        <button class="action-btn" onclick="showKapAlarms()">
            🚨<br>
            KAP / Haber
        </button>

        <button class="action-btn" onclick="showSearch()">'''

    if hedef not in s:
        raise SystemExit("ANA SAYFA BUTON NOKTASI BULUNAMADI")

    s = s.replace(
        hedef,
        yeni,
        1
    )


# -------------------------------------------------
# 2) KAP ALARM SAYFASI
# -------------------------------------------------

if 'id="kapAlarmPage"' not in s:

    hedef = '''<!-- TARAMA -->'''

    yeni = '''
<!-- KAP / HABER ALARMLARI -->
<div id="kapAlarmPage" class="page" style="display:none">

    <div class="page-header">
        <button class="back-btn" onclick="goHome()">←</button>

        <div>
            <div style="font-weight:800;font-size:19px">
                🚨 Anlık KAP / Haber Alarmı
            </div>

            <div style="font-size:12px;opacity:.65;margin-top:3px">
                AI ile analiz edilen önemli şirket haberları
            </div>
        </div>
    </div>

    <div id="kapAlarmList" class="list">
        <div class="empty">
            KAP alarm verisi yükleniyor...
        </div>
    </div>

</div>


<!-- TARAMA -->'''

    if hedef not in s:
        raise SystemExit("KAP SAYFA EKLEME NOKTASI BULUNAMADI")

    s = s.replace(
        hedef,
        yeni,
        1
    )


# -------------------------------------------------
# 3) SAYFA GIZLEMEYE KAP SAYFASI
# -------------------------------------------------

hedef = '''    document.getElementById("gunIciTop10Page").style.display = "none";'''

if (
    hedef in s
    and 'document.getElementById("kapAlarmPage").style.display = "none";'
    not in s
):

    yeni = hedef + '''
    document.getElementById("kapAlarmPage").style.display = "none";'''

    s = s.replace(
        hedef,
        yeni,
        1
    )


# -------------------------------------------------
# 4) KAP ALARM JS FONKSIYONU
# -------------------------------------------------

if "async function showKapAlarms()" not in s:

    hedef = '''/* HİSSE ARA */'''

    js = r'''
/* KAP / HABER ALARMLARI */

async function showKapAlarms(){

    oncekiSayfa = "kap_alarm";

    tumSayfalariGizle();

    document.getElementById(
        "kapAlarmPage"
    ).style.display = "block";

    const alan = document.getElementById(
        "kapAlarmList"
    );

    alan.innerHTML =
        '<div class="empty">KAP alarmları yükleniyor...</div>';

    try{

        const cevap = await fetch(
            "data/kap_alarmlar.json?t=" + Date.now(),
            {
                cache:"no-store"
            }
        );

        if(!cevap.ok){
            throw new Error(
                "Henüz KAP alarm dosyası oluşmadı"
            );
        }

        const veri = await cevap.json();

        const liste = Array.isArray(
            veri.alarmlar
        )
            ? veri.alarmlar
            : [];

        if(!liste.length){

            alan.innerHTML = `
                <div class="empty">
                    🚨 Henüz önemli yeni KAP alarmı yok.
                    <br><br>
                    Güçlü pozitif veya negatif haber
                    geldiğinde burada görünecek.
                </div>
            `;

            return;
        }


        alan.innerHTML = liste.map(
            (a) => {

                const pozitif =
                    String(a.etki_sinifi || "")
                    .includes("POZITIF");

                const negatif =
                    String(a.etki_sinifi || "")
                    .includes("NEGATIF");

                const ikon =
                    pozitif
                    ? "🟢"
                    : negatif
                    ? "🔴"
                    : "🟡";

                const yon =
                    pozitif
                    ? "Pozitif Etki"
                    : negatif
                    ? "Negatif Etki"
                    : "Nötr";

                return `
                    <div class="detail-card"
                         style="
                            margin-bottom:12px;
                            border-left:5px solid ${
                                pozitif
                                ? "#20c997"
                                : negatif
                                ? "#ff5b5b"
                                : "#f0b429"
                            };
                         ">

                        <div style="
                            display:flex;
                            justify-content:space-between;
                            gap:10px;
                            align-items:flex-start;
                        ">

                            <div>
                                <div style="
                                    font-size:20px;
                                    font-weight:900;
                                ">
                                    ${ikon}
                                    ${a.sembol || "-"}
                                </div>

                                <div style="
                                    margin-top:4px;
                                    font-size:13px;
                                    opacity:.7;
                                ">
                                    ${a.tarih || ""}
                                </div>
                            </div>

                            <div style="
                                text-align:right;
                                font-weight:800;
                            ">
                                ${yon}
                                <br>
                                ${Number(
                                    a.etki_puani || 0
                                ).toFixed(1)}/10
                            </div>

                        </div>

                        <div style="
                            margin-top:12px;
                            font-weight:700;
                            line-height:1.45;
                        ">
                            ${a.baslik || ""}
                        </div>

                        <div style="
                            display:grid;
                            grid-template-columns:
                                repeat(2,minmax(0,1fr));
                            gap:8px;
                            margin-top:14px;
                        ">

                            <div class="detail-box">
                                <div class="detail-label">
                                    🤖 AI Güven
                                </div>
                                <div class="detail-value">
                                    %${Number(
                                        a.guven || 0
                                    ).toFixed(0)}
                                </div>
                            </div>

                            <div class="detail-box">
                                <div class="detail-label">
                                    ⚡ Önem
                                </div>
                                <div class="detail-value">
                                    %${Number(
                                        a.onem || 0
                                    ).toFixed(0)}
                                </div>
                            </div>

                            <div class="detail-box">
                                <div class="detail-label">
                                    📊 Sınıf
                                </div>
                                <div class="detail-value">
                                    ${
                                        a.etki_sinifi
                                        || "NOTR"
                                    }
                                </div>
                            </div>

                            <div class="detail-box">
                                <div class="detail-label">
                                    💹 Fiyatlanma
                                </div>
                                <div class="detail-value">
                                    ${
                                        a.fiyatlandi_riski
                                        || "BILINMIYOR"
                                    }
                                </div>
                            </div>

                        </div>

                    </div>
                `;
            }
        ).join("");

    }
    catch(e){

        alan.innerHTML = `
            <div class="empty">
                🚨 Henüz kaydedilmiş KAP alarmı yok.
                <br><br>
                Canlı izleme yeni önemli haber
                yakaladığında bu ekran otomatik dolacak.
            </div>
        `;
    }
}


'''

    if hedef not in s:
        raise SystemExit(
            "KAP JS EKLEME NOKTASI BULUNAMADI"
        )

    s = s.replace(
        hedef,
        js + hedef,
        1
    )


p.write_text(
    s,
    encoding="utf-8"
)

print("WEB KAP ALARM EKRANI EKLENDI")
