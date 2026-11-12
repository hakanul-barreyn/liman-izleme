"""Rapor: bütün verinin makale düzeninde özeti (Türkçe ve İngilizce).

rapor/index.html   Türkçe
rapor/en.html      İngilizce (uluslararası kuruluşlar için)
veri/rapor-ozet.json  raporun dayandığı sayılar ve veri kesitinin SHA-256 özeti

Rapor her site üretiminde güncel veriyle yeniden yazılır. Sürüm tarihi, veri dönemi ve veri kesitinin özeti
künyede yazar; aynı kesit aynı özeti verir. Tarihli PDF kopyaları ayrıca GitHub Releases'ta saklanır.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import ozet as oz
from .ulkeler import ISO3_AD, MID_ISO3

ISO3_EN = {
    "PAN": "Panama", "LBR": "Liberia", "MHL": "Marshall Islands", "MLT": "Malta", "CMR": "Cameroon", "VUT": "Vanuatu",
    "PRT": "Portugal", "PLW": "Palau", "HKG": "Hong Kong", "BRB": "Barbados", "SGP": "Singapore", "ITA": "Italy",
    "TUR": "Türkiye", "ISR": "Israel", "GRC": "Greece", "CYP": "Cyprus", "EGY": "Egypt", "BGR": "Bulgaria",
    "ATG": "Antigua and Barbuda", "BHS": "Bahamas", "BLZ": "Belize", "COM": "Comoros", "DEU": "Germany", "DNK": "Denmark",
    "GBR": "United Kingdom", "GAB": "Gabon", "GNB": "Guinea-Bissau", "HND": "Honduras", "KNA": "Saint Kitts and Nevis",
    "MDA": "Moldova", "NLD": "Netherlands", "NOR": "Norway", "RUS": "Russia", "SLE": "Sierra Leone", "TGO": "Togo",
    "TZA": "Tanzania", "VCT": "Saint Vincent and the Grenadines", "COK": "Cook Islands", "TUV": "Tuvalu", "KHM": "Cambodia",
    "GEO": "Georgia", "ESP": "Spain", "FRA": "France", "BEL": "Belgium", "CHN": "China", "IND": "India", "JPN": "Japan",
    "KOR": "South Korea", "LBN": "Lebanon", "SYR": "Syria", "UKR": "Ukraine", "ROU": "Romania", "HRV": "Croatia",
    "ARE": "United Arab Emirates", "SAU": "Saudi Arabia", "JOR": "Jordan", "LUX": "Luxembourg", "GIB": "Gibraltar",
    "IMN": "Isle of Man", "STP": "São Tomé and Príncipe", "DMA": "Dominica", "JAM": "Jamaica", "GUY": "Guyana",
    "BOL": "Bolivia", "MNG": "Mongolia", "TUN": "Tunisia", "DZA": "Algeria", "LBY": "Libya", "MAR": "Morocco",
}
LIMAN_EN = {
    "Hayfa": "Haifa", "Aşdod": "Ashdod", "Aşkelon (EAPC petrol terminali)": "Ashkelon (EAPC oil terminal)",
    "Hadera (Orot Rabin)": "Hadera (Orot Rabin)", "Eilat": "Eilat",
    "İskenderun Körfezi (Ceyhan, Dörtyol, İskenderun)": "Gulf of İskenderun (Ceyhan, Dörtyol, İskenderun)",
    "Aliağa – Nemrut Körfezi": "Aliağa – Nemrut Bay", "İstanbul – Ambarlı": "Istanbul – Ambarlı",
    "İzmit Körfezi (Kocaeli)": "Gulf of İzmit (Kocaeli)", "Mersin": "Mersin", "Pire": "Piraeus",
    "İskenderiye ve Dekheila": "Alexandria and Dekheila", "Dimyat (Damietta)": "Damietta", "Port Said": "Port Said",
    "Limasol": "Limassol", "Larnaka": "Larnaca", "Vasiliko": "Vasiliko", "Selanik": "Thessaloniki", "Burgaz": "Burgas",
    "Varna": "Varna", "İsrail kıyı yaklaşma alanı": "Israeli coastal approach zone",
}
ULKE_EN = {"Türkiye": "Türkiye", "İsrail": "Israel", "Mısır": "Egypt", "Yunanistan": "Greece", "Kıbrıs": "Cyprus",
           "Bulgaristan": "Bulgaria", "İtalya": "Italy", "Rusya": "Russia", "Romanya": "Romania", "Gürcistan": "Georgia",
           "Ukrayna": "Ukraine", "Lübnan": "Lebanon", "Malta": "Malta", "İspanya": "Spain", "Fransa": "France",
           "Hırvatistan": "Croatia", "Slovenya": "Slovenia", "Arnavutluk": "Albania", "Karadağ": "Montenegro"}
DUZEY_EN = {"kayitli": "Recorded arrival at an Israeli port", "aktarma": "Via a third-country port",
            "acik": "AIS off near Israel", "iz": "Position off Israel or under GPS interference", "bekleme": "Waited off the Israeli coast", "sts": "Ship-to-ship",
            "karanlik": "Long AIS gap"}


def liman_tr(ad: str | None) -> str:
    """GFW'de adı olmayan liman: "Türkiye limanı" -> "Türkiye, adı kayıtsız liman"."""
    if ad and ad.endswith(" limanı") and ad[:-7] in ULKE_EN:
        return f"{ad[:-7]}, adı kayıtsız liman"
    return ad or "?"


def liman_en(ad: str | None) -> str:
    if not ad:
        return "unknown"
    if ad in LIMAN_EN:
        return LIMAN_EN[ad]
    if ad.endswith(" limanı") and ad[:-7] in ULKE_EN:
        return f"unnamed port, {ULKE_EN[ad[:-7]]}"
    s = ad
    for tr, en in (("adsız demirleme yeri", "unnamed anchorage"), (" kıyı açıkları (limana girmeden, ", " offshore (no port entry, "),
                   (" açıkları (AIS kapalıyken)", " offshore (AIS off)"), (" saat)", " h)"), (" limanı", " port"),
                   ("varış kayıtsız", "no recorded arrival")):
        s = s.replace(tr, en)
    for tr, en in ULKE_EN.items():
        s = s.replace(tr, en)
    return s


def bayrak_ad(iso3: str | None, mmsi=None, en: bool = False) -> str:
    if not iso3 and mmsi:
        m = str(mmsi)
        iso3 = MID_ISO3.get(m[:3]) if len(m) == 9 else None
    if not iso3 or iso3 == "?":
        return "unknown" if en else "bilinmiyor"
    return (ISO3_EN if en else ISO3_AD).get(iso3, iso3)


def _n(x, en=False) -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        s = f"{x:,.1f}"
        return s if en else s.replace(",", "X").replace(".", ",").replace("X", ".")
    s = f"{x:,}"
    return s if en else s.replace(",", ".")


def _gun(s: str | None, en=False) -> str:
    if not s:
        return "?"
    y, m, d = s[:10].split("-")
    return f"{int(d)} {(oz.AY_EN if en else oz.AY)[int(m) - 1]} {y}"


def _ay(m: str | None, en=False) -> str:
    if not m:
        return "?"
    return f"{(oz.AY_EN if en else oz.AY)[int(m[5:7]) - 1]} {m[:4]}"


def _yuzde(a, b, en=False) -> str:
    if not b:
        return "–"
    return (f"{100 * a / b:.0f}%" if en else f"%{100 * a / b:.0f}")


def _tablo(E, bas, rows, num=(), baslik="", not_=""):
    th = "".join(f'<th scope="col"{" class=sayi" if i in num else ""}>{E(h)}</th>' for i, h in enumerate(bas))
    tr = "".join("<tr>" + "".join(f'<td{" class=sayi" if i in num else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>"
                 for r in rows)
    cap = f"<caption>{baslik}</caption>" if baslik else ""
    alt = f'<p class="tablo-not">{not_}</p>' if not_ else ""
    return f'<div class="tablo"><table>{cap}<thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>{alt}'


def _kaynakca(o, en=False) -> list[tuple[str, str]]:
    """(metin, bağlantı) listesi; resmî açıklamalar config.yaml'dan."""
    out = []
    for t in o.get("testler") or []:
        kim = t.get("kim_en") if en else t.get("kim")
        out.append((f"{kim} ({_gun(t['gun'], en)}). {t.get('kaynak')}.", t.get("url")))
    sabit = [
        ("Al-Monitor (9 April 2024). Turkey imposes trade restrictions on Israel over Gaza war." if en else
         "Al-Monitor (9 Nisan 2024). Turkey imposes trade restrictions on Israel over Gaza war.",
         "https://www.al-monitor.com/originals/2024/04/turkey-imposes-trade-restrictions-israel-over-gaza-war"),
        ("Hürriyet Daily News (12 April 2024). Turkish ministry rejects claims of continued export to Israel amid ban." if en else
         "Hürriyet Daily News (12 Nisan 2024). Turkish ministry rejects claims of continued export to Israel amid ban.",
         "https://hurriyetdailynews.com/turkish-ministry-rejects-claims-of-continued-export-to-israel-amid-ban-192387"),
        ("Middle East Eye (2024). New evidence reveals routine oil shipments from Turkey to Israel.",
         "https://www.middleeasteye.net/news/new-evidence-reveals-routine-oil-shipments-turkey-israel"),
        ("Greek City Times (7 October 2025). Greek ship transports oil from Turkey to Israel." if en else
         "Greek City Times (7 Ekim 2025). Greek ship transports oil from Turkey to Israel.",
         "https://greekcitytimes.com/2025/10/07/greek-ship-transports-oil-turkey/"),
        ("NPR (22 April 2024). Israel fakes GPS locations to deter attacks, but it also throws off planes and ships." if en else
         "NPR (22 Nisan 2024). Israel fakes GPS locations to deter attacks, but it also throws off planes and ships.",
         "https://npr.org/2024/04/22/1245847903/israel-gps-spoofing"),
        ("Kroodsma, D. A. et al. (2018). Tracking the global footprint of fisheries. Science, 359(6378), 904–908.",
         "https://doi.org/10.1126/science.aao5646"),
        ("Welch, H. et al. (2022). Hot spots of unseen fishing vessels. Science Advances, 8(44), eabq2109.",
         "https://doi.org/10.1126/sciadv.abq2109"),
        ("Global Fishing Watch. API documentation: events (port visits, AIS gaps) and 4Wings (AIS presence)." if en else
         "Global Fishing Watch. API belgeleri: olaylar (liman ziyaretleri, AIS boşlukları) ve 4Wings (AIS varlığı).",
         "https://globalfishingwatch.org/our-apis/documentation"),
        ("International Maritime Organization. SOLAS Chapter V, Regulation 19: carriage requirements for shipborne "
         "navigational systems and equipment (AIS)." if en else
         "Uluslararası Denizcilik Örgütü (IMO). SOLAS Bölüm V, Kural 19: gemide bulunması zorunlu seyir sistemleri (AIS).",
         "https://www.imo.org/en/OurWork/Safety/Pages/AIS.aspx"),
        ("aisstream.io. Real-time AIS data stream." if en else "aisstream.io. Gerçek zamanlı AIS veri akışı.",
         "https://aisstream.io"),
    ]
    return out + sabit


def _ekler(cfg, o, en: bool) -> dict:
    """Metinde kullanılan sayılar."""
    d = o["yonler"].get("TR>IL") or next(iter(o["yonler"].values()))
    i = next((x for x in o["yonler"].values() if not x["ihracat"]), None)
    a = d["aile_sonra"]
    kaps = o["kapsama"]
    erken_tamam = (kaps.get("erken") or 0) >= 95 or kaps.get("tamam")
    return {"d": d, "i": i, "a": a, "kaps": kaps, "erken_tamam": erken_tamam,
            "oran": (d["ort_sonra"] / d["ort_once"]) if d.get("ort_once") and d.get("ort_sonra") else None}


# --------------------------------------------------------------------------- Türkçe
def _tr(cfg, o, E) -> str:
    x = _ekler(cfg, o, False)
    d, i, a, kaps = x["d"], x["i"], x["a"], x["kaps"]
    th = cfg.th
    tk, cy = o["tanker"], o["ceyhan"]
    n = lambda v: _n(v)  # noqa: E731
    beyan, kisit = o["beyan"], o.get("liman_kisit")
    karanlik = a.get("karanlik", 0) + a.get("sts", 0)
    kutu = th.get("hedef_acik_deniz")
    kutu_s = (f"{kutu[0][0]}–{kutu[1][0]}° K, {kutu[0][1]}–{kutu[1][1]}° D".replace(".", ",") if kutu else "tanımlı değil")
    ara_ulke = "Mısır, Yunanistan, Kıbrıs ve Bulgaristan"
    sifir = d.get("sifir_ay") or []
    sifir_tr = (f"{len(sifir)} ayda hiç sefer kaydedilmedi ({', '.join(_ay(m) for m in sifir)})" if sifir
                else "Açıklamadan sonra hiçbir ayda sefer sayısı sıfıra inmedi")
    sifir_tr_kisa = "bazı aylarda kesintiye uğrayan bir trafik" if sifir else "hiçbir ayda sıfıra inmeyen bir trafik"
    bayraklar = ", ".join(bayrak_ad(b_) for b_, _c in d["bayrak"][:3])
    karsilastirma = ""
    if x["erken_tamam"] and x["oran"] is not None:
        karsilastirma = (f"Beyandan önceki aylarda (Kasım 2023 – Nisan 2024) Türk limanlarından İsrail limanlarına ayda ortalama "
                         f"{n(d['ort_once'])} sefer kaydedildi; beyandan sonra ortalama {n(d['ort_sonra'])}. Beyan sonrası sefer "
                         f"sayısı, beyan öncesinin {_yuzde(d['ort_sonra'], d['ort_once'])}'i düzeyinde.")
    else:
        karsilastirma = (f"Beyan öncesi dönemin (7 Ekim 2023 – 1 Mayıs 2024) geçmiş taraması henüz tamamlanmadı "
                         f"(şu an {'%' + n(kaps.get('erken')) if kaps.get('erken') is not None else 'başlamadı'}). Bu yüzden "
                         "beyan öncesi ve sonrası karşılaştırması bu sürümde verilmiyor; tarama bittiğinde rapor kendiliğinden "
                         "güncellenir.")
    ozet_p = (
        f"Türkiye Ticaret Bakanlığı 2 Mayıs 2024’te İsrail’le bütün ürünlerde ihracat ve ithalatın durdurulduğunu açıkladı. "
        f"Bu çalışma, gemilerin yayınladığı AIS (Otomatik Tanımlama Sistemi) sinyallerinden üretilen açık liman ziyareti ve "
        f"sinyal kesintisi kayıtlarıyla bu açıklamadan sonra Türk limanları ile İsrail limanları arasındaki gemi hareketini "
        f"inceliyor. {_gun(beyan)} ile {_gun(o['son_gun'])} arasında Türk limanlarından çıkıp İsrail limanlarına varan "
        f"<b>{n(d['sonra'])} sefer</b> ({n(d['gemi_sonra'])} gemi) tespit edildi: {n(a.get('dogrudan', 0))} sefer doğrudan, "
        f"{n(a.get('liman', 0))} sefer {ara_ulke} limanları üzerinden, {n(karanlik)} seferde gemi yolda AIS sinyalini kapattı ya da "
        f"İsrail açıklarında limana girmeden bekledi. "
        f"{sifir_tr} (en az {d['min_ay'][0] if d['min_ay'] else '–'}, en çok {d['max_ay'][0] if d['max_ay'] else '–'}). "
        + (f"Aynı dönemde İsrail limanlarından Türk limanlarına {n(i['sonra'])} sefer ({n(i['gemi_sonra'])} gemi) kaydedildi. " if i else "")
        + f"29 Ağustos 2025’te açıklanan liman kısıtlamalarından sonra da {n(d['kisit_sonra'])} sefer sürdü; bunların "
        f"{n(d['tr_bayrak_kisit'])} tanesinde gemi Türk bayraklıydı. Türk limanlarından İsrail’e giden ya da İsrail açıklarında "
        f"AIS’i kesilen {n(tk['gemi'])} tanker ya da muhtemel tanker belirlendi; bunların {n(tk['ceyhan_gemi'])} tanesi Ceyhan "
        f"terminallerinin önünden çıktı. Bulgular gemi hareketini gösterir; "
        "yükün ne olduğunu, sahibini ve ticaretin taraflarını göstermez. Bütün seferler gemi adı, IMO numarası ve tarihiyle "
        "listelenmiştir; yetkili kurumların gümrük beyannameleri ve konşimentolarla doğrulamasına açıktır.")
    bulgular = [
        f"Ticaretin durdurulduğu açıklanan 2 Mayıs 2024’ten sonra Türk limanlarından İsrail limanlarına {n(d['sonra'])} sefer "
        f"yapıldı ({n(d['gemi_sonra'])} gemi, ayda ortalama {n(d['ort_sonra'])}).",
        f"Seferlerin {n(a.get('liman', 0))}’i ({_yuzde(a.get('liman', 0), d['sonra'])}) önce {ara_ulke} limanlarına uğradı; en sık "
        f"ara limanlar {', '.join(x for x, _ in d['ara'][:3])}.",
        f"29 Ağustos 2025’teki liman kısıtlamalarından sonra {n(d['kisit_sonra'])} sefer; Türk bayraklı gemilerle "
        f"{n(d['tr_bayrak_kisit'])} sefer.",
        (f"İsrail limanlarından Türk limanlarına {n(i['sonra'])} sefer ({n(i['gemi_sonra'])} gemi)." if i else ""),
        f"Türk limanlarından İsrail’e giden ya da AIS’i İsrail açıklarında kesilen {n(tk['gemi'])} tanker ya da muhtemel tanker "
        f"({n(tk['sefer'])} sefer; {n(tk['ceyhan_gemi'])} gemi Ceyhan’dan); basında adı geçen tankerler de Ceyhan kayıtlarında görünüyor.",
    ]
    tablo_tur = _tablo(E, ["Sefer türü", "Türkiye → İsrail", "İsrail → Türkiye"], [
        [E(ad), n(d["aile_sonra"].get(k, 0)), n(i["aile_sonra"].get(k, 0)) if i else "–"]
        for k, ad in (("dogrudan", "Doğrudan (arada liman yok)"), ("liman", "Üçüncü ülke limanı üzerinden"),
                      ("sts", "Denizde gemiden gemiye"), ("karanlik", "AIS kapatılmış ya da kıyı açığında bekleme"))]
        + [["<b>Toplam</b>", f"<b>{n(d['sonra'])}</b>", f"<b>{n(i['sonra'])}</b>" if i else "–"],
           ["Gemi sayısı", n(d["gemi_sonra"]), n(i["gemi_sonra"]) if i else "–"],
           ["Aylık ortalama (tam aylar)", n(d["ort_sonra"]), n(i["ort_sonra"]) if i else "–"]],
        num=(1, 2), baslik=f"Tablo 2. {_gun(beyan)} – {_gun(o['son_gun'])} arasındaki seferler, türlerine göre")
    tablo_hat = _tablo(E, ["Çıkış (Türkiye)", "Varış (İsrail)", "Sefer"],
                       [[E(liman_tr(a_)), E(liman_tr(b_)), n(c)] for (a_, b_), c in d["hat"][:10]], num=(2,),
                       baslik="Tablo 3. En sık hatlar (beyandan sonra, Türkiye → İsrail)")
    tablo_ara = _tablo(E, ["Ara liman", "Uğrak"], [[E(liman_tr(a_)), n(c)] for a_, c in d["ara"][:10]], num=(1,),
                       baslik="Tablo 4. Ara limanlar (Türkiye → üçüncü ülke → İsrail seferlerinde)")
    tablo_bayrak = _tablo(E, ["Bayrak", "Sefer"], [[E(bayrak_ad(b_)), n(c)] for b_, c in d["bayrak"][:10]], num=(1,),
                          baslik="Tablo 5. Seferlerin gemi bayrağına göre dağılımı (beyandan sonra, Türkiye → İsrail)",
                          not_=f"Türk bayraklı gemilerle beyandan sonra {n(d['tr_bayrak'])} sefer, 29 Ağustos 2025’ten sonra "
                               f"{n(d['tr_bayrak_kisit'])} sefer; İsrail bayraklı gemilerle {n(d['il_bayrak'])} sefer.")
    tablo_gemi = _tablo(E, ["Gemi", "IMO", "Bayrak", "Sefer", "İlk", "Son"],
                        [[f"<b>{E(g['ad'])}</b>", E(g["imo"] or "–"), E(bayrak_ad(g["bayrak"], g["mmsi"])), n(g["n"]),
                          E(_ay(g["ilk"][:7])), E(_ay(g["son"][:7]))] for g in d["en_cok"][:15]], num=(3,),
                        baslik="Tablo 6. Beyandan sonra en çok sefer yapan 15 gemi (Türkiye → İsrail)")
    tablo_tanker = _tablo(E, ["Gemi", "IMO", "Bayrak", "Kanıt", "Sefer"],
                          [[f'<a href="../tankerler/{E(t["anahtar"])}.html"><b>{E(t["ad"])}</b></a>' + (" *" if t["basin"] else ""),
                            E(t["imo"] or "–"), E(t["bayrak"] or "–"), E(_duzey_tr(t["duzey"])), n(t["n"])]
                           for t in tk["ornekler"][:10]], num=(4,),
                          baslik="Tablo 8. Tanker dosyalarından örnekler (en güçlü kanıt önce)",
                          not_="* Basında da adı geçiyor. Her geminin dosyasında seferler, AIS’in kesildiği ve yeniden geldiği "
                               "noktalar ve o günlere ait uydu görüntüsü bağlantıları var.")
    kaynak = "".join(f'<li>{E(m)} <a href="{E(u)}" rel="noopener">{E(u)}</a></li>' for m, u in _kaynakca(o))
    kapsama = (f"Geçmiş taramanın bu sürümdeki durumu: beyan sonrası varış limanı taraması "
               f"{'%' + n(kaps['ana']) if kaps.get('ana') is not None else 'bilinmiyor'}, Ceyhan gemileri "
               f"{'%' + n(kaps['ceyhan']) if kaps.get('ceyhan') is not None else 'bilinmiyor'}, beyan öncesi dönem "
               f"{'%' + n(kaps['erken']) if kaps.get('erken') is not None else 'başlamadı'}. Tarama sürdükçe sayılar artabilir; "
               "azalmaz, çünkü eklenen her kayıt yeni bir liman ziyaretidir.")
    return f'''
<header class="makale-bas">
  <p class="dil"><a href="en.html" hreflang="en" lang="en">English version</a></p>
  <h1>Beyan ve kayıt: Türkiye’nin İsrail’le ticareti durdurma kararından sonra Türk limanlarından İsrail limanlarına gemi seferleri</h1>
  <p class="alt-baslik">AIS verisine dayanan bağımsız bir inceleme, 7 Ekim 2023 – {E(_gun(o["son_gun"]))}</p>
  <dl class="kunye-rapor">
    <div><dt>Hazırlayan</dt><dd>{E((cfg.raw.get("rapor") or {}).get("hazirlayan") or "Avvam, açık kaynak gemi izleme projesi")}</dd></div>
    <div><dt>Sürüm</dt><dd>{E(_gun(o["olusturma"][:10]))}, {E(o["olusturma"][11:16])} UTC</dd></div>
    <div><dt>Veri dönemi</dt><dd>7 Ekim 2023 – {E(_gun(o["son_gun"]))}</dd></div>
    <div class="genis"><dt>Veri kesitinin özeti (SHA-256)</dt><dd><code>{E(o["veri_hash"])}</code></dd></div>
  </dl>
  <p class="pdf-satir" id="pdf-satir"></p>
</header>
<section class="ozet-kutu" aria-labelledby="ozet"><h2 id="ozet">Özet</h2><p>{ozet_p}</p>
  <h3>Ana bulgular</h3><ul>{"".join(f"<li>{b}</li>" for b in bulgular if b)}</ul></section>

<h2 id="giris">1. Giriş</h2>
<p>Türkiye, Gazze’deki savaşla bağlantılı olarak İsrail’le ticarete adım adım kısıtlama getirdiğini açıkladı. Ticaret Bakanlığı
9 Nisan 2024’te 54 ürün grubunda (1.019 gümrük tarife pozisyonu) İsrail’e ihracatı kısıtladı. 2 Mayıs 2024’te İsrail’le ilgili
bütün ihracat ve ithalat işlemlerinin durdurulduğunu duyurdu. Dışişleri Bakanı Hakan Fidan 29 Ağustos 2025’te İsrail gemilerinin
Türk limanlarına girmesine ve Türk bayraklı gemilerin İsrail limanlarına gitmesine izin verilmediğini söyledi. Ticaret Bakanlığı
30 Mart 2026’da transit ve serbest bölge ticareti de dahil bütün ticaretin durduğunu, Filistin’e giden ürünlerin ise Filistin’in
kendi limanı olmadığı için İsrail limanlarından geçtiğini belirtti.</p>
<p>Bu çalışmanın sorusu şudur: Bu açıklamalardan sonra Türk limanları ile İsrail limanları arasındaki gemi trafiği durdu mu?
Soruyu gümrük kayıtlarıyla değil, gemilerin kendi yayınladığı konum sinyalleriyle cevaplıyoruz. Gemi hareketi ticaretin kendisi
değildir; ama bir limandan çıkıp başka bir ülkenin limanına giren gemi, iki ülke arasındaki deniz bağlantısının fiilî kaydıdır ve
herkesin erişebildiği verilerle doğrulanabilir.</p>
<p>Rapor üç şey sunuyor: (1) beyandan sonraki seferlerin gemi gemi, tarih tarih listesi; (2) seferlerin nasıl yapıldığının
sınıflandırması: doğrudan, üçüncü ülke limanı üzerinden ya da AIS sinyali kapatılarak; (3) Ceyhan’daki petrol terminallerinden
çıkan tankerlerin ayrı incelemesi. Bütün veri ve kod açıktır; her günün kaydı mühürlenir.</p>

<h2 id="aciklamalar">2. Resmî açıklamalar</h2>
{_tablo(E, ["Tarih", "Kurum", "Açıklama", "Kaynak"],
        [[E(_gun(t["gun"])), E(t["kim"]), (E(t["metin"]) if t.get("aktarim") else f"“{E(t['metin'])}”")
          + (" <span class=not>(özet)</span>" if t.get("aktarim") else ""), f'<a href="{E(t["url"])}" rel="noopener">{E(t["kaynak"])}</a>']
         for t in o.get("testler") or []], baslik="Tablo 1. Verinin sınadığı resmî açıklamalar")}

<h2 id="yontem">3. Veri ve yöntem</h2>
<h3>3.1 Veri kaynakları</h3>
<p>Uluslararası sefer yapan 300 gros ton ve üstü gemiler ile bütün yolcu gemileri AIS taşımak zorundadır (SOLAS Bölüm V, Kural 19).
AIS cihazı geminin kimliğini (ad, MMSI, IMO), konumunu, hızını ve beyan ettiği varış yerini birkaç saniye ile birkaç dakika arasında
bir yayınlar. Bu raporda iki kaynak kullanıldı:</p>
<ul>
<li><b>Global Fishing Watch (GFW)</b>: AIS sinyallerinden üretilen ve herkese açık olan liman ziyareti olayları (güven düzeyi 3 ve 4),
AIS boşluğu olayları ve AIS varlık verisi. Dönem: 7 Ekim 2023’ten bugüne. GFW verisi birkaç gün gecikmeli oluşur; bu sürümün son
günü {E(_gun(o["son_gun"]))}. Veri CC BY-NC 4.0 lisanslıdır.</li>
<li><b>Bu projenin canlı AIS kaydı</b>: aisstream.io üzerinden Türk, İsrail ve ara ülke limanlarının çevresindeki bütün gemilerin
mesajları. Her günün ham dosyası değiştirilmeden saklanır, SHA-256 ile mühürlenir ve günler birbirine zincirlenir; zincirin ucu
OpenTimestamps ile zaman damgası alır.</li>
</ul>
<h3>3.2 Sefer tanımı</h3>
<p>Bir geminin liman ziyaretleri zaman sırasına dizilir. Aynı limanda art arda gelen ve aralarında 72 saatten az olan ziyaretler tek
uğrak sayılır. İstanbul ve Çanakkale boğazlarının bekleme alanlarındaki demirlemeler liman uğrağı sayılmaz. Bir sefer, Türk
limanından son çıkışla başlar ve İsrail limanına ilk girişle biter:</p>
<ul>
<li><b>Doğrudan</b>: arada başka liman uğrağı yok; çıkıştan varışa en fazla {th["dogrudan_max_gun"]} gün.</li>
<li><b>Üçüncü ülke limanı üzerinden</b>: arada en fazla {th["aktarma_max_liman"]} uğrak, yalnızca {ara_ulke} limanlarında; çıkıştan varışa
en fazla {th["aktarma_max_gun"]} gün. Başka bir ülkenin limanına uğrayan geminin yükü orada değişmiş olabileceği için o sefer sayılmaz.</li>
<li><b>Yolda AIS boşluğu</b>: Türk limanından İsrail limanına giden gemi yolda en az {th["ais_bosluk_saat"]} saat sinyal vermedi.</li>
<li><b>İsrail açıklarında AIS kapalı</b>: gemi Türk limanından çıktı, hiçbir limana uğramadan AIS sinyali en az
{th.get("hedef_acik_bosluk_saat") or 12} saat kesildi ve sinyalin kesildiği ya da yeniden geldiği nokta İsrail’in açık denizinde
({E(kutu_s)}). GFW kıyıya yakın kesintileri çoğu zaman “kasıtlı kapatma” saymaz; bu kural GFW’nin bu işaretine bakmaz.</li>
<li><b>Konumu İsrail açıklarında ya da GPS karıştırma izinde</b>: gemi Türk limanından çıktı ve bir sonraki liman uğrağından önce, AIS
açıkken, konumu İsrail’in açık denizinde ya da Beyrut havalimanında göründü (GFW AIS varlık verisi). İsrail yakınındaki gemi ve uçakların
sahte konumu çoğunlukla Beyrut havalimanında görünür (NPR, 2024); kara üzerindeki bu noktada konumu görünen gemi İsrail’in GPS karıştırma
menzilindedir. Karıştırma, gemi İsrail limanına girse bile GFW’nin bu ziyareti kaydetmesini engelleyebilir.</li>
<li><b>Limansız Ceyhan dönüşü</b>: gemi Ceyhan’dan çıkıp hiçbir limana uğramadan {th.get("limansiz_donus_gun") or 20} gün içinde
Ceyhan’a döndü. Yüklediği petrolü nereye boşalttığı kayıtta yoktur. Bu tek başına İsrail’e gidildiğini göstermez; tanker dosyalarında
ayrıca sayılır.</li>
<li><b>Kıyı açığında bekleme</b>: gemi İsrail kıyısının yaklaşık 25 km yakınında, hiçbir limana girmeden, ardışık günlerde en az 12 saat
bulundu (GFW AIS varlık verisi) ve bir önceki uğrağı Türk limanıydı (olası şamandıra boşaltması).</li>
<li><b>Karanlık sefer</b>: Türk limanından çıkan gemi Doğu Akdeniz’de en az {th["karanlik_sefer_saat"]} saat sinyal vermedi ve varış
limanı kayıtsız kaldı. Gemi İsrail’e gitmiş olabilir ya da olmayabilir; bu tür ayrıca gösterilir.</li>
</ul>
<h3>3.3 Dönem kuralı</h3>
<p>Bir seferin beyandan sonra sayılması için Türk tarafındaki olayın beyandan sonra olması gerekir: Türkiye’den İsrail’e seferde
Türk limanından çıkış, İsrail’den Türkiye’ye seferde Türk limanına varış 2 Mayıs 2024 ve sonrasındadır.</p>
<h3>3.4 Tankerler</h3>
<p>Ceyhan’daki Bakü-Tiflis-Ceyhan (BTC) ve Kerkük-Ceyhan terminalleri birbirine birkaç kilometre uzaktadır ve AIS konumuyla ayırt
edilemez; GFW bu terminallere gelen gemilerin ziyaretlerini terminallerin 6-10 km güneyindeki demirleme noktalarına bağlar. Bu yüzden
terminallerin 11 km çevresi “Ceyhan terminalleri ve demirleme alanı” sayıldı. Aynı alanda kömür, gübre ve çimento gemileri de
bulunabildiği için bir gemi ancak şu kanıtlardan biriyle tanker sayıldı: AIS’te kendini tanker olarak bildirmesi, sıvı dökme yük
iskelesine yanaşması, rotasında başka petrol iskelelerinin bulunması ya da basında tanker olarak adının geçmesi. GFW’nin kargo gemisi
saymadığı (tankerlerin bulunduğu sınıftaki) gemiler “muhtemel tanker” olarak ayrıca işaretlendi.</p>
<h3>3.5 Kanıt bütünlüğü</h3>
<p>Bu sürümün dayandığı bütün sefer kayıtlarının (kimlik, tür, gemi, çıkış ve varış limanı ve zamanı) sabit sıralı özetinin SHA-256
değeri künyede yazılıdır: <code>{E(o["veri_hash"][:16])}…</code>. Aynı kayıtlardan herkes aynı değeri hesaplayabilir. Kayıtların tamamı
CSV olarak indirilebilir; her seferin satırında dayandığı GFW olaylarının (çıkış ve varış liman ziyareti, ara uğraklar, AIS boşlukları)
kimlikleri ve geminin GFW kimliği yazılıdır, böylece her sefer GFW’nin kendi kayıtlarından bağımsız olarak doğrulanabilir.
Sınıflandırmayı yapan kod açık kaynaklıdır.</p>

<h2 id="bulgular">4. Bulgular</h2>
<h3>4.1 Genel tablo</h3>
<p>{_gun(beyan)} ile {_gun(o["son_gun"])} arasında Türk limanlarından İsrail limanlarına {n(d["sonra"])} sefer kaydedildi. Bu seferleri
{n(d["gemi_sonra"])} farklı gemi yaptı. Tam ayların ortalaması ayda {n(d["ort_sonra"])} sefer; en az sefer
{_ay(d["min_ay"][1]) if d["min_ay"] else "–"} ayında ({d["min_ay"][0] if d["min_ay"] else "–"}), en çok sefer
{_ay(d["max_ay"][1]) if d["max_ay"] else "–"} ayında ({d["max_ay"][0] if d["max_ay"] else "–"}) yapıldı. {sifir_tr} (Şekil 1).</p>
<figure class="sekil"><div class="grafik-kaydir">{oz.aylik_svg(o, "TR>IL", kimlik="sekil1")}</div><figcaption>Şekil 1. Türk limanlarından İsrail limanlarına aylık sefer sayısı,
sefer türüne göre. Kesik dikey çizgiler resmî açıklamaların tarihleridir. Son sütun içinde bulunulan aydır ve eksiktir.
{"" if x["erken_tamam"] else "Gölgeli dönemin taraması sürmektedir."}</figcaption></figure>
{tablo_tur}
<h3>4.2 Limanlar ve hatlar</h3>
<p>Türkiye tarafında en çok sefer {E(d["cikis"][0][0]) if d["cikis"] else "–"} ({n(d["cikis"][0][1]) if d["cikis"] else "–"}) ve
{E(d["cikis"][1][0]) if len(d["cikis"]) > 1 else "–"} ({n(d["cikis"][1][1]) if len(d["cikis"]) > 1 else "–"}) çıkışlı; İsrail tarafında
varışların {n(d["varis"][0][1]) if d["varis"] else "–"} tanesi {E(d["varis"][0][0]) if d["varis"] else "–"},
{n(d["varis"][1][1]) if len(d["varis"]) > 1 else "–"} tanesi {E(d["varis"][1][0]) if len(d["varis"]) > 1 else "–"} limanına (Tablo 3).</p>
{tablo_hat}
<h3>4.3 Üçüncü ülke limanları üzerinden seferler</h3>
<p>Seferlerin {n(a.get("liman", 0))} tanesinde ({_yuzde(a.get("liman", 0), d["sonra"])}) gemi Türk limanından çıktıktan sonra, İsrail
limanına girmeden önce {ara_ulke} limanlarından en az birine uğradı (Tablo 4). Bu seferlerin bir kısmı birçok limana uğrayan düzenli
hat seferleridir; bir kısmında yükün ara limanda el değiştirmiş olması da mümkündür. Veri ikisini ayırt etmez.</p>
{tablo_ara}
<h3>4.4 Bayrak</h3>
<p>En çok sefer yapan bayraklar {E(bayraklar)} (Tablo 5). Türk bayraklı
gemilerle beyandan sonra {n(d["tr_bayrak"])} sefer, Türk bayraklı gemilerin İsrail limanlarına gitmeyeceğinin açıklandığı 29 Ağustos
2025’ten sonra {n(d["tr_bayrak_kisit"])} sefer kaydedildi. Bayrak bilgisi GFW’nin olay kaydındaki bayraktır; gemi sonradan bayrak
değiştirmiş olabilir.</p>
{tablo_bayrak}
<h3>4.5 Gemiler</h3>
<p>Beyandan sonra en çok sefer yapan 15 gemi Tablo 6’da. Bütün gemilerin listesi, her geminin bütün seferleriyle birlikte
<a href="../raporlar/index.html">gemiler sayfasında</a> ve CSV dosyalarındadır.</p>
{tablo_gemi}
<h3>4.6 Ceyhan ve petrol tankerleri</h3>
<p>Geçmiş taramada Ceyhan terminallerinin önündeki demirleme alanından {n(cy["cikis"])} çıkış ({n(cy["gemi"])} gemi) işlendi. Bunların
{n(cy["il"])} tanesinde bir sonraki uğrak İsrail limanıydı; {n(cy["il_acik"])} tanesinde gemi hiçbir limana uğramadan AIS sinyali
İsrail açıklarında kesildi ya da orada yeniden geldi. {n(cy["donus"])} çıkışta ({n(cy["donus_gemi"])} gemi) gemi hiçbir limana
uğramadan {th.get("limansiz_donus_gun") or 20} gün içinde Ceyhan’a döndü: yüklenen petrolün boşaltıldığı yer kayıtsız. {n(cy["iz"])}
çıkışta geminin AIS konumu bir sonraki liman uğrağından önce İsrail açıklarında ya da Beyrut havalimanındaki sahte konum noktasında
göründü{(", bunların " + n(cy["iz_donus"]) + " tanesi limansız dönüş") if cy.get("iz_donus") else ""}. Tanker dosyalarında
{n(tk["gemi"])} gemi ve {n(tk["sefer"])} sefer var; bunların
{n(tk["dogrulanan"])} gemisinin tanker olduğu AIS tipi, iskele, rota ya da basın kaydıyla doğrulandı (Tablo 8). İsrail limanına kayıtlı varışı olan Ceyhan seferleri Tablo 7’de. {_basin_tr(o)}</p>
{_cey_ornek_tr(o, E)}
{tablo_tanker}
<h3>4.7 İsrail’den Türkiye’ye seferler</h3>
<p>{(f"Aynı dönemde İsrail limanlarından çıkıp Türk limanlarına varan {n(i['sonra'])} sefer ({n(i['gemi_sonra'])} gemi, ayda ortalama "
     f"{n(i['ort_sonra'])}) kaydedildi; en çok varış {E(i['varis'][0][0]) if i['varis'] else '–'} limanına. Ticaret Bakanlığı’na göre "
     "2 Mayıs 2024’ten bu yana İsrail’den bir sevkiyat yoktur; gemi hareketi yükün kaynağını göstermez, ancak bu seferlerin her biri "
     "gemi adı ve tarihiyle listelenmiştir.") if i else "Bu yönde kayıt yok."}</p>
<figure class="sekil"><div class="grafik-kaydir">{oz.aylik_svg(o, next((y for y, v in o["yonler"].items() if not v["ihracat"]), "TR>IL"), kimlik="sekil2")}</div>
<figcaption>Şekil 2. İsrail limanlarından Türk limanlarına aylık sefer sayısı.</figcaption></figure>
<h3>4.8 Beyan öncesiyle karşılaştırma</h3>
<p>{karsilastirma}</p>

<h2 id="tartisma">5. Tartışma</h2>
<h3>5.1 Resmî açıklamalarla karşılaştırma</h3>
<p>Ticaret Bakanlığı’nın 2 Mayıs 2024 açıklaması bir gümrük kararıdır; gemi trafiğinin bütünüyle durmasını gerektirmez. Ancak
açıklamadan sonra Türk limanlarından İsrail limanlarına her ay onlarca seferin sürmesi, iki ülke arasındaki deniz bağlantısının
kesilmediğini gösterir. Enerji Bakanlığı’nın 11 Kasım 2024’te “İsrail varışlı sevkiyat olmadı” açıklaması, Ceyhan’dan çıkan
tankerlerin İsrail limanlarına girdiği ya da İsrail açıklarında AIS’ini kapattığı kayıtlarla karşılaştırılmalıdır (Bölüm 4.6).
Fidan’ın 29 Ağustos 2025 açıklamasından sonra Türk bayraklı gemilerle yapılan {n(d["tr_bayrak_kisit"])} sefer ve bütün bayraklarla
yapılan {n(d["kisit_sonra"])} sefer, liman kısıtlamalarının trafiği durdurmadığını gösterir.</p>
<h3>5.2 Başka açıklamalar</h3>
<ul>
<li><b>Filistin ticareti.</b> Ticaret Bakanlığı, Filistin’e giden ürünlerin İsrail limanlarından geçtiğini ve bu ticaretin ayda
50-60 milyon dolar olduğunu söylüyor; aynı açıklamaya göre savaştan önce İsrail’e aylık ihracat 600-700 milyon dolardı. Bu, değer
olarak savaş öncesinin yaklaşık %7-10’u demektir. {("Gemi seferlerinin aylık ortalaması ise beyan öncesinin " + _yuzde(d["ort_sonra"], d["ort_once"]) + "’i düzeyindedir. Sefer sayısı yük değerini doğrudan göstermez; yine de iki oran arasındaki büyük fark, seferlerin tamamını Filistin ticaretiyle açıklamayı güçleştirir.") if x["erken_tamam"] and x["oran"] else "Bu oranı sefer sayısıyla karşılaştırmak için beyan öncesi dönemin taramasının tamamlanması bekleniyor."}</li>
<li><b>Düzenli hat ve aktarma.</b> Konteyner ve genel kargo gemilerinin bir kısmı birçok ülkeye uğrayan düzenli hatlarda çalışır ve
üçüncü ülkelerin yükünü de taşır. Bu gemilerin Türk limanından İsrail limanına geçişi, Türk menşeli yükün İsrail’e indiğini tek başına
göstermez. Öte yandan Bakanlığın açıklamasına göre transit ticaret de durdurulmuştur.</li>
<li><b>Boş sefer.</b> Bir gemi yük almadan da bir limandan diğerine gidebilir. AIS’teki su çekimi değişimi bu konuda ipucu verir, ama
geçmiş taramada su çekimi bilgisi yoktur.</li>
<li><b>Veri hataları.</b> GFW liman ziyaretleri bir sınıflandırma modelinin çıktısıdır; güven düzeyi düşük ziyaretler kullanılmadı.
Adı olmayan demirleme yerleri en yakın limana göre adlandırıldı.</li>
</ul>
<h3>5.3 Sınırlar</h3>
<ul>
<li>AIS sinyalini tamamen kapatan ya da sahte konum yayınlayan gemiler kayıtta eksik kalır; gerçek sefer sayısı bu rapordakinden büyük
olabilir.</li>
<li>Canlı kayıt, gönüllülerin kurduğu kıyı alıcılarına dayanır; İskenderun, Aliağa ve İzmit’te canlı kapsama yoktur. Bu limanlar için
GFW verisi kullanıldı.</li>
<li>{E(kapsama)}</li>
<li>Bu rapor yükü, yükün sahibini, satıcısını ya da ticaretin hukuki niteliğini incelemez.</li>
</ul>

<h2 id="sonuc">6. Sonuç</h2>
<p>Gemilerin kendi yayınladığı konum sinyallerinden üretilen açık kayıtlar, Türkiye’nin İsrail’le ticareti durdurduğunu açıkladığı
2 Mayıs 2024’ten sonra Türk limanlarından İsrail limanlarına gemi seferlerinin durmadığını gösteriyor: {n(d["sonra"])} sefer,
{n(d["gemi_sonra"])} gemi ve {sifir_tr_kisa}. Seferlerin bir bölümü üçüncü ülke limanları üzerinden yapıldı, bir
bölümünde gemi yolda AIS sinyalini kapattı. {_cey_sonuc_tr(o)} Bu bulgular yükün sahibini ve ticaretin taraflarını belirlemez; ancak her sefer gemi adı, IMO numarası, liman ve
saatle listelendiği için, yetkili kurumlar bu listeyi gümrük beyannameleri, konşimentolar ve liman kayıtlarıyla doğrulayabilir.
Önerimiz, bu listenin bağımsız denetimle karşılaştırılması ve uyumsuzlukların kamuoyuyla paylaşılmasıdır.</p>

<h2 id="veri">Veri erişimi ve atıf</h2>
<ul>
<li>Bütün seferler: <a href="../raporlar/tr-il-seferler.csv">Türkiye → İsrail (CSV)</a>, <a href="../raporlar/il-tr-seferler.csv">İsrail →
Türkiye (CSV)</a>; tankerler: <a href="../tankerler/tankerler.csv">tankerler.csv</a>; raporun sayıları:
<a href="../veri/rapor-ozet.json">rapor-ozet.json</a>.</li>
<li>Günlük arşiv ve kanıt zinciri: <a href="../kanit.html">Kanıt zinciri</a>. Yöntemin bütün eşikleri: <a href="../yontem.html">Yöntem</a>.</li>
<li>Atıf: Avvam ({o["olusturma"][:4]}). <i>Beyan ve kayıt: Türkiye’nin İsrail’le ticareti durdurma kararından sonra Türk limanlarından
İsrail limanlarına gemi seferleri</i>. Sürüm {E(_gun(o["olusturma"][:10]))}, veri özeti {E(o["veri_hash"][:16])}.</li>
<li>Geçmiş tarama: Powered by Global Fishing Watch. Veri CC BY-NC 4.0.</li>
</ul>
<h2 id="kaynakca">Kaynakça</h2><ol class="kaynakca">{kaynak}</ol>'''


def _cey_sonuc_tr(o) -> str:
    t = o["tanker"]
    if t.get("ceyhan_kayitli"):
        return (f"Ceyhan terminallerinin önünden çıkan {t['ceyhan_kayitli']} tanker ya da muhtemel tanker beyandan sonra İsrail limanına "
                f"girdi ({t['ceyhan_kayitli_sefer']} sefer); {t.get('ceyhan_gizli', 0)} tanker ya da muhtemel tankerin Ceyhan çıkışlı "
                "seferlerinde AIS sinyali kapandı ya da konumu gizlendi.")
    if t.get("ceyhan_gizli"):
        return (f"Ceyhan terminallerinin önünden çıkan {t['ceyhan_gizli']} tanker ya da muhtemel tankerin seferlerinde AIS sinyali "
                "kapandı ya da konumu gizlendi; bu sürümde Ceyhan’dan İsrail limanına kayıtlı tanker varışı yok.")
    return "Bu sürümde Ceyhan’dan İsrail’e kayıtlı tanker seferi yok; Ceyhan gemilerinin geçmiş taraması sürüyor."


def _cey_sonuc_en(o) -> str:
    t = o["tanker"]
    if t.get("ceyhan_kayitli"):
        return (f"{t['ceyhan_kayitli']} tankers or probable tankers leaving the Ceyhan terminals entered Israeli ports after the "
                f"declaration ({t['ceyhan_kayitli_sefer']} voyages); on voyages from Ceyhan of {t.get('ceyhan_gizli', 0)} tankers or "
                "probable tankers the AIS signal went off or the position was concealed.")
    if t.get("ceyhan_gizli"):
        return (f"On voyages from Ceyhan of {t['ceyhan_gizli']} tankers or probable tankers the AIS signal went off or the position "
                "was concealed; this version has no recorded tanker arrival from Ceyhan at an Israeli port.")
    return "This version has no recorded tanker voyage from Ceyhan to Israel; the historical scan of Ceyhan vessels is in progress."


def _cey_ornek_tr(o, E) -> str:
    xs = o["tanker"].get("ceyhan_ornek") or []
    if not xs:
        return ""
    rows = [[f'<a href="../tankerler/{E(x["anahtar"])}.html"><b>{E(x["ad"])}</b></a>', E(x["imo"] or "–"), E(x["bayrak"] or "–"),
             E(_gun(x["t0"])), E(", ".join(x["ara"]) or "–"), E(liman_tr(x["d"])), E(_gun(x["t1"]))] for x in xs]
    return _tablo(E, ["Gemi", "IMO", "Bayrak", "Ceyhan’dan çıkış", "Ara liman", "Varış", "Varış tarihi"], rows,
                  baslik="Tablo 7. Ceyhan terminallerinin önünden çıkıp İsrail limanına kayıtlı varışı olan tanker seferleri (en yeni önce)",
                  not_="Varış, Global Fishing Watch’ın liman ziyareti kaydıdır (gemi o limanın demirleme ya da iskele alanında görüldü).")


def _cey_ornek_en(o, E) -> str:
    xs = o["tanker"].get("ceyhan_ornek") or []
    if not xs:
        return ""
    rows = [[f'<a href="../tankerler/{E(x["anahtar"])}.html"><b>{E(x["ad"])}</b></a>', E(x["imo"] or "–"),
             E(bayrak_ad(x.get("flag3"), x.get("mmsi"), True)),
             E(_gun(x["t0"], True)), E(", ".join(liman_en(a) for a in x["ara"]) or "–"), E(liman_en(x["d"])), E(_gun(x["t1"], True))]
            for x in xs]
    return _tablo(E, ["Vessel", "IMO", "Flag", "Left Ceyhan", "Intermediate port", "Arrival", "Arrival date"], rows,
                  baslik="Table 7. Tanker voyages from the Ceyhan terminals with a recorded arrival at an Israeli port (latest first)",
                  not_="The arrival is a Global Fishing Watch port-visit record (the vessel was seen in the anchorage or berth area of "
                       "that port).")


def _basin_tr(o) -> str:
    b = o.get("basin") or []
    if not b:
        return ""
    p = []
    for x in b:
        if not x["taranan"]:
            p.append(f"{x['ad']} Ceyhan’a {len(x['alan'])} kez uğradı (geçmişi taranıyor)" if x["alan"]
                     else f"{x['ad']} için geçmiş taraması sürüyor")
        else:
            p.append(f"{x['ad']} Ceyhan’dan {x['cikis']} kez çıktı; bunların {x['il_liman']} tanesinde sonraki uğrak İsrail limanı, "
                     f"{x['il_acik']} tanesinde AIS sinyali İsrail açıklarında kesildi ya da orada yeniden geldi")
    s = ("Middle East Eye ve Greek City Times’ın Ceyhan’dan Aşkelon’a petrol taşıdığını yazdığı tankerler bu verilerde de var: "
         + "; ".join(p) + ".")
    taranan = [x for x in b if x["taranan"]]
    if taranan and all(x["il_liman"] == 0 for x in taranan):
        s += (" Geçmişi taranan bu gemilerin hiçbirinin Ceyhan çıkışından sonra GFW’de İsrail limanı kaydı yok; bu, haberlerde "
              "anlatılan AIS kapatma örüntüsüyle tutarlıdır.")
    return s


def _basin_en(o) -> str:
    b = o.get("basin") or []
    if not b:
        return ""
    p = []
    for x in b:
        if not x["taranan"]:
            p.append(f"{x['ad']} called at Ceyhan {len(x['alan'])} times (history scan in progress)" if x["alan"]
                     else f"the history scan of {x['ad']} is in progress")
        else:
            p.append(f"{x['ad']} left Ceyhan {x['cikis']} times; the next call was an Israeli port in {x['il_liman']} of them, and in "
                     f"{x['il_acik']} the AIS signal stopped or resumed near Israel")
    s = ("Tankers that Middle East Eye and Greek City Times reported as carrying oil from Ceyhan to Ashkelon also appear in these "
         "data: " + "; ".join(p) + ".")
    taranan = [x for x in b if x["taranan"]]
    if taranan and all(x["il_liman"] == 0 for x in taranan):
        s += (" None of the scanned vessels has an Israeli port visit in GFW after leaving Ceyhan, which is consistent with the AIS "
              "switch-off pattern described in the reports.")
    return s


def _duzey_tr(k: str) -> str:
    from .tanker import AD
    return AD.get(k, k)


# --------------------------------------------------------------------------- English
def _en(cfg, o, E) -> str:
    x = _ekler(cfg, o, True)
    d, i, a, kaps = x["d"], x["i"], x["a"], x["kaps"]
    th = cfg.th
    tk, cy = o["tanker"], o["ceyhan"]
    n = lambda v: _n(v, True)  # noqa: E731
    g = lambda s: _gun(s, True)  # noqa: E731
    beyan = o["beyan"]
    karanlik = a.get("karanlik", 0) + a.get("sts", 0)
    kutu = th.get("hedef_acik_deniz")
    kutu_s = f"{kutu[0][0]}–{kutu[1][0]}° N, {kutu[0][1]}–{kutu[1][1]}° E" if kutu else "not defined"
    via = "Egypt, Greece, Cyprus and Bulgaria"
    sifir = d.get("sifir_ay") or []
    sifir_en = (f"No voyages were recorded in {len(sifir)} month(s) ({', '.join(_ay(m, True) for m in sifir)})" if sifir
                else "In no month after the announcement did the number of voyages fall to zero")
    sifir_en_kisa = "traffic that was interrupted in some months" if sifir else "traffic that did not fall to zero in any month"
    flags = ", ".join(bayrak_ad(b_, en=True) for b_, _c in d["bayrak"][:3])
    pct = lambda p: f"{p:.1f}%" if p is not None else "not started"  # noqa: E731
    if x["erken_tamam"] and x["oran"] is not None:
        comp = (f"In the months before the declaration (November 2023 – April 2024) an average of {n(d['ort_once'])} voyages a month "
                f"went from Turkish to Israeli ports; after the declaration the average was {n(d['ort_sonra'])}, i.e. "
                f"{_yuzde(d['ort_sonra'], d['ort_once'], True)} of the earlier level.")
    else:
        comp = (f"The historical scan of the period before the declaration (7 October 2023 – 1 May 2024) is not yet complete "
                f"({pct(kaps.get('erken'))}). The before/after comparison is therefore not given in this version; the report "
                "updates itself when the scan is finished.")
    abstract = (
        f"On 2 May 2024 the Ministry of Trade of Türkiye announced that all export and import transactions with Israel had been "
        f"stopped. This study examines vessel movements between Turkish and Israeli ports after that announcement, using open "
        f"port-visit and signal-gap records derived from the Automatic Identification System (AIS) signals that ships broadcast. "
        f"Between {g(beyan)} and {g(o['son_gun'])} we identified <b>{n(d['sonra'])} voyages</b> by {n(d['gemi_sonra'])} vessels that left "
        f"a Turkish port and arrived at an Israeli port: {n(a.get('dogrudan', 0))} direct, {n(a.get('liman', 0))} via ports in {via}, "
        f"and {n(karanlik)} in which the vessel switched off its AIS en route or waited off the Israeli coast without entering port. "
        f"{sifir_en} (minimum {d['min_ay'][0] if d['min_ay'] else '–'}, "
        f"maximum {d['max_ay'][0] if d['max_ay'] else '–'}). "
        + (f"In the same period {n(i['sonra'])} voyages ({n(i['gemi_sonra'])} vessels) went from Israeli to Turkish ports. " if i else "")
        + f"After the port restrictions announced on 29 August 2025, {n(d['kisit_sonra'])} voyages continued, "
        f"{n(d['tr_bayrak_kisit'])} of them by Turkish-flagged vessels. We identified {n(tk['gemi'])} tankers or probable tankers that "
        f"left Turkish ports and either entered Israeli ports or had their AIS signal cut off near Israel, {n(tk['ceyhan_gemi'])} of "
        f"them from the Ceyhan oil terminals. The findings "
        "describe vessel movements; they do not establish the nature, ownership or parties of the cargo. Every voyage is listed with "
        "vessel name, IMO number and time, so that competent authorities can verify it against customs declarations and bills of lading.")
    findings = [
        f"After 2 May 2024, when trade was declared halted, {n(d['sonra'])} voyages went from Turkish to Israeli ports "
        f"({n(d['gemi_sonra'])} vessels, {n(d['ort_sonra'])} a month on average).",
        f"{n(a.get('liman', 0))} voyages ({_yuzde(a.get('liman', 0), d['sonra'], True)}) first called at ports in {via}; the most "
        f"frequent intermediate ports were {', '.join(liman_en(p) for p, _ in d['ara'][:3])}.",
        f"After the port restrictions of 29 August 2025: {n(d['kisit_sonra'])} voyages, {n(d['tr_bayrak_kisit'])} of them by "
        "Turkish-flagged vessels.",
        (f"From Israeli to Turkish ports: {n(i['sonra'])} voyages ({n(i['gemi_sonra'])} vessels)." if i else ""),
        f"{n(tk['gemi'])} tankers or probable tankers ({n(tk['sefer'])} voyages; {n(tk['ceyhan_gemi'])} vessels from Ceyhan) went "
        "from Turkish ports to Israel or had their AIS cut off near Israel; tankers named in press reports also appear in the Ceyhan records.",
    ]
    t_type = _tablo(E, ["Voyage type", "Türkiye → Israel", "Israel → Türkiye"], [
        [E(ad), n(d["aile_sonra"].get(k, 0)), n(i["aile_sonra"].get(k, 0)) if i else "–"]
        for k, ad in (("dogrudan", "Direct (no intermediate port)"), ("liman", "Via a third-country port"),
                      ("sts", "Ship-to-ship at sea"), ("karanlik", "AIS off or waiting offshore"))]
        + [["<b>Total</b>", f"<b>{n(d['sonra'])}</b>", f"<b>{n(i['sonra'])}</b>" if i else "–"],
           ["Vessels", n(d["gemi_sonra"]), n(i["gemi_sonra"]) if i else "–"],
           ["Monthly average (full months)", n(d["ort_sonra"]), n(i["ort_sonra"]) if i else "–"]],
        num=(1, 2), baslik=f"Table 2. Voyages between {g(beyan)} and {g(o['son_gun'])}, by type")
    t_route = _tablo(E, ["Departure (Türkiye)", "Arrival (Israel)", "Voyages"],
                     [[E(liman_en(a_)), E(liman_en(b_)), n(c)] for (a_, b_), c in d["hat"][:10]], num=(2,),
                     baslik="Table 3. Most frequent routes (after the declaration, Türkiye → Israel)")
    t_via = _tablo(E, ["Intermediate port", "Calls"], [[E(liman_en(a_)), n(c)] for a_, c in d["ara"][:10]], num=(1,),
                   baslik="Table 4. Intermediate ports (Türkiye → third country → Israel)")
    t_flag = _tablo(E, ["Flag", "Voyages"], [[E(bayrak_ad(b_, en=True)), n(c)] for b_, c in d["bayrak"][:10]], num=(1,),
                    baslik="Table 5. Voyages by vessel flag (after the declaration, Türkiye → Israel)",
                    not_=f"Turkish-flagged vessels: {n(d['tr_bayrak'])} voyages after the declaration, {n(d['tr_bayrak_kisit'])} after "
                         f"29 August 2025; Israeli-flagged vessels: {n(d['il_bayrak'])}.")
    t_ship = _tablo(E, ["Vessel", "IMO", "Flag", "Voyages", "First", "Last"],
                    [[f"<b>{E(s['ad'])}</b>", E(s["imo"] or "–"), E(bayrak_ad(s["bayrak"], s["mmsi"], True)), n(s["n"]),
                      E(_ay(s["ilk"][:7], True)), E(_ay(s["son"][:7], True))] for s in d["en_cok"][:15]], num=(3,),
                    baslik="Table 6. The 15 vessels with most voyages after the declaration (Türkiye → Israel)")
    t_tank = _tablo(E, ["Vessel", "IMO", "Flag", "Evidence", "Voyages"],
                    [[f'<a href="../tankerler/{E(t["anahtar"])}.html"><b>{E(t["ad"])}</b></a>' + (" *" if t["basin"] else ""),
                      E(t["imo"] or "–"), E(bayrak_ad(t.get("flag3"), t.get("mmsi"), True)),
                      E(DUZEY_EN.get(t["duzey"], t["duzey"])), n(t["n"])] for t in tk["ornekler"][:10]],
                    num=(4,), baslik="Table 8. Examples from the tanker files (strongest evidence first)",
                    not_="* Also named in press reports. Each vessel file lists its voyages, the points where AIS went off and came "
                         "back on, and satellite imagery links for those dates (in Turkish).")
    refs = "".join(f'<li>{E(m)} <a href="{E(u)}" rel="noopener">{E(u)}</a></li>' for m, u in _kaynakca(o, en=True))
    coverage = (f"Status of the historical scan in this version: destination-port vessels after the declaration "
                f"{pct(kaps.get('ana'))}, Ceyhan vessels {pct(kaps.get('ceyhan'))}, period before the declaration "
                f"{pct(kaps.get('erken'))}. Numbers can only grow as the scan continues, since each added record is a new port visit.")
    statements = _tablo(E, ["Date", "Institution", "Statement", "Source"],
                        [[E(g(t["gun"])), E(t.get("kim_en") or t["kim"]),
                          (E(t.get("metin_en") or t["metin"]) if t.get("aktarim") else f"“{E(t.get('metin_en') or t['metin'])}”")
                          + (" <span class=not>(summary)</span>" if t.get("aktarim") else " <span class=not>(translation)</span>"),
                          f'<a href="{E(t["url"])}" rel="noopener">{E(t["kaynak"])}</a>'] for t in o.get("testler") or []],
                        baslik="Table 1. Official statements tested against the data")
    imp = (f"In the same period {n(i['sonra'])} voyages ({n(i['gemi_sonra'])} vessels, {n(i['ort_sonra'])} a month on average) left "
           f"Israeli ports and arrived at Turkish ports; most arrivals were at {E(liman_en(i['varis'][0][0])) if i['varis'] else '–'}. "
           "According to the Ministry of Trade there have been no shipments from Israel since 2 May 2024; vessel movements do not "
           "show the origin of the cargo, but each of these voyages is listed with vessel name and date.") if i else "No records."
    return f'''
<header class="makale-bas" lang="en">
  <p class="dil"><a href="index.html" hreflang="tr" lang="tr">Türkçe</a></p>
  <h1>Declaration and record: vessel voyages from Turkish to Israeli ports after Türkiye declared a halt to trade with Israel</h1>
  <p class="alt-baslik">An independent study based on AIS data, 7 October 2023 – {E(g(o["son_gun"]))}</p>
  <dl class="kunye-rapor">
    <div><dt>Prepared by</dt><dd>{E((cfg.raw.get("rapor") or {}).get("hazirlayan_en") or "Avvam, an open-source vessel monitoring project")}</dd></div>
    <div><dt>Version</dt><dd>{E(g(o["olusturma"][:10]))}, {E(o["olusturma"][11:16])} UTC</dd></div>
    <div><dt>Data period</dt><dd>7 October 2023 – {E(g(o["son_gun"]))}</dd></div>
    <div class="genis"><dt>Data snapshot digest (SHA-256)</dt><dd><code>{E(o["veri_hash"])}</code></dd></div>
  </dl>
  <p class="pdf-satir" id="pdf-satir"></p>
</header>
<div lang="en">
<section class="ozet-kutu" aria-labelledby="abstract"><h2 id="abstract">Abstract</h2><p>{abstract}</p>
  <h3>Key findings</h3><ul>{"".join(f"<li>{b}</li>" for b in findings if b)}</ul></section>

<h2 id="introduction">1. Introduction</h2>
<p>Türkiye announced step-by-step restrictions on trade with Israel in connection with the war in Gaza. On 9 April 2024 the Ministry
of Trade restricted exports to Israel in 54 product groups (1,019 tariff lines). On 2 May 2024 it announced that all export and import
transactions related to Israel had been stopped. On 29 August 2025 Foreign Minister Hakan Fidan said that Israeli ships were not allowed
into Turkish ports and Turkish-flagged ships were not allowed to go to Israeli ports. On 30 March 2026 the Ministry of Trade stated
that all trade, including transit and free-zone trade, had stopped, and that goods destined for Palestine pass through Israeli ports
because Palestine has no port of its own.</p>
<p>The question of this study is: did ship traffic between Turkish and Israeli ports stop after these statements? We answer it not
with customs records but with the position signals that ships broadcast themselves. A vessel movement is not trade itself; but a
vessel that leaves a port in one country and enters a port in another is a factual record of the maritime link between the two, and it
can be verified by anyone with publicly available data.</p>
<p>The report offers three things: (1) a vessel-by-vessel, date-by-date list of voyages after the declaration; (2) a classification of
how the voyages were made: directly, via a third-country port, or with the AIS signal switched off; (3) a separate examination of
tankers leaving the oil terminals at Ceyhan. All data and code are open; each day of records is sealed.</p>

<h2 id="statements">2. Official statements</h2>
{statements}

<h2 id="methods">3. Data and methods</h2>
<h3>3.1 Data sources</h3>
<p>Ships of 300 gross tonnage and above on international voyages, and all passenger ships, must carry AIS (SOLAS Chapter V, Regulation
19). The AIS transponder broadcasts the vessel’s identity (name, MMSI, IMO), position, speed and declared destination every few
seconds to every few minutes. Two sources were used:</p>
<ul>
<li><b>Global Fishing Watch (GFW)</b>: publicly available port-visit events (confidence levels 3 and 4), AIS gap events and AIS presence
data derived from AIS signals, from 7 October 2023 to date. GFW data are produced with a delay of a few days; the last day in this
version is {E(g(o["son_gun"]))}. Data licensed under CC BY-NC 4.0.</li>
<li><b>The project’s own live AIS record</b>: messages of all vessels around Turkish, Israeli and intermediate-country ports, received
via aisstream.io. Each day’s raw file is stored unchanged, sealed with SHA-256 and chained to the previous day; the chain head is
timestamped with OpenTimestamps.</li>
</ul>
<h3>3.2 Voyage definition</h3>
<p>A vessel’s port visits are ordered in time. Consecutive visits to the same port less than 72 hours apart count as a single call.
Anchorages in the waiting areas of the Istanbul and Çanakkale straits are not counted as port calls. A voyage starts at the last
departure from a Turkish port and ends at the first entry into an Israeli port:</p>
<ul>
<li><b>Direct</b>: no intermediate port call; at most {th["dogrudan_max_gun"]} days from departure to arrival.</li>
<li><b>Via a third-country port</b>: at most {th["aktarma_max_liman"]} intermediate calls, only at ports in {via}; at most
{th["aktarma_max_gun"]} days in total. If the vessel calls at a port in any other country the voyage is not counted, since its cargo
may have changed there.</li>
<li><b>AIS gap en route</b>: on a voyage from a Turkish to an Israeli port the vessel transmitted no signal for at least
{th["ais_bosluk_saat"]} hours.</li>
<li><b>AIS off near Israel</b>: the vessel left a Turkish port and, without calling at any port, its AIS signal was off for at least
{th.get("hedef_acik_bosluk_saat") or 12} hours, with the point where the signal stopped or resumed in Israel’s offshore waters
({E(kutu_s)}). GFW often does not flag gaps close to the coast as intentional disabling; this rule therefore does not rely on that flag.</li>
<li><b>Position off Israel or under GPS interference</b>: the vessel left a Turkish port and, before its next port call and with AIS on,
its position appeared in Israel’s offshore waters or at Beirut airport (GFW AIS presence data). Spoofed positions of ships and aircraft
near Israel mostly appear at Beirut airport (NPR, 2024); a vessel whose position appears at this point on land is within range of
Israel’s GPS interference. The interference can also prevent GFW from recording a visit to an Israeli port.</li>
<li><b>Return to Ceyhan without a port call</b>: the vessel left Ceyhan and came back to Ceyhan within
{th.get("limansiz_donus_gun") or 20} days without calling at any port. Where it discharged the oil is not recorded. This alone does not
show a voyage to Israel; it is counted separately in the tanker files.</li>
<li><b>Waiting offshore</b>: the vessel spent at least 12 hours on consecutive days within about 25 km of the Israeli coast without
entering any port (GFW AIS presence data), and its previous call was a Turkish port (possible buoy discharge).</li>
<li><b>Dark voyage</b>: a vessel leaving a Turkish port transmitted no signal for at least {th["karanlik_sefer_saat"]} hours in the
Eastern Mediterranean and no arrival was recorded. The vessel may or may not have gone to Israel; this type is reported separately.</li>
</ul>
<h3>3.3 Period rule</h3>
<p>A voyage counts as after the declaration if the event on the Turkish side took place on or after 2 May 2024: departure from the
Turkish port for voyages to Israel, arrival at the Turkish port for voyages from Israel.</p>
<h3>3.4 Tankers</h3>
<p>The Baku–Tbilisi–Ceyhan (BTC) and Kirkuk–Ceyhan terminals at Ceyhan lie a few kilometres apart and cannot be told apart by AIS
position; GFW attributes visits to these terminals to anchorage points 6–10 km south of them. The area within 11 km of the terminals
was therefore treated as “Ceyhan terminals and anchorage”. Because coal, fertiliser and cement carriers also use this area, a vessel
was counted as a tanker only with one of the following: its AIS type is tanker, it berthed at a liquid-bulk terminal, its route
includes other oil terminals, or it is named as a tanker in press reports. Vessels that GFW does not classify as cargo vessels (the
class that contains tankers) are marked separately as probable tankers.</p>
<h3>3.5 Evidence integrity</h3>
<p>The SHA-256 digest of a fixed-order summary of all voyage records used in this version (identifier, type, vessel, departure and
arrival port and time) is printed in the header: <code>{E(o["veri_hash"][:16])}…</code>. Anyone can compute the same value from the
same records. All records can be downloaded as CSV; each voyage row lists the identifiers of the GFW events it rests on (departure and
arrival port visits, intermediate calls, AIS gaps) and the vessel’s GFW identifier, so that every voyage can be verified independently
against GFW’s own records. The classification code is open source.</p>

<h2 id="results">4. Results</h2>
<h3>4.1 Overview</h3>
<p>Between {g(beyan)} and {g(o["son_gun"])}, {n(d["sonra"])} voyages from Turkish to Israeli ports were recorded, made by
{n(d["gemi_sonra"])} different vessels. The average over full months was {n(d["ort_sonra"])} voyages a month; the fewest were in
{_ay(d["min_ay"][1], True) if d["min_ay"] else "–"} ({d["min_ay"][0] if d["min_ay"] else "–"}), the most in
{_ay(d["max_ay"][1], True) if d["max_ay"] else "–"} ({d["max_ay"][0] if d["max_ay"] else "–"}). {sifir_en} (Figure 1).</p>
<figure class="sekil"><div class="grafik-kaydir">{oz.aylik_svg(o, "TR>IL", en=True, kimlik="figure1")}</div><figcaption>Figure 1. Monthly voyages from Turkish to Israeli
ports, by voyage type. Dashed vertical lines mark the dates of official statements. The last bar is the current month and is incomplete.
{"" if x["erken_tamam"] else "The scan of the shaded period is in progress."}</figcaption></figure>
{t_type}
<h3>4.2 Ports and routes</h3>
<p>On the Turkish side most voyages departed from {E(liman_en(d["cikis"][0][0])) if d["cikis"] else "–"}
({n(d["cikis"][0][1]) if d["cikis"] else "–"}) and {E(liman_en(d["cikis"][1][0])) if len(d["cikis"]) > 1 else "–"}
({n(d["cikis"][1][1]) if len(d["cikis"]) > 1 else "–"}); on the Israeli side {n(d["varis"][0][1]) if d["varis"] else "–"} arrivals were at
{E(liman_en(d["varis"][0][0])) if d["varis"] else "–"} and {n(d["varis"][1][1]) if len(d["varis"]) > 1 else "–"} at
{E(liman_en(d["varis"][1][0])) if len(d["varis"]) > 1 else "–"} (Table 3).</p>
{t_route}
<h3>4.3 Voyages via third-country ports</h3>
<p>In {n(a.get("liman", 0))} voyages ({_yuzde(a.get("liman", 0), d["sonra"], True)}) the vessel called at one or more ports in {via}
after leaving the Turkish port and before entering the Israeli port (Table 4). Some of these are scheduled liner services calling at
many ports; in others the cargo may have changed hands at the intermediate port. The data do not distinguish the two.</p>
{t_via}
<h3>4.4 Flag</h3>
<p>The most frequent flags were {E(flags)} (Table 5). Turkish-flagged
vessels made {n(d["tr_bayrak"])} voyages after the declaration and {n(d["tr_bayrak_kisit"])} after 29 August 2025, when it was announced
that Turkish-flagged ships would not go to Israeli ports. The flag is the one recorded in the GFW event; vessels may have changed flag
later.</p>
{t_flag}
<h3>4.5 Vessels</h3>
<p>The 15 vessels with most voyages after the declaration are listed in Table 6. The full list of vessels with all their voyages is on
the <a href="../raporlar/index.html">vessels page</a> and in the CSV files.</p>
{t_ship}
<h3>4.6 Ceyhan and oil tankers</h3>
<p>The historical scan processed {n(cy["cikis"])} departures ({n(cy["gemi"])} vessels) from the anchorage area off the Ceyhan terminals.
In {n(cy["il"])} of them the next call was an Israeli port; in {n(cy["il_acik"])} the vessel called at no port and its AIS signal stopped
or resumed near Israel. In {n(cy["donus"])} departures ({n(cy["donus_gemi"])} vessels) the vessel came back to Ceyhan within
{th.get("limansiz_donus_gun") or 20} days without calling at any port: where the oil loaded was discharged is not recorded. In
{n(cy["iz"])} departures the vessel’s AIS position appeared off Israel or at the spoofed position at Beirut airport before its next port
call{(", " + n(cy["iz_donus"]) + " of them returns without a port call") if cy.get("iz_donus") else ""}. The tanker files contain
{n(tk["gemi"])} vessels and {n(tk["sefer"])} voyages; for {n(tk["dogrulanan"])} of these
vessels the tanker type is confirmed by AIS type, berth, route or press record (Table 8). Voyages from Ceyhan with a recorded arrival at an Israeli port are listed in Table 7. {_basin_en(o)}</p>
{_cey_ornek_en(o, E)}
{t_tank}
<h3>4.7 Voyages from Israel to Türkiye</h3>
<p>{imp}</p>
<figure class="sekil"><div class="grafik-kaydir">{oz.aylik_svg(o, next((y for y, v in o["yonler"].items() if not v["ihracat"]), "TR>IL"), en=True, kimlik="figure2")}</div>
<figcaption>Figure 2. Monthly voyages from Israeli to Turkish ports.</figcaption></figure>
<h3>4.8 Comparison with the period before the declaration</h3>
<p>{comp}</p>

<h2 id="discussion">5. Discussion</h2>
<h3>5.1 Comparison with official statements</h3>
<p>The Ministry of Trade’s announcement of 2 May 2024 is a customs decision and does not by itself require all shipping traffic to stop.
However, the continuation of dozens of voyages a month from Turkish to Israeli ports after the announcement shows that the maritime link
between the two countries was not cut. The Ministry of Energy’s statement of 11 November 2024 that no shipments with an Israeli
destination took place should be weighed against the records of tankers from Ceyhan that entered Israeli ports or switched off their AIS
near Israel (Section 4.6). The {n(d["tr_bayrak_kisit"])} voyages by Turkish-flagged vessels and {n(d["kisit_sonra"])} voyages under all
flags after Foreign Minister Fidan’s statement of 29 August 2025 show that the port restrictions did not stop the traffic.</p>
<h3>5.2 Alternative explanations</h3>
<ul>
<li><b>Trade with Palestine.</b> The Ministry of Trade says that goods destined for Palestine pass through Israeli ports and amount to
USD 50–60 million a month; according to the same statement, exports to Israel before the war were USD 600–700 million a month. In value
this is about 7–10% of the pre-war level. {("The monthly number of voyages, by contrast, is " + _yuzde(d["ort_sonra"], d["ort_once"], True) + " of its level before the declaration. The number of voyages does not measure cargo value directly; still, the large gap between the two ratios makes it difficult to explain all voyages by trade with Palestine.") if x["erken_tamam"] and x["oran"] else "Comparing this ratio with voyage numbers requires the scan of the period before the declaration to be completed."}</li>
<li><b>Liner services and transhipment.</b> Some container and general cargo vessels operate scheduled services calling at many
countries and carry cargo of third countries. Their passage from a Turkish to an Israeli port does not by itself show that cargo of
Turkish origin was unloaded in Israel. On the other hand, according to the Ministry, transit trade has also been halted.</li>
<li><b>Empty legs.</b> A vessel may sail between ports without cargo. Changes in AIS draught give an indication, but the historical
scan contains no draught data.</li>
<li><b>Data errors.</b> GFW port visits are the output of a classification model; low-confidence visits were not used. Unnamed anchorages
were named after the nearest port.</li>
</ul>
<h3>5.3 Limitations</h3>
<ul>
<li>Vessels that switch off AIS entirely or broadcast false positions are missing from the records; the true number of voyages may be
higher than reported here.</li>
<li>The live record relies on shore receivers set up by volunteers; there is no live coverage at İskenderun, Aliağa or İzmit. GFW data
were used for these ports.</li>
<li>{E(coverage)}</li>
<li>This report does not examine the cargo, its owner or seller, or the legal nature of the trade.</li>
</ul>

<h2 id="conclusion">6. Conclusion</h2>
<p>Open records derived from the position signals that ships broadcast themselves show that vessel voyages from Turkish to Israeli ports
did not stop after 2 May 2024, when Türkiye declared that it had halted trade with Israel: {n(d["sonra"])} voyages, {n(d["gemi_sonra"])}
vessels, and {sifir_en_kisa}. Some voyages went via third-country ports; in some, the vessel switched off
its AIS en route. {_cey_sonuc_en(o)} These findings do not
identify the owner of the cargo or the parties to the trade; but because every voyage is listed with vessel name, IMO number, port and
time, competent authorities can verify the list against customs declarations, bills of lading and port records. We recommend that the
list be compared with these records under independent oversight and that discrepancies be made public.</p>

<h2 id="data">Data availability and citation</h2>
<ul>
<li>All voyages: <a href="../raporlar/tr-il-seferler.csv">Türkiye → Israel (CSV)</a>, <a href="../raporlar/il-tr-seferler.csv">Israel →
Türkiye (CSV)</a>; tankers: <a href="../tankerler/tankerler.csv">tankerler.csv</a>; figures of this report:
<a href="../veri/rapor-ozet.json">rapor-ozet.json</a> (column headings in Turkish).</li>
<li>Daily archive and evidence chain: <a href="../kanit.html">Evidence chain</a>. All thresholds of the method:
<a href="../yontem.html">Method</a> (in Turkish).</li>
<li>Citation: Avvam ({o["olusturma"][:4]}). <i>Declaration and record: vessel voyages from Turkish to Israeli ports after Türkiye
declared a halt to trade with Israel</i>. Version {E(g(o["olusturma"][:10]))}, data digest {E(o["veri_hash"][:16])}.</li>
<li>Historical scan: Powered by Global Fishing Watch. Data licensed CC BY-NC 4.0.</li>
</ul>
<h2 id="references">References</h2><ol class="kaynakca">{refs}</ol>
</div>'''


PDF_JS = r'''<script>(function(){var p=document.getElementById("pdf-satir");if(!p||!p.dataset.depo)return;
var depo=p.dataset.depo,dil=p.dataset.dil;fetch("https://api.github.com/repos/"+depo+"/releases/tags/rapor-son")
.then(function(r){return r.ok?r.json():null}).then(function(d){if(!d)return;var ad="avvam-rapor-"+dil+".pdf";
var a=(d.assets||[]).filter(function(x){return x.name===ad})[0];if(!a)return;
var l=(d.body||"").split("\n").filter(function(x){return x.indexOf(ad)>=0})[0]||"",h=l.match(/[0-9a-f]{64}/),
t=l.indexOf("(")>=0?l.slice(l.indexOf("(")+1,l.indexOf(")")):"";
var e=function(s,c,u){var x=document.createElement(u?"a":"span");x.textContent=s;if(c)x.className=c;if(u)x.href=u;return x};
p.appendChild(e(p.dataset.yazi,"",a.browser_download_url));
if(h)p.appendChild(e(" "+t.replace("T"," ")+", SHA-256 "+h[0].slice(0,16)+"…","not"));
p.appendChild(document.createTextNode(" "));p.appendChild(e(p.dataset.arsiv,"not","https://github.com/"+depo+"/releases?q=rapor-"));
}).catch(function(){})})();</script>'''


def build(cfg, o: dict, out: Path) -> None:
    from .site import E as _E, _page, _write

    def E(x) -> str:
        return _E("" if x is None else str(x))
    rdir = out / "rapor"
    depo = E(cfg.pub.get("depo") or "")
    tr = _tr(cfg, o, E).replace('id="pdf-satir"', f'id="pdf-satir" data-depo="{depo}" data-dil="tr" data-yazi="PDF olarak indir" '
                                'data-arsiv="Tarihli sürümler"', 1)
    en = _en(cfg, o, E).replace('id="pdf-satir"', f'id="pdf-satir" data-depo="{depo}" data-dil="en" data-yazi="Download PDF" '
                                'data-arsiv="Dated versions"', 1)
    d = o["yonler"].get("TR>IL") or {}
    desc_tr = (f"Türkiye’nin İsrail’le ticareti durdurduğunu açıkladığı 2 Mayıs 2024’ten sonra Türk limanlarından İsrail limanlarına "
               f"{_n(d.get('sonra'))} sefer: yöntem, bulgular, sınırlar.")
    desc_en = (f"After Türkiye declared a halt to trade with Israel on 2 May 2024, {_n(d.get('sonra'), True)} voyages went from "
               "Turkish to Israeli ports: method, findings, limitations.")
    adres = (cfg.pub.get("adres") or "").rstrip("/")
    from urllib.parse import urlencode

    def paylas(metin, url, yazi, kopya):
        x = "https://x.com/intent/post?" + urlencode({"text": metin, "url": url})
        return (f'<p class="paylas-satir"><a href="{E(x)}" target="_blank" rel="noopener">{yazi}</a> '
                f'<button type="button" class="kopyala-link" data-url="{E(url)}">{kopya}</button></p>')
    kopya_js = ('<script>document.addEventListener("click",function(e){var b=e.target.closest(".kopyala-link");if(!b)return;'
                '(navigator.clipboard?navigator.clipboard.writeText(b.dataset.url):Promise.reject()).then(function(){'
                'b.textContent=document.documentElement.lang==="en"?"Copied":"Kopyalandı"},function(){})});</script>')
    if adres:
        tr = tr.replace('<p class="pdf-satir"', paylas(desc_tr, f"{adres}/rapor/", "X’te paylaş", "Bağlantıyı kopyala")
                        + '<p class="pdf-satir"', 1)
        en = en.replace('<p class="pdf-satir"', paylas(desc_en, f"{adres}/rapor/en.html", "Share on X", "Copy link")
                        + '<p class="pdf-satir"', 1)
    _write(rdir / "index.html", _page(cfg, "Rapor: Beyan ve kayıt", f'<main class="makale" id="icerik">{tr}</main>{PDF_JS}{kopya_js}', 1,
                                      "rapor", desc=desc_tr))
    sayfa = _page(cfg, "Report: Declaration and record", f'<main class="makale" id="icerik">{en}</main>{PDF_JS}{kopya_js}', 1,
                  "rapor", desc=desc_en)
    _write(rdir / "en.html", sayfa.replace('<html lang="tr">', '<html lang="en">', 1))
    veri = {k: v for k, v in o.items() if k not in ("kesit",)}
    _write(out / "veri" / "rapor-ozet.json", json.dumps(veri, ensure_ascii=False, default=str, indent=1))
    _write(out / "veri" / "rapor-kesit.json", json.dumps(o["kesit"], ensure_ascii=False, default=str, separators=(",", ":")))
