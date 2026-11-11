"""Beyan testi: A ülkesi limanlarından B ülkesi limanlarına doğrudan ve dolaylı gemi hareketleri.

Her bacak kurala dayalı olarak sınıflandırılır (kurallar yontem sayfasında yayımlanır):
  denizde_aktarma         bacak sırasında açık denizde başka gemiyle buluşma (STS)
  karanlik_bacak          bacak sırasında açık denizde AIS boşluğu
  aktarmali               arada başka limana veya liman dışı uzun durağa uğradı
  dogrudan                kesintisiz izlendi, arada durak yok
  dogrudan_izlenmedi      A'dan çıkış ve B'ye varış kayıtlı, ara güzergâh izlenemedi
  dolayli_sts             A'dan çıkan gemi denizde yükünü başka gemiye verdi, o gemi B'ye vardı
Ek işaret: masked = AIS'te beyan edilen varış noktası B ülkesini göstermiyordu.
"""
from __future__ import annotations

import json
from collections import defaultdict

from .cargo import infer
from .util import hours_between

CLASS_LABELS = {
    "dogrudan": "Doğrudan",
    "dogrudan_izlenmedi": "Doğrudan (ara güzergâh izlenemedi)",
    "aktarmali": "Ara duraklı",
    "karanlik_bacak": "Karanlık bacak (AIS boşluğu)",
    "denizde_aktarma": "Denizde buluşma (olası aktarma)",
    "dolayli_sts": "Dolaylı: denizde gemiden gemiye",
}
CLASS_ORDER = list(CLASS_LABELS)
CLASS_SHORT = {"dogrudan": "Doğrudan", "dogrudan_izlenmedi": "Doğrudan*", "aktarmali": "Ara duraklı",
               "karanlik_bacak": "Karanlık", "denizde_aktarma": "Denizde buluşma", "dolayli_sts": "Dolaylı"}


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
    max_h = cfg.th["guzergah_max_gun"] * 24
    m2k, k2m = vessel_keys(con)
    country = {p.code: p.country for p in cfg.ports}
    vessels = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM vessels")}
    by_key = defaultdict(list)
    for v in con.execute("SELECT * FROM visits WHERE transit IS NOT 1 ORDER BY t_in"):
        if v["status"] == "closed" or v["status"] == "open":
            by_key[m2k.get(v["mmsi"], f"mmsi{v['mmsi']}")].append(dict(v))

    def events_between(mmsis, a, b):
        q = ",".join("?" * len(mmsis))
        return [dict(e) for e in con.execute(
            f"SELECT * FROM events WHERE (mmsi IN ({q}) OR mmsi2 IN ({q})) AND t_start >= ? AND t_start < ? ORDER BY t_start",
            (*mmsis, *mmsis, a, b))]

    def tracked(mmsis, a, b):
        q = ",".join("?" * len(mmsis))
        return con.execute(f"SELECT count(*) FROM positions WHERE mmsi IN ({q}) AND port IS NULL AND t>? AND t<?",
                           (*mmsis, a, b)).fetchone()[0] > 0

    def name_of(mmsi):
        v = vessels.get(mmsi) or {}
        return v.get("name") or f"MMSI {mmsi}"

    rows = 0
    legs_by_mmsi_origin = []  # dolaylı arama için: (mmsi, A, B, çıkış ziyareti)
    for key, vs in by_key.items():
        mmsis = k2m.get(key) or [vs[0]["mmsi"]]
        for (A, B) in cfg.directions:
            for i, v in enumerate(vs):
                if country[v["port"]] != A or v["status"] != "closed":
                    continue
                legs_by_mmsi_origin.append((mmsis, A, B, v))
                j = next((j for j in range(i + 1, len(vs)) if country[vs[j]["port"]] in (A, B)), None)
                if j is None or country[vs[j]["port"]] != B:
                    continue  # sonraki ilgili liman yine A: bacak oradan başlar
                w = vs[j]
                if hours_between(v["t_out"], w["t_in"]) > max_h:
                    continue
                mids = [{"liman": cfg.port_by_code[x["port"]].name, "ulke": country[x["port"]],
                         "giris": x["t_in"], "cikis": x["t_out"]} for x in vs[i + 1:j]]
                evs = events_between(mmsis, v["t_out"], w["t_in"])
                kinds = {e["kind"] for e in evs}
                was_tracked = tracked(mmsis, v["t_out"], w["t_in"])
                if "sts" in kinds:
                    cls = "denizde_aktarma"
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
                cg = infer(cfg, vt, v, w, sts_note)
                flags = {"ara_liman": bool(mids), "ais_boslugu": "gap" in kinds, "durak": "stop" in kinds,
                         "sts": "sts" in kinds, "izlendi": was_tracked,
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
            for mmsis, A, B, v in legs_by_mmsi_origin:
                if giver not in mmsis or not (v["t_out"] <= e["t_start"]) or hours_between(v["t_out"], e["t_start"]) > max_h:
                    continue
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
                rows += 1
                break
    con.commit()
    return rows
