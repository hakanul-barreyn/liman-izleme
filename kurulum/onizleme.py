"""Önizleme: siteyi yerelde sunar, gerçek tarayıcıda açar, ekran görüntüsü ve tarayıcı kayıtlarını _onizleme/ klasörüne yazar.

GitHub Actions'taki "Önizleme" iş akışı çalıştırır; sonuçlar 'onizleme' dalına gönderilir.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("_onizleme")
OUT.mkdir(exist_ok=True)
SERVERS = {"gercek": ("site", 8001), "demo": ("demo/site", 8002)}


def biggest_ship(site: str) -> str | None:
    files = sorted(Path(site, "veri", "gemi").glob("*.json"), key=lambda p: p.stat().st_size, reverse=True)
    return files[0].stem if files else None


def main() -> int:
    procs = [subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", d],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for d, port in SERVERS.values()]
    time.sleep(1.5)
    real_ship = biggest_ship("site")
    shots = [
        ("gercek-masaustu", "gercek", "index.html", 1440, 900, "light", False),
        ("gercek-koyu", "gercek", "index.html", 1440, 900, "dark", False),
        ("gercek-gecmis", "gercek", "index.html#k=g", 1440, 900, "light", False),
        ("gercek-mobil", "gercek", "index.html", 390, 844, "light", True),
        ("demo-masaustu", "demo", "index.html", 1440, 900, "light", False),
        ("demo-secili", "demo", "index.html#sec=c4", 1440, 900, "light", False),
        ("demo-gemi", "demo", "gemiler/imo9000003.html", 1280, 1100, "light", False),
        ("gercek-beyan", "gercek", "beyan.html", 1280, 1300, "light", False),
    ]
    if real_ship:
        shots.append(("gercek-gemi", "gercek", f"gemiler/{real_ship}.html", 1280, 1100, "light", False))
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for name, srv, path, w, h, scheme, mobile in shots:
            ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, device_scale_factor=1,
                                      is_mobile=mobile, has_touch=mobile, locale="tr-TR", timezone_id="Europe/Istanbul")
            page = ctx.new_page()
            logs = []
            page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"[:500]))
            page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"[:800]))
            page.on("requestfailed", lambda r: logs.append(f"requestfailed: {r.url[:160]} {r.failure}"))
            url = f"http://127.0.0.1:{SERVERS[srv][1]}/{path}"
            t0 = time.time()
            try:
                page.goto(url, wait_until="load", timeout=60000)
                try:
                    page.wait_for_function("window.__haritaHazir", timeout=25000)
                except Exception:  # noqa: BLE001
                    logs.append("harita 25 sn içinde hazır olmadı")
                page.wait_for_timeout(1500)
                timing = page.evaluate("""() => {const n = performance.getEntriesByType('navigation')[0];
                    return {dom: Math.round(n.domContentLoadedEventEnd), yuk: Math.round(n.loadEventEnd),
                            harita: window.__haritaHazir || null,
                            kaynak: performance.getEntriesByType('resource').length}}""")
            except Exception as e:  # noqa: BLE001
                timing = {"hata": str(e)[:300]}
            page.screenshot(path=str(OUT / f"{name}.png"))
            report[name] = {"url": url, "sure_sn": round(time.time() - t0, 1), "zaman": timing, "kayit": logs[:60]}
            ctx.close()
        browser.close()
    sizes = {str(f.relative_to("site")): f.stat().st_size for f in Path("site/veri/harita").glob("*.json")}
    sizes.update({str(f.relative_to("site")): f.stat().st_size for f in Path("site/vendor").rglob("*") if f.is_file()})
    report["_boyutlar"] = sizes
    (OUT / "rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for pr in procs:
        pr.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
