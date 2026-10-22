from pathlib import Path
import math
import sqlite3

import pandas as pd
import pydeck as pdk
import streamlit as st


DATABASE_PATH = Path(__file__).resolve().parent / "BNB_Co_SOP_Prototype.sqlite"
MAP_COORDINATES_PATH = Path(__file__).resolve().parent / "map_coordinates.csv"

st.set_page_config(page_title="BNB Co. S&OP", layout="wide")


def read_query(sql: str, parameters: tuple = ()) -> pd.DataFrame:
    connection = sqlite3.connect(DATABASE_PATH)
    try:
        return pd.read_sql_query(sql, connection, params=parameters)
    finally:
        connection.close()


@st.cache_data(ttl=300)
def get_products() -> pd.DataFrame:
    return read_query("SELECT * FROM item_master ORDER BY sku_id")


@st.cache_data(ttl=300)
def get_locations() -> pd.DataFrame:
    return read_query("SELECT * FROM location_master ORDER BY location_type, country, location_name")


@st.cache_data(ttl=300)
def get_stocked_pairs() -> pd.DataFrame:
    return read_query(
        """
        SELECT x.location_id, l.location_name, l.country, x.sku_id,
               i.product_family, i.flavor, i.consumer_pack_g
        FROM item_location_master x
        JOIN item_master i ON i.sku_id = x.sku_id
        JOIN location_master l ON l.location_id = x.location_id
        WHERE x.is_stocked = 'True' AND l.location_type = 'LOCAL_WAREHOUSE'
        ORDER BY l.country, l.location_name, x.sku_id
        """
    )


@st.cache_data(ttl=300)
def get_sales(sku_id: str, location_id: str) -> pd.DataFrame:
    return read_query(
        """
        SELECT substr(date, 1, 7) AS month, SUM(sold_units) AS sales_units
        FROM sales_history
        WHERE sku_id = ? AND warehouse_id = ?
        GROUP BY substr(date, 1, 7)
        ORDER BY month
        """,
        (sku_id, location_id),
    )


@st.cache_data(ttl=300)
def get_forecast(sku_id: str, location_id: str) -> pd.DataFrame:
    return read_query(
        """
        SELECT target_month AS month, SUM(forecast_units) AS forecast_units
        FROM demand_plan
        WHERE scenario_id = 'BASE' AND sku_id = ? AND warehouse_id = ?
        GROUP BY target_month
        ORDER BY month
        """,
        (sku_id, location_id),
    )


@st.cache_data(ttl=300)
def get_inventory(sku_id: str, location_id: str) -> pd.DataFrame:
    return read_query(
        """
        SELECT batch_id, production_date, expiry_date, on_hand_units,
               usable_units, as_of_date
        FROM inventory_opening
        WHERE sku_id = ? AND location_id = ?
        ORDER BY expiry_date, batch_id
        """,
        (sku_id, location_id),
    )


@st.cache_data(ttl=300)
def get_top_baseline_products(location_id: str) -> pd.DataFrame:
    return read_query(
        """
        SELECT i.sku_id AS Product, i.flavor AS Flavor,
               SUM(d.forecast_units) AS Forecast
        FROM demand_plan d
        JOIN item_master i ON i.sku_id = d.sku_id
        WHERE d.scenario_id = 'BASE' AND d.warehouse_id = ?
        GROUP BY i.sku_id, i.flavor
        ORDER BY Forecast DESC
        LIMIT 5
        """,
        (location_id,),
    )


def answer_baseline_question(
    question: str,
    sku_id: str,
    location_id: str,
    sales_data: pd.DataFrame,
    forecast_data: pd.DataFrame,
    inventory_data: pd.DataFrame,
) -> tuple[str, pd.DataFrame | None]:
    normalized_question = question.lower()

    if any(word in normalized_question for word in ("top", "highest")) and any(
        word in normalized_question for word in ("product", "sku")
    ):
        top_products = get_top_baseline_products(location_id)
        return (
            f"These are the top products by total BASE demand at {location_id}.",
            top_products,
        )

    if any(word in normalized_question for word in ("inventory", "stock", "batch", "expir")):
        on_hand = int(inventory_data["on_hand_units"].sum()) if not inventory_data.empty else 0
        expired = 0
        expiring = 0
        if not inventory_data.empty:
            expiry_days = (
                pd.to_datetime(inventory_data["expiry_date"])
                - pd.to_datetime(inventory_data["as_of_date"])
            ).dt.days
            expired = int(inventory_data.loc[expiry_days < 0, "on_hand_units"].sum())
            expiring = int(inventory_data.loc[expiry_days.between(0, 7), "on_hand_units"].sum())
        return (
            f"{sku_id} has {on_hand:,} units on hand at the 2026-10-01 snapshot; "
            f"{expired:,} units are already past expiry, and {expiring:,} expire "
            "within 7 days of that snapshot.",
            None,
        )

    if any(word in normalized_question for word in ("sales", "sold", "history")):
        total_sales = int(sales_data["sales_units"].sum()) if not sales_data.empty else 0
        if any(word in normalized_question for word in ("highest", "best", "peak")) and not sales_data.empty:
            peak_month = sales_data.loc[sales_data["sales_units"].idxmax()]
            return (
                f"The highest sales month was {peak_month['month']} with "
                f"{int(peak_month['sales_units']):,} units. Total historical sales were {total_sales:,} units.",
                None,
            )
        return (
            f"Historical sales for {sku_id} at {location_id} total {total_sales:,} units.",
            sales_data.rename(columns={"month": "Month", "sales_units": "Sales (units)"}),
        )

    if any(word in normalized_question for word in ("baseline", "forecast", "demand", "month")):
        total_forecast = int(forecast_data["forecast_units"].sum()) if not forecast_data.empty else 0
        if any(word in normalized_question for word in ("highest", "peak", "maximum")) and not forecast_data.empty:
            peak_month = forecast_data.loc[forecast_data["forecast_units"].idxmax()]
            return (
                f"The highest BASE demand month for {sku_id} at {location_id} is "
                f"{peak_month['month']} with {int(peak_month['forecast_units']):,} units.",
                None,
            )
        return (
            f"BASE demand for {sku_id} at {location_id} totals {total_forecast:,} units "
            f"across {len(forecast_data)} planned months.",
            forecast_data.rename(columns={"month": "Month", "forecast_units": "BASE demand (units)"}),
        )

    return (
        "I can answer questions about BASE demand or its peak month, top products by "
        "BASE demand at this warehouse, historical sales, and inventory or expiry. "
        "Try: 'What is the baseline demand?'",
        None,
    )


@st.cache_data(ttl=300)
def get_quality_checks() -> pd.DataFrame:
    checks = [
        (
            "Sales reference a known product",
            "SELECT COUNT(*) FROM sales_history s LEFT JOIN item_master i ON i.sku_id = s.sku_id WHERE i.sku_id IS NULL",
            "Expected: 0 unmatched sales rows",
            False,
        ),
        (
            "Sales reference a known warehouse",
            "SELECT COUNT(*) FROM sales_history s LEFT JOIN location_master l ON l.location_id = s.warehouse_id WHERE l.location_id IS NULL",
            "Expected: 0 unmatched sales rows",
            False,
        ),
        (
            "Historical demand balances",
            "SELECT COUNT(*) FROM demand_history WHERE unconstrained_demand_units != fulfilled_units + lost_sales_units",
            "Expected: 0 rows where demand differs from fulfilled plus lost sales",
            False,
        ),
        (
            "Inventory quantities are non-negative",
            "SELECT COUNT(*) FROM inventory_opening WHERE on_hand_units < 0 OR usable_units < 0",
            "Expected: 0 negative quantities",
            False,
        ),
        (
            "Expired batches still have stock",
            "SELECT COUNT(*) FROM inventory_opening WHERE on_hand_units > 0 AND expiry_date < as_of_date",
            "Expected: 0 expired batches with stock; compare using each row's snapshot date",
            True,
        ),
    ]
    results = []
    for label, sql, detail, is_review_check in checks:
        count = int(read_query(sql).iloc[0, 0])
        passed = count == 0
        results.append(
            {
                "Check": label,
                "Status": "PASS" if passed else ("REVIEW" if is_review_check else "FAIL"),
                "Rows to review": count,
                "Expected result": detail,
            }
        )
    integrity = str(read_query("PRAGMA integrity_check").iloc[0, 0])
    results.append(
        {
            "Check": "SQLite database integrity",
            "Status": "PASS" if integrity == "ok" else "FAIL",
            "Rows to review": 0 if integrity == "ok" else 1,
            "Expected result": "SQLite integrity_check returns ok",
        }
    )
    return pd.DataFrame(results)


@st.cache_data(ttl=300)
def get_network_lanes() -> pd.DataFrame:
    return read_query(
        """
        SELECT n.lane_id, n.origin_location_id, origin.location_name AS origin_name,
               origin.location_type AS origin_type, n.destination_location_id,
               destination.location_name AS destination_name,
               destination.location_type AS destination_type, n.mode,
               n.lead_time_days, n.weekly_capacity_kg, n.cold_chain_required
        FROM network_lane_master n
        JOIN location_master origin ON origin.location_id = n.origin_location_id
        JOIN location_master destination ON destination.location_id = n.destination_location_id
        ORDER BY origin.location_type, origin.location_name, destination.location_name
        """
    )


@st.cache_data(ttl=300)
def get_mapped_locations() -> pd.DataFrame:
    locations = get_locations()
    coordinates = pd.read_csv(MAP_COORDINATES_PATH)
    return locations.merge(coordinates, on="location_id", how="left", validate="one_to_one")


@st.cache_data(ttl=300)
def get_category_snapshot() -> pd.DataFrame:
    return read_query(
        """
        WITH bounds AS (
            SELECT MAX(date) AS end_date, date(MAX(date), '-89 days') AS start_date
            FROM sales_history
        ), inventory AS (
            SELECT i.product_family AS category,
                   SUM(b.on_hand_units) AS inventory_units,
                   SUM(b.on_hand_units * i.unit_cost_usd) AS inventory_value
            FROM inventory_opening b
            JOIN item_master i ON i.sku_id = b.sku_id
            GROUP BY i.product_family
        ), recent_sales AS (
            SELECT i.product_family AS category, SUM(s.sold_units) AS sales_units
            FROM sales_history s
            JOIN item_master i ON i.sku_id = s.sku_id
            CROSS JOIN bounds
            WHERE s.date BETWEEN bounds.start_date AND bounds.end_date
            GROUP BY i.product_family
        )
        SELECT inventory.category AS Category,
               inventory.inventory_units AS "On hand (units)",
               ROUND(inventory.inventory_value, 2) AS "Inventory value (USD)",
               COALESCE(recent_sales.sales_units, 0) AS "Sales, last 90 days (units)"
        FROM inventory
        LEFT JOIN recent_sales USING (category)
        ORDER BY inventory.category
        """
    )


@st.cache_data(ttl=300)
def get_revenue_summary() -> pd.DataFrame:
    return read_query(
        """
        SELECT date(MAX(date), '-364 days') AS start_date,
               MAX(date) AS end_date,
               SUM(net_revenue_usd) AS revenue_usd
        FROM sales_history
        WHERE date >= date((SELECT MAX(date) FROM sales_history), '-364 days')
        """
    )


@st.cache_data(ttl=300)
def get_supply_demand_risks() -> pd.DataFrame:
    return read_query(
        """
        WITH demand AS (
            SELECT target_month AS month, sku_id, SUM(forecast_units) AS demand_units
            FROM demand_plan
            WHERE scenario_id = 'BASE'
            GROUP BY target_month, sku_id
        ), supply AS (
            SELECT month, sku_id, SUM(planned_production_units) AS planned_units,
                   MIN(approval_status) AS approval_status
            FROM approved_supply_plan
            WHERE scenario_id = 'BASE'
            GROUP BY month, sku_id
        ), comparison AS (
            SELECT demand.month, item_master.product_family AS category,
                   COALESCE(supply.approval_status, 'NOT PLANNED') AS approval_status,
                   demand.demand_units, COALESCE(supply.planned_units, 0) AS planned_units
            FROM demand
            JOIN item_master ON item_master.sku_id = demand.sku_id
            LEFT JOIN supply ON supply.month = demand.month AND supply.sku_id = demand.sku_id
        )
        SELECT month AS Month, category AS Category, approval_status AS "Plan status",
               SUM(demand_units) AS "BASE demand (units)",
               SUM(planned_units) AS "Planned production (units)",
               SUM(planned_units - demand_units) AS "Plan gap (units)"
        FROM comparison
        GROUP BY month, category, approval_status
        ORDER BY ABS(SUM(planned_units - demand_units)) DESC
        """
    )


def require_database() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not DATABASE_PATH.exists():
        st.error("The SQLite database was not found. Follow the extraction steps in README.md.")
        st.stop()
    try:
        products = get_products()
        locations = get_locations()
        stocked_pairs = get_stocked_pairs()
    except sqlite3.Error as error:
        st.error(f"Could not read the SQLite database: {error}")
        st.stop()
    if products.empty or locations.empty or stocked_pairs.empty:
        st.error("The database is missing product, location, or stocked product/warehouse data.")
        st.stop()
    return products, locations, stocked_pairs


def render_network_map() -> None:
    require_database()
    st.title("BNB Co. Southeast Asia Supply Network")
    st.subheader("Yoghurt S&OP Network Map")
    lanes = get_network_lanes()
    locations = get_mapped_locations()
    if locations[["latitude", "longitude"]].isna().any().any():
        missing_ids = locations.loc[
            locations["latitude"].isna() | locations["longitude"].isna(), "location_id"
        ].tolist()
        st.error(f"Map coordinates are missing for: {', '.join(missing_ids)}")
        st.stop()

    colors = {
        "FACTORY": [218, 39, 45, 230],
        "REGIONAL_DC": [238, 111, 29, 230],
        "COUNTRY_DC": [22, 155, 165, 230],
        "LOCAL_WAREHOUSE": [42, 126, 54, 230],
        "PORT": [112, 72, 171, 230],
        "CROSS_DOCK": [112, 72, 171, 230],
    }
    locations["color"] = locations["location_type"].map(colors)

    coordinate_by_id = locations.set_index("location_id")[["longitude", "latitude"]].to_dict("index")
    route_paths = []
    route_arrows = []
    for lane in lanes.itertuples(index=False):
        origin = coordinate_by_id[lane.origin_location_id]
        destination = coordinate_by_id[lane.destination_location_id]
        start = (origin["longitude"], origin["latitude"])
        end = (destination["longitude"], destination["latitude"])
        is_sea = lane.mode in ("REEFER_SEA", "REEFER_SEA_TRUCK")
        color = [26, 104, 210, 220] if is_sea else [46, 61, 77, 200]

        if is_sea:
            delta_x = end[0] - start[0]
            delta_y = end[1] - start[1]
            distance = max(math.hypot(delta_x, delta_y), 0.01)
            curve = min(3.0, max(1.0, distance * 0.12))
            control = (
                (start[0] + end[0]) / 2 - delta_y / distance * curve,
                (start[1] + end[1]) / 2 + delta_x / distance * curve,
            )
            path = []
            for step in range(33):
                progress = step / 32
                inverse = 1 - progress
                path.append(
                    [
                        inverse**2 * start[0]
                        + 2 * inverse * progress * control[0]
                        + progress**2 * end[0],
                        inverse**2 * start[1]
                        + 2 * inverse * progress * control[1]
                        + progress**2 * end[1],
                    ]
                )
            for step in range(0, 30, 4):
                route_paths.append({"path": path[step : step + 3], "color": color})
        else:
            path = [[start[0], start[1]], [end[0], end[1]]]
            route_paths.append({"path": path, "color": color})

        arrow_index = min(len(path) - 2, int(len(path) * 0.78))
        arrow_start = path[arrow_index]
        arrow_end = path[arrow_index + 1]
        delta_longitude = (arrow_end[0] - arrow_start[0]) * math.cos(
            math.radians(arrow_end[1])
        )
        delta_latitude = arrow_end[1] - arrow_start[1]
        distance = max(math.hypot(delta_longitude, delta_latitude), 0.0001)
        direction = (delta_longitude / distance, delta_latitude / distance)
        perpendicular = (-direction[1], direction[0])
        arrow_length = 0.28
        arrow_width = 0.12
        tip = arrow_end
        base = (
            tip[0] - direction[0] * arrow_length / math.cos(math.radians(tip[1])),
            tip[1] - direction[1] * arrow_length,
        )
        wing_delta_longitude = perpendicular[0] * arrow_width / math.cos(math.radians(tip[1]))
        wing_delta_latitude = perpendicular[1] * arrow_width
        route_arrows.append(
            {
                "polygon": [
                    [tip[0], tip[1]],
                    [base[0] + wing_delta_longitude, base[1] + wing_delta_latitude],
                    [base[0] - wing_delta_longitude, base[1] - wing_delta_latitude],
                ],
                "color": color,
            }
        )

    hq_longitude, hq_latitude = 103.74, 1.24
    hq_star = []
    for point in range(10):
        radius = 0.22 if point % 2 == 0 else 0.09
        angle = math.pi / 2 + point * math.pi / 5
        hq_star.append(
            [
                hq_longitude + radius * math.cos(angle) / math.cos(math.radians(hq_latitude)),
                hq_latitude + radius * math.sin(angle),
            ]
        )
    hq = pd.DataFrame(
        [
            {
                "polygon": hq_star,
                "location_name": "Singapore HQ",
                "location_type": "HEADQUARTERS",
                "country": "SG",
            }
        ]
    )
    layers = [
        pdk.Layer(
            "PathLayer",
            data=route_paths,
            get_path="path",
            get_color="color",
            get_width=2,
            width_min_pixels=2,
            pickable=False,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=locations,
            get_position="[longitude, latitude]",
            get_radius=36000,
            get_fill_color="color",
            get_line_color=[255, 255, 255, 245],
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        ),
        pdk.Layer(
            "PolygonLayer",
            data=route_arrows,
            get_polygon="polygon",
            get_fill_color="color",
            get_line_color="color",
            get_line_width=1,
            line_width_min_pixels=1,
            stroked=True,
            filled=True,
            pickable=False,
        ),
        pdk.Layer(
            "PolygonLayer",
            data=hq,
            get_polygon="polygon",
            get_fill_color=[20, 46, 94, 255],
            get_line_color=[255, 255, 255, 255],
            get_line_width=2,
            stroked=True,
            filled=True,
            line_width_min_pixels=2,
            pickable=True,
        ),
    ]
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=4.5, longitude=111.5, zoom=3.0, pitch=0, bearing=0),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={
            "html": "<b>{location_name}</b><br/>{location_type}<br/>{country}",
            "style": {"backgroundColor": "#ffffff", "color": "#172b4d"},
        },
    )

    st.pydeck_chart(deck, width="stretch", height=540)

    st.markdown("### Legend")
    legend_items = [
        ("#142e5e", "Headquarters"),
        ("#da272d", "Factory"),
        ("#ee6f1d", "Regional DC"),
        ("#169ba5", "Country DC"),
        ("#2a7e36", "Local warehouse"),
        ("#7048ab", "Port / customs"),
    ]
    legend_columns = st.columns(len(legend_items))
    for column, (color, label) in zip(legend_columns, legend_items):
        column.markdown(
            f'<span style="display:inline-block;width:11px;height:11px;border-radius:50%;'
            f'background:{color};margin-right:7px;"></span>{label}',
            unsafe_allow_html=True,
        )
    st.markdown("**Solid dark line:** land / regional flow &nbsp;&nbsp; **Dashed blue line:** sea freight / customs")

    market_paths = [
        ("TH", "Thailand", "Factory -> Rayong RDC -> Bangkok / Chiang Mai DCs"),
        ("MY", "Malaysia", "Factory -> Malacca RDC -> Ipoh DC"),
        ("SG", "Singapore (HQ)", "Country DC -> local warehouses"),
        ("ID", "Indonesia", "Regional DCs -> Jakarta / Surabaya DCs"),
        ("PH", "Philippines", "Rayong RDC -> Manila port / customs -> warehouses"),
        ("VN", "Vietnam", "Rayong RDC -> HCMC port / customs -> warehouses"),
    ]
    st.markdown("### Country flows and warehouse labels")
    market_columns = st.columns(3)
    locations_by_country = get_locations().groupby("country")
    for index, (country_code, market, path) in enumerate(market_paths):
        with market_columns[index % 3]:
            with st.container(border=True):
                st.markdown(f"**{market}**")
                st.caption(path)
                country_locations = locations_by_country.get_group(country_code)
                warehouse_names = country_locations.loc[
                    country_locations["location_type"] == "LOCAL_WAREHOUSE", "location_name"
                ].tolist()
                if warehouse_names:
                    st.markdown("\n".join(f"- {name}" for name in warehouse_names))

    st.caption(
        "City-center coordinates are approximate display placements; they are not in the source database. "
        "Solid lines are land/regional lanes; dashed blue lines are sea freight and customs routes."
    )
    lane_view = lanes.rename(
        columns={
            "lane_id": "Lane",
            "origin_name": "Origin",
            "origin_type": "Origin type",
            "destination_name": "Destination",
            "destination_type": "Destination type",
            "mode": "Mode",
            "lead_time_days": "Lead time (days)",
            "weekly_capacity_kg": "Weekly capacity (kg)",
            "cold_chain_required": "Cold chain required",
        }
    )
    with st.expander(f"Lane details ({len(lane_view)})"):
        st.dataframe(
            lane_view[
                [
                    "Lane",
                    "Origin",
                    "Origin type",
                    "Destination",
                    "Destination type",
                    "Mode",
                    "Lead time (days)",
                    "Weekly capacity (kg)",
                    "Cold chain required",
                ]
            ],
            width="stretch",
            hide_index=True,
        )
def render_overview() -> None:
    products, locations, _ = require_database()
    st.title("Overview")
    st.caption("Revenue, category inventory coverage, and baseline supply-plan watchlist")

    revenue = get_revenue_summary().iloc[0]
    category_snapshot = get_category_snapshot()
    total_inventory_value = float(category_snapshot["Inventory value (USD)"].sum())
    risks = get_supply_demand_risks()
    shortage_count = int((risks["Plan gap (units)"] < 0).sum())
    largest_gap = int(risks["Plan gap (units)"].abs().max()) if not risks.empty else 0

    summary_columns = st.columns(4)
    summary_columns[0].metric("Revenue, last 12 months", f"${float(revenue['revenue_usd']):,.0f}")
    summary_columns[1].metric("Inventory value", f"${total_inventory_value:,.0f}")
    summary_columns[2].metric("Product categories", f"{len(category_snapshot)}")
    summary_columns[3].metric("Largest category plan gap", f"{largest_gap:,} units")
    st.caption(f"Revenue period: {revenue['start_date']} to {revenue['end_date']}.")

    st.subheader("Days of inventory by category")
    coverage = category_snapshot.copy()
    coverage["Days of inventory"] = (
        coverage["On hand (units)"] * 90 / coverage["Sales, last 90 days (units)"].replace(0, pd.NA)
    ).round(1)
    st.bar_chart(coverage.set_index("Category")[["Days of inventory"]])
    st.dataframe(coverage, width="stretch", hide_index=True)
    st.caption(
        "Coverage uses opening on-hand stock dated 2026-10-01 divided by average daily sales over the "
        "90 days ending 2026-09-30. Inventory value uses the product master unit cost."
    )

    st.subheader("Top demand-supply balancing risks")
    st.caption(
        "Monthly BASE demand compared with planned production by category. This is a plan-gap indicator, "
        "not a projected stockout calculation; it excludes opening inventory and scheduled receipts. "
        "PROPOSED production is not approved."
    )
    if shortage_count:
        st.warning(f"{shortage_count} category-month row(s) have BASE demand above planned production.")
    elif not risks.empty:
        st.info("No category-month has BASE demand above planned production. The table ranks the largest plan surpluses.")
    st.dataframe(risks.head(10), width="stretch", hide_index=True)

    with st.expander("Product and location master data"):
        product_tab, location_tab = st.tabs(["Products", "Locations"])
        with product_tab:
            st.dataframe(products, width="stretch", hide_index=True)
        with location_tab:
            st.dataframe(locations, width="stretch", hide_index=True)

    quality_checks = get_quality_checks()
    st.subheader("Data quality checks")
    if (quality_checks["Status"] == "FAIL").any():
        st.error("One or more data-quality checks failed.")
    elif (quality_checks["Status"] == "REVIEW").any():
        st.warning("One or more data-quality checks need review.")
    else:
        st.success("All data-quality checks passed.")
    st.dataframe(quality_checks, width="stretch", hide_index=True)


def render_historic_sales() -> None:
    _, _, stocked_pairs = require_database()
    st.title("Historic sales and future forecast")
    st.caption("Choose a stocked product and warehouse, then review the history and BASE demand plan")

    with st.sidebar:
        st.divider()
        st.subheader("Filter data")
        location_options = stocked_pairs[["location_id", "location_name", "country"]].drop_duplicates()
        location_ids = location_options["location_id"].tolist()
        location_names = {
            row.location_id: f"{row.location_name} ({row.country})"
            for row in location_options.itertuples(index=False)
        }
        selected_location = st.selectbox(
            "Warehouse",
            location_ids,
            format_func=lambda location_id: location_names[location_id],
        )
        available_products = stocked_pairs[stocked_pairs["location_id"] == selected_location]
        product_ids = available_products["sku_id"].tolist()
        product_names = {
            row.sku_id: f"{row.sku_id} | {row.flavor} | {row.product_family} | {row.consumer_pack_g} g"
            for row in available_products.itertuples(index=False)
        }
        selected_product = st.selectbox(
            "Product",
            product_ids,
            format_func=lambda sku_id: product_names[sku_id],
        )

    sales = get_sales(selected_product, selected_location)
    forecast = get_forecast(selected_product, selected_location)
    inventory = get_inventory(selected_product, selected_location)
    if not inventory.empty:
        inventory["expiry_date"] = pd.to_datetime(inventory["expiry_date"])
        inventory["as_of_date"] = pd.to_datetime(inventory["as_of_date"])
        inventory["days_to_expiry"] = (inventory["expiry_date"] - inventory["as_of_date"]).dt.days

    total_sales = int(sales["sales_units"].sum()) if not sales.empty else 0
    total_forecast = int(forecast["forecast_units"].sum()) if not forecast.empty else 0
    total_on_hand = int(inventory["on_hand_units"].sum()) if not inventory.empty else 0
    expiring_soon = (
        int(inventory.loc[inventory["days_to_expiry"].between(0, 7), "on_hand_units"].sum())
        if not inventory.empty
        else 0
    )
    st.subheader(f"{selected_product} at {location_names[selected_location]}")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Sales (units)", f"{total_sales:,}")
    metric_columns[1].metric("BASE demand (units)", f"{total_forecast:,}")
    metric_columns[2].metric("On hand (units)", f"{total_on_hand:,}")
    metric_columns[3].metric("Expiring in 7 days", f"{expiring_soon:,}")

    st.subheader("Ask about the baseline")
    st.caption("Answers use the selected product and warehouse. This version reads the database directly; it does not use an AI service.")
    with st.form("baseline_question_form"):
        prompt_column, ask_column = st.columns([6, 1])
        with prompt_column:
            question = st.text_input(
                "Question",
                placeholder="Example: Which month has the highest baseline demand?",
                label_visibility="collapsed",
            )
        with ask_column:
            submitted = st.form_submit_button("Ask", width="stretch")

    if "baseline_question_response" not in st.session_state:
        st.session_state["baseline_question_response"] = None
    if submitted and question.strip():
        answer, answer_table = answer_baseline_question(
            question.strip(), selected_product, selected_location, sales, forecast, inventory
        )
        st.session_state["baseline_question_response"] = (
            selected_product, selected_location, question.strip(), answer, answer_table
        )
    response = st.session_state["baseline_question_response"]
    if response and response[:2] == (selected_product, selected_location):
        st.markdown(f"**Answer**  \n{response[3]}")
        if response[4] is not None and not response[4].empty:
            st.dataframe(response[4], width="stretch", hide_index=True)

    chart_columns = st.columns(2)
    with chart_columns[0]:
        st.subheader("Historical monthly sales")
        if sales.empty:
            st.info("No historical sales are available for this product and warehouse.")
        else:
            st.line_chart(sales.set_index("month").rename(columns={"sales_units": "Sales (units)"}))
    with chart_columns[1]:
        st.subheader("Planned demand by month")
        st.caption("BASE scenario from the demand plan")
        if forecast.empty:
            st.info("No BASE demand plan is available for this product and warehouse.")
        else:
            st.bar_chart(forecast.set_index("month").rename(columns={"forecast_units": "Forecast (units)"}))

    with st.expander("Inventory batches for this product and warehouse"):
        if inventory.empty:
            st.info("No opening inventory batches are recorded for this selection.")
        else:
            batch_view = inventory.rename(
                columns={
                    "batch_id": "Batch",
                    "production_date": "Production date",
                    "expiry_date": "Expiry date",
                    "on_hand_units": "On hand (units)",
                    "usable_units": "Usable (units)",
                    "days_to_expiry": "Days to expiry at snapshot",
                }
            )
            st.dataframe(
                batch_view[
                    [
                        "Batch",
                        "Production date",
                        "Expiry date",
                        "Days to expiry at snapshot",
                        "On hand (units)",
                        "Usable (units)",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )


def render_inventory_snapshot() -> None:
    require_database()
    st.title("Inventory snapshot by category")
    st.caption("Opening inventory on 2026-10-01, valued at standard product cost")
    snapshot = get_category_snapshot()
    snapshot["Days of inventory"] = (
        snapshot["On hand (units)"] * 90 / snapshot["Sales, last 90 days (units)"].replace(0, pd.NA)
    ).round(1)
    summary_columns = st.columns(3)
    summary_columns[0].metric("Total inventory value", f"${snapshot['Inventory value (USD)'].sum():,.0f}")
    summary_columns[1].metric("Total units on hand", f"{snapshot['On hand (units)'].sum():,.0f}")
    summary_columns[2].metric(
        "Categories above 90 days",
        f"{int((snapshot['Days of inventory'] > 90).sum())} / {len(snapshot)}",
    )
    st.bar_chart(snapshot.set_index("Category")[["Inventory value (USD)"]])
    st.dataframe(snapshot, width="stretch", hide_index=True)
    st.caption(
        "Days of inventory = category on-hand units divided by average daily sales over the 90 days "
        "ending 2026-09-30. Inventory is valued using item_master.unit_cost_usd."
    )


st.sidebar.title("BNB Co. | S&OP")
page = st.navigation(
    [
        st.Page(render_network_map, title="Network map", icon=":material/hub:"),
        st.Page(render_overview, title="Overview", icon=":material/space_dashboard:"),
        st.Page(render_historic_sales, title="Historic sales and future forecast", icon=":material/show_chart:"),
        st.Page(render_inventory_snapshot, title="Inventory snapshot by category", icon=":material/inventory_2:"),
    ],
    position="sidebar",
)
page.run()