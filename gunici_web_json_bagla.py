from pathlib import Path

p = Path("webapp/index.html")
s = p.read_text(encoding="utf-8")

start = s.find("function showGunIciTop10(){")
end = s.find("function showSearch(){", start)

if start < 0 or end < 0:
    raise SystemExit("HATA: Gun Ici TOP10 fonksiyonu bulunamadi")

new = r'''async function showGunIciTop10(){

    oncekiSayfa = "gunici_top10";

    tumSayfalariGizle();

    document.getElementById("gunIciTop10Page").style.display = "block";

    const alan = document.getElementById("gunIciTop10List");

    alan.innerHTML =
        '<div class="empty">Gün İçi TOP 10 yükleniyor...</div>';

    try{

        const cevap = await fetch(
            "data/gun_ici_top10.json?t=" + Date.now(),
            {cache:"no-store"}
        );

        if(!cevap.ok){
            throw new Error("Gün İçi veri dosyası okunamadı");
        }

        const veri = await cevap.json();

        const liste = Array.isArray(veri.top10)
            ? veri.top10
            : [];

        if(!liste.length){

            alan.innerHTML =
                '<div class="empty">Gün İçi TOP 10 verisi bulunamadı.</div>';

            return;
        }

        alan.innerHTML = liste.map((hisse,index) => {

            const kopya = {
                ...hisse,
                puan: Number(hisse.gun_ici_puan || 0),
                degisim: Number(hisse.acilisa_gore_degisim || 0)
            };

            return hisseSatiri(
                kopya,
                index + 1
            );

        }).join("");

    }
    catch(hata){

        console.error(hata);

        alan.innerHTML =
            '<div class="empty">Gün İçi TOP 10 verisi yüklenemedi.</div>';
    }
}


'''

s = s[:start] + new + s[end:]

# Yeni sayfanin diger sayfalarla birlikte gizlenmesini sagla
old = 'document.getElementById("top10Page").style.display = "none";'

new_hide = '''document.getElementById("top10Page").style.display = "none";
    document.getElementById("gunIciTop10Page").style.display = "none";'''

if 'document.getElementById("gunIciTop10Page").style.display = "none";' not in s:
    if old not in s:
        raise SystemExit("HATA: Sayfa gizleme bolumu bulunamadi")
    s = s.replace(old, new_hide, 1)

p.write_text(s, encoding="utf-8")

print("GUN ICI TOP10 WEB JSON BAGLANTISI TAMAM")