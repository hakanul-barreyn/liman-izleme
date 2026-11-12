"""Raporu (Türkçe ve İngilizce) PDF'e yazdırır ve her dosyanın SHA-256 özetini çıkarır.

Kullanım: python kurulum/rapor_pdf.py site _pdf
Çıktı: _pdf/avvam-rapor-tr.pdf, _pdf/avvam-rapor-en.pdf, _pdf/ozet.json
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
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
            b.close()
    finally:
        srv.terminate()
    veri = Path(site, "veri", "rapor-ozet.json")
    if veri.exists():
        ozet["veri_hash"] = json.loads(veri.read_text(encoding="utf-8")).get("veri_hash")
    (hedef / "ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(ozet, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:3] or ["site", "_pdf"])))
