"""Komut satırı:

  python -m liman calistir            toplayıcıyı ve zamanlanmış işleri başlatır (7/24)
  python -m liman kontrol             ayar dosyasını ve anahtarı kontrol eder
  python -m liman saatlik             analizleri ve siteyi bir kez günceller
  python -m liman gunluk [--gonder]   bekleyen günleri arşivler, siteyi üretir, istenirse GitHub'a gönderir
  python -m liman dogrula GÜN         bir günün dosyalarını kanıt zincirine göre doğrular
  python -m liman demo                kurgusal verilerle uçtan uca deneme yapar (demo/ klasörüne)
  python -m liman tur --dakika 50     GitHub Actions modu: belirtilen süre toplar, sonra arşiv ve site üretir
  python -m liman durum-yukle KLASÖR  kayıtlı durumu geri yükler (Actions)
  python -m liman durum-kaydet KLASÖR durumu sıkıştırıp kaydeder (Actions)
  python -m liman gecmis --baslangic 2024-05-02 [--dilim 8]
                                      Global Fishing Watch ile geçmişe dönük tarama (kaldığı yerden devam eder)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from . import config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m liman", description="Liman İzleme")
    ap.add_argument("komut", choices=["calistir", "kontrol", "saatlik", "gunluk", "dogrula", "demo",
                                      "tur", "durum-yukle", "durum-kaydet", "ham-hazirla", "gecmis"])
    ap.add_argument("gun", nargs="?")
    ap.add_argument("--ayar", default="config.yaml")
    ap.add_argument("--gonder", action="store_true", help="GitHub'a gönder (gunluk)")
    ap.add_argument("--dakika", type=float, default=50, help="tur: kaç dakika veri toplanacak")
    ap.add_argument("--baslangic", default="", help="gecmis: tarama başlangıç tarihi (YYYY-AA-GG)")
    ap.add_argument("--bitis", default="", help="gecmis: tarama bitiş tarihi (varsayılan bugün)")
    ap.add_argument("--dilim", type=float, default=None, help="gecmis: bu çalıştırmada en fazla kaç dakika sorgu")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    if a.komut == "demo":
        from . import demo
        return demo.run()

    cfg = config.load(a.ayar)
    if a.komut == "kontrol":
        from .collector import port_boxes
        print(f"Proje: {cfg.name} · saat dilimi {cfg.tz}")
        for p in cfg.ports:
            print(f"  {p.code:10s} {p.name} [{p.country}] rol={p.role} terminal={len(p.terminals)}")
        print("Beyan yönleri:", ", ".join(f"{x}>{y}" for x, y in cfg.directions) or "yok")
        print("aisstream kutuları:", json.dumps(port_boxes(cfg)))
        key = os.environ.get(cfg.ais["anahtar_degiskeni"])
        print("aisstream anahtarı:", "var" if key else "YOK (.env dosyasına ekle)")
        return 0 if key and cfg.ports else 1
    if a.komut == "gecmis":
        from . import gecmis
        print(gecmis.run(cfg, a.baslangic or None, a.bitis or None, a.dilim))
        return 0
    if a.komut == "ham-hazirla":
        from . import durum
        print(" ".join(durum.prepare_raw(cfg)))
        return 0
    if a.komut in ("durum-yukle", "durum-kaydet"):
        from pathlib import Path
        from . import durum
        d = Path(a.gun or "_durum")
        if a.komut == "durum-yukle":
            durum.load(cfg, d)
        else:
            durum.save(cfg, d)
        return 0
    if a.komut == "tur":
        from . import jobs, runner
        rc = 0
        if cfg.ports and os.environ.get(cfg.ais["anahtar_degiskeni"]):
            try:
                rc = asyncio.run(runner.main(cfg, minutes=a.dakika))
            except Exception:  # noqa: BLE001  (toplama hatası arşiv ve siteyi engellemesin)
                logging.exception("Toplama sırasında hata")
                rc = 1
        else:
            logging.warning("Liman veya aisstream anahtarı yok; yalnızca site üretiliyor")
        print(jobs.daily(cfg, push=False))
        return rc
    if a.komut == "calistir":
        from . import runner
        if not cfg.ports:
            # Limanlar henüz girilmemiş: GitHub'daki config.yaml doldurulana kadar 5 dakikada bir kontrol et
            import subprocess
            import time
            logging.info("config.yaml içinde liman yok; GitHub'da doldurulması bekleniyor")
            while True:
                subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=cfg.root, capture_output=True)
                if config.load(a.ayar).ports:
                    logging.info("Limanlar eklendi, başlatılıyor")
                    return 3  # servis yeniden başlar
                time.sleep(300)
        return asyncio.run(runner.main(cfg))
    if a.komut == "saatlik":
        from . import jobs
        print(jobs.hourly(cfg))
        return 0
    if a.komut == "gunluk":
        from . import jobs
        print(jobs.daily(cfg, push=a.gonder or None))
        return 0
    if a.komut == "dogrula":
        from . import proof
        if not a.gun:
            print("Gün ver: python -m liman dogrula 2026-11-12")
            return 2
        ok, lines = proof.verify(cfg, a.gun)
        print("\n".join(lines))
        print("SONUÇ:", "DOĞRULANDI" if ok else "BAŞARISIZ")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
