"""Tanker dosyaları: Türk petrol iskelelerinden (özellikle Ceyhan'daki BTC ve Kerkük-Ceyhan terminalleri)
çıkıp İsrail'e giden ya da İsrail açıklarında AIS'i kapalı görülen gemiler, kanıtlarıyla.

tankerler/index.html     bütün dosyalar, kanıt gücüne göre sıralı; arama ve süzgeç
tankerler/<gemi>.html    tek geminin dosyası: seferler (seyir defteri gibi), Ceyhan uğrakları, kimlik, paylaşım metni
tankerler/tankerler.csv  sefer sefer tablo
veri/tankerler.json      makinece okunur liste

Kaynak: geçmiş tarama (Global Fishing Watch liman ziyaretleri, AIS boşlukları ve AIS varlık verisi) ile bu sitenin
canlı AIS kaydı. Her kayıt bir tespittir, hüküm değildir: gemi hareketini gösterir, yükü ve ticaretin tarafını göstermez.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, urlencode

from . import harita
from .geo import haversine_km
from .ulkeler import bayrak
from .util import add_hours, hours_between, parse_iso

# kanıt düzeyleri, güçlüden zayıfa: (anahtar, kısa ad, açıklama, haritadaki aile rengi)
DUZEYLER = [
    ("kayitli", "İsrail limanına kayıtlı varış",
     "Global Fishing Watch’ın liman ziyareti kaydına göre gemi İsrail limanına girdi.", "dogrudan"),
    ("aktarma", "Üçüncü ülke limanı üzerinden",
     "Türk limanından çıktı, Mısır, Kıbrıs, Yunanistan ya da Bulgaristan limanına uğradı, oradan İsrail limanına girdi.", "liman"),
    ("acik", "AIS İsrail açıklarında kapalı",
     "Limana girişi kayıtsız; AIS sinyali İsrail açıklarında kesildi ya da orada yeniden geldi.", "karanlik"),
    ("bekleme", "İsrail kıyı açığında bekledi",
     "Limana girmeden İsrail kıyısı açığında en az 12 saat bekledi (olası şamandıra boşaltması).", "karanlik"),
    ("sts", "Denizde gemiden gemiye",
     "Yükünü denizde başka bir gemiye verdi ya da başka bir gemiden aldı; o gemi İsrail’e gitti.", "sts"),
    ("karanlik", "AIS uzun süre kapalı",
     "Yolda en az 24 saat AIS sinyali yok, varış limanı kayıtsız; nereye gittiği bilinmiyor.", "karanlik"),
]
SIRA = {k: i for i, (k, *_x) in enumerate(DUZEYLER)}
AD = {k: a for k, a, *_x in DUZEYLER}
AILE = {k: f for k, _a, _b, f in DUZEYLER}
SINIF_DUZEY = {"dogrudan": "kayitli", "dogrudan_izlenmedi": "kayitli", "karanlik_bacak": "kayitli",
               "aktarmali": "aktarma", "karanlik_acik": "acik", "kiyida_kayboldu": "acik",
               "kiyida_bosaltma": "bekleme", "denizde_aktarma": "sts", "dolayli_sts": "sts",
               "karanlik_sefer": "karanlik"}
# GFW'nin gemi sınıfları: tankerler "kargo" değil, "other_non_fishing" (ve yakıt ikmal gemisi "bunker") sınıfındadır
GFW_TANKER_SINIFI = {"other_non_fishing", "bunker"}
UNLU = "aeıioöuü"
YONLER = ["kuzeyi", "kuzeydoğusu", "doğusu", "güneydoğusu", "güneyi", "güneybatısı", "batısı", "kuzeybatısı"]
KISA_AY = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


# --------------------------------------------------------------------------- dil yardımcıları
def kisa_ad(ad: str) -> str:
    """"Aşkelon (EAPC petrol terminali)" -> "Aşkelon"; "İstanbul – Ambarlı" -> "İstanbul"."""
    return ad.split(" (")[0].split(" – ")[0].split(" ve ")[0].strip()


def iyelik(ad: str) -> str:
    """Tamlayan eki: Aşkelon’un, Hayfa’nın, Port Said’in."""
    son = next((c for c in reversed(ad.lower()) if c in UNLU), "a")
    ek = {"a": "ın", "ı": "ın", "e": "in", "i": "in", "o": "un", "u": "un", "ö": "ün", "ü": "ün"}[son]
    return f"{ad}’{'n' if ad[-1].lower() in UNLU else ''}{ek}"


def _sayi(x: float, n: int = 1) -> str:
    return f"{x:.{n}f}".replace(".", ",")


def koordinat(lat, lon) -> str:
    if lat is None or lon is None:
        return "konum yok"
    return f"{_sayi(lat, 2)}° K, {_sayi(lon, 2)}° D"


def _yon(lat0, lon0, lat1, lon1) -> str:
    dy = lat1 - lat0
    dx = (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))
    a = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return YONLER[int((a + 22.5) // 45) % 8]


def yer(cfg, lat, lon) -> str:
    """Bir deniz noktasını en yakın limana göre anlatır: "Aşkelon’un 38 km batısı"."""
    if lat is None or lon is None:
        return "konum yok"
    best = None
    for p in cfg.ports:
        if p.approach:
            continue
        d = haversine_km(lat, lon, *p.area.center)
        if best is None or d < best[0]:
            best = (d, p)
    if not best or best[0] > 320:
        return koordinat(lat, lon)
    d, p = best
    if d < 6:
        return f"{kisa_ad(p.name)} önleri"
    return f"{iyelik(kisa_ad(p.name))} {round(d)} km {_yon(*p.area.center, lat, lon)}"


def gun(cfg, s: str | None, yil: bool = True, saat: bool = False) -> str:
    from zoneinfo import ZoneInfo
    if not s:
        return "?"
    t = parse_iso(s).astimezone(ZoneInfo(cfg.tz))
    out = f"{t.day} {KISA_AY[t.month - 1]}" + (f" {t.year}" if yil else "")
    return f"{out}, {t:%H:%M}" if saat else out


def uydu(lat, lon, t0: str, t1: str, radar: bool) -> str:
    """Copernicus Browser bağlantısı (Sentinel-1 radar ya da Sentinel-2 optik)."""
    q = urlencode({"zoom": 12, "lat": f"{lat:.4f}", "lng": f"{lon:.4f}", "themeId": "DEFAULT-THEME",
                   "datasetId": "S1_CDAS_IW_VVVH" if radar else "S2_L2A_CDAS",
                   "fromTime": f"{t0[:10]}T00:00:00.000Z", "toTime": f"{t1[:10]}T23:59:59.999Z"})
    return f"https://browser.dataspace.copernicus.eu/?{q}"


def cikis_adi(cfg, r: dict, kisa: bool = False) -> str:
    """Çıkış limanının adı; GFW'de adı olmayan demirleme yerleri için en yakın limana göre konum."""
    o = r.get("o") or "Türk limanı"
    if (o.endswith(" limanı") or "adsız demirleme" in o) and r.get("w"):
        y = yer(cfg, r["w"][0][1], r["w"][0][0])
        return y if kisa else f"{o.replace(' limanı', '')}, adsız demirleme yeri ({y})"
    return kisa_ad(o) if kisa else o


def anahtar(d: dict) -> str:
    if d.get("imo"):
        return f"imo-{d['imo']}"
    if d.get("mmsi"):
        return f"mmsi-{d['mmsi']}"
    return "ad-" + "".join(c if c.isalnum() else "-" for c in (d.get("ad") or "bilinmiyor").lower()).strip("-")


# --------------------------------------------------------------------------- veri
def _secim(cfg, recs: list[dict]) -> list[dict]:
    """Türk petrol iskelesinden ya da Ceyhan terminallerinin önünden İsrail'e (ya da açıklarına) giden seferler."""
    home = {p.country for p in cfg.ports if p.role == "izlenen"}
    dest = cfg.dest_countries()
    out = []
    for r in recs:
        a, _s, b = r["y"].partition(">")
        if a in home and b in dest and r.get("k") in SINIF_DUZEY and \
                (r.get("sv") or (r.get("ter") or "").startswith("Ceyhan")):
            out.append(r)
    return out


def _basin(cfg) -> list[dict]:
    import yaml
    p = Path(cfg.root) / "gemiler.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [b for b in (data.get("basin") or []) if isinstance(b, dict) and (b.get("ad") or b.get("imo"))]


def dosyalar(cfg, con, recs: list[dict]) -> tuple[list[dict], int]:
    """Gemi gemi tanker dosyaları (en güçlü kanıt önce) ve tanker olmadığı için dışarıda bırakılan gemi sayısı.

    Listeye giren gemi ya tankerliği doğrulanmış (AIS tipi, petrol iskelesi, rotadaki başka petrol iskeleleri, basın)
    ya da Global Fishing Watch'ın kargo gemisi saymadığı (tankerlerin bulunduğu sınıftaki) gemidir. GFW'nin kargo
    gemisi saydığı ve başka tanker kanıtı olmayan gemiler (Ceyhan körfezindeki kömür, gübre, çimento gemileri) girmez."""
    from .db import get_meta
    from .rapor import bilgi_kaynagi
    sec = _secim(cfg, recs)
    if not sec:
        return [], 0
    g2vid = {f"g{i}": v for i, v in con.execute("SELECT id, vessel_id FROM gecmis WHERE vessel_id IS NOT NULL")}
    canli_tip = {r[0]: r[1] for r in con.execute("SELECT mmsi, type FROM vessels WHERE type IS NOT NULL")}
    cik = json.loads(get_meta(con, "ceyhan_cikislari", "[]") or "[]")
    petrol_lim = json.loads(get_meta(con, "gemi_petrol_iskeleleri", "{}") or "{}")
    cik_m: dict[str, list] = defaultdict(list)
    cik_v: dict[str, list] = defaultdict(list)
    for x in cik:
        if x.get("m"):
            cik_m[str(x["m"])].append(x)
        if x.get("vid"):
            cik_v[x["vid"]].append(x)
    bilgi = bilgi_kaynagi(cfg, con)
    basin = _basin(cfg)
    by: dict = defaultdict(list)
    for r in sec:
        by[r.get("m") or f"ad:{r.get('n')}"].append(r)
    out = []
    dislanan = 0
    for key, rs in by.items():
        rs.sort(key=lambda r: r.get("t0") or r.get("t1") or "", reverse=True)
        mmsi = key if isinstance(key, int) else None
        vids = sorted({g2vid[r["id"]] for r in rs if r["id"] in g2vid})
        imo = next((str(r["imo"]) for r in rs if r.get("imo")), None)
        ek = bilgi(mmsi, imo, vids[0] if vids else None)
        imo = imo or ek.get("imo")
        flag = next((r["b"] for r in rs if r.get("b")), None)
        ad = rs[0].get("n") or (f"MMSI {mmsi}" if mmsi else "Adı bilinmiyor")
        adlar = sorted({r.get("n") for r in rs if r.get("n")} - {ad})
        # Ceyhan uğrakları: MMSI ya da GFW kimliğiyle; aynı çıkış bir kez
        cy, gor = [], set()
        for x in cik_m.get(str(mmsi), []) + [y for v in vids for y in cik_v.get(v, [])]:
            if (x.get("vid"), x.get("t")) not in gor:
                gor.add((x.get("vid"), x.get("t")))
                cy.append(x)
        cy.sort(key=lambda x: x.get("t") or "", reverse=True)
        # tip kanıtı
        tip = []
        at = canli_tip.get(mmsi) if mmsi else None
        if any(r.get("tk") for r in rs) or (at is not None and 80 <= at <= 89):
            tip.append("AIS’te kendini tanker olarak bildiriyor")
        iskele = sorted({r["ter"] for r in rs if r.get("ter") and r.get("sv") and not r.get("tk")
                         and not r["ter"].startswith("Ceyhan terminalleri ve demirleme")})
        for t in iskele:
            tip.append(f"Petrol iskelesinden çıktı: {t}")
        diger = sorted({x for v in vids for x in petrol_lim.get(v, [])})
        if diger:
            tip.append("Rotasında başka petrol iskeleleri de var: " + ", ".join(diger[:4]))
        bas = [b for b in basin if (b.get("imo") and imo and str(b["imo"]) == str(imo))
               or (not b.get("imo") and str(b.get("ad", "")).upper() in {(n or "").upper() for n in [ad, *adlar]} and cy)]
        if bas:
            tip.append("Basında tanker olarak adı geçiyor")
        dogru = bool(tip)
        # GFW sınıfı: seferlerdeki ve Ceyhan uğraklarındaki gemi tipi (çoğunluk)
        sinif = Counter([r["tip"] for r in rs if r["id"].startswith("g") and r.get("tip") and r["tip"] != "Tanker (AIS)"]
                        + [x["tip"] for x in cy if x.get("tip")])
        gfw_tip = sinif.most_common(1)[0][0] if sinif else None
        if not dogru and gfw_tip not in GFW_TANKER_SINIFI:
            dislanan += 1
            continue
        if not dogru:
            tip.append("Global Fishing Watch kargo gemisi saymıyor; tankerler bu sınıfta (doğrulanmadı)")
        seferler = []
        for r in rs:
            dz = SINIF_DUZEY[r["k"]]
            seferler.append({**r, "duzey": dz})
        say = Counter(s["duzey"] for s in seferler)
        best = min(say, key=lambda k: SIRA[k])
        d = {"ad": ad, "adlar": adlar, "mmsi": mmsi, "imo": imo, "vid": ek.get("vid"), "cagri": ek.get("cagri"),
             "bayrak": bayrak(flag, mmsi), "flag3": flag, "firma": ek.get("firma") or [], "foto": ek.get("foto") or [],
             "tip": tip, "dogrulandi": dogru, "gfw_tip": gfw_tip, "seferler": seferler, "say": say, "duzey": best,
             "ceyhan": cy, "basin": bas,
             "ilk": min((s.get("t0") or s.get("t1") or "") for s in seferler),
             "son": max((s.get("t0") or s.get("t1") or "") for s in seferler)}
        d["anahtar"] = anahtar(d)
        out.append(d)
    # aynı anahtar iki kez çıkmasın (aynı IMO, farklı MMSI)
    gor_a: Counter = Counter()
    for d in out:
        gor_a[d["anahtar"]] += 1
        if gor_a[d["anahtar"]] > 1:
            d["anahtar"] += f"-{gor_a[d['anahtar']]}"
    out.sort(key=lambda d: (SIRA[d["duzey"]], not d["dogrulandi"], -len(d["seferler"]), -_ts(d["son"])))
    return out, dislanan


def _ts(s: str) -> float:
    try:
        return parse_iso(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


# --------------------------------------------------------------------------- metin
def adimlar(cfg, r: dict) -> list[tuple[str | None, str, str]]:
    """Bir seferin seyir defteri satırları: (zaman, metin, tür)."""
    out = [(r.get("t0"), f"{cikis_adi(cfg, r)} çıkışı" + (f" ({r['ter']})" if r.get("ter") else ""), "cikis")]
    ats = r.get("at") or []
    for i, x in enumerate(r.get("ara") or []):
        at = ats[i] if i < len(ats) and ats[i] else [None, None]
        sure = ""
        if at and at[0] and at[1]:
            h = hours_between(at[0], at[1])
            sure = f", {round(h / 24)} gün kaldı" if h >= 48 else f", {max(1, round(h))} saat kaldı"
        out.append((at[0], f"Ara liman: {x}{sure}", "ara"))
    for s in r.get("sts") or []:
        out.append((s[2], "Denizde başka bir gemiyle yan yana" + (f", {_sayi(s[4])} saat" if s[4] else ""), "sts"))
    for k in r.get("kp") or []:
        lon0, lat0, lon1, lat1, saat, t0, t1 = (list(k) + [None] * 7)[:7]
        il0, il1 = cfg.in_dest_offshore(lat0, lon0), cfg.in_dest_offshore(lat1, lon1)
        out.append((t0, f"AIS sinyali kesildi: {yer(cfg, lat0, lon0)} ({koordinat(lat0, lon0)})", "kapandi-il" if il0 else "kapandi"))
        out.append((t1, f"AIS sinyali yeniden geldi: {yer(cfg, lat1, lon1)} ({koordinat(lat1, lon1)})"
                    + (f", {_sayi(saat)} saat sonra" if saat else ""), "acildi-il" if il1 else "acildi"))
    if r["k"] == "kiyida_bosaltma":
        out.append((r.get("t1"), f"{r.get('d')}", "bekleme"))
    elif r["k"] == "kiyida_kayboldu":
        out.append((r.get("t1"), f"{r.get('d') or 'Kıyı alanı'}: sinyal kesildi, hiçbir limanda kaydı yok", "kapandi-il"))
    elif r["k"] == "karanlik_acik":
        pass  # boşluk satırları yeterli
    elif r.get("d"):
        out.append((r.get("t1"), f"Varış: {r['d']}", "varis"))
    else:
        out.append((None, "Varış limanı kayıtsız", "bilinmez"))
    if r.get("sl") and r["k"] in ("karanlik_acik", "karanlik_sefer", "kiyida_bosaltma"):
        out.append((None, f"Sonraki kayıtlı liman: {r['sl']}", "sonraki"))
    return out


def ozet(cfg, r: dict) -> str:
    """Seferin tek cümlelik özeti."""
    ham = r.get("o") or ""
    o = cikis_adi(cfg, r, kisa=True)
    if ham.endswith(" limanı") or "adsız demirleme" in ham:
        o = f"adsız demirleme yeri ({o})"
    t = gun(cfg, r.get("t0"))
    kp = r.get("kp") or []
    if r["k"] == "karanlik_acik" and kp:
        k = kp[0]
        il1 = cfg.in_dest_offshore(k[3], k[2])
        nokta = yer(cfg, k[3], k[2]) if il1 else yer(cfg, k[1], k[0])
        ne = "yeniden geldi" if il1 else "kesildi"
        return f"{t}: {o} çıkışı. AIS {_sayi(k[4] or 0)} saat kapalı; sinyal {nokta} {ne}."
    if r["k"] == "kiyida_bosaltma":
        return f"{t}: {o} çıkışı. {gun(cfg, r.get('t1'))}: {r.get('d')}."
    if r["k"] == "karanlik_sefer":
        h = sum((k[4] or 0) for k in kp)
        return f"{t}: {o} çıkışı. Yolda {_sayi(h)} saat AIS kapalı; varış limanı kayıtsız."
    via = f", ara liman {', '.join(r['ara'])}" if r.get("ara") else ""
    ais = f", yolda AIS {_sayi(sum((k[4] or 0) for k in kp))} saat kapalı" if kp else ""
    return f"{t}: {o} çıkışı{via}{ais}. {gun(cfg, r.get('t1'))}: varış {r.get('d') or 'kayıtsız'}."


def paylasim(cfg, d: dict, url: str) -> str:
    """X'te paylaşılabilecek metin (280 karakter; bağlantı 23 sayılır)."""
    r = min(d["seferler"], key=lambda s: (SIRA[s["duzey"]], -_ts(s.get("t0") or "")))
    kim = ", ".join(filter(None, [f"{d['bayrak']} bayraklı" if d["bayrak"] else None,
                                  "tanker" if d["dogrulandi"] else None, f"IMO {d['imo']}" if d["imo"] else None]))
    satir = [f"{d['ad']}" + (f" ({kim})" if kim else "")]
    satir.append(f"Çıkış: {cikis_adi(cfg, r, kisa=True)}, {gun(cfg, r.get('t0'))}")
    kp = r.get("kp") or []
    if kp:
        k = kp[0]
        satir.append(f"AIS kesildi: {gun(cfg, k[5], yil=False)}, {yer(cfg, k[1], k[0])}")
        satir.append(f"AIS geldi: {gun(cfg, k[6], yil=False)}, {yer(cfg, k[3], k[2])}")
    if r["k"] == "kiyida_bosaltma":
        satir.append(f"{gun(cfg, r.get('t1'), yil=False)}: İsrail kıyı açığında limana girmeden bekledi")
    elif r.get("d") and r["k"] not in ("karanlik_acik",):
        satir.append(f"Varış: {kisa_ad(r['d'])}, {gun(cfg, r.get('t1'), yil=False)}")
    elif not r.get("d"):
        satir.append("Varış limanı kayıtsız")
    n = len(d["seferler"])
    if n > 1:
        satir.append(f"Toplam {n} sefer ({aralik(cfg, d['ilk'], d['son'])})")
    son = "Veri: Global Fishing Watch. Tespit, hüküm değil."

    def uzunluk(xs):
        return len("\n".join(xs + [son])) + 1 + 23

    while uzunluk(satir) > 280 and len(satir) > 2:
        satir.pop()  # en sondaki ayrıntıdan başlayarak kısalt
    return "\n".join(satir + [son, url])


# --------------------------------------------------------------------------- sayfalar
def _serit(cfg, E, r: dict) -> str:
    """Seferin zaman şeridi: çıkıştan varışa; AIS'in kapalı olduğu aralıklar macenta."""
    t0 = r.get("t0")
    son = [x for x in [r.get("t1")] + [k[6] for k in r.get("kp") or [] if len(k) > 6] if x]
    t1 = max(son) if son else None
    if not t0 or not t1 or t1 <= t0:
        return ""
    T0, T1 = _ts(t0), _ts(t1)
    w = max(T1 - T0, 1)
    parca = []
    for k in r.get("kp") or []:
        if len(k) < 7 or not k[5] or not k[6]:
            continue
        a = max(0.0, (_ts(k[5]) - T0) / w * 100)
        b = min(100.0, (_ts(k[6]) - T0) / w * 100)
        il = cfg.in_dest_offshore(k[3], k[2]) or cfg.in_dest_offshore(k[1], k[0])
        parca.append(f'<span class="kapali{" il" if il else ""}" style="left:{a:.2f}%;width:{max(b - a, 0.8):.2f}%">'
                     f'<small>{_sayi(k[4] or 0, 0)} sa</small></span>')
    for i, at in enumerate(r.get("at") or []):
        if at and at[0]:
            a = (_ts(at[0]) - T0) / w * 100
            parca.append(f'<span class="ara" style="left:{min(max(a, 0), 100):.2f}%" title="{E((r.get("ara") or [""])[i] if i < len(r.get("ara") or []) else "")}"></span>')
    gun_say = (T1 - T0) / 86400
    etiket = f"{gun(cfg, t0)} – {gun(cfg, t1)}, {_sayi(gun_say)} gün"
    son_ad = "Varış" if r.get("d") and r["k"] not in ("karanlik_acik", "kiyida_bosaltma") else "Son kayıt"
    return (f'<div class="serit-kutu"><div class="serit" role="img" aria-label="{E(etiket)}">'
            f'<span class="cizgi"></span>{"".join(parca)}<span class="uc bas"></span><span class="uc son"></span></div>'
            f'<div class="serit-alt"><span>Çıkış, {E(gun(cfg, t0, yil=False))}</span>'
            f'<span>{_sayi(gun_say)} gün</span><span>{E(son_ad)}, {E(gun(cfg, t1, yil=False))}</span></div></div>')


def _rozet(E, dz: str) -> str:
    return f'<span class="rozet" style="--c:var(--c-{AILE[dz]})">{E(AD[dz])}</span>'


SAYIM = {"kayitli": "kayıtlı varış", "aktarma": "üçüncü ülke limanı üzerinden", "acik": "AIS İsrail açıklarında kapalı",
         "bekleme": "İsrail kıyı açığında bekleme", "sts": "gemiden gemiye", "karanlik": "AIS uzun süre kapalı"}


def _sayim(E, say: Counter) -> str:
    return ", ".join(f"{say[k]} {E(SAYIM[k])}" for k in sorted(say, key=lambda k: SIRA[k]))


def aralik(cfg, a: str | None, b: str | None) -> str:
    """"2 Şub – 2 Mar 2025"; yıllar farklıysa ikisi de yıllı."""
    if not a or not b or a[:10] == b[:10]:
        return gun(cfg, a or b)
    return f"{gun(cfg, a, yil=a[:4] != b[:4])} – {gun(cfg, b)}"


def _uydu_satiri(cfg, E, r: dict) -> str:
    """Sinyalin kesildiği aralık için uydu görüntüsü bağlantıları: AIS'in İsrail açığında kesildiği/geldiği nokta ve
    Aşkelon'daki EAPC şamandıraları."""
    yerler = []
    for k in r.get("kp") or []:
        if len(k) < 7 or not k[5] or not k[6]:
            continue
        for la, lo, ad in ((k[1], k[0], "Sinyalin kesildiği nokta"), (k[3], k[2], "Sinyalin geldiği nokta")):
            if la is not None:
                yerler.append((ad, la, lo, k[5], k[6]))
        for p in cfg.ports:
            for t in p.terminals:
                if p.country in cfg.dest_countries() and t.cargo == "sivi_dokme":
                    yerler.append((f"{kisa_ad(p.name)}, {t.name}", *t.area.center, k[5], k[6]))
        break
    if r["k"] == "kiyida_bosaltma" and r.get("w") and r.get("t1"):
        lon, lat = r["w"][-1]
        yerler.append(("Bekleme alanı", lat, lon, r["t1"], add_hours(r["t1"], 72)))
        for p in cfg.ports:
            for t in p.terminals:
                if p.country in cfg.dest_countries() and t.cargo == "sivi_dokme":
                    yerler.append((f"{kisa_ad(p.name)}, {t.name}", *t.area.center, r["t1"], add_hours(r["t1"], 72)))
    if not yerler:
        return ""
    li = "".join(f'<li><span>{E(ad)}</span> <a href="{E(uydu(la, lo, a, b, True))}" target="_blank" rel="noopener">Radar</a> '
                 f'<a href="{E(uydu(la, lo, a, b, False))}" target="_blank" rel="noopener">Optik</a></li>'
                 for ad, la, lo, a, b in yerler)
    return (f'<div class="uydu-linkleri"><p class="not">Uydu görüntüsü, {E(gun(cfg, yerler[0][3]))} – {E(gun(cfg, yerler[0][4]))} '
            f'(Copernicus Sentinel-1 radar buluttan etkilenmez; Sentinel-2 optik bulutsuz günde işe yarar):</p><ul>{li}</ul></div>')


def _sefer_blok(cfg, E, directions, r: dict) -> str:
    from .rapor import _harita_link
    ad = "".join(f'<li class="{c}"><time>{E(gun(cfg, t, saat=True)) if t else ""}</time><span>{E(x)}</span></li>'
                 for t, x, c in adimlar(cfg, r))
    onu = '<span class="on-not">Ticaret durdurma beyanından önce</span>' if r.get("on") else ""
    harita_l = f'<a href="{_harita_link(directions, r)}">Haritada</a>' if r["id"][0] in "cg" else ""
    return (f'<article class="sefer-kayit" id="{E(r["id"])}"><header>{_rozet(E, r["duzey"])}{onu}'
            f'<h3>{E(gun(cfg, r.get("t0")))}, {E(cikis_adi(cfg, r, kisa=True))}</h3>{harita_l}</header>'
            f'{_serit(cfg, E, r)}<ol class="defter">{ad}</ol>{_uydu_satiri(cfg, E, r)}</article>')


def _ceyhan_tablo(cfg, E, d: dict) -> str:
    from .site import _tbl
    if not d["ceyhan"]:
        return ""
    t0s = {s.get("t0") for s in d["seferler"]}
    rows = []
    for x in d["ceyhan"]:
        kal = ""
        if x.get("t0") and x.get("t"):
            kal = _sayi(hours_between(x["t0"], x["t"]), 0)
        son = ", ".join(f'{w["ad"]} ({gun(cfg, w["giris"], yil=False)})' for w in (x.get("sonrakiler") or [])[:3]) \
            or (x.get("sonraki") or "kayıt yok")
        bos = "; ".join(f'{_sayi(g["saat"], 0)} sa' + (" (İsrail açığı)" if g.get("il") else "") for g in x.get("bosluk") or [])
        bek = "; ".join(f'{_sayi(e["saat"], 0)} sa' for e in x.get("acik") or [])
        rows.append([f'<span class="tarih">{E(gun(cfg, x.get("t0")))}</span>', f'<span class="tarih">{E(gun(cfg, x.get("t")))}</span>',
                     kal, E(son), f'<span class="uyari">{E(bos)}</span>' if bos else "–",
                     f'<span class="uyari">{E(bek)}</span>' if bek else "–",
                     "evet" if x.get("t") in t0s else ""])
    return ('<h2>Ceyhan uğrakları</h2><p class="not">Geminin Ceyhan terminallerinin önündeki demirleme alanına (11 km) bütün '
            'uğrakları ve her birinden sonra olanlar. Son sütun, uğrağın yukarıdaki seferlerden biri olup olmadığını gösterir.</p>'
            + _tbl(["Giriş", "Çıkış", "Kalış (saat)", "Sonraki uğraklar", "Yolda AIS boşluğu", "İsrail açığında bekleme",
                    "Seferlerde"], rows, num=(2,)))


def _kimlik(E, d: dict) -> str:
    from .rapor import _kunye
    satir = [("Bayrak", d["bayrak"] or "bilinmiyor"), ("IMO", d["imo"] or "bilinmiyor"), ("MMSI", d["mmsi"] or "bilinmiyor"),
             ("Çağrı işareti", d.get("cagri") or "bilinmiyor"),
             ("Tip", "; ".join(d["tip"]) if d["tip"] else "Doğrulanmadı")]
    if d["adlar"]:
        satir.append(("Önceki adları", ", ".join(d["adlar"])))
    dl = "".join(f'<div{" class=genis" if k in ("Tip", "Önceki adları") else ""}><dt>{E(k)}</dt><dd>{E(v)}</dd></div>'
                 for k, v in satir)
    return f'<dl class="kimlik-tablo">{dl}</dl>{_kunye(E, d)}'


def _basin_blok(E, d: dict) -> str:
    if not d["basin"]:
        return ""
    li = "".join(f'<li><a href="{E(b["url"])}" rel="noopener">{E(b.get("kaynak") or "Haber")}'
                 f'{", " + E(str(b["tarih"])) if b.get("tarih") else ""}</a>: {E(b.get("ozet") or b.get("baslik") or "")}</li>'
                 for b in d["basin"] if b.get("url"))
    return (f'<h2>Basında</h2><p class="not">Bu gemi aşağıdaki haberlerde de adı geçiyor. Haberdeki bilgi bu sitenin verisi '
            f'değildir; sitenin tespitiyle karşılaştırmak için verilir.</p><ul class="basin">{li}</ul>')


def _basin_sagla(cfg, E, con, ds: list[dict]) -> str:
    """Basında adı geçen tankerler bu sitenin verisinde nasıl görünüyor? (sağlama tablosu)"""
    from .db import get_meta
    from .site import _tbl
    adlar = []
    for b in _basin(cfg):
        a = str(b.get("ad") or "").upper().strip()
        if a and a not in adlar:
            adlar.append(a)
    if not adlar:
        return ""
    cik = json.loads(get_meta(con, "ceyhan_cikislari", "[]") or "[]")
    # geçmişi henüz alınmamış gemiler: İskenderun Körfezi alan sorgularındaki Ceyhan uğrakları
    from .gecmis import CEYHAN, CEYHAN_KM
    alan: dict[str, set] = defaultdict(set)
    kod = cfg.locate(*CEYHAN)[0] or "%"
    for (data,) in con.execute("SELECT data FROM gfw_cache WHERE key LIKE ?", (f"area_pv:{kod}:%",)):
        try:
            evs = json.loads(data) or []
        except ValueError:
            continue
        for e in evs:
            ad_ = str((e.get("vessel") or {}).get("name") or "").upper().strip()
            pos = e.get("position") or {}
            if ad_ in adlar and pos.get("lat") is not None and e.get("start") and \
                    haversine_km(pos["lat"], pos["lon"], *CEYHAN) <= CEYHAN_KM:
                alan[ad_].add(e["start"][:19] + "Z" if len(e["start"]) >= 19 else e["start"])
    alan = {k: sorted(v) for k, v in alan.items()}
    dosya = {}
    for d in ds:
        for n in [d["ad"], *d["adlar"]]:
            dosya.setdefault((n or "").upper(), d)
    rows = []
    for a in adlar:
        xs = [x for x in cik if (x.get("ad") or "").upper().strip() == a]
        d = dosya.get(a)
        if not xs and not d:
            g = alan.get(a) or []
            rows.append([f"<b>{E(a)}</b>", (f"{len(g)} uğrak" + (f' <span class="not tarih">({E(aralik(cfg, g[0], g[-1]))})</span>'
                                                                  if g else "") if g else "kayıt yok")
                         + '<br><span class="not">geçmişi taranıyor</span>', "–", "–", "–"])
            continue
        il_liman = sum(1 for x in xs if x.get("ulke") in cfg.dest_countries())
        il_acik = sum(1 for x in xs if any(g.get("il") for g in x.get("bosluk") or []))
        bekle = sum(1 for x in xs if x.get("acik"))
        ts = sorted(x["t"] for x in xs if x.get("t"))
        ad_h = f'<a href="{E(d["anahtar"])}.html"><b>{E(a)}</b></a>' if d else f"<b>{E(a)}</b>"
        rows.append([ad_h, f"{len(xs)} çıkış" + (f' <span class="not tarih">({E(aralik(cfg, ts[0], ts[-1]))})</span>' if ts else ""),
                     str(il_liman), f'<span class="uyari">{il_acik}</span>' if il_acik else "0", str(bekle)])
    return ('<h2>Basında adı geçen tankerler bu veride</h2><p class="not">Haberlerde Ceyhan’dan İsrail’e petrol taşıdığı '
            'yazılan tankerler ve bu sitenin Global Fishing Watch verisinde gördükleri. Haberdeki bilgiler gemi '
            'dosyalarında “Basında” başlığında, kaynağıyla.</p>'
            + _tbl(["Gemi", "Ceyhan’dan", "Sonraki uğrak İsrail", "AIS İsrail açıklarında kesik", "İsrail açığında bekleme"],
                   rows, num=(2, 3, 4)))


def _paylas_blok(E, metin: str, url: str) -> str:
    x = "https://x.com/intent/post?" + urlencode({"text": metin})
    return (f'<h2>Paylaş</h2><div class="paylas"><textarea readonly rows="8" aria-label="Paylaşım metni">{E(metin)}</textarea>'
            f'<p class="dugme-sira"><button type="button" class="kopyala" data-metin="{E(metin)}">Metni kopyala</button>'
            f'<a class="dugme" href="{E(x)}" target="_blank" rel="noopener">X’te paylaş</a>'
            f'<a class="dugme" href="{E(url)}">Kalıcı bağlantı</a></p></div>')


KOPYALA = ('<script>document.addEventListener("click",function(e){var b=e.target.closest(".kopyala");if(!b)return;'
           'var t=b.dataset.metin;(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){'
           'b.textContent="Kopyalandı"},function(){var a=b.closest(".paylas").querySelector("textarea");a.select();'
           'b.textContent="Seçildi, Ctrl+C ile kopyala"});setTimeout(function(){b.textContent="Metni kopyala"},2500)});</script>')

SUZGEC = '''<script>(function(){
var l=document.getElementById("dosya-liste");if(!l)return;var k=[].slice.call(l.querySelectorAll(".dosya")),
a=document.getElementById("dosya-ara"),o=document.getElementById("dosya-say"),t=document.getElementById("yalniz-tanker"),s="",z;
function g(){var q=a.value.trim().toLocaleLowerCase("tr"),n=0;k.forEach(function(d){var u=(!q||d.dataset.ara.indexOf(q)>=0)
&&(!s||(" "+d.dataset.duzey+" ").indexOf(" "+s+" ")>=0)&&(!t.checked||d.dataset.tip==="1");d.hidden=!u;if(u)n++});
o.textContent=n+" gemi";}
a.addEventListener("input",function(){clearTimeout(z);z=setTimeout(g,120)});t.addEventListener("change",g);
document.querySelectorAll("[data-duzey-sec]").forEach(function(b){b.addEventListener("click",function(){
s=b.dataset.duzeySec;document.querySelectorAll("[data-duzey-sec]").forEach(function(x){x.setAttribute("aria-pressed",String(x===b))});g()})});
g()})();</script>'''


def _kart(cfg, E, d: dict) -> str:
    r = min(d["seferler"], key=lambda s: (SIRA[s["duzey"]], -_ts(s.get("t0") or "")))
    kim = ", ".join(filter(None, [f"{d['bayrak']} bayraklı" if d["bayrak"] else None, f"IMO {d['imo']}" if d["imo"] else None,
                                  f"MMSI {d['mmsi']}" if d["mmsi"] else None]))
    firma = d["firma"][0]["ad"] if d["firma"] else None
    ara = " ".join(filter(None, [d["ad"], *d["adlar"], str(d["mmsi"] or ""), str(d["imo"] or ""), d["bayrak"],
                                 *[f["ad"] for f in d["firma"]], *[s.get("o") or "" for s in d["seferler"]],
                                 *[s.get("d") or "" for s in d["seferler"]]])).lower()
    tip = ('<span class="tip-dogru">Tanker</span>' if d["dogrulandi"]
           else '<span class="tip-belirsiz">Muhtemel tanker</span>')
    basin = '<span class="basin-isaret">Basında adı geçiyor</span>' if d["basin"] else ""
    return (f'<article class="dosya" id="{E(d["anahtar"])}" data-duzey="{E(" ".join(sorted(d["say"])))}" '
            f'data-tip="{1 if d["dogrulandi"] else 0}" data-ara="{E(ara)}">'
            f'<header><h2><a href="{E(d["anahtar"])}.html">{E(d["ad"])}</a></h2>{_rozet(E, d["duzey"])}</header>'
            f'<p class="kim">{E(kim)}</p>'
            f'<p class="etiketler">{tip}{basin}{f"<span>{E(firma)}</span>" if firma else ""}</p>'
            f'<p class="say"><b>{len(d["seferler"])} sefer</b>: {_sayim(E, d["say"])}. '
            f'{E(aralik(cfg, d["ilk"], d["son"]))}.</p>'
            f'{_serit(cfg, E, r)}<p class="ozet">{E(ozet(cfg, r))}</p>'
            f'<p class="baglantilar"><a href="{E(d["anahtar"])}.html">Dosyayı aç</a></p></article>')


def build(cfg, con, recs: list[dict], out: Path) -> list[dict]:
    from .rapor import _csv
    from .site import E as _E, _n, _page, _write

    def E(x) -> str:
        return _E("" if x is None else str(x))

    tdir = out / "tankerler"
    if tdir.exists():
        for f in tdir.iterdir():
            if f.is_file():
                f.unlink()
    ds, dislanan = dosyalar(cfg, con, recs)
    directions = [f"{a}>{b}" for a, b in cfg.directions]
    adres = (cfg.pub.get("adres") or "").rstrip("/")
    b_ad = ", ".join(cfg.country_name(c) for c in sorted(cfg.dest_countries()))
    yol = '<p class="yol"><a href="../raporlar/index.html">Raporlar</a>, Tanker dosyaları</p>'
    not_ = ('<p class="not son-not">Kayıtlar Global Fishing Watch’ın liman ziyareti, AIS boşluğu ve AIS varlık verisinden '
            '(Powered by Global Fishing Watch) ve bu sitenin canlı AIS kaydından üretilir. Gemi hareketini gösterir; yükü, '
            'yükün sahibini ve ticaretin tarafını göstermez. Her kayıt bir tespittir, hüküm değildir. Kurallar: '
            '<a href="../yontem.html">Yöntem</a>.</p>')
    # her gemi için ayrı sayfa
    for d in ds:
        url = f"{adres}/tankerler/{d['anahtar']}.html" if adres else f"tankerler/{d['anahtar']}.html"
        d["paylasim"] = paylasim(cfg, d, url)
        bloklar = "".join(_sefer_blok(cfg, E, directions, r) for r in d["seferler"])
        govde = (f'<main class="sayfa rapor tanker-dosya" id="icerik"><header><p class="yol"><a href="../raporlar/index.html">Raporlar</a>, '
                 f'<a href="index.html">Tanker dosyaları</a></p><h1>{E(d["ad"])}</h1>'
                 f'<p class="giris">{_rozet(E, d["duzey"])} {len(d["seferler"])} sefer: {_sayim(E, d["say"])}. '
                 f'{E(aralik(cfg, d["ilk"], d["son"]))}.</p></header>'
                 f'{_kimlik(E, d)}<h2>Seferler</h2><p class="not">En yeni sefer en üstte. Saatler {E(cfg.tz)} saatiyle. '
                 f'Kesik macenta şerit AIS sinyalinin kesildiği aralıktır; düz macenta şerit, sinyalin İsrail açıklarında kesildiği '
                 f'ya da yeniden geldiği aralıktır.</p>'
                 f'{bloklar}{_ceyhan_tablo(cfg, E, d)}{_basin_blok(E, d)}{_paylas_blok(E, d["paylasim"], url)}{not_}</main>{KOPYALA}')
        _write(tdir / f"{d['anahtar']}.html", _page(cfg, f"{d['ad']}: tanker dosyası", govde, 1, "tankerler",
                                                    desc=d["paylasim"].split("\n")[0] + ". " + ozet(cfg, d["seferler"][0])))
    # liste
    say = Counter(dz for d in ds for dz in d["say"])
    sefer_say = Counter(s["duzey"] for d in ds for s in d["seferler"])
    n_sefer = sum(len(d["seferler"]) for d in ds)
    ceyhan_say = sum(1 for d in ds if any((s.get("ter") or "").startswith("Ceyhan") for s in d["seferler"]))
    dugme = ['<button type="button" data-duzey-sec="" aria-pressed="true">Hepsi</button>'] + [
        f'<button type="button" data-duzey-sec="{k}" aria-pressed="false" style="--c:var(--c-{AILE[k]})">{E(AD[k])} '
        f'<small>{say[k]}</small></button>' for k, *_x in DUZEYLER if say.get(k)]
    tanim = "".join(f'<div style="--c:var(--c-{f})"><dt>{E(a)}</dt><dd>{E(acik)} <b>{_n(sefer_say.get(k, 0))} sefer</b></dd></div>'
                    for k, a, acik, f in DUZEYLER if sefer_say.get(k))
    if ds:
        giris = (f'<p class="giris">7 Ekim 2023’ten bu yana Türk petrol iskelelerinden, çoğu Ceyhan’daki BTC ve Kerkük-Ceyhan '
                 f'terminallerinden çıkıp {E(b_ad)}’e giden ya da {E(b_ad)} açıklarında AIS’i kapalı görülen '
                 f'<b>{_n(len(ds))} gemi, {_n(n_sefer)} sefer</b>. {_n(ceyhan_say)} gemi Ceyhan’dan. Liste en güçlü kanıttan '
                 'en zayıfa sıralı.</p>'
                 + (f'<p class="not">Ceyhan körfezinden İsrail’e giden ama Global Fishing Watch’ın kargo gemisi saydığı ve '
                    f'başka tanker kanıtı olmayan {_n(dislanan)} gemi (kömür, gübre, çimento gemileri olabilir) bu listede '
                    'yok; onların seferleri <a href="../raporlar/index.html">Raporlar</a>’da.</p>' if dislanan else ""))
        liste = (f'<div class="arac"><label class="ara"><span class="gizli">Gemi ara</span><input type="search" id="dosya-ara" '
                 f'placeholder="Gemi adı, IMO, bayrak, firma ya da liman" autocomplete="off"></label>'
                 f'<label class="tik"><input type="checkbox" id="yalniz-tanker"> Yalnızca tipi doğrulananlar</label>'
                 f'<output id="dosya-say"></output></div><div class="dugmeler duzeyler" role="group" aria-label="Kanıt türü">'
                 f'{"".join(dugme)}</div><div id="dosya-liste" class="dosya-liste">'
                 + "".join(_kart(cfg, E, d) for d in ds) + "</div>" + SUZGEC)
    else:
        giris = ('<p class="giris">Henüz tanker dosyası yok. Geçmiş tarama Ceyhan’a uğrayan gemilerin geçmişini aldıkça '
                 'dosyalar burada görünür.</p>')
        liste = ""
    from .db import get_meta
    durum = json.loads(get_meta(con, "gecmis_durum", "{}") or "{}")
    ilerleme = ""
    if durum.get("gorev") and not durum.get("tamam"):
        a_, b_ = durum["gorev"]
        ilerleme = (f'<p class="not">Geçmiş tarama sürüyor ({_n(a_)} / {_n(b_)} sorgu); liste her saat uzar. '
                    f'Ceyhan’a uğrayan gemilerin geçmişi öncelikli alınıyor.</p>')
    govde = (f'<main class="sayfa rapor tankerler" id="icerik"><header>{yol}<h1>Tanker dosyaları</h1>{giris}{ilerleme}</header>'
             + _basin_sagla(cfg, E, con, ds)
             + (f'<dl class="duzey-tanim">{tanim}</dl>' if tanim else "") + liste
             + (f'<p class="not">İndir: <a href="tankerler.csv">tankerler.csv</a> (sefer sefer), '
                f'<a href="../veri/tankerler.json">tankerler.json</a></p>' if ds else "") + not_ + "</main>")
    _write(tdir / "index.html", _page(cfg, "Tanker dosyaları", govde, 1, "tankerler",
                                      desc=f"Türk petrol iskelelerinden {b_ad}’e giden {len(ds)} tanker ve kanıtları."))
    # tablo ve JSON
    rows = [["Gemi", "IMO", "MMSI", "Bayrak", "Firma", "Tip", "Kanıt", "Çıkış", "Çıkış zamanı (UTC)", "Ara limanlar",
             "Varış ya da son kayıt", "Zaman (UTC)", "AIS kapalı (saat)", "Sinyal kesildi (enlem, boylam)",
             "Sinyal geldi (enlem, boylam)", "Sonraki liman", "Kayıt", "Dosya"]]
    for d in ds:
        for r in d["seferler"]:
            kp = r.get("kp") or []
            rows.append([d["ad"], d["imo"] or "", d["mmsi"] or "", d["bayrak"], "; ".join(f["ad"] for f in d["firma"]),
                         "; ".join(d["tip"]) or "doğrulanmadı", AD[r["duzey"]], r.get("o") or "", r.get("t0") or "",
                         ", ".join(r.get("ara") or []), r.get("d") or "", r.get("t1") or "",
                         _sayi(sum((k[4] or 0) for k in kp)) if kp else "",
                         "; ".join(f"{k[1]}, {k[0]}" for k in kp), "; ".join(f"{k[3]}, {k[2]}" for k in kp),
                         r.get("sl") or "", r["id"], f"{adres}/tankerler/{d['anahtar']}.html" if adres else d["anahtar"]])
    (tdir / "tankerler.csv").write_bytes(_csv(rows))
    veri = [{"gemi": d["ad"], "imo": d["imo"], "mmsi": d["mmsi"], "bayrak": d["bayrak"], "gfw": d["vid"],
             "firma": [f["ad"] for f in d["firma"]], "tip": d["tip"], "kanit": d["duzey"], "dosya": d["anahtar"],
             "basin": [b.get("url") for b in d["basin"]],
             "seferler": [{"id": r["id"], "kanit": r["duzey"], "sinif": r["k"], "cikis": r.get("o"), "t0": r.get("t0"),
                           "ara": r.get("ara") or [], "varis": r.get("d"), "t1": r.get("t1"), "ais_kapali": r.get("kp") or [],
                           "sonraki": r.get("sl"), "beyandan_once": bool(r.get("on"))} for r in d["seferler"]]}
            for d in ds]
    _write(out / "veri" / "tankerler.json", json.dumps(veri, ensure_ascii=False))
    return ds
