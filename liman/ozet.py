"""Bütün verinin özeti: ana sayfa ve rapor (makale) bu sayıları kullanır.

Sayılar harita kayıtlarından (canlı kayıt ve geçmiş tarama) ve tanker dosyalarından hesaplanır. Dönem kuralı:
Türk tarafındaki olay (ihracatta Türk limanından çıkış, ithalatta Türk limanına varış) beyan tarihinden sonra olmalı.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict

from . import harita
from .util import now_utc

AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
AY_K = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
AY_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
         "December"]
AY_EN_K = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _aylar(a: str, b: str) -> list[str]:
    """a ve b ("YYYY-AA") arasındaki bütün aylar."""
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _gemi(r: dict):
    return r.get("m") or f"ad:{r.get('n')}"


def hesapla(cfg, con, recs: list[dict], tankerler: list[dict] | None = None) -> dict:
    from .db import get_meta
    from .gecmis import erken_bas, target
    home = {p.country for p in cfg.ports if p.role == "izlenen"}
    aciklamalar = [a for a in (cfg.declaration.get("aciklamalar") or []) if a.get("gun")]
    beyan = str(aciklamalar[0]["gun"])[:10] if aciklamalar else None
    liman_kisit = str(aciklamalar[1]["gun"])[:10] if len(aciklamalar) > 1 else None
    t = target(con)
    if not beyan and t:
        beyan = t["baslangic"]  # açıklama tanımlı değilse geçmiş taramanın başlangıcı
    erken = erken_bas(cfg, t) if t else beyan
    durum = json.loads(get_meta(con, "gecmis_durum", "{}") or "{}")
    bugun = now_utc().date()
    # GFW liman ziyaretleri birkaç gün geç gelir: son tam ay, bugünden 3 gün önceki günün bir önceki ayı
    son_gun = (bugun - dt.timedelta(days=3)).isoformat()
    son_tam_ay = (dt.date.fromisoformat(son_gun[:8] + "01") - dt.timedelta(days=1)).isoformat()[:7]
    out: dict = {"beyan": beyan, "liman_kisit": liman_kisit, "erken": erken, "son_gun": son_gun,
                 "son_tam_ay": son_tam_ay, "olusturma": now_utc().isoformat(timespec="seconds"),
                 "yonler": {}, "kapsama": {}}
    out["_isaretler"] = sorted(
        [{"gun": str(a["gun"])[:10], "etiket": a.get("etiket") or "", "etiket_en": a.get("etiket_en") or a.get("etiket") or "",
          "ana": i == 0} for i, a in enumerate(aciklamalar) if a.get("etiket")]
        + [{"gun": str(a["gun"])[:10], "etiket": a.get("etiket") or "", "etiket_en": a.get("etiket_en") or a.get("etiket") or "",
            "ana": False} for a in (cfg.declaration.get("isaretler") or []) if a.get("gun")],
        key=lambda x: x["gun"])
    out["testler"] = [dict(x, gun=str(x["gun"])[:10]) for x in (cfg.declaration.get("testler") or []) if x.get("gun")]
    # kapsama: geçmiş taramanın hangi bölümü bitti
    onc = durum.get("oncelik") or {}

    def oran(*ks):
        a = sum((onc.get(k) or [0, 0])[0] for k in ks)
        b = sum((onc.get(k) or [0, 0])[1] for k in ks)
        return round(100 * a / b, 1) if b else None
    out["kapsama"] = {"tamam": bool(durum.get("tamam")), "ana": oran("-1", "0"), "ceyhan": oran("1"), "erken": oran("2"),
                      "ceyhan_erken": oran("3"), "diger": oran("4", "5"), "gorev": durum.get("gorev")}
    for A, B in cfg.directions:
        y = f"{A}>{B}"
        ihr = A in home
        sel = [r for r in recs if r["y"] == y]

        def tt(r):
            return (r.get("t0") if ihr else r.get("t1")) or r.get("t0") or r.get("t1") or ""
        sonra = [r for r in sel if beyan and tt(r) >= beyan]
        once = [r for r in sel if beyan and erken and erken <= tt(r) < beyan]
        aylik: dict[str, Counter] = defaultdict(Counter)
        for r in sel:
            if tt(r) >= (erken or ""):
                aylik[tt(r)[:7]][r["a"]] += 1
        aylar = _aylar((erken or tt(min(sel, key=tt)))[:7], son_gun[:7]) if sel else []
        tam_sonra = [m for m in aylar if beyan and beyan[:7] <= m <= son_tam_ay]
        tam_once = [m for m in aylar if beyan and erken[:7] < m < beyan[:7]]  # ilk ay (Ekim 2023) eksik başlar
        say_ay = {m: sum(aylik[m].values()) for m in aylar}
        gemiler: dict = defaultdict(list)
        for r in sonra:
            gemiler[_gemi(r)].append(r)
        en_cok = []
        for k, rs in sorted(gemiler.items(), key=lambda kv: (-len(kv[1]), kv[1][0].get("n") or "")):
            rs.sort(key=tt)
            en_cok.append({"ad": rs[-1].get("n") or "Adı bilinmiyor", "mmsi": rs[-1].get("m"),
                           "imo": next((x.get("imo") for x in rs if x.get("imo")), None),
                           "bayrak": next((x.get("b") for x in rs if x.get("b")), None),
                           "n": len(rs), "aile": Counter(x["a"] for x in rs), "ilk": tt(rs[0]), "son": tt(rs[-1]),
                           "hat": Counter((x.get("o") or "?", x.get("d") or "?") for x in rs).most_common(1)[0][0],
                           "tanker": any(x.get("sv") for x in rs)})
        try:
            from .rapor import bilgi_kaynagi
            bilgi = bilgi_kaynagi(cfg, con)
            for g in en_cok[:25]:
                if not g["imo"] and isinstance(g["mmsi"], int):
                    g["imo"] = bilgi(g["mmsi"], None).get("imo")
        except Exception:  # noqa: BLE001
            pass
        bayrak = Counter(r.get("b") or "?" for r in sonra)
        tr_bayrak = [r for r in sonra if r.get("b") == "TUR"]
        il_bayrak = [r for r in sonra if r.get("b") == "ISR"]
        out["yonler"][y] = {
            "A": A, "B": B, "ihracat": ihr, "toplam": len(sel), "sonra": len(sonra), "once": len(once),
            "gemi_sonra": len(gemiler), "gemi_once": len({_gemi(r) for r in once}),
            "aile_sonra": Counter(r["a"] for r in sonra), "sinif_sonra": Counter(r["k"] for r in sonra),
            "aylik": {m: dict(aylik[m]) for m in aylar}, "aylar": aylar,
            "ort_sonra": round(sum(say_ay[m] for m in tam_sonra) / len(tam_sonra), 1) if tam_sonra else None,
            "ort_once": round(sum(say_ay[m] for m in tam_once) / len(tam_once), 1) if tam_once else None,
            "min_ay": min(((say_ay[m], m) for m in tam_sonra), default=None),
            "max_ay": max(((say_ay[m], m) for m in tam_sonra), default=None),
            "sifir_ay": [m for m in tam_sonra if not say_ay[m]],
            "tam_sonra": tam_sonra, "tam_once": tam_once,
            "cikis": Counter(r.get("o") or "?" for r in sonra).most_common(12),
            "varis": Counter(r.get("d") or "varış kayıtsız" for r in sonra).most_common(12),
            "hat": Counter((r.get("o") or "?", r.get("d") or "varış kayıtsız") for r in sonra).most_common(12),
            "ara": Counter(x for r in sonra for x in (r.get("ara") or [])).most_common(12),
            "bayrak": bayrak.most_common(15),
            "tr_bayrak": len(tr_bayrak),
            "tr_bayrak_kisit": len([r for r in tr_bayrak if liman_kisit and tt(r) >= liman_kisit]),
            "il_bayrak": len(il_bayrak),
            "il_bayrak_kisit": len([r for r in il_bayrak if liman_kisit and tt(r) >= liman_kisit]),
            "kisit_sonra": len([r for r in sonra if liman_kisit and tt(r) >= liman_kisit]),
            "en_cok": en_cok[:25],
            "petrol": len([r for r in sonra if r.get("sv")]),
            "ceyhan": len([r for r in sonra if (r.get("ter") or "").startswith("Ceyhan")]),
            "kaynak": Counter(r["s"] for r in sonra),
            "ornek_tr_bayrak": sorted(tr_bayrak, key=tt)[-3:],
        }
    # tankerler
    ds = tankerler or []
    # Ceyhan'dan çıkıp İsrail limanına kayıtlı varışı olan tanker seferleri (en yeni önce): somut örnekler
    cey_ornek = []
    for d in ds:
        for s_ in d["seferler"]:
            if (s_.get("ter") or "").startswith("Ceyhan") and s_.get("duzey") in ("kayitli", "aktarma") and \
                    (s_.get("t0") or "") >= (beyan or ""):
                cey_ornek.append({"ad": d["ad"], "anahtar": d["anahtar"], "imo": d["imo"], "bayrak": d["bayrak"],
                                  "flag3": d.get("flag3"), "mmsi": d.get("mmsi"),
                                  "dogrulandi": d["dogrulandi"], "t0": s_.get("t0"), "t1": s_.get("t1"), "d": s_.get("d"),
                                  "ara": s_.get("ara") or [], "id": s_.get("id")})
    cey_ornek.sort(key=lambda x: x["t1"] or "", reverse=True)
    out["tanker"] = {
        "ceyhan_kayitli": len({x["anahtar"] for x in cey_ornek}), "ceyhan_kayitli_sefer": len(cey_ornek),
        "ceyhan_gizli": sum(1 for d in ds if any((s_.get("ter") or "").startswith("Ceyhan") and
                                                s_.get("duzey") in ("acik", "iz", "bekleme", "karanlik") for s_ in d["seferler"])),
        "ceyhan_ornek": cey_ornek[:8],
        "gemi": len(ds), "sefer": sum(len(d["seferler"]) for d in ds),
        "dogrulanan": sum(1 for d in ds if d["dogrulandi"]),
        "duzey": Counter(s["duzey"] for d in ds for s in d["seferler"]),
        "ceyhan_gemi": sum(1 for d in ds if any((s.get("ter") or "").startswith("Ceyhan") for s in d["seferler"])),
        "sonra": sum(1 for d in ds for s in d["seferler"] if beyan and (s.get("t0") or "") >= beyan),
        "ornekler": [{"ad": d["ad"], "anahtar": d["anahtar"], "imo": d["imo"], "bayrak": d["bayrak"], "duzey": d["duzey"],
                      "flag3": d.get("flag3"), "mmsi": d.get("mmsi"),
                      "n": len(d["seferler"]), "basin": bool(d["basin"]), "dogrulandi": d["dogrulandi"]} for d in ds[:12]],
    }
    from .tanker import basin_ozeti
    try:
        out["basin"] = basin_ozeti(cfg, con, ds)
    except Exception:  # noqa: BLE001  (sağlama tablosu raporu durdurmasın)
        out["basin"] = []
    cik = json.loads(get_meta(con, "ceyhan_cikislari", "[]") or "[]")
    out["ceyhan"] = {"cikis": len(cik), "gemi": len({x["vid"] for x in cik}),
                     "il": sum(1 for x in cik if x.get("ulke") in cfg.dest_countries()),
                     "il_acik": sum(1 for x in cik if any(g.get("il") for g in x.get("bosluk") or [])),
                     "kayitsiz": sum(1 for x in cik if not x.get("ulke")),
                     "donus": sum(1 for x in cik if x.get("donus")),
                     "donus_gemi": len({x["vid"] for x in cik if x.get("donus")}),
                     "iz": sum(1 for x in cik if (x.get("iz") or {}).get("acik") or (x.get("iz") or {}).get("sahte")),
                     "iz_donus": sum(1 for x in cik if x.get("donus") and ((x.get("iz") or {}).get("acik")
                                                                         or (x.get("iz") or {}).get("sahte"))),
                     "sahte": sum(1 for x in cik if (x.get("iz") or {}).get("sahte")
                                  or any(g.get("sahte") for g in x.get("bosluk") or []))}
    out["petrol"] = petrol_dengesi(cfg, cik, ds)
    # bu sürümün veri kesiti: kayıtların sabit sıralı özetinin SHA-256'sı
    kesit = sorted([r["id"], r["y"], r["k"], r.get("m"), r.get("n"), r.get("o"), r.get("t0"), r.get("d"), r.get("t1")]
                   for r in recs)
    ham = json.dumps(kesit, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    out["veri_hash"] = hashlib.sha256(ham).hexdigest()
    out["kesit"] = kesit
    return out


def petrol_dengesi(cfg, cik: list[dict], ds: list[dict]) -> dict:
    """Azerbaycan petrolü: kaynaklara göre İsrail'e gitmesi gereken tanker sayısı ile Ceyhan çıkışlarında görülen iz.

    Beklenen sefer = (izleme şirketlerinin yıllık varil/gün tahmini × gün) / (BP'nin açıkladığı Ceyhan yüklemesi başına
    ortalama varil). Görülen = geçmiş taramada işlenen Ceyhan çıkışları ve bunların İsrail'e işaret eden kayıtları."""
    az = (cfg.raw.get("azerbaycan") or {}) if hasattr(cfg, "raw") else {}
    btc = az.get("btc") or {}
    ort = (btc.get("varil") / btc.get("tanker")) if btc.get("varil") and btc.get("tanker") else None
    tahmin = {str(t["yil"]): t for t in az.get("tahmin") or []}
    tanker_m = {str(d.get("mmsi")) for d in ds if d.get("mmsi")}
    hedef = cfg.dest_countries()
    yillar = sorted({(x.get("t") or x.get("t0") or "")[:4] for x in cik if (x.get("t") or x.get("t0"))} | set(tahmin))
    satir = []
    for y in yillar:
        if not y or y < "2023":
            continue
        xs = [x for x in cik if (x.get("t") or x.get("t0") or "")[:4] == y]
        tk = [x for x in xs if (x.get("tip") or "").lower() in ("other_non_fishing", "bunker", "tanker")
              or str(x.get("m")) in tanker_m]

        def isr(x):
            iz = x.get("iz") or {}
            return {"kayitli": x.get("ulke") in hedef,
                    "acik": any(g.get("il") for g in x.get("bosluk") or []),
                    "iz": bool(iz.get("acik") or iz.get("sahte")),
                    "sahte": bool(iz.get("sahte") or any(g.get("sahte") for g in x.get("bosluk") or [])),
                    "donus": bool(x.get("donus"))}
        f = [isr(x) for x in tk]
        isaret = sum(1 for z in f if z["kayitli"] or z["acik"] or z["iz"] or z["sahte"])
        donus_yalniz = sum(1 for z in f if z["donus"] and not (z["kayitli"] or z["acik"] or z["iz"] or z["sahte"]))
        ulke = Counter((x.get("ulke_ad") or "Kayıtsız (sonraki uğrak yok)") for x in tk)
        t = tahmin.get(y) or {}
        gun = 366 if int(y) % 4 == 0 else 365
        bek = round(t["varil_gun"] * gun / ort) if t.get("varil_gun") and ort else None
        satir.append({"yil": y, "cikis": len(xs), "tanker": len(tk), "kayitli": sum(z["kayitli"] for z in f),
                      "acik": sum(z["acik"] for z in f), "iz": sum(z["iz"] for z in f), "sahte": sum(z["sahte"] for z in f),
                      "donus": sum(z["donus"] for z in f), "donus_yalniz": donus_yalniz, "isaret": isaret,
                      "beklenen": bek, "varil_gun": t.get("varil_gun"), "tahmin_kaynak": t.get("kaynak"),
                      "gumruk_ton": t.get("gumruk_ton"), "btc_tanker": (btc.get("tanker") if str(btc.get("yil")) == y else None),
                      "ulkeler": ulke.most_common(6)})
    return {"ort_varil": round(ort) if ort else None, "btc": btc, "yillar": satir,
            "aciklamalar": az.get("aciklamalar") or []}


# --------------------------------------------------------------------------- grafik
def aylik_svg(o: dict, y: str, *, en: bool = False, genis: int = 1040, yuk: int = 300, kimlik: str = "grafik",
              aileli: bool = True) -> str:
    """Aylık sefer sayısı, sütun grafik (SVG). Beyan tarihleri kesik dikey çizgiyle işaretli."""
    d = o["yonler"].get(y)
    if not d or not d["aylar"]:
        return ""
    aylar = d["aylar"]
    sira = harita.FAMILY_ORDER
    deg = [{a: d["aylik"].get(m, {}).get(a, 0) for a in sira} for m in aylar]
    top = [sum(x.values()) for x in deg]
    ust = max(top + [1])
    adim = next(s for s in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000) if ust / s <= 5)
    ymax = adim * (int(ust / adim) + 1)
    sol, sag, ust_p, alt_p = 40, 8, 30, 34
    w, h = genis - sol - sag, yuk - ust_p - alt_p
    n = len(aylar)
    bw = w / n
    gap = 2 if bw > 6 else 1
    kisa = AY_EN_K if en else AY_K
    parts = []
    # ızgara ve eksen
    for v in range(0, ymax + 1, adim):
        yy = ust_p + h - h * v / ymax
        parts.append(f'<line class="izgara" x1="{sol}" x2="{sol + w}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
                     f'<text class="eksen" x="{sol - 6}" y="{yy + 4:.1f}" text-anchor="end">{v}</text>')
    # ön dönem taraması tamamlanmadıysa gölge
    erken_tamam = (o["kapsama"].get("erken") or 0) >= 95 or o["kapsama"].get("tamam")
    if o.get("beyan") and not erken_tamam:
        i_b = next((i for i, m in enumerate(aylar) if m >= o["beyan"][:7]), n)
        if i_b > 0:
            parts.append(f'<rect class="eksik" x="{sol}" y="{ust_p}" width="{bw * i_b:.1f}" height="{h}"/>')
            bos = next((i for i in range(i_b) if top[i]), i_b)  # baştaki boş aylar: yazı oraya
            satir = (["Scan in", "progress"] if en else ["Tarama", "sürüyor"])
            if bos * bw >= 54:
                parts.append(f'<text class="eksik-yazi" x="{sol + bos * bw / 2:.1f}" y="{ust_p + h / 2:.1f}" text-anchor="middle">'
                             f'<tspan x="{sol + bos * bw / 2:.1f}">{satir[0]}</tspan>'
                             f'<tspan x="{sol + bos * bw / 2:.1f}" dy="14">{satir[1]}</tspan></text>')
    # sütunlar
    for i, (m, x) in enumerate(zip(aylar, deg)):
        kismi = m > o.get("son_tam_ay", "9999")  # içinde bulunulan ay: veri eksik
        x0 = sol + i * bw + gap / 2
        y0 = ust_p + h
        seg = []
        for a in (sira if aileli else ["_"]):
            v = x[a] if aileli else top[i]
            if not v:
                continue
            hh = h * v / ymax
            cls = f"s-{a}" if aileli else "s-tek"
            seg.append((cls, y0 - hh, hh))
            y0 -= hh
        etiket = (f"{AY_EN[int(m[5:]) - 1] if en else AY[int(m[5:]) - 1]} {m[:4]}: {top[i]} "
                  + ("voyages" if en else "sefer"))
        if aileli and top[i]:
            etiket += " (" + ", ".join(f"{(FAM_EN if en else harita.FAMILY_LABELS)[a].lower()} {x[a]}"
                                       for a in sira if x[a]) + ")"
        if kismi:
            etiket += ". " + ("Month in progress; data incomplete." if en else "Ay sürüyor; veri eksik.")
        rects = "".join(f'<rect class="{c}" x="{x0:.1f}" y="{yy:.1f}" width="{max(bw - gap, 1):.1f}" height="{hh:.1f}"'
                        f'{' rx="1.5"' if j == len(seg) - 1 else ""}/>' for j, (c, yy, hh) in enumerate(seg))
        parts.append(f'<g class="ay{" kismi" if kismi else ""}"><title>{etiket}</title><rect class="isabet" x="{x0:.1f}" y="{ust_p}" '
                     f'width="{max(bw - gap, 1):.1f}" height="{h}"/>{rects}</g>')
        if m[5:] in ("01", "04", "07", "10"):
            parts.append(f'<text class="eksen" x="{x0 + (bw - gap) / 2:.1f}" y="{ust_p + h + 16}" text-anchor="middle">'
                         f'{kisa[int(m[5:]) - 1]}</text>')
            if m[5:] == "01" or i == 0:
                parts.append(f'<text class="eksen yil" x="{x0 + (bw - gap) / 2:.1f}" y="{ust_p + h + 30}" '
                             f'text-anchor="middle">{m[:4]}</text>')
    # beyan çizgileri
    isaretler = []
    for a in (o.get("_isaretler") or []):
        g = a["gun"]
        if not aylar[0] <= g[:7] <= aylar[-1]:
            continue
        i = aylar.index(g[:7])
        gunler = 31
        frac = (int(g[8:10]) - 1) / gunler
        xx = sol + (i + frac) * bw
        isaretler.append((xx, a["etiket_en"] if en else a["etiket"], a.get("ana")))
    # etiketler: önce ana beyan, sonra diğerleri; çakışan etiket yazılmaz (çizgi kalır)
    yer_: list[tuple[float, float]] = []
    for xx, et, ana in sorted(isaretler, key=lambda t: (not t[2], t[0])):
        parts.append(f'<line class="beyan{" ana" if ana else ""}" x1="{xx:.1f}" x2="{xx:.1f}" y1="{ust_p - 6}" y2="{ust_p + h}"/>')
        gen = len(et) * 6.4 + 8
        a0, a1, anc, tx = (xx + 4, xx + 4 + gen, "start", xx + 4) if xx + gen < sol + w else (xx - 4 - gen, xx - 4, "end", xx - 4)
        if all(a1 < b0 or a0 > b1 for b0, b1 in yer_):
            parts.append(f'<text class="beyan-yazi{" ana" if ana else ""}" x="{tx:.1f}" y="{ust_p - 10}" text-anchor="{anc}">{et}</text>')
            yer_.append((a0, a1))
    ozet_ = (f"Monthly voyages from {o['yonler'][y]['A']} to {o['yonler'][y]['B']}" if en
             else "Aylara göre sefer sayısı")
    return (f'<svg class="aylik" id="{kimlik}" viewBox="0 0 {genis} {yuk}" role="img" aria-label="{ozet_}" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>')


FAM_EN = {"dogrudan": "Direct", "liman": "Via a third-country port", "sts": "Ship-to-ship", "karanlik": "AIS off"}
