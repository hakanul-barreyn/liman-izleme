"""Ana sayfa: resmî açıklama ve kayıt yan yana. Veri analisti olmayan biri de ilk ekranda sonucu görmeli.

Sayfa sırası: açıklama (alıntı) ve tek cümlelik sonuç, aylık sefer grafiği, açıklamalar ve kayıtlar (her açıklamaya
verinin cevabı), gemiler nasıl gidiyor, en çok sefer yapan gemiler, kayıtların kaynağı ve sınırları.
"""
from __future__ import annotations

from . import ozet as oz
from .ulkeler import bayrak, ulke_adi

YON_SVG = {
    "dogrudan": '<svg viewBox="0 0 120 24" aria-hidden="true"><circle cx="8" cy="12" r="5"/><path d="M14 12H106"/>'
                '<circle cx="112" cy="12" r="5" class="dolu"/></svg>',
    "liman": '<svg viewBox="0 0 120 24" aria-hidden="true"><circle cx="8" cy="12" r="5"/><path d="M14 12H54M66 12H106"/>'
             '<rect x="54.5" y="6.5" width="11" height="11" transform="rotate(45 60 12)" class="ara"/>'
             '<circle cx="112" cy="12" r="5" class="dolu"/></svg>',
    "karanlik": '<svg viewBox="0 0 120 24" aria-hidden="true"><circle cx="8" cy="12" r="5"/><path d="M14 12H36"/>'
                '<path d="M40 12H100" class="kesik"/><circle cx="112" cy="12" r="5" class="bos"/></svg>',
}


def _sayi(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n).replace(".", ",")


def _gun(s: str | None) -> str:
    if not s:
        return "?"
    y, m, d = s[:10].split("-")
    return f"{int(d)} {oz.AY[int(m) - 1]} {y}"


def _ay(m: str) -> str:
    return f"{oz.AY[int(m[5:7]) - 1]} {m[:4]}"


def _lim(ad: str) -> str:
    from .makale import liman_tr
    return liman_tr(ad)


def build(cfg, o: dict, E) -> str:
    """Ana sayfanın gövdesi (main)."""
    y = next(iter(o["yonler"]), None)
    d = o["yonler"].get(y) if y else None
    if not d or not o.get("beyan"):
        return ('<main class="ozet" id="icerik"><section class="iddia"><h1 class="sonuc">Henüz yeterli kayıt yok.</h1>'
                '<p class="sonuc-alt">Veri toplandıkça bu sayfa her saat güncellenir. <a href="harita.html">Harita</a></p>'
                '</section></main>')
    geri = [x for x in o["yonler"].values() if not x["ihracat"]]
    ithal = geri[0] if geri else None
    A, B = cfg.country_name(d["A"]), cfg.country_name(d["B"])
    test = {t["kimlik"]: t for t in o.get("testler") or []}
    t0 = test.get("ticaret") or {}
    aile = d["aile_sonra"]
    karanlik = aile.get("karanlik", 0) + aile.get("sts", 0)
    # 1) açıklama ve sonuç
    alinti = (f'<figure class="belge"><blockquote><p>“{E(t0.get("metin"))}”</p></blockquote>'
              f'<figcaption>{E(t0.get("kim"))}, {E(_gun(t0.get("gun")))}. <a href="{E(t0.get("url"))}" rel="noopener">Kaynak</a>'
              '</figcaption></figure>') if t0 else ""
    aralik = ""
    if d["min_ay"] and d["max_ay"]:
        aralik = (f' Ticaretin durdurulduğu açıklanan günden sonra hiçbir ay sıfıra inmedi: ayda en az {d["min_ay"][0]}, '
                  f'en çok {d["max_ay"][0]} sefer.')
    iddia = (f'<section class="iddia">{alinti}<h1 class="sonuc">O günden bu yana {E(A)} limanlarından {E(B)} limanlarına '
             f'<b>{_sayi(d["sonra"])} sefer</b> yapıldı.</h1>'
             f'<p class="sonuc-alt">{_sayi(d["gemi_sonra"])} farklı gemi.{aralik} Kayıtlar gemilerin kendi yayınladığı '
             f'konum sinyallerinden (AIS) çıkarıldı; son veri {E(_gun(o["son_gun"]))}.</p></section>')
    # 2) grafik
    lejant = "".join(f'<span class="isaret" style="--c:var(--c-{k})">{E(n)}</span>'
                     for k, n in (("dogrudan", "Doğrudan"), ("liman", "Üçüncü ülke limanı üzerinden"),
                                  ("sts", "Gemiden gemiye"), ("karanlik", "AIS kapatılmış")) if aile.get(k) or k == "dogrudan")
    kaps = o["kapsama"]
    eksik = "" if (kaps.get("erken") or 0) >= 95 or kaps.get("tamam") else (
        " Gölgeli dönemin (beyandan önce) taraması sürüyor; o aylardaki sayılar artacak.")
    grafik = (f'<section class="grafik-bolum" aria-labelledby="g-baslik"><h2 id="g-baslik" class="gizli">Aylara göre seferler</h2>'
              f'<div class="grafik-kaydir">{oz.aylik_svg(o, y, kimlik="ana-grafik")}</div><div class="grafik-alt"><p class="lejant">{lejant}</p>'
              f'<p class="not">Her sütun bir ay: o ay {E(A)} limanından çıkıp {E(B)} limanına varan seferler. Kesik çizgiler '
              f'resmî açıklamaların tarihleri. Son sütun içinde bulunduğumuz ay, eksik.{eksik}</p></div>'
              '<p class="eylemler"><a class="eylem ana" href="rapor/index.html">Raporu oku</a>'
              '<a class="eylem" href="harita.html">Haritada gör</a>'
              f'<a class="eylem" href="raporlar/{y.replace(">", "-").lower()}-seferler.csv">Bütün seferleri indir (CSV)</a></p></section>')
    # 3) açıklamalar ve kayıtlar
    satir = []

    def ekle(t, kayit_html, link):
        if not t:
            return
        q = f'“{E(t["metin"])}”' if not t.get("aktarim") else E(t["metin"])
        satir.append(f'<li><div class="beyan"><p class="soz">{q}</p><p class="kim">{E(t["kim"])}, {E(_gun(t["gun"]))}. '
                     f'<a href="{E(t["url"])}" rel="noopener">Kaynak</a>{"" if not t.get("aktarim") else " (özet)"}</p></div>'
                     f'<div class="kayit">{kayit_html}<p class="git">{link}</p></div></li>')
    ekle(test.get("ticaret"), f'<p><b>{_sayi(d["sonra"])} sefer</b> {E(A)} limanından çıkıp {E(B)} limanına vardı '
                              f'({_sayi(aile.get("dogrudan", 0))} doğrudan, {_sayi(aile.get("liman", 0))} üçüncü ülke limanı '
                              f'üzerinden). Ayda ortalama {_sayi(d["ort_sonra"])} sefer.</p>',
         '<a href="raporlar/index.html">Gemi gemi liste</a>')
    tk = o["tanker"]
    cey = d["ceyhan"]
    if test.get("ceyhan"):
        ek = (f' Ayrıca {_sayi(o["ceyhan"]["il_acik"])} Ceyhan çıkışında AIS sinyali İsrail açıklarında kesildi ya da orada '
              'yeniden geldi.') if o["ceyhan"]["il_acik"] else ""
        ekle(test["ceyhan"], f'<p><b>{_sayi(cey)} sefer</b> Ceyhan terminallerinin önünden çıkıp {E(B)} limanına '
                             f'ya da açıklarına gitti; tanker dosyalarında {_sayi(tk["gemi"])} gemi, {_sayi(tk["sefer"])} sefer var.'
                             f'{ek}</p>', '<a href="tankerler/index.html">Tanker dosyaları</a>')
    if test.get("bayrak") and o.get("liman_kisit"):
        ekle(test["bayrak"], f'<p><b>{_sayi(d["kisit_sonra"])} sefer</b> bu açıklamadan sonra {E(A)} limanından {E(B)} '
                             f'limanına vardı. Bunların {_sayi(d["tr_bayrak_kisit"])} tanesinde gemi Türk bayraklıydı; '
                             f'beyandan bu yana Türk bayraklı gemilerle {_sayi(d["tr_bayrak"])} sefer.</p>',
             '<a href="raporlar/index.html">Bayrağa göre bak</a>')
    if test.get("hepsi") and ithal:
        ekle(test["hepsi"], f'<p><b>{_sayi(ithal["sonra"])} sefer</b> {E(B)} limanından çıkıp {E(A)} limanına vardı '
                            f'({_sayi(ithal["gemi_sonra"])} gemi); ayda ortalama {_sayi(ithal["ort_sonra"])}. '
                            f'Gemi hareketi yükün Filistin’e mi, {E(B)}’e mi gittiğini göstermez; bu ayrım için raporda '
                            'sefer sayısı savaş öncesiyle karşılaştırılıyor.</p>',
            '<a href="rapor/index.html#tartisma">Raporda tartışma</a>')
    karsi = (f'<section class="karsi" aria-labelledby="k-baslik"><h2 id="k-baslik">Açıklamalar ve kayıtlar</h2>'
             f'<p class="giris-kisa">Her resmî açıklamanın yanında, aynı dönemde gemi kayıtlarının gösterdiği.</p>'
             f'<ol class="defter-liste">{"".join(satir)}</ol></section>') if satir else ""
    # 4) nasıl gidiyorlar
    ara = ", ".join(f"{a}" for a, _n in d["ara"][:3])
    yollar = [
        ("dogrudan", "Doğrudan", aile.get("dogrudan", 0),
         f"{A} limanından çıkan gemi bir sonraki durağında {B} limanına giriyor."),
        ("liman", "Üçüncü ülke limanı üzerinden", aile.get("liman", 0),
         f"Arada Mısır, Yunanistan, Kıbrıs ya da Bulgaristan limanına uğruyor. En sık: {ara}." if ara else
         "Arada Mısır, Yunanistan, Kıbrıs ya da Bulgaristan limanına uğruyor."),
        ("karanlik", "AIS kapatılarak ya da gizlenerek", karanlik,
         f"Yolda konum sinyalini kapatıyor, sinyali {B} açıklarında kesiliyor, konumu GPS karıştırmasının sahte noktasında "
         "görünüyor ya da limana girmeden kıyı açığında bekliyor."),
    ]
    nasil = ('<section class="nasil" aria-labelledby="n-baslik"><h2 id="n-baslik">Gemiler nasıl gidiyor?</h2><div class="yollar">'
             + "".join(f'<div class="yol-tur" style="--c:var(--c-{k})">{YON_SVG[k]}<h3>{E(ad)}</h3>'
                       f'<p class="adet">{_sayi(n)} sefer</p><p>{E(acik)}</p></div>' for k, ad, n, acik in yollar)
             + '</div></section>')
    # 5) gemiler
    rows = []
    for g in d["en_cok"][:8]:
        kim = ", ".join(filter(None, [bayrak(g["bayrak"], g["mmsi"]), f'IMO {g["imo"]}' if g["imo"] else None]))
        rows.append(f'<tr><td><b>{E(g["ad"])}</b><span class="not">{E(kim)}</span></td><td class="sayi">{g["n"]}</td>'
                    f'<td>{E(_lim(g["hat"][0]))} – {E(_lim(g["hat"][1]))}</td><td class="tarih">{E(_ay(g["son"][:7]))}</td></tr>')
    gemiler = ('<section class="gemiler-ozet" aria-labelledby="s-baslik"><h2 id="s-baslik">En çok sefer yapan gemiler</h2>'
               f'<p class="giris-kisa">Beyandan sonra {E(A)} limanından {E(B)} limanına en çok sefer yapan gemiler. Her gemi '
               'kendi adıyla, IMO numarasıyla ve tarihleriyle listede.</p>'
               '<div class="tablo"><table><thead><tr><th scope="col">Gemi</th><th scope="col" class="sayi">Sefer</th>'
               '<th scope="col">En sık hat</th><th scope="col">Son sefer</th></tr></thead><tbody>'
               + "".join(rows) + '</tbody></table></div><p class="eylemler"><a class="eylem" href="raporlar/index.html">'
               f'Bütün gemiler ({_sayi(d["gemi_sonra"])})</a><a class="eylem" href="tankerler/index.html">Tanker dosyaları</a></p></section>')
    # 6) kaynak ve sınırlar
    guven = ('<section class="guven" aria-labelledby="v-baslik"><h2 id="v-baslik">Bu kayıtlar nereden geliyor?</h2>'
             '<div class="iki"><div><h3>Kaynak</h3><ul>'
             '<li>Gemiler konumlarını, adlarını ve kimlik numaralarını AIS ile kendileri yayınlar; büyük gemiler için bu zorunludur.</li>'
             '<li>Liman ziyaretleri ve sinyal kesintileri, Global Fishing Watch’ın bu sinyallerden ürettiği açık kayıtlardan alınır.</li>'
             '<li>Bu sitenin kendi kaydettiği sinyaller her gün mühürlenir (SHA-256 ve OpenTimestamps); sonradan değiştirilemez.</li>'
             '<li>Bütün seferler gemi adı, IMO numarası ve saatiyle indirilebilir; herkes kontrol edebilir.</li></ul></div>'
             '<div><h3>Neyi göstermez</h3><ul>'
             '<li>Geminin hareketini gösterir; yükün ne olduğunu, sahibini ve satıcısını göstermez.</li>'
             f'<li>Ticaret Bakanlığı’na göre Filistin’e giden ürünler {E(B)} limanlarından geçiyor; bir kısım sefer bunu taşıyor olabilir.</li>'
             '<li>Bazı gemiler birçok ülkeye uğrayan düzenli hat gemileridir; üçüncü ülkelerin yükünü de taşırlar.</li>'
             '<li>Sinyalini tamamen kapatan gemiler kayıtta eksik kalır; gerçek sayı bundan büyük olabilir.</li></ul></div></div>'
             '<p class="eylemler"><a class="eylem" href="yontem.html">Yöntem</a><a class="eylem" href="kanit.html">Kanıt zinciri</a>'
             '</p></section>')
    yonlendir = ('<script>(function(){var h=location.hash;if(/(^#|&)(sec|y|hat|q|k|p|t|a)=/.test(h))'
                 'location.replace("harita.html"+h)})();</script>')
    kaydir = ('<script>document.querySelectorAll(".grafik-kaydir").forEach(function(k){k.scrollLeft=k.scrollWidth})</script>')
    return f'{yonlendir}<main class="ozet" id="icerik">{iddia}{grafik}{karsi}{nasil}{gemiler}{guven}</main>{kaydir}'


def ulke(c: str) -> str:
    return ulke_adi(c)
