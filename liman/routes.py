"""Beyan testi: A ülkesi limanlarından B ülkesi limanlarına doğrudan ve dolaylı gemi hareketleri.

Her bacak kurala dayalı olarak sınıflandırılır (kurallar yontem sayfasında yayımlanır):
  denizde_aktarma         bacak sırasında açık denizde başka gemiyle buluşma (STS)
  karanlik_bacak          bacak sırasında açık denizde AIS boşluğu
  aktarmali               arada başka limana veya liman dışı uzun durağa uğradı
  dogrudan                kesintisiz izlendi, arada durak yok
  dogrudan_izlenmedi      A'dan çıkış ve B'ye varış kayıtlı, ara güzergâh izlenemedi
  dolayli_sts             A'dan çıkan gemi denizde yükünü başka gemiye verdi, o gemi B'ye vardı
  kiyida_kayboldu         B kıyısındaki yaklaşma alanına girdi, liman kaydı yok, ardından uzun sessizlik
  karanlik_sefer          A'dan çıktı, B'de hiçbir kaydı yok, ama açık denizde (karanlık bölgede) uzun AIS
                          boşluğu var; boşluktan sonra su çekimi düştüyse yük boşaltılmış olabilir
Ek işaret: masked = AIS'te beyan edilen varış noktası B ülkesini göstermiyordu.
"""
from __future__ import annotations

import json
from collections import defaultdict

from .cargo import infer
from .db import get_meta
from .util import add_hours, hours_between

CLASS_LABELS = {
    "dogrudan": "Doğrudan",
    "dogrudan_izlenmedi": "Doğrudan (ara güzergâh izlenemedi)",
    "aktarmali": "Ara duraklı",
    "karanlik_bacak": "Karanlık bacak (AIS boşluğu)",
    "denizde_aktarma": "Denizde buluşma (olası aktarma)",
    "dolayli_sts": "Dolaylı: denizde gemiden gemiye",
    "kiyida_kayboldu": "Hedef ülke kıyısında AIS kapandı",
    "karanlik_sefer": "Karanlık sefer (varış limanı kayıtsız)",
}
CLASS_ORDER = list(CLASS_LABELS)
CLASS_SHORT = {"dogrudan": "Doğrudan", "dogrudan_izlenmedi": "Doğrudan*", "aktarmali": "Ara duraklı",
               "karanlik_bacak": "Karanlık", "denizde_aktarma": "Denizde buluşma", "dolayli_sts": "Dolaylı",
               "kiyida_kayboldu": "Kıyıda kayıp", "karanlik_sefer": "Karanlık sefer"}


def vessel_keys(con) -> tuple[dict, dict]:
    """mmsi → anahtar (IMO varsa 'imo:...' yoksa 'mmsi:...') ve anahtar → mmsi listesi."""
    m2k, k2m = {}, defaultdict(list)
    for r in con.execute("SELECT mmsi, imo FROM vessels"):
        k = f"imo{r['imo']}" if r["imo"] else f"mmsi{r['mmsi']}"
        m2k[r["mmsi"]] = k
        k2m[k].append(r["mmsi"])
    return m2k, k2m


def compute(cfg, con) -> int:
    con.execute("DELETE FROM routes")
    if not cfg.directions:
        con.commit()
        return 0
    th = cfg.th
    max_h = th["guzergah_max_gun"] * 24
    quiet_h = th["yaklasma_sessizlik_saat"]
    latest = get_meta(con, "visit_latest_t", "") or ""
    m2k, k2m = vessel_keys(con)
    country = {p.code: p.country for p in cfg.ports}
    approach = {p.code for p in cfg.ports if p.approach}
    vessels = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM vessels")}
    by_key = defaultdict(list)
    for v in con.execute("SELECT * FROM visits ORDER BY t_in"):
        v = dict(v)
        if v["port"] not in country:
            continue  # liman ayardan çıkarılmış
        if v["port"] in approach:
            # Kıyı yaklaşma alanı: durduysa varış sayılır; durmadan geçtiyse ancak ardından uzun sessizlik varsa
            if v["status"] != "closed":
                continue
            if v["transit"]:
                nxt = con.execute("SELECT t FROM positions WHERE mmsi=? AND t>? ORDER BY t LIMIT 1",
                                  (v["mmsi"], v["last_in"])).fetchone()
                until = nxt["t"] if nxt else latest
                if not until or hours_between(v["last_in"], until) < quiet_h:
                    continue
                v["_kayip"] = True
                v["_sessizlik_saat"] = round(hours_between(v["last_in"], until), 1)
        elif v["transit"]:
            continue
        by_key[m2k.get(v["mmsi"], f"mmsi{v['mmsi']}")].append(v)

    def events_between(mmsis, a, b):
        q = ",".join("?" * len(mmsis))
        return [dict(e) for e in con.execute(
            f"SELECT * FROM events WHERE (mmsi IN ({q}) OR mmsi2 IN ({q})) AND t_start >= ? AND t_start < ? "
            "AND kind != 'spoof' ORDER BY t_start", (*mmsis, *mmsis, a, b))]

    def tracked(mmsis, a, b):
        q = ",".join("?" * len(mmsis))
        return con.execute(f"SELECT count(*) FROM seen_offport WHERE mmsi IN ({q}) AND hour>? AND hour<?",
                           (*mmsis, a[:13], b[:13])).fetchone()[0] > 0

    def name_of(mmsi):
        v = vessels.get(mmsi) or {}
        return v.get("name") or f"MMSI {mmsi}"

    rows = 0
    used: set[tuple] = set()   # bir rotaya bağlanmış çıkış ziyaretleri (karanlık sefer taramasında atlanır)
    legs_by_mmsi_origin = []  # dolaylı arama için: (mmsi, A, B, çıkış ziyareti)
    for key, vs in by_key.items():
        mmsis = k2m.get(key) or [vs[0]["mmsi"]]
        for (A, B) in cfg.directions:
            for i, v in enumerate(vs):
                if country[v["port"]] != A or v["status"] != "closed" or v["port"] in approach:
                    continue
                legs_by_mmsi_origin.append((mmsis, A, B, v))
                rel = [k for k in range(i + 1, len(vs)) if country[vs[k]["port"]] in (A, B)]
                if not rel or country[vs[rel[0]]["port"]] != B:
                    continue  # sonraki ilgili liman yine A: bacak oradan başlar
                j = rel[0]
                w = vs[j]
                if w["port"] in approach:
                    # kıyı alanından sonra kısa sürede gerçek bir limana girdiyse varış o limandır
                    for k in rel[1:]:
                        if country[vs[k]["port"]] == A:
                            break
                        if vs[k]["port"] not in approach and hours_between(w["last_in"], vs[k]["t_in"]) <= 72:
                            j, w = k, vs[k]
                            break
                span = hours_between(v["t_out"], w["t_in"])
                if span > max_h:
                    continue
                mids = [{"liman": cfg.port_by_code[x["port"]].name, "ulke": country[x["port"]],
                         "giris": x["t_in"], "cikis": x["t_out"]} for x in vs[i + 1:j] if x["port"] not in approach]
                if (mids and (len(mids) > th["aktarma_max_liman"] or span > th["aktarma_max_gun"] * 24)) or \
                        (not mids and span > th["dogrudan_max_gun"] * 24):
                    continue  # bağ zayıf: çok fazla ara liman ya da çok uzun süre
                used.add((A, B, v["id"]))
                evs = events_between(mmsis, v["t_out"], w["t_in"])
                kinds = {e["kind"] for e in evs}
                was_tracked = tracked(mmsis, v["t_out"], w["t_in"])
                lost = bool(w.get("_kayip"))
                if "sts" in kinds:
                    cls = "denizde_aktarma"
                elif lost:
                    cls = "kiyida_kayboldu"
                elif "gap" in kinds:
                    cls = "karanlik_bacak"
                elif mids or "stop" in kinds:
                    cls = "aktarmali"
                elif was_tracked:
                    cls = "dogrudan"
                else:
                    cls = "dogrudan_izlenmedi"
                dm = cfg.destination_matches(v["dest_out"], B)
                sts_note = None
                for e in evs:
                    if e["kind"] == "sts":
                        d = json.loads(e["detail"])
                        mine = d["draft_1"] if e["mmsi"] in mmsis else d["draft_2"]
                        if mine[0] is not None and mine[1] is not None and mine[1] - mine[0] >= 0.5:
                            sts_note = f"Denizdeki buluşmadan sonra su çekimi arttı: {mine[0]} → {mine[1]} m"
                vt = (vessels.get(v["mmsi"]) or {}).get("type")
                cg = infer(cfg, vt, v, None if lost else w, sts_note)
                flags = {"ara_liman": bool(mids), "ais_boslugu": "gap" in kinds, "durak": "stop" in kinds,
                         "sts": "sts" in kinds, "izlendi": was_tracked, "kiyida_kayip": lost,
                         "sessizlik_saat": w.get("_sessizlik_saat"),
                         "varis_beyani": "eslesiyor" if dm else ("bos" if dm is None else "farkli")}
                con.execute(
                    """INSERT INTO routes(direction,kind,vkey,mmsi,name,origin_port,t_dep,dest_port,t_arr,cls,flags,
                       mids,evts,masked,dest_text,tracked,cargo,cargo_conf,cargo_basis)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"{A}>{B}", "bacak", key, v["mmsi"], name_of(v["mmsi"]), v["port"], v["t_out"], w["port"],
                     w["t_in"], cls, json.dumps(flags), json.dumps(mids, ensure_ascii=False),
                     json.dumps([e["id"] for e in evs]), int(dm is False), v["dest_out"], int(was_tracked),
                     cg["cargo"], cg["conf"], json.dumps(cg["basis"], ensure_ascii=False)))
                rows += 1

    # --- dolaylı: A'dan çıkan gemi denizde başka gemiyle buluştu, o gemi B'ye vardı ---
    sts_events = [dict(e) for e in con.execute("SELECT * FROM events WHERE kind='sts' ORDER BY t_start")]
    for e in sts_events:
        for giver, receiver in ((e["mmsi"], e["mmsi2"]), (e["mmsi2"], e["mmsi"])):
            gk, rk = m2k.get(giver), m2k.get(receiver)
            if not gk or not rk or gk == rk:
                continue
            cands = [(mm, A, B, v) for mm, A, B, v in legs_by_mmsi_origin
                     if giver in mm and v["t_out"] <= e["t_start"] and hours_between(v["t_out"], e["t_start"]) <= max_h]
            # buluşmadan önceki en son A çıkışı
            for mmsis, A, B, v in sorted(cands, key=lambda c: c[3]["t_out"], reverse=True):
                # alıcının buluşmadan sonraki ilk B ziyareti
                arr = next((x for x in by_key.get(rk, []) if x["t_in"] >= e["t_end"]
                            and country[x["port"]] == B and hours_between(e["t_end"], x["t_in"]) <= max_h), None)
                if not arr:
                    continue
                d = json.loads(e["detail"])
                gd, rd = (d["draft_1"], d["draft_2"]) if e["mmsi"] == giver else (d["draft_2"], d["draft_1"])
                note = None
                if all(x is not None for x in gd + rd):
                    note = (f"Buluşmada verenin su çekimi {gd[0]} → {gd[1]} m, "
                            f"alanın su çekimi {rd[0]} → {rd[1]} m")
                rt = (vessels.get(receiver) or {}).get("type")
                cg = infer(cfg, rt, v, arr, note)
                dm = cfg.destination_matches(v["dest_out"], B)
                con.execute(
                    """INSERT INTO routes(direction,kind,vkey,mmsi,name,origin_port,t_dep,dest_port,t_arr,cls,flags,
                       mids,evts,masked,dest_text,tracked,cargo,cargo_conf,cargo_basis,via_vkey,via_mmsi,via_name)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"{A}>{B}", "dolayli", rk, receiver, name_of(receiver), v["port"], v["t_out"], arr["port"],
                     arr["t_in"], "dolayli_sts",
                     json.dumps({"sts": True, "izlendi": True,
                                 "varis_beyani": "eslesiyor" if dm else ("bos" if dm is None else "farkli")}),
                     json.dumps([{"liman": "Denizde buluşma", "ulke": "-", "giris": e["t_start"], "cikis": e["t_end"],
                                  "konum": [round(e["lat"], 3), round(e["lon"], 3)]}], ensure_ascii=False),
                     json.dumps([e["id"]]), int(dm is False), v["dest_out"], 1,
                     cg["cargo"], cg["conf"], json.dumps(cg["basis"], ensure_ascii=False),
                     gk, giver, name_of(giver)))
                used.add((A, B, v["id"]))
                rows += 1
                break

    # --- karanlık sefer: A'dan çıktı, B'de kaydı yok, ama karanlık bölgede uzun AIS boşluğu var ---
    dark_h = th["karanlik_sefer_saat"]
    win_h = th["karanlik_sefer_gun"] * 24
    for key, vs in by_key.items():
        mmsis = k2m.get(key) or [vs[0]["mmsi"]]
        for (A, B) in cfg.directions:
            for i, v in enumerate(vs):
                if (country[v["port"]] != A or v["status"] != "closed" or v["port"] in approach
                        or (A, B, v["id"]) in used):
                    continue
                nxt = vs[i + 1] if i + 1 < len(vs) else None
                end = add_hours(v["t_out"], win_h)
                if nxt and nxt["t_in"] < end:
                    end = nxt["t_in"]
                cand = []
                for g in events_between(mmsis, v["t_out"], end):
                    if g["kind"] != "gap":
                        continue
                    d = json.loads(g["detail"])
                    if d.get("saat", 0) >= dark_h and cfg.in_dark_box(*(d.get("baslangic") or [None, None])):
                        cand.append((g, d))
                if not cand:
                    continue
                g, d = max(cand, key=lambda c: c[1]["saat"])
                once, sonra = d.get("draft_once"), d.get("draft_sonra")
                dropped = once is not None and sonra is not None and once - sonra >= th["draft_degisim_m"]
                note = (f"Karanlık süreden sonra su çekimi azaldı: {once} → {sonra} m (yük boşaltılmış olabilir)"
                        if dropped else None)
                vt = (vessels.get(v["mmsi"]) or {}).get("type")
                cg = infer(cfg, vt, v, None, note)
                dm = cfg.destination_matches(v["dest_out"], B)
                flags = {"ais_boslugu": True, "karanlik_saat": d["saat"], "draft_dustu": dropped,
                         "kapanis": d.get("baslangic"), "acilis": d.get("bitis"),
                         "sonraki_liman": cfg.port_by_code[nxt["port"]].name if nxt and nxt["t_in"] <= end else None,
                         "izlendi": True,
                         "varis_beyani": "eslesiyor" if dm else ("bos" if dm is None else "farkli")}
                con.execute(
                    """INSERT INTO routes(direction,kind,vkey,mmsi,name,origin_port,t_dep,dest_port,t_arr,cls,flags,
                       mids,evts,masked,dest_text,tracked,cargo,cargo_conf,cargo_basis)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"{A}>{B}", "supheli", key, v["mmsi"], name_of(v["mmsi"]), v["port"], v["t_out"], None,
                     g["t_end"], "karanlik_sefer", json.dumps(flags), "[]", json.dumps([g["id"]]),
                     int(dm is False), v["dest_out"], 1,
                     cg["cargo"], cg["conf"], json.dumps(cg["basis"], ensure_ascii=False)))
                rows += 1
    con.commit()
    return rows
