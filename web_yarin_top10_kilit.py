p = "webapp/index.html"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

baslangic = s.find("function showTop10(){")
bitis = s.find("/* HİSSE SATIRI */", baslangic)

if baslangic == -1 or bitis == -1:
    raise SystemExit("showTop10 BLOGU BULUNAMADI")

yeni = '''async function showTop10(){

    oncekiSayfa = "top10";

    tumSayfalariGizle();

    document.getElementById("top10Page").style.display = "block";

    const alan = document.getElementById("top10List");

    alan.innerHTML =
        '<div class="empty">Kilitli Yarın TOP 10 yükleniyor...</div>';

    try{

        const cevap = await fetch(
            "data/yarin_top10.json?t=" + Date.now(),
            { cache: "no-store" }
        );

        if(!cevap.ok){
            throw new Error("Yarın TOP10 dosyası bulunamadı.");
        }

        const veri = await cevap.json();

        const liste = Array.isArray(veri.top10)
            ? veri.top10
            : [];

        if(!liste.length){

            alan.innerHTML =
                '<div class="empty">Kilitli Yarın TOP 10 listesi henüz oluşturulmadı.</div>';

            return;
        }

        alan.innerHTML = liste.map((hisse,index) =>
            hisseSatiri(
                hisse,
                hisse.yarin_top10_sira ?? (index + 1),
                "YARIN_TOP10"
            )
        ).join("");

    }catch(e){

        alan.innerHTML =
            '<div class="empty">Kilitli Yarın TOP 10 verisi henüz hazır değil.</div>';

        console.error("YARIN TOP10 HATASI:", e);
    }
}


'''

s = s[:baslangic] + yeni + s[bitis:]

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("WEB YARIN TOP10 KILITLI JSON DOSYASINA BAGLANDI")