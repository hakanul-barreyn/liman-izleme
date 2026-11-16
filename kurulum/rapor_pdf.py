"""Raporu (Türkçe ve İngilizce) PDF'e yazdırır ve her dosyanın SHA-256 özetini çıkarır.

Kullanım: python kurulum/rapor_pdf.py site _pdf
Çıktı: _pdf/avvam-rapor-tr.pdf, _pdf/avvam-rapor-en.pdf, _pdf/avvam-ekler.pdf, _pdf/ozet.json ve
_pdf/avvam-kanit-paketi.zip (rapor, ekler, her tankerin dosyası, veri, kaynaklar, SHA256SUMS.txt, BENIOKU.txt)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = 8781
ALT = ('<div style="font:8px Archivo,Helvetica,Arial,sans-serif;color:#556;width:100%;padding:0 15mm;display:flex;'
       'justify-content:space-between"><span>{baslik}</span><span><span class="pageNumber"></span> / '
       '<span class="totalPages"></span></span></div>')


def main(site: str, out: str) -> int:
    hedef = Path(out)
    hedef.mkdir(parents=True, exist_ok=True)
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", site],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    ozet = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for dil, yol, baslik in (("tr", "rapor/index.html", "Avvam: Beyan ve kayıt"),
                                     ("en", "rapor/en.html", "Avvam: Declaration and record")):
                pg = b.new_page(locale="tr-TR" if dil == "tr" else "en-GB")
                pg.goto(f"http://127.0.0.1:{PORT}/{yol}", wait_until="networkidle", timeout=60000)
                pg.emulate_media(media="print", color_scheme="light")
                pg.wait_for_timeout(500)
                dosya = hedef / f"avvam-rapor-{dil}.pdf"
                pg.pdf(path=str(dosya), format="A4", print_background=True, display_header_footer=True,
                       header_template="<div></div>", footer_template=ALT.format(baslik=baslik),
                       margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
                ozet[dil] = {"dosya": dosya.name, "sha256": hashlib.sha256(dosya.read_bytes()).hexdigest(),
                             "bayt": dosya.stat().st_size, "tarih": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%MZ")}
                pg.close()
            # ekler: geniş tablolar için yatay A4
            pg = b.new_page(locale="tr-TR")
            pg.set_default_timeout(600000)
            pg.goto(f"http://127.0.0.1:{PORT}/rapor/ekler.html", wait_until="networkidle", timeout=180000)
            pg.emulate_media(media="print", color_scheme="light")
            dosya = hedef / "avvam-ekler.pdf"
            pg.pdf(path=str(dosya), format="A4", landscape=True, print_background=True, display_header_footer=True,
                   header_template="<div></div>", footer_template=ALT.format(baslik="Avvam: Ekler / Annexes"),
                   margin={"top": "12mm", "bottom": "14mm", "left": "10mm", "right": "10mm"})
            ozet["ekler"] = {"dosya": dosya.name, "sha256": hashlib.sha256(dosya.read_bytes()).hexdigest(),
                             "bayt": dosya.stat().st_size, "tarih": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%MZ")}
            pg.close()
            # her tankerin dosyası
            td = hedef / "tanker-dosyalari"
            td.mkdir(exist_ok=True)
            tj = Path(site, "veri", "tankerler.json")
            for t in (json.loads(tj.read_text(encoding="utf-8")) if tj.exists() else []):
                ad = t.get("dosya")
                if not ad or not Path(site, "tankerler", f"{ad}.html").exists():
                    continue
                pg = b.new_page(locale="tr-TR")
                try:
                    pg.goto(f"http://127.0.0.1:{PORT}/tankerler/{ad}.html", wait_until="networkidle", timeout=60000)
                    pg.emulate_media(media="print", color_scheme="light")
                    pg.pdf(path=str(td / f"{ad}.pdf"), format="A4", print_background=True, display_header_footer=True,
                           header_template="<div></div>",
                           footer_template=ALT.format(baslik=f"Avvam: tanker dosyası {t.get('ad') or ad}"),
                           margin={"top": "14mm", "bottom": "16mm", "left": "13mm", "right": "13mm"})
                except Exception as e:  # tek dosya paketi durdurmasın
                    print(f"tanker dosyası atlandı: {ad}: {e}", file=sys.stderr)
                pg.close()
            b.close()
    finally:
        srv.terminate()
    veri = Path(site, "veri", "rapor-ozet.json")
    if veri.exists():
        ozet["veri_hash"] = json.loads(veri.read_text(encoding="utf-8")).get("veri_hash")
    ozet["paket"] = paketle(Path(site), hedef)
    (hedef / "ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(ozet, ensure_ascii=False))
    return 0


VERI = ["raporlar/tr-il-seferler.csv", "raporlar/tr-il-gemiler.csv", "raporlar/il-tr-seferler.csv", "raporlar/il-tr-gemiler.csv",
        "tankerler/tankerler.csv", "veri/tankerler.json", "veri/rapor-ozet.json", "veri/rapor-kesit.json", "veri/kaynaklar.csv",
        "veri/gecmis.json", "veri/harita/seferler.json"]


def paketle(site: Path, hedef: Path) -> dict:
    """Kanıt paketi: sabit klasör düzeni, her dosyanın SHA-256 özeti SHA256SUMS.txt'te."""
    girdi: list[tuple[str, Path]] = []
    for ad in ("avvam-rapor-tr.pdf", "avvam-rapor-en.pdf", "avvam-ekler.pdf"):
        if (hedef / ad).exists():
            girdi.append((f"rapor/{ad}", hedef / ad))
    for f in sorted((hedef / "tanker-dosyalari").glob("*.pdf")):
        girdi.append((f"tanker-dosyalari/{f.name}", f))
    for yol in VERI:
        f = site / yol
        if f.exists():
            girdi.append((f"veri/{Path(yol).name}", f))
    toplam = "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {ic}\n" for ic, f in girdi)
    zipy = hedef / "avvam-kanit-paketi.zip"
    with zipfile.ZipFile(zipy, "w", zipfile.ZIP_DEFLATED) as z:
        beni = site / "rapor" / "BENIOKU.txt"
        if beni.exists():
            z.write(beni, "BENIOKU.txt")
        for ic, f in girdi:
            z.write(f, ic)
        z.writestr("SHA256SUMS.txt", toplam)
    (hedef / "SHA256SUMS.txt").write_text(toplam, encoding="utf-8")
    return {"dosya": zipy.name, "sha256": hashlib.sha256(zipy.read_bytes()).hexdigest(), "bayt": zipy.stat().st_size,
            "icerik": len(girdi), "tarih": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%MZ")}


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:3] or ["site", "_pdf"])))
