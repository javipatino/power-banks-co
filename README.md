# Power Banks CO · Rents dashboard

Live page: https://javipatino.github.io/power-banks-co/

## Weekly update
1. Download the Google Sheet as Excel (File → Download → Microsoft Excel).
2. Rename it to `data.xlsx`.
3. In GitHub: open the `data` folder → **Add file → Upload files** → drop `data.xlsx` → **Commit changes**.
4. Wait ~1–2 minutes (tab **Actions** shows the run). Refresh the page.

## Categories
`data/station_categories.csv` maps each station to a category. Edit it to fix a category.
Stations not in the file get a category from keyword rules in `scripts/build.py`.

## Structure
- `data/` – input Excel + category mapping
- `scripts/build.py` – computes all metrics → `docs/data/dashboard.json`
- `docs/index.html` – the page (GitHub Pages serves `/docs`)
- `.github/workflows/build.yml` – runs the script on every upload
