"""Günlük arşiv: her liman için ziyaret listesi, harita görseli, olaylar, kesintiler, ham veri."""
from __future__ import annotations

import csv
import gzip
import io
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import proof, tracks  # noqa: E402
from .util import SHIP_GROUP_LABELS, day_bounds_utc, fmt_local, hours_between, ship_group  # noqa: E402

VISIT_FIELDS = ["mmsi", "imo", "ad", "tip", "giris_utc", "cikis_utc", "sure_saat", "terminal",
                "draft_giris_m", "draft_cikis_m", "draft_fark_m", "beyan_edilen_varis"]


def _visit_rows(cfg, con, port_code: str, a: str, b: str) -> list[dict]:
    rows = []
    for v in con.execute(
            """SELECT v.*, s.imo, s.name, s.type FROM visits v LEFT JOIN vessels s ON s.mmsi=v.mmsi
               WHERE v.port=? AND transit IS NOT 1 AND v.t_in < ? AND coalesce(v.t_out, v.last_in) >= ?
               ORDER BY v.t_in""", (port_code, b, a)):
        d_in, d_out = v["draught_in"], v["draught_out"]
        rows.append({
            "mmsi": v["mmsi"], "imo": v["imo"], "ad": v["name"],
            "tip": SHIP_GROUP_LABELS[ship_group(v["type"])],
            "giris_utc": v["t_in"], "cikis_utc": v["t_out"] or "",
            "sure_saat": round(hours_between(v["t_in"], v["t_out"] or v["last_in"]), 1),
            "terminal": v["terminal"] or "",
            "draft_giris_m": d_in, "draft_cikis_m": d_out,
            "draft_fark_m": round(d_out - d_in, 1) if d_in is not None and d_out is not None else None,
            "beyan_edilen_varis": v["dest_out"] or "",
        })
    return rows


def _map(cfg, con, port, a: str, b: str, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 6), dpi=110)
    fig.patch.set_facecolor("#f7f6f2")
    ax.set_facecolor("#e8eef2")
    xs = [p[1] for p in port.area.outline()]
    ys = [p[0] for p in port.area.outline()]
    ax.fill(xs, ys, color="#c9d6df", alpha=0.6, lw=0)
    ax.plot(xs, ys, color="#5b7083", lw=1)
    for t in port.terminals:
        o = t.area.outline()
        ax.fill([p[1] for p in o], [p[0] for p in o], color="#e0b25a", alpha=0.45, lw=0)
        ax.annotate(t.name, (t.area.center[1], t.area.center[0]), fontsize=7, color="#6b4e12", ha="center")
    tracks = {}
    for r in con.execute("SELECT mmsi,lat,lon FROM positions WHERE port=? AND t>=? AND t<? ORDER BY t",
                         (port.code, a, b)):
        tracks.setdefault(r["mmsi"], []).append((r["lon"], r["lat"]))
    names = {r["mmsi"]: r["name"] for r in con.execute("SELECT mmsi,name FROM vessels")}
    cmap = plt.get_cmap("tab10")
    for i, (m, pts) in enumerate(sorted(tracks.items())):
        c = cmap(i % 10)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=c, lw=2, alpha=0.9)
        ax.plot(pts[-1][0], pts[-1][1], "o", color=c, ms=6)
        if len(tracks) <= 25:
            ax.annotate(names.get(m) or str(m), pts[-1], fontsize=8.5, color="#222",
                        xytext=(3, 3), textcoords="offset points")
    bb = port.area.bbox(1.5)
    ax.set_xlim(bb[0][1], bb[1][1])
    ax.set_ylim(bb[0][0], bb[1][0])
    ax.set_aspect(1 / max(0.2, __import__("math").cos(__import__("math").radians(port.area.center[0]))))
    ax.set_title(f"{port.name} · {fmt_local(a, cfg.tz)[:10]} · {len(tracks)} gemi", fontsize=10)
    ax.tick_params(labelsize=7)
    ax.set_xlabel("Boylam", fontsize=7)
    ax.set_ylabel("Enlem", fontsize=7)
    note = "Kaynak: AIS (aisstream.io) · ham veri ve hash'ler arşivde"
    if cfg.fictional:
        note = "KURGUSAL DEMO VERİSİ · " + note
    fig.text(0.01, 0.01, note, fontsize=6.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    # tarih bilgisi görselin içinde yazılı olsun ama dosya her üretimde aynı kalsın
    fig.savefig(out, metadata={"Software": None, "Creation Time": None}, facecolor=fig.get_facecolor())
    plt.close(fig)


def _gzip_deterministic(src: Path, dst: Path) -> None:
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fo, mtime=0) as gz:
            shutil.copyfileobj(fi, gz)


def build_day(cfg, con, day: str) -> dict:
    a, b = day_bounds_utc(day, cfg.tz)
    out = cfg.site_dir / "arsiv" / day
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    summary = {"gun": day, "utc_aralik": [a, b], "limanlar": {}, "kurgusal": cfg.fictional}
    for port in cfg.ports:
        rows = _visit_rows(cfg, con, port.code, a, b)
        (out / f"{port.code}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=VISIT_FIELDS)
        w.writeheader()
        w.writerows(rows)
        (out / f"{port.code}.csv").write_text(buf.getvalue(), encoding="utf-8")
        if port.role == "izlenen":
            _map(cfg, con, port, a, b, out / f"{port.code}.png")
        entered = sum(1 for r in rows if a <= r["giris_utc"] < b)
        left = sum(1 for r in rows if r["cikis_utc"] and a <= r["cikis_utc"] < b)
        summary["limanlar"][port.code] = {"ad": port.name, "ulke": port.country, "rol": port.role,
                                          "ziyaret": len(rows), "giren": entered, "cikan": left}
    izler = tracks.build_day(cfg, con, day)
    names = {r["mmsi"]: r["name"] for r in con.execute("SELECT mmsi, name FROM vessels")}
    (out / "izler.json").write_text(json.dumps(
        {"gun": day, "aciklama": "Her geminin o günkü sadeleştirilmiş AIS izi: [boylam, enlem, dakika (Unix/60)]",
         "gemiler": {m: {"ad": names.get(int(m)), "iz": segs} for m, segs in izler.items()}},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    summary["iz_gemi_sayisi"] = len(izler)
    evs = [dict(e) | {"detail": json.loads(e["detail"] or "{}")} for e in con.execute(
        "SELECT * FROM events WHERE t_start>=? AND t_start<? ORDER BY t_start", (a, b))]
    (out / "olaylar.json").write_text(json.dumps(evs, ensure_ascii=False, indent=1), encoding="utf-8")
    outs = [dict(o) for o in con.execute(
        "SELECT conn,t_start,t_end,reason FROM outages WHERE t_start<? AND coalesce(t_end,'9999')>=?", (b, a))]
    (out / "kesintiler.json").write_text(json.dumps(outs, ensure_ascii=False, indent=1), encoding="utf-8")
    summary["olay_sayisi"] = len(evs)
    summary["kesinti_sayisi"] = len(outs)
    raw = cfg.data_dir / "ham" / f"{day}.jsonl"
    if raw.exists():
        if cfg.pub.get("ham_veri_yayinla", True):
            _gzip_deterministic(raw, out / "ham.jsonl.gz")
            summary["ham_veri"] = "ham.jsonl.gz"
        else:
            summary["ham_veri_hash"] = proof.sha256_file(raw)
            summary["ham_veri"] = "yerelde saklanıyor (yalnızca hash yayımlandı)"
    else:
        summary["ham_veri"] = "yok"
    (out / "ozet.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    entry = proof.seal(cfg, con, day, out)
    summary["gun_hash"] = entry["gun_hash"]
    return summary
