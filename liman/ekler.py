"""Raporun ekleri ve indirilebilir kanıt paketi.

rapor/ekler.html      iki dilli ekler: gemi listeleri, sefer listeleri, tanker dosyaları, kaynaklar ve doğrulama
veri/kaynaklar.csv    bütün kaynaklar: bağlantı ve İnternet Arşivi (Wayback Machine) bağlantısı
rapor/BENIOKU.txt     paketin içeriği ve doğrulama yolu (kanıt paketinde README olarak yer alır)

Ekler, sitede yayımlanan CSV dosyalarından üretilir; PDF'teki tablo ile indirilen veri aynı kayıttır.
Paket (PDF'ler, tanker dosyaları, veri, SHA256SUMS) kurulum/rapor_pdf.py tarafından GitHub Releases'ta yayımlanır.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

PAKET = "avvam-kanit-paketi.zip"
DOSYALAR = {  # sürümdeki dosya adı: (Türkçe, İngilizce)
    "avvam-rapor-tr.pdf": ("Rapor (PDF, Türkçe)", "Report (PDF, Turkish)"),
    "avvam-rapor-en.pdf": ("Rapor (PDF, İngilizce)", "Report (PDF, English)"),
    "avvam-ekler.pdf": ("Ekler: gemiler, seferler, tankerler, kaynaklar (PDF)", "Annexes: vessels, voyages, tankers, sources (PDF)"),
    PAKET: ("Tam kanıt paketi (ZIP): rapor, ekler, tanker dosyaları, veri, kaynaklar, SHA-256 listesi",
            "Full evidence package (ZIP): report, annexes, tanker files, data, sources, SHA-256 list"),
}


def indirme_kutusu(depo: str, en: bool, E) -> str:
    """Raporun başındaki indirme listesi. Bağlantılar 'rapor-son' sürümüne sabittir; tarih ve özetleri betik doldurur."""
    if not depo:
        return ""
    taban = f"https://github.com/{depo}/releases/download/rapor-son/"
    sira = ["avvam-rapor-en.pdf", "avvam-rapor-tr.pdf"] if en else ["avvam-rapor-tr.pdf", "avvam-rapor-en.pdf"]
    li = "".join(f'<li><a href="{E(taban + ad)}" data-dosya="{E(ad)}">{E(DOSYALAR[ad][1 if en else 0])}</a></li>'
                 for ad in sira + ["avvam-ekler.pdf", PAKET])
    bas = "Download" if en else "İndir"
    ars = "Dated versions" if en else "Tarihli sürümler"
    return (f'<div class="indir" id="indir" data-depo="{E(depo)}"><h2 class="indir-baslik">{bas}</h2><ul>{li}</ul>'
            f'<p class="not"><a href="https://github.com/{E(depo)}/releases?q=rapor-">{ars}</a>. '
            + ("Each file’s SHA-256 digest is listed in the release notes and in SHA256SUMS.txt inside the package."
               if en else "Her dosyanın SHA-256 özeti sürüm notlarında ve paketteki SHA256SUMS.txt dosyasında yazılıdır.")
            + '</p></div>')


INDIR_JS = r'''<script>(function(){var k=document.getElementById("indir");if(!k)return;
fetch("https://api.github.com/repos/"+k.dataset.depo+"/releases/tags/rapor-son").then(function(r){return r.ok?r.json():null})
.then(function(d){if(!d)return;var var_={};(d.assets||[]).forEach(function(a){var_[a.name]=a});
var satir=(d.body||"").split("\n");k.querySelectorAll("a[data-dosya]").forEach(function(a){var x=var_[a.dataset.dosya];
if(!x){a.parentNode.classList.add("yok");return}var l=satir.filter(function(s){return s.indexOf(a.dataset.dosya)>=0})[0]||"",
h=l.match(/[0-9a-f]{64}/),s=document.createElement("span");s.className="not";
s.textContent=" "+(x.size>1048576?(x.size/1048576).toFixed(1)+" MB":Math.max(1,Math.round(x.size/1024))+" KB")
+(h?", SHA-256 "+h[0].slice(0,16)+"…":"");a.parentNode.appendChild(s)})}).catch(function(){})})();</script>'''


def _oku(yol: Path) -> list[dict]:
    if not yol.exists():
        return []
    return list(csv.DictReader(io.StringIO(yol.read_text(encoding="utf-8-sig")), delimiter=";"))


def _gun(s: str | None) -> str:
    return (s or "")[:10]


def _tablo(E, kimlik, baslik, bas, satirlar, not_="", kod=()):
    th = "".join(f"<th scope=col>{E(h)}</th>" for h in bas)
    tr = "".join("<tr>" + "".join(f'<td{" class=kod" if i in kod else ""}>{E(c)}</td>' for i, c in enumerate(r)) + "</tr>"
                 for r in satirlar)
    bos = '<p class="not">Kayıt yok. / No records.</p>' if not satirlar else ""
    return (f'<section class="ek" id="{kimlik}"><h2>{baslik}</h2>'
            + (f'<p class="not">{not_}</p>' if not_ else "")
            + (f'<div class="ek-kaydir"><table class="ek-tablo"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
               if satirlar else bos) + "</section>")


def kaynaklar(o) -> list[dict]:
    from .makale import _kaynakca
    tr, en = _kaynakca(o), _kaynakca(o, True)
    out = []
    for i, (metin, url) in enumerate(tr):
        out.append({"no": i + 1, "kaynak": metin, "source": en[i][0] if i < len(en) else metin, "url": url,
                    "arsiv": f"https://web.archive.org/web/{url}" if url.startswith("http") else ""})
    return out


def beni_oku(cfg, o) -> str:
    depo = cfg.pub.get("depo") or ""
    adres = (cfg.pub.get("adres") or "").rstrip("/")
    return f"""AVVAM: BEYAN VE KAYIT / DECLARATION AND RECORD
Kanıt paketi / Evidence package
Sürüm / Version: {o.get("olusturma", "")}
Veri kesitinin SHA-256 özeti / Data snapshot digest: {o.get("veri_hash", "")}
Site: {adres}
Kaynak kod ve sürümler / Source code and releases: https://github.com/{depo}

İÇİNDEKİLER
  rapor/avvam-rapor-tr.pdf       Rapor, Türkçe
  rapor/avvam-rapor-en.pdf       Rapor, İngilizce
  rapor/avvam-ekler.pdf          Ekler: gemi listeleri, sefer listeleri, tanker dosyaları özeti, kaynaklar
  tanker-dosyalari/*.pdf         Her tanker için ayrı dosya: seyir defteri, Ceyhan çıkışları, GFW olay kimlikleri
  veri/*.csv, veri/*.json        Raporun dayandığı bütün kayıtlar (CSV ayırıcısı noktalı virgül, UTF-8)
  veri/kaynaklar.csv             Bütün kaynaklar, bağlantıları ve İnternet Arşivi bağlantıları
  SHA256SUMS.txt                 Paketteki her dosyanın SHA-256 özeti

DOĞRULAMA
  Linux/macOS:  sha256sum -c SHA256SUMS.txt
  Windows:      certutil -hashfile rapor\\avvam-rapor-tr.pdf SHA256
  Her seferin dayandığı Global Fishing Watch olay kimliği (GFW çıkış/varış olayı) CSV dosyalarında yazılıdır;
  olaylar GFW Events API'de bu kimlikle sorgulanabilir: https://globalfishingwatch.org/our-apis/

NİTELİK
  Bu paketteki her bulgu bir tespittir, hüküm değil: gemilerin AIS yayınlarından ve Global Fishing Watch'un
  liman ziyareti, AIS boşluğu ve AIS varlık verilerinden çıkarılan kayıtlardır. Yükün sahibi, alıcısı ve
  ticaretin hukuki niteliği bu kayıtlardan belirlenemez. Yöntem ve sınırlar raporun 2. ve 6. bölümlerindedir.

LİSANS VE ATIF
  Powered by Global Fishing Watch. GFW verisi CC BY-NC 4.0 lisanslıdır: ticari olmayan kullanım, atıfla.
  Basın ve resmî açıklamalar özgün kaynaklarına bağlantıyla verilmiştir; metinlerin kendisi pakete konmamıştır.

------------------------------------------------------------------------------
CONTENTS
  rapor/avvam-rapor-tr.pdf, rapor/avvam-rapor-en.pdf   Report in Turkish and English
  rapor/avvam-ekler.pdf          Annexes: vessel lists, voyage lists, tanker files summary, sources
  tanker-dosyalari/*.pdf         One file per tanker: log, departures from Ceyhan, GFW event identifiers
  veri/                          All records the report rests on (CSV with semicolon separator, UTF-8)
  veri/kaynaklar.csv             All sources with links and Internet Archive links
  SHA256SUMS.txt                 SHA-256 digest of every file in the package

VERIFY: sha256sum -c SHA256SUMS.txt

NATURE OF THE FINDINGS
  Every finding in this package is a detection, not a verdict: records derived from ships' AIS broadcasts and
  from Global Fishing Watch port-visit, AIS-gap and AIS-presence data. The owner and buyer of a cargo and the
  legal character of the trade cannot be established from these records. Method and limitations: Sections 2 and 6.

LICENCE AND ATTRIBUTION
  Powered by Global Fishing Watch. GFW data are licensed CC BY-NC 4.0. Press and official statements are linked to
  their original sources; their texts are not included in the package.
"""


def build(cfg, o: dict, out: Path) -> None:
    from .site import E as _E, _page, _write

    def E(x) -> str:
        return _E("" if x is None else str(x))
    bol = []
    for yon, ad_tr, ad_en, harf in (("tr-il", "Türkiye → İsrail", "Türkiye → Israel", "A"),
                                     ("il-tr", "İsrail → Türkiye", "Israel → Türkiye", "B")):
        g = _oku(out / "raporlar" / f"{yon}-gemiler.csv")
        bol.append(_tablo(E, f"ek-{harf.lower()}", f"Ek {harf}. Gemiler, {ad_tr} / Annex {harf}. Vessels, {ad_en}",
                          ["Gemi / Vessel", "IMO", "MMSI", "Bayrak / Flag", "Sefer / Voyages", "Doğrudan / Direct",
                           "Ara limanlı / Via port", "STS", "AIS kapalı / AIS off", "İlk / First", "Son / Last",
                           "Başlıca hat / Main route"],
                          [[r.get("Gemi"), r.get("IMO"), r.get("MMSI"), r.get("Bayrak"), r.get("Sefer"), r.get("Doğrudan"),
                            r.get("Ara limanlı"), r.get("Gemiden gemiye"), r.get("AIS kapatılmış"),
                            _gun(r.get("İlk sefer (varış)")), _gun(r.get("Son sefer (varış)")), r.get("Başlıca hat")] for r in g],
                          f"{len(g)} gemi / vessels. Kaynak / source: raporlar/{yon}-gemiler.csv"))
    for yon, ad_tr, ad_en, harf in (("tr-il", "Türkiye → İsrail", "Türkiye → Israel", "C"),
                                     ("il-tr", "İsrail → Türkiye", "Israel → Türkiye", "D")):
        s = sorted(_oku(out / "raporlar" / f"{yon}-seferler.csv"), key=lambda r: r.get("Çıkış tarihi") or "")
        bol.append(_tablo(E, f"ek-{harf.lower()}", f"Ek {harf}. Seferler, {ad_tr} / Annex {harf}. Voyages, {ad_en}",
                          ["Çıkış / Departure", "Çıkış limanı / From", "Ara / Via", "Varış / Arrival", "Varış limanı / To",
                           "Gemi / Vessel", "IMO", "MMSI", "Bayrak / Flag", "Kayıt / Record", "GFW çıkış olayı / departure event",
                           "GFW varış olayı / arrival event"],
                          [[_gun(r.get("Çıkış tarihi")), r.get("Çıkış limanı"), r.get("Ara limanlar"), _gun(r.get("Varış tarihi")),
                            r.get("Varış limanı"), r.get("Gemi"), r.get("IMO"), r.get("MMSI"), r.get("Bayrak"), r.get("Kayıt"),
                            r.get("GFW çıkış olayı"), r.get("GFW varış olayı")] for r in s],
                          kod=(10, 11), not_=f"{len(s)} sefer / voyages, çıkış tarihine göre / by departure date. Sefer türü ve AIS boşluğu olayları "
                          f"CSV’de / voyage type and AIS-gap events in the CSV: raporlar/{yon}-seferler.csv"))
    t = _oku(out / "tankerler" / "tankerler.csv")
    bol.append(_tablo(E, "ek-e", "Ek E. Tanker dosyaları / Annex E. Tanker files",
                      ["Gemi / Vessel", "IMO", "MMSI", "Bayrak / Flag", "Kanıt / Evidence", "Çıkış / From", "Çıkış zamanı / Departure",
                       "Varış ya da son kayıt / Arrival or last record", "Zaman / Time", "Dosya / File"],
                      [[r.get("Gemi"), r.get("IMO"), r.get("MMSI"), r.get("Bayrak"), r.get("Kanıt"), r.get("Çıkış"),
                        _gun(r.get("Çıkış zamanı (UTC)")), r.get("Varış ya da son kayıt"), _gun(r.get("Zaman (UTC)")),
                        f'tanker-dosyalari/{r.get("Dosya")}.pdf'] for r in t],
                      "Her tankerin ayrıntılı dosyası pakette ayrı PDF olarak yer alır. / "
                      "Each tanker’s detailed file is included in the package as a separate PDF."))
    k = kaynaklar(o)
    bol.append(_tablo(E, "ek-f", "Ek F. Kaynaklar / Annex F. Sources",
                      ["No", "Kaynak / Source", "Bağlantı / Link", "İnternet Arşivi / Internet Archive"],
                      [[x["no"], x["kaynak"], x["url"], x["arsiv"]] for x in k], kod=(2, 3), not_=
                      "Resmî açıklamalar, basın haberleri ve yöntem kaynakları. İnternet Arşivi bağlantısı sayfanın kaydedilmiş en "
                      "yakın kopyasını açar. / Official statements, press reports and method sources. The Internet Archive link opens "
                      "the nearest saved copy of the page."))
    bol.append(f'''<section class="ek" id="ek-g"><h2>Ek G. Paketin içeriği ve doğrulama / Annex G. Package contents and verification</h2>
<pre class="ek-pre">{E(beni_oku(cfg, o))}</pre></section>''')
    kunye = (f'<header class="ek-kunye"><h1>Ekler / Annexes</h1><p>Avvam: Beyan ve kayıt / Declaration and record. '
             f'Sürüm / version {E(o.get("olusturma", "")[:16].replace("T", " "))} UTC. '
             f'Veri kesiti / data snapshot SHA-256: <code>{E(o.get("veri_hash"))}</code></p>'
             '<p class="not">Her kayıt bir tespittir, hüküm değil. / Every record is a detection, not a verdict. '
             'Powered by Global Fishing Watch (CC BY-NC 4.0).</p>'
             '<nav class="ek-icindekiler"><ol>'
             + "".join(f'<li><a href="#ek-{h}">{a}</a></li>' for h, a in (
                 ("a", "Gemiler, Türkiye → İsrail / Vessels, Türkiye → Israel"), ("b", "Gemiler, İsrail → Türkiye / Vessels, Israel → Türkiye"),
                 ("c", "Seferler, Türkiye → İsrail / Voyages, Türkiye → Israel"), ("d", "Seferler, İsrail → Türkiye / Voyages, Israel → Türkiye"),
                 ("e", "Tanker dosyaları / Tanker files"), ("f", "Kaynaklar / Sources"), ("g", "Paket ve doğrulama / Package and verification")))
             + "</ol></nav></header>")
    _write(out / "rapor" / "ekler.html",
           _page(cfg, "Ekler: gemiler, seferler, kaynaklar", f'<style>@media print{{@page{{size:A4 landscape;margin:12mm 10mm 14mm}}}}</style>'
                 f'<main class="makale ekler" id="icerik">{kunye}{"".join(bol)}</main>', 1,
                 "rapor", desc="Raporun ekleri: bütün gemiler, bütün seferler, tanker dosyaları ve kaynaklar."))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["No", "Kaynak", "Source", "URL", "İnternet Arşivi"])
    for x in k:
        w.writerow([x["no"], x["kaynak"], x["source"], x["url"], x["arsiv"]])
    _write(out / "veri" / "kaynaklar.csv", "﻿" + buf.getvalue())
    _write(out / "rapor" / "BENIOKU.txt", beni_oku(cfg, o))
