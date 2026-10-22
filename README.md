# vpc-vibe-coding

## BNB Co. S&OP Dashboard

A read-only first milestone for exploring BNB Co.'s fictional yoghurt supply-chain data. The app connects to the supplied SQLite database and has four pages: a network map, a high-level overview, historical sales and future forecast, and an inventory snapshot by category. It also includes a database-backed baseline question box; it does not call an AI service or include AI agents.

## 1. Check Python

Open the macOS **Terminal** app and go to this project folder. The folder path may be copied from Finder and placed after `cd`:

```bash
cd "/path/to/BNB_SOP_AI"
python3 --version
```

Use Python 3.10 or newer. If `python3` is not found, install Python from [python.org](https://www.python.org/downloads/macos/) and reopen Terminal.

## 2. Create an isolated Python environment

This keeps the app's packages separate from other Python projects:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

When the environment is active, Terminal usually shows `(.venv)` at the start of the prompt. If you open a new Terminal later, run `source .venv/bin/activate` again from the project folder.

## 3. Extract the SQLite database

The database is inside the supplied starter ZIP. From the project folder, run:

```bash
unzip -o "BNB_Co_SOP_Database_Starter (4).zip" BNB_Co_SOP_Prototype.sqlite
```

This extracts the database next to `app.py`. It is a large local file and is intentionally excluded from Git by `.gitignore`.

## 4. Run the app

```bash
streamlit run app.py
```

Streamlit prints a local URL, usually <http://localhost:8501>, and may open it in your browser. The app is read-only: choosing a warehouse and product filters the dashboard without changing the database.

## 5. Test the first milestone

1. Use the collapsible left sidebar to open **Network map**, **Overview**, **Historic sales and future forecast**, or **Inventory snapshot by category**.
2. On the network page, inspect the Southeast Asia map and colored route lines. Approximate city-center coordinates are kept in `map_coordinates.csv` because the SQLite database has no coordinates. Hover over map markers for the location name and type; open **Lane details** for route mode and lead time.
3. On Overview, review revenue, inventory value, days of inventory by category, the demand/production plan-gap list, and data-quality checks. Expand the master-data section to see products and locations.
4. On Historic sales and future forecast, select a warehouse and product, then inspect sales, BASE demand, and inventory batches. Try asking which month has the highest baseline demand.
5. On Inventory snapshot by category, compare stock units, estimated inventory value, and days of coverage across product families.
6. In Terminal, you can also verify Python syntax with `python -m py_compile app.py`.

## What the figures mean

- Historical sales are grouped by month from `sales_history`.
- Planned demand comes from the `BASE` scenario in `demand_plan`.
- Batch inventory and expiry dates are from `inventory_opening`, a snapshot dated **2026-10-01**. "Expires within 7 days" is measured from each batch's snapshot date, not today's date.
- Overview revenue is the trailing 12 months through the latest available sales date.
- Category inventory value uses `inventory_opening` units multiplied by the product's standard `unit_cost_usd`.
- Category days of inventory uses opening stock divided by average daily sales over the 90 days ending **2026-09-30**.
- The overview's plan-gap list compares monthly BASE demand with planned production by category. It is not a stockout prediction: it does not include opening stock or scheduled receipts. Production marked `PROPOSED` is not approved.
- The network page draws the 42 reference lanes between locations. Approximate city-center coordinates are visual placements only, not source-system coordinates. The map uses an online CARTO basemap, so an internet connection is needed to show country outlines and labels.
- The quality checks cover product/location references, historical demand balancing, non-negative opening stock, expired stock, and SQLite integrity.
- The supplied dataset is synthetic. Its inventory ledger and supply plan have documented limitations in `BNB_Co_SOP_Data/README.md`; this dashboard is for exploration, not operational planning.

## Troubleshooting

- **Database not found:** repeat the extraction step from the project folder and check that `BNB_Co_SOP_Prototype.sqlite` is beside `app.py`.
- **`streamlit: command not found`:** activate `.venv` with `source .venv/bin/activate`, then run `python -m pip install -r requirements.txt` again. You can also launch with `python -m streamlit run app.py`.
- **Port already in use:** run `streamlit run app.py --server.port 8502` and open the URL Streamlit prints.
- **Stop the app:** click Terminal and press `Control+C`.