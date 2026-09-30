"""Build docs/data/dashboard.json from data/data.xlsx.

Run locally:  python scripts/build.py
The GitHub Action runs this automatically when data/ or scripts/ change.
"""
import json, re, unicodedata
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "data.xlsx"
CATS = ROOT / "data" / "station_categories.csv"
OUT = ROOT / "docs" / "data" / "dashboard.json"

SERIES_START = pd.Timestamp("2026-06-29")  # Monday; section 1 starts here
EXCLUDE = r"@Bogota office|Warehouse|Тест|Тестовая"  # storage / test locations

# ---------- category rules (fallback for stations not in station_categories.csv)
RULES = [
    ("Universities", r"universi"),
    ("Yango Pro partner office", r"yango pro"),
    ("Pharmacy", r"drog|drigueria|farma|podologia|fertilidad|nutricion"),
    ("Gym & sports", r"athletic|gym|gimnasio|crossfit|padel|polideportivo|fit\b|movifit|dance|training|bike|bici"),
    ("Pets", r"pet|mascota|\bdog|vet|perros|patitas"),
    ("Barber & beauty", r"barb|peluquer|belleza|nails|spa\b|tat+o|tatoo|cosmetic|perfum"),
    ("Convenience & market", r"cigarr|tienda|market|mercado|oxxo|exito|grocery|licorera|minimercado|supermercado"),
    ("Stationery & print", r"papel|copia|copy|impre|print"),
    ("Phone & tech", r"cell|phone|smart|tech|mobile|accesorios"),
    ("Auto & moto", r"moto|lavado|detailing|taller"),
    ("Mall & office", r"centro comercial|\bcc\b|centro empresarial|we work|edificio|oficina|cowork"),
    ("Bar & entertainment", r"\bbar\b|pub|cervec|beer|tejo|billar|bolirana|bowling|karaoke|discoteca|club"),
    ("Cafe & bakery", r"cafe|coffe|panader|paster|reposter|bagel|helader|postre"),
    ("Restaurant", r"restau|parrill|pizza|burg|sushi|taquer|empana|arepa|wings|food|gastro|comida|asadero|pollo|chicharr|hotdog|steak|grill"),
]


def norm(t):
    return unicodedata.normalize("NFKD", str(t).lower()).encode("ascii", "ignore").decode()


def rule_category(name):
    t = norm(name)
    for cat, pat in RULES:
        if re.search(pat, t):
            return cat
    return "Other"


def city_of(lat, lon):
    if 4.4 <= lat <= 4.9 and -74.3 <= lon <= -73.9:
        return "Bogota"
    if 6.0 <= lat <= 6.45 and -75.8 <= lon <= -75.4:
        return "Medellin"
    return "not_classified"


def clean_addr(a):
    a = str(a).strip()
    a = re.sub(r"^(Colombia|Колумбия),\s*(Bogot[aá]|Богота|Bogota DC)?,?\s*", "", a, flags=re.I)
    a = re.sub(r"^(Чапинеро),\s*", "Chapinero, ", a)
    return a.strip(" ,")


def ref_time(xl):
    """Last data refresh (About tab), else latest rent start."""
    try:
        about = xl["About"]
        for _, row in about.iterrows():
            if "Last refresh (Bogota)" in str(row.iloc[0]):
                return pd.Timestamp(row.iloc[1])
    except Exception:
        pass
    return xl["Rent History"]["rent_start_date"].max()


def main():
    xl = pd.read_excel(XLSX, sheet_name=None)
    rents = xl["Rent History"].copy()
    st = xl["Station Details"].copy()
    ut = xl["Utilization"][["vending_number", "status"]]

    # ----- stations
    st = st.merge(ut, left_on="station_id", right_on="vending_number", how="left")
    st["city"] = [city_of(a, b) for a, b in zip(st.latitude, st.longitude)]
    st["excluded"] = st.place_name.astype(str).str.contains(EXCLUDE, regex=True) | (st.city == "not_classified")
    cats = pd.read_csv(CATS) if CATS.exists() else pd.DataFrame(columns=["station_id", "category"])
    cmap = dict(zip(cats.station_id, cats.category))
    st["category"] = [cmap.get(i) or rule_category(n) for i, n in zip(st.station_id, st.place_name)]
    dep = st[~st.excluded].copy()
    excluded_ids = set(st[st.excluded].station_id)

    # ----- rents
    rents = rents[~rents.station_id_start.isin(excluded_ids)]
    rents = rents.merge(dep[["station_id", "city"]], left_on="station_id_start", right_on="station_id", how="left")
    rents["city"] = rents.city.fillna("not_classified")
    comp = rents[rents.rent_status == "completed"].copy()
    comp["dur"] = (comp.rent_end_date - comp.rent_start_date).dt.total_seconds() / 60

    # ----- week windows
    ref = ref_time(xl)
    last_end = (ref.normalize() - pd.Timedelta(days=ref.weekday()))  # Monday 00:00 of ref week
    weeks = [(last_end - pd.Timedelta(days=14), last_end - pd.Timedelta(days=7)),
             (last_end - pd.Timedelta(days=7), last_end)]
    w_start, w_end = weeks[0][0], weeks[1][1]

    # ----- section 1: weekly completed rents by city
    s1 = comp[(comp.rent_start_date >= SERIES_START) & (comp.rent_start_date < last_end)].copy()
    s1["wk"] = s1.rent_start_date.dt.to_period("W-SUN").dt.start_time
    wk_index = pd.date_range(SERIES_START, last_end - pd.Timedelta(days=7), freq="7D")
    piv = s1.pivot_table(index="wk", columns="city", values="user_id", aggfunc="count").reindex(wk_index).fillna(0)
    section1 = {
        "weeks": [d.strftime("%Y-%m-%d") for d in wk_index],
        "series": {c: [int(v) for v in piv.get(c, pd.Series(0, index=wk_index))] for c in ["Bogota", "Medellin", "not_classified"]},
    }

    # ----- sections 2 & 3 per city
    win = comp[(comp.rent_start_date >= w_start) & (comp.rent_start_date < w_end)]
    cities = {}
    for city in ["Bogota", "Medellin"]:
        g0 = win[win.city == city]
        d0 = dep[dep.city == city].copy()
        meds, sames, acts = [], [], []
        for a, b in weeks:
            g = g0[(g0.rent_start_date >= a) & (g0.rent_start_date < b)]
            n_dep = int((d0.location_created_at < b).sum())
            if len(g):
                meds.append(g.dur.median())
                sames.append((g.station_id_start == g.station_id_returned).mean())
            acts.append(g.station_id_start.nunique() / n_dep if n_dep else np.nan)
        vc = g0.station_id_start.value_counts()
        if len(vc):
            n = int(np.ceil(len(vc) * 0.10))
            cut = vc.iloc[n - 1]
            top = vc[vc >= cut]  # ties at the cutoff are included
            top_share = top.sum() / vc.sum()
        else:
            top, top_share = vc, None
        info = d0.set_index("station_id")
        top_rows = [[int(i), str(info.at[i, "place_name"]).strip(), clean_addr(info.at[i, "address"]), int(k), str(info.at[i, "status"])]
                    for i, k in top.items()]
        dow = g0.rent_start_date.dt.dayofweek.value_counts().reindex(range(7), fill_value=0)

        d0["rents"] = d0.station_id.map(vc).fillna(0).astype(int)
        cat_rows, cat_st = [], {}
        total = int(d0.rents.sum())
        for cat, g in d0.groupby("category"):
            r = int(g.rents.sum())
            cat_rows.append({"category": cat, "stations": int(len(g)), "rents": r,
                             "rents_per_station": round(r / len(g), 2),
                             "active_pct": round((g.rents > 0).mean() * 100),
                             "share_pct": round(r / total * 100) if total else 0})
            gg = g[g.rents > 0].sort_values(["rents", "place_name"], ascending=[False, True])
            cat_st[cat] = [[int(i), str(n).strip(), clean_addr(a), int(k), str(s)]
                           for i, n, a, k, s in zip(gg.station_id, gg.place_name, gg.address, gg.rents, gg.status)]
        cat_rows.sort(key=lambda x: (-x["rents_per_station"], -x["stations"]))

        cities[city] = {
            "completed_rents": int(len(g0)),
            "stations": int(len(d0)),
            "median_minutes": round(float(np.mean(meds))) if meds else None,
            "same_station_pct": round(float(np.mean(sames)) * 100) if sames else None,
            "active_pct": round(float(np.nanmean(acts)) * 100) if acts else None,
            "top10_share_pct": round(top_share * 100) if top_share is not None else None,
            "top10_count": int(len(top)),
            "renting_stations": int(len(vc)),
            "dow_totals": [int(v) for v in dow],
            "top_stations": top_rows,
            "categories": cat_rows,
            "category_stations": cat_st,
        }

    out = {
        "generated_from_refresh": ref.strftime("%Y-%m-%d %H:%M"),
        "window": {"start": w_start.strftime("%Y-%m-%d"), "end": (w_end - pd.Timedelta(days=1)).strftime("%Y-%m-%d")},
        "section1": section1,
        "cities": cities,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} · window {out['window']} · refresh {out['generated_from_refresh']}")


if __name__ == "__main__":
    main()
