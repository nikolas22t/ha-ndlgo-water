#!/usr/bin/env python3
"""NDLGO (Nicosia water board, online.ndlgo.org.cy) -> Home Assistant water stats.

Meter has no AMR, so only bi-monthly billed readings exist. Each period's m3 and
EUR are spread evenly over its hours and imported as external statistics
ndlgo:water_consumption (m3) and ndlgo:water_cost (EUR). The whole series is
rewritten each run from the earliest period (sum starts at 0) so it stays consistent.
Env: HA_WS, HA_TOKEN, HA_INSECURE, NDLGO_USER, NDLGO_PASS
"""
import json, os, sys, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

API = "https://online.ndlgo.org.cy/api/"
TZ, UTC = ZoneInfo("Europe/Nicosia"), ZoneInfo("UTC")
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


class HA:
    """Minimal Home Assistant websocket client."""
    def __init__(self):
        import ssl, websocket
        self.ws = websocket.create_connection(
            os.environ["HA_WS"], sslopt={"cert_reqs": ssl.CERT_NONE} if os.environ.get("HA_INSECURE") else None)
        self.ws.recv()
        self.ws.send(json.dumps({"type": "auth", "access_token": os.environ["HA_TOKEN"]}))
        if json.loads(self.ws.recv())["type"] != "auth_ok":
            sys.exit("HA auth failed")
        self.i = 0

    def call(self, **msg):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, **msg}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self.i:
                if not r.get("success"):
                    sys.exit(f"HA error: {r}")
                return r.get("result")


def get(path, jwt=None, body=None):
    h = dict(UA)
    if jwt:
        h["Cookie"] = "jwt=" + jwt
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None, headers=h)
    return json.load(urllib.request.urlopen(req, timeout=60))


def periods():
    jwt = get("oraclelogin", body={"username": os.environ["NDLGO_USER"],
                                   "password": os.environ["NDLGO_PASS"]})["accessToken"]
    out = []
    for inst in get("wbninst", jwt):
        for p in get(f"wbnperiods/{inst['inst_serial_no']}", jwt):
            a, b = p["period_desc"].split("-")
            y = int(p["read_year"])
            (sd, sm), (ed, em) = map(int, a.split("/")), map(int, b.split("/"))
            start = datetime(y - (sm > em), sm, sd, tzinfo=TZ)
            end = datetime(y, em, ed, tzinfo=TZ)
            out.append((start, end, float(p["reading"]), float(p["read_amount"]), p))
    return sorted(out, key=lambda x: x[0])


def series(pers, idx):
    hours = {}
    for start, end, m3, eur, _ in pers:
        s, e = start.astimezone(UTC), end.astimezone(UTC)
        n = int((e - s).total_seconds() // 3600)
        v = (m3, eur)[idx] / n
        for i in range(n):
            hours[s + timedelta(hours=i)] = v
    return dict(sorted(hours.items()))


def push(ha, hours, sid, name, unit, unit_class):
    total, stats = 0.0, []
    for h, v in hours.items():
        total += v
        stats.append({"start": h.isoformat(), "state": round(v, 5), "sum": round(total, 4)})
    ha.call(type="recorder/import_statistics",
            metadata={"source": "ndlgo", "statistic_id": sid, "name": name, "unit_of_measurement": unit,
                      "unit_class": unit_class, "has_mean": False, "mean_type": 0, "has_sum": True},
            stats=stats)
    print(f"{sid}: {len(stats)} h {stats[0]['start']}..{stats[-1]['start']} total {total:.2f} {unit}")


def dashboard(ha, pers):
    """(Re)build the separate 'Νερό' dashboard (url water-ndlgo) — not the Energy module."""
    if not any(d["url_path"] == "water-ndlgo" for d in ha.call(type="lovelace/dashboards/list")):
        ha.call(type="lovelace/dashboards/create", url_path="water-ndlgo", title="Νερό",
                icon="mdi:water", require_admin=False, show_in_sidebar=True, mode="storage")
    last = pers[-1]
    days = (last[1] - last[0]).days
    rows = "\n".join(f"| {s:%d/%m/%Y} – {e:%d/%m/%Y} | {m3:g} | {m3 / (e - s).days * 1000:.0f} | €{eur:.2f} |"
                     for s, e, m3, eur, _ in reversed(pers))
    tot_m3, tot_eur = sum(p[2] for p in pers), sum(p[3] for p in pers)
    md = (f"## Τελευταίος λογαριασμός\n**{last[0]:%d/%m} – {last[1]:%d/%m/%Y}**: {last[2]:g} m³ · "
          f"**€{last[3]:.2f}** · ~{last[2] / days * 1000:.0f} λίτρα/μέρα\n\n"
          "| Περίοδος | m³ | λίτρα/μέρα | Ποσό |\n|---|---:|---:|---:|\n" + rows +
          f"\n| **Σύνολο** | **{tot_m3:g}** | | **€{tot_eur:.2f}** |\n\n"
          f"<small>Πηγή: ΣΑΛΑ/NDLGO, διμηνιαίοι λογαριασμοί (όχι έξυπνος μετρητής) · "
          f"ενημ. {datetime.now(TZ):%d/%m/%Y %H:%M}</small>")
    graph = lambda sid, title, unit: {"type": "statistics-graph", "title": title, "entities": [sid],
                                      "stat_types": ["change"], "period": "month", "chart_type": "bar",
                                      "days_to_show": 400, "unit": unit}
    cfg = {"title": "Νερό", "views": [{"title": "Νερό", "path": "water", "icon": "mdi:water", "cards": [
        {"type": "markdown", "content": md},
        graph("ndlgo:water_consumption", "Κατανάλωση ανά μήνα (m³)", "m³"),
        graph("ndlgo:water_cost", "Κόστος ανά μήνα (€)", "€")]}]}
    ha.call(type="lovelace/config/save", url_path="water-ndlgo", config=cfg)
    print("dashboard water updated")


if __name__ == "__main__":
    pers = periods()
    for s, e, m3, eur, _ in pers:
        print(f"{s:%Y-%m-%d} -> {e:%Y-%m-%d}: {m3:g} m3  EUR {eur:.2f}")
    if "--dry" in sys.argv:
        sys.exit()
    ha = HA()
    push(ha, series(pers, 0), "ndlgo:water_consumption", "Water Consumption (NDLGO)", "m³", "volume")
    push(ha, series(pers, 1), "ndlgo:water_cost", "Water Cost (NDLGO)", "EUR", None)
    dashboard(ha, pers)

