"""Kaynakçadaki her bağlantıyı İnternet Arşivi'ne (Wayback Machine, Save Page Now) kaydettirir.

Kullanım: python kurulum/kaynak_arsivle.py [--yeniden-gun 90]
- Kopyası olmayan ya da kopyası --yeniden-gun'den eski bağlantılar kaydettirilir.
- Kaydetme başarısız olursa var olan en yakın kopya kullanılır (yol: "var olan kopya").
- Sonuç arsiv/kaynaklar.json dosyasına yazılır; iş akışı bu dosyayı depoya kaydeder.
Anahtar gerekmez; Save Page Now'ın anonim hız sınırı için istekler arasında beklenir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from liman.arsiv import DOSYA, harita, toplanan  # noqa: E402

UA = "Avvam kaynak arsivi (+https://github.com/hakanul-barreyn/liman-izleme)"
ZAMAN = re.compile(r"/web/(\d{14})/")


def _iste(url: str, sure: int) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=sure) as r:
        r.read(2048)
        return r.geturl(), r.status


def _zaman(kopya: str) -> str | None:
    m = ZAMAN.search(kopya)
    if not m:
        return None
    z = m.group(1)
    return f"{z[:4]}-{z[4:6]}-{z[6:8]}T{z[8:10]}:{z[10:12]}:{z[12:14]}Z"


def kaydet(url: str) -> dict:
    """Save Page Now; yönlendirilen son adres kopyanın adresidir."""
    son, _ = _iste("https://web.archive.org/save/" + url, 180)
    if "/web/" not in son:
        raise RuntimeError(f"beklenmeyen yanıt: {son}")
    return {"kopya": son, "zaman": _zaman(son), "yol": "kaydedildi"}


def var_olan(url: str) -> dict | None:
    q = "https://archive.org/wayback/available?" + urllib.parse.urlencode({"url": url})
    req = urllib.request.Request(q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    c = (d.get("archived_snapshots") or {}).get("closest") or {}
    if not c.get("available"):
        return None
    k = c["url"].replace("http://", "https://", 1)
    return {"kopya": k, "zaman": _zaman(k), "yol": "var olan kopya"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yeniden-gun", type=int, default=90)
    ap.add_argument("--bekle", type=float, default=12)
    a = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    h = harita(root)
    simdi = dt.datetime.now(dt.UTC)
    sinir = (simdi - dt.timedelta(days=a.yeniden_gun)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ozet = {"kaydedildi": 0, "var olan kopya": 0, "basarisiz": 0, "guncel": 0}
    for url in toplanan(root):
        eski = h.get(url) or {}
        if eski.get("kopya") and eski.get("yol") == "kaydedildi" and (eski.get("zaman") or "") >= sinir:
            ozet["guncel"] += 1
            continue
        kayit = None
        hata = ""
        for deneme in range(2):
            try:
                kayit = kaydet(url)
                break
            except Exception as e:  # noqa: BLE001  ağ hatası, hız sınırı, sitenin arşivi engellemesi
                hata = f"{type(e).__name__}: {e}"[:200]
                time.sleep(a.bekle * (3 if deneme == 0 else 1))
        if kayit is None:
            try:
                kayit = var_olan(url)
            except Exception as e:  # noqa: BLE001
                hata += f" | var olan kopya sorgusu: {type(e).__name__}: {e}"[:200]
        if kayit is None and eski.get("kopya"):
            kayit = {k: eski[k] for k in ("kopya", "zaman", "yol") if k in eski}
        kayit = kayit or {}
        kayit["denendi"] = simdi.strftime("%Y-%m-%dT%H:%M:%SZ")
        if hata and kayit.get("yol") != "kaydedildi":
            kayit["hata"] = hata
        h[url] = kayit
        ozet[kayit.get("yol", "basarisiz") if kayit.get("kopya") else "basarisiz"] += 1
        print(f"{kayit.get('yol', 'BAŞARISIZ'):15} {url} -> {kayit.get('kopya', hata)}", flush=True)
        f = root / DOSYA
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(dict(sorted(h.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        time.sleep(a.bekle)
    print(json.dumps(ozet, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
