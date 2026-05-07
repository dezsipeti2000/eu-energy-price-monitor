import os
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st
import plotly.express as px
import eurostat
import requests
from dotenv import load_dotenv
from entsoe import EntsoePandasClient


# --------------------------------------------------
# Basic setup
# --------------------------------------------------

load_dotenv()
def get_secret(secret_name: str):
    """
    Reads API keys from local .env first.
    If not found, reads from Streamlit Cloud secrets.
    """
    value = os.getenv(secret_name)

    if value:
        return value

    try:
        return st.secrets[secret_name]
    except Exception:
        return None

st.set_page_config(
    page_title="EU Energy Price Monitor",
    layout="wide"
)

st.title("EU Energy Price Monitor")
st.write(
    "EU energy market monitoring using ENTSO-E electricity prices, "
    "GIE gas storage data, Eurostat industrial benchmarks, and an experimental energy stress index."
)

# --------------------------------------------------
# Data loading functions
# --------------------------------------------------

@st.cache_data(ttl=60 * 60)
def load_entsoe_prices_for_one_zone(country_code: str, days: int) -> pd.DataFrame:
    """
    Loads ENTSO-E day-ahead electricity prices for one bidding zone.
    Cache refreshes every 1 hour.
    """

    api_key = get_secret("ENTSOE_API_KEY")

    if not api_key:
        raise ValueError("ENTSOE_API_KEY not found. Please check your .env file.")

    client = EntsoePandasClient(api_key=api_key)

    start = pd.Timestamp.now(tz="Europe/Brussels") - pd.Timedelta(days=days)
    end = pd.Timestamp.now(tz="Europe/Brussels")

    prices = client.query_day_ahead_prices(
        country_code,
        start=start,
        end=end
    )

    df = prices.reset_index()
    df.columns = ["date_time", "price_eur_mwh"]
    df["country_code"] = country_code
    df["date_time"] = pd.to_datetime(df["date_time"])

    return df


@st.cache_data(ttl=60 * 60)
def load_entsoe_prices_multiple_zones(selected_zones: dict, days: int) -> pd.DataFrame:
    """
    Loads ENTSO-E prices for multiple bidding zones and combines them.
    """

    all_data = []

    for country_name, country_code in selected_zones.items():
        try:
            temp = load_entsoe_prices_for_one_zone(country_code, days)
            temp["country_name"] = country_name
            all_data.append(temp)
        except Exception as error:
            st.warning(f"Could not load data for {country_name} ({country_code}).")
            st.write(error)

    if not all_data:
        return pd.DataFrame()

    return pd.concat(all_data, ignore_index=True)


@st.cache_data(ttl=24 * 60 * 60)
def load_eurostat_dataset(dataset_code: str) -> pd.DataFrame:
    """
    Loads Eurostat data and transforms it into long format.
    Cache refreshes every 24 hours.
    """

    raw = eurostat.get_data_df(dataset_code, flags=False)

    raw.columns = [str(col).replace("\\", "_") for col in raw.columns]

    time_cols = [col for col in raw.columns if str(col)[:4].isdigit()]
    id_cols = [col for col in raw.columns if col not in time_cols]

    long_df = raw.melt(
        id_vars=id_cols,
        value_vars=time_cols,
        var_name="period",
        value_name="value"
    )

    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
    long_df = long_df.dropna(subset=["value"])

    return long_df

@st.cache_data(ttl=6 * 60 * 60)
def load_gie_eu_storage(days: int = 60) -> pd.DataFrame:
    """
    Loads EU-level gas storage data from GIE AGSI.
    Cache refreshes every 6 hours.
    """

    api_key = get_secret("GIE_API_KEY")

    if not api_key:
        raise ValueError("GIE_API_KEY not found. Please check your .env file.")

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    url = "https://agsi.gie.eu/api"

    params = {
        "type": "eu",
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "size": 300,
        "page": 1,
    }

    headers = {
        "x-key": api_key
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    json_data = response.json()
    data = json_data.get("data", [])

    if not data:
        raise ValueError("No data returned from GIE AGSI API.")

    df = pd.DataFrame(data)

    numeric_columns = [
        "gasInStorage",
        "workingGasVolume",
        "consumption",
        "consumptionFull",
        "injection",
        "withdrawal",
        "netWithdrawal",
        "injectionCapacity",
        "withdrawalCapacity",
        "contractedCapacity",
        "availableCapacity",
        "coveredCapacity",
        "full",
        "trend",
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["gasDayStart"] = pd.to_datetime(df["gasDayStart"])
    df = df.sort_values("gasDayStart")

    return df
# --------------------------------------------------
# Sidebar navigation
# --------------------------------------------------

page = st.sidebar.radio(
    "Choose dashboard page",
    [
        "ENTSO-E live electricity prices",
        "GIE gas storage monitor",
        "Energy stress index",
        "Eurostat industrial energy prices",
        "Modules / roadmap"
    ]
)

# --------------------------------------------------
# Page 1: ENTSO-E
# --------------------------------------------------

if page == "ENTSO-E live electricity prices":

    st.header("ENTSO-E day-ahead electricity prices")

    st.write(
        "This page shows near-live wholesale day-ahead electricity prices. "
        "The data comes from the ENTSO-E Transparency Platform through your API token."
    )

    bidding_zones = {
        "Hungary": "HU",
        "Germany / Luxembourg": "DE_LU",
        "France": "FR",
        "Austria": "AT",
        "Poland": "PL",
        "Slovakia": "SK",
        "Czechia": "CZ",
        "Romania": "RO",
        "Netherlands": "NL",
        "Belgium": "BE",
        "Spain": "ES",
        "Italy North": "IT_NORD",
    }

    selected_country_names = st.sidebar.multiselect(
        "Choose countries / bidding zones",
        list(bidding_zones.keys()),
        default=["Hungary", "Germany / Luxembourg", "France"]
    )

    days = st.sidebar.slider(
        "How many days should be shown?",
        min_value=1,
        max_value=30,
        value=7
    )

    selected_zones = {
        name: bidding_zones[name]
        for name in selected_country_names
    }

    if not selected_zones:
        st.warning("Please choose at least one country / bidding zone.")
        st.stop()

    with st.spinner("Loading ENTSO-E data..."):
        df = load_entsoe_prices_multiple_zones(selected_zones, days)

    if df.empty:
        st.error("No ENTSO-E data could be loaded.")
        st.stop()

    # Latest observation per country
    latest_df = (
        df.sort_values("date_time")
        .groupby("country_name")
        .tail(1)
        .sort_values("price_eur_mwh", ascending=False)
    )

    average_df = (
        df.groupby("country_name")["price_eur_mwh"]
        .agg(["mean", "min", "max"])
        .reset_index()
        .rename(
            columns={
                "mean": "average_price",
                "min": "minimum_price",
                "max": "maximum_price"
            }
        )
    )

    ranking_df = latest_df[["country_name", "country_code", "date_time", "price_eur_mwh"]].merge(
        average_df,
        on="country_name",
        how="left"
    )

    # Main metrics
    latest_overall = df.sort_values("date_time").iloc[-1]["price_eur_mwh"]
    average_overall = df["price_eur_mwh"].mean()
    min_overall = df["price_eur_mwh"].min()
    max_overall = df["price_eur_mwh"].max()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Latest loaded price", f"{latest_overall:.2f} EUR/MWh")

    with col2:
        st.metric("Average price", f"{average_overall:.2f} EUR/MWh")

    with col3:
        st.metric("Minimum price", f"{min_overall:.2f} EUR/MWh")

    with col4:
        st.metric("Maximum price", f"{max_overall:.2f} EUR/MWh")

    # Line chart
    st.subheader("Price trend")

    fig = px.line(
        df,
        x="date_time",
        y="price_eur_mwh",
        color="country_name",
        markers=True,
        title="Day-ahead electricity price comparison"
    )

    fig.update_layout(
        xaxis_title="Date and time",
        yaxis_title="Price [EUR/MWh]",
        legend_title="Country / bidding zone"
    )

    st.plotly_chart(fig, use_container_width=True)

    # Ranking table
    st.subheader("Current country ranking")

    ranking_display = ranking_df.copy()
    ranking_display["price_eur_mwh"] = ranking_display["price_eur_mwh"].round(2)
    ranking_display["average_price"] = ranking_display["average_price"].round(2)
    ranking_display["minimum_price"] = ranking_display["minimum_price"].round(2)
    ranking_display["maximum_price"] = ranking_display["maximum_price"].round(2)

    st.dataframe(
        ranking_display.rename(
            columns={
                "country_name": "Country",
                "country_code": "ENTSO-E code",
                "date_time": "Latest timestamp",
                "price_eur_mwh": "Latest price [EUR/MWh]",
                "average_price": "Average [EUR/MWh]",
                "minimum_price": "Minimum [EUR/MWh]",
                "maximum_price": "Maximum [EUR/MWh]"
            }
        ),
        use_container_width=True
    )

    # Bar chart for latest prices
    st.subheader("Latest price comparison")

    fig_bar = px.bar(
        ranking_display,
        x="country_name",
        y="price_eur_mwh",
        title="Latest day-ahead price by country / bidding zone"
    )

    fig_bar.update_layout(
        xaxis_title="Country / bidding zone",
        yaxis_title="Latest price [EUR/MWh]"
    )

    st.plotly_chart(fig_bar, use_container_width=True)

    # Download
    st.subheader("Download ENTSO-E data")

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download ENTSO-E data as CSV",
        data=csv,
        file_name=f"entsoe_day_ahead_prices_{datetime.now().date()}.csv",
        mime="text/csv"
    )

    with st.expander("Show full raw ENTSO-E data"):
        st.dataframe(df.sort_values("date_time", ascending=False), use_container_width=True)


# --------------------------------------------------
# Page 2: Eurostat
# --------------------------------------------------

if page == "GIE gas storage monitor":

    st.header("GIE AGSI gas storage monitor")

    st.write(
        "This page shows EU-level gas storage data from GIE AGSI. "
        "Gas storage is important because it strongly affects European gas-price risk."
    )

    storage_days = st.sidebar.slider(
        "How many days of gas storage data should be shown?",
        min_value=30,
        max_value=365,
        value=90
    )

    with st.spinner("Loading GIE AGSI gas storage data..."):
        gie_df = load_gie_eu_storage(days=storage_days)

    if gie_df.empty:
        st.error("No GIE gas storage data loaded.")
        st.stop()

    latest = gie_df.sort_values("gasDayStart").iloc[-1]

    latest_full = latest["full"]
    latest_gas = latest["gasInStorage"]
    latest_capacity = latest["workingGasVolume"]
    latest_injection = latest["injection"]
    latest_withdrawal = latest["withdrawal"]

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Storage full", f"{latest_full:.2f} %")

    with col2:
        st.metric("Gas in storage", f"{latest_gas:.2f} TWh")

    with col3:
        st.metric("Working gas volume", f"{latest_capacity:.2f} TWh")

    with col4:
        st.metric("Injection", f"{latest_injection:.2f} GWh/day")

    with col5:
        st.metric("Withdrawal", f"{latest_withdrawal:.2f} GWh/day")

    st.subheader("EU gas storage filling level")

    fig_full = px.line(
        gie_df,
        x="gasDayStart",
        y="full",
        markers=True,
        title="EU gas storage filling level"
    )

    fig_full.update_layout(
        xaxis_title="Date",
        yaxis_title="Storage level [%]"
    )

    st.plotly_chart(fig_full, use_container_width=True)

    st.subheader("Gas in storage")

    fig_storage = px.line(
        gie_df,
        x="gasDayStart",
        y="gasInStorage",
        markers=True,
        title="EU gas in storage"
    )

    fig_storage.update_layout(
        xaxis_title="Date",
        yaxis_title="Gas in storage [TWh]"
    )

    st.plotly_chart(fig_storage, use_container_width=True)

    st.subheader("Injection and withdrawal")

    flow_df = gie_df.melt(
        id_vars=["gasDayStart"],
        value_vars=["injection", "withdrawal"],
        var_name="Flow type",
        value_name="Value"
    )

    fig_flow = px.line(
        flow_df,
        x="gasDayStart",
        y="Value",
        color="Flow type",
        markers=True,
        title="EU gas storage injection and withdrawal"
    )

    fig_flow.update_layout(
        xaxis_title="Date",
        yaxis_title="Flow [GWh/day]"
    )

    st.plotly_chart(fig_flow, use_container_width=True)

    st.subheader("Latest gas storage data")

    columns_to_show = [
        "gasDayStart",
        "gasInStorage",
        "workingGasVolume",
        "full",
        "injection",
        "withdrawal",
        "trend",
        "status"
    ]

    available_columns = [
        col for col in columns_to_show
        if col in gie_df.columns
    ]

    st.dataframe(
        gie_df[available_columns].sort_values("gasDayStart", ascending=False),
        use_container_width=True
    )

    csv_gie = gie_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download GIE gas storage data as CSV",
        data=csv_gie,
        file_name=f"gie_agsi_eu_gas_storage_{datetime.now().date()}.csv",
        mime="text/csv"
    )

    st.caption("Data source: GIE AGSI / Gas Infrastructure Europe.")

# --------------------------------------------------
# Page: Energy Stress Index
# --------------------------------------------------

if page == "Energy stress index":

    st.header("EU Energy Stress Index")

    st.write(
        "This page creates a simple experimental energy stress signal by combining "
        "electricity market prices from ENTSO-E with EU gas storage data from GIE AGSI."
    )

    st.warning(
        "This is a beginner research prototype, not an official market indicator."
    )

    # -----------------------------
    # Settings
    # -----------------------------

    bidding_zones = {
        "Hungary": "HU",
        "Germany / Luxembourg": "DE_LU",
        "France": "FR",
        "Austria": "AT",
        "Poland": "PL",
        "Slovakia": "SK",
        "Czechia": "CZ",
        "Romania": "RO",
        "Netherlands": "NL",
        "Belgium": "BE",
        "Spain": "ES",
        "Italy North": "IT_NORD",
    }

    selected_country_name = st.sidebar.selectbox(
        "Choose electricity market zone",
        list(bidding_zones.keys())
    )

    selected_country_code = bidding_zones[selected_country_name]

    stress_days = st.sidebar.slider(
        "Electricity price lookback period",
        min_value=3,
        max_value=30,
        value=7
    )

    # -----------------------------
    # Load data
    # -----------------------------

    with st.spinner("Loading ENTSO-E electricity data..."):
        electricity_df = load_entsoe_prices_for_one_zone(
            selected_country_code,
            stress_days
        )

    with st.spinner("Loading GIE gas storage data..."):
        gas_df = load_gie_eu_storage(days=90)

    if electricity_df.empty or gas_df.empty:
        st.error("Not enough data to calculate the stress index.")
        st.stop()

    # -----------------------------
    # Latest values
    # -----------------------------

    latest_electricity_price = (
        electricity_df
        .sort_values("date_time")
        .iloc[-1]["price_eur_mwh"]
    )

    average_electricity_price = electricity_df["price_eur_mwh"].mean()
    max_electricity_price = electricity_df["price_eur_mwh"].max()

    latest_gas = gas_df.sort_values("gasDayStart").iloc[-1]

    latest_storage_full = latest_gas["full"]
    latest_injection = latest_gas["injection"]
    latest_withdrawal = latest_gas["withdrawal"]

    # -----------------------------
    # Simple scoring logic
    # -----------------------------
    # Electricity score:
    # 50 EUR/MWh = low stress
    # 200 EUR/MWh or more = very high stress

    electricity_score = ((latest_electricity_price - 50) / (200 - 50)) * 100
    electricity_score = max(0, min(100, electricity_score))

    # Gas storage score:
    # 90% full = low stress
    # 20% full = very high stress

    gas_storage_score = ((90 - latest_storage_full) / (90 - 20)) * 100
    gas_storage_score = max(0, min(100, gas_storage_score))

    # Flow score:
    # If withdrawal is higher than injection, stress increases.
    # If injection is higher, stress is lower.

    net_withdrawal = latest_withdrawal - latest_injection

    if net_withdrawal <= 0:
        flow_score = 20
    elif net_withdrawal < 1000:
        flow_score = 50
    elif net_withdrawal < 3000:
        flow_score = 75
    else:
        flow_score = 100

    # Final index
    # Electricity is weighted 50%, gas storage 35%, flow 15%.

    energy_stress_index = (
        0.50 * electricity_score
        + 0.35 * gas_storage_score
        + 0.15 * flow_score
    )

    # -----------------------------
    # Category
    # -----------------------------

    if energy_stress_index < 25:
        category = "Normal"
    elif energy_stress_index < 50:
        category = "Elevated"
    elif energy_stress_index < 75:
        category = "High stress"
    else:
        category = "Crisis-level stress"

    # -----------------------------
    # Display metrics
    # -----------------------------

    st.subheader("Current energy stress signal")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Energy Stress Index",
            f"{energy_stress_index:.1f} / 100"
        )

    with col2:
        st.metric(
            "Risk category",
            category
        )

    with col3:
        st.metric(
            "Latest electricity price",
            f"{latest_electricity_price:.2f} EUR/MWh"
        )

    with col4:
        st.metric(
            "EU gas storage full",
            f"{latest_storage_full:.2f} %"
        )

    st.subheader("Index components")

    component_df = pd.DataFrame(
        {
            "Component": [
                "Electricity price stress",
                "Gas storage stress",
                "Gas flow stress"
            ],
            "Score": [
                electricity_score,
                gas_storage_score,
                flow_score
            ],
            "Weight": [
                0.50,
                0.35,
                0.15
            ]
        }
    )

    component_df["Weighted contribution"] = (
        component_df["Score"] * component_df["Weight"]
    )

    st.dataframe(
        component_df.round(2),
        use_container_width=True
    )

    fig_components = px.bar(
        component_df,
        x="Component",
        y="Score",
        title="Energy stress index components"
    )

    fig_components.update_layout(
        xaxis_title="Component",
        yaxis_title="Score [0–100]"
    )

    st.plotly_chart(fig_components, use_container_width=True)

    st.subheader("Interpretation")

    st.write(f"""
    For **{selected_country_name}**, the current experimental energy stress index is:

    **{energy_stress_index:.1f} / 100 — {category}**

    The index is based on three simple components:

    1. **Electricity price stress** — higher day-ahead electricity prices increase the score.
    2. **Gas storage stress** — lower EU gas storage levels increase the score.
    3. **Gas flow stress** — high withdrawals compared to injections increase the score.

    This can later be improved into a PhD-level model using statistical normalization,
    historical percentiles, sector-specific weights, and econometric validation.
    """)

    st.subheader("Underlying data")

    with st.expander("Show electricity data"):
        st.dataframe(electricity_df.sort_values("date_time", ascending=False), use_container_width=True)

    with st.expander("Show gas storage data"):
        st.dataframe(gas_df.sort_values("gasDayStart", ascending=False), use_container_width=True)

if page == "Eurostat industrial energy prices":

    st.header("Eurostat industrial energy price benchmarks")

    st.write(
        "This page shows official Eurostat industrial / non-household energy price data. "
        "These datasets are not hourly live market prices, but they are very useful for "
        "long-term industrial cost comparison between EU countries."
    )

    datasets = {
        "Industrial electricity prices — nrg_pc_205": "nrg_pc_205",
        "Industrial gas prices — nrg_pc_203": "nrg_pc_203",
    }

    selected_dataset_name = st.sidebar.selectbox(
        "Choose Eurostat dataset",
        list(datasets.keys())
    )

    dataset_code = datasets[selected_dataset_name]

    with st.spinner("Loading Eurostat data..."):
        euro_df = load_eurostat_dataset(dataset_code)

    geo_cols = [col for col in euro_df.columns if "geo" in col.lower()]

    if not geo_cols:
        st.error("Could not find the country column in this Eurostat dataset.")
        st.stop()

    geo_col = geo_cols[0]

    available_countries = sorted(euro_df[geo_col].dropna().astype(str).unique())

    default_countries = [
        c for c in ["EU27_2020", "DE", "FR", "IT", "HU", "PL", "SK", "CZ", "RO"]
        if c in available_countries
    ]

    selected_countries = st.sidebar.multiselect(
        "Choose countries",
        available_countries,
        default=default_countries
    )

    filtered = euro_df[euro_df[geo_col].astype(str).isin(selected_countries)].copy()

    st.sidebar.subheader("Eurostat filters")

    dimension_cols = [
        col for col in filtered.columns
        if col not in ["period", "value", geo_col]
    ]

    for col in dimension_cols:
        values = sorted(filtered[col].dropna().astype(str).unique())

        if 1 < len(values) <= 50:
            selected_value = st.sidebar.selectbox(
                f"{col}",
                values,
                index=0
            )
            filtered = filtered[filtered[col].astype(str) == selected_value]

    if filtered.empty:
        st.warning("No Eurostat data for this filter combination.")
        st.stop()

    latest_period = filtered["period"].max()
    latest = filtered[filtered["period"] == latest_period]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Dataset", dataset_code)

    with col2:
        st.metric("Latest period", latest_period)

    with col3:
        st.metric("Selected countries", len(selected_countries))

    st.subheader("Latest Eurostat values")

    st.dataframe(
        latest[[geo_col, "period", "value"]].sort_values("value", ascending=False),
        use_container_width=True
    )

    st.subheader("Eurostat trend")

    fig_eurostat = px.line(
        filtered,
        x="period",
        y="value",
        color=geo_col,
        markers=True,
        title=selected_dataset_name
    )

    fig_eurostat.update_layout(
        xaxis_title="Period",
        yaxis_title="Value",
        legend_title="Country"
    )

    st.plotly_chart(fig_eurostat, use_container_width=True)

    csv_eurostat = filtered.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download Eurostat filtered data as CSV",
        data=csv_eurostat,
        file_name=f"{dataset_code}_filtered_{datetime.now().date()}.csv",
        mime="text/csv"
    )

    with st.expander("Show full filtered Eurostat data"):
        st.dataframe(filtered, use_container_width=True)


# --------------------------------------------------
# Page: Modules / roadmap
# --------------------------------------------------

if page == "Modules / roadmap":

    st.header("Modules and development roadmap")

    st.write(
        "This page summarizes the current modules of the EU Energy Price Monitor "
        "and the next planned development steps."
    )

    st.subheader("Implemented modules")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
            ### ENTSO-E electricity prices
            **Status:** active  
            **Purpose:** near-live day-ahead electricity price monitoring  
            **Output:** price trend, country comparison, ranking table, CSV export  
            """
        )

        st.markdown(
            """
            ### GIE AGSI gas storage monitor
            **Status:** active  
            **Purpose:** EU gas storage risk monitoring  
            **Output:** storage level, gas in storage, injection, withdrawal, CSV export  
            """
        )

    with col2:
        st.markdown(
            """
            ### Energy Stress Index
            **Status:** active experimental module  
            **Purpose:** combine electricity price pressure and gas storage conditions  
            **Output:** 0–100 stress score and qualitative risk category  
            """
        )

        st.markdown(
            """
            ### Eurostat industrial benchmarks
            **Status:** active  
            **Purpose:** official industrial electricity and gas price comparison  
            **Output:** long-term country-level industrial price trends  
            """
        )

    st.subheader("Current data sources")

    sources_df = pd.DataFrame(
        {
            "Source": [
                "ENTSO-E Transparency Platform",
                "GIE AGSI",
                "Eurostat"
            ],
            "Used for": [
                "Day-ahead electricity prices",
                "EU gas storage data",
                "Industrial electricity and gas price benchmarks"
            ],
            "Update character": [
                "Near-live / hourly-daily",
                "Daily",
                "Semi-annual official statistics"
            ],
            "Status": [
                "Connected",
                "Connected",
                "Connected"
            ]
        }
    )

    st.dataframe(sources_df, use_container_width=True)

    st.subheader("Next development modules")

    roadmap_df = pd.DataFrame(
        {
            "Priority": [
                1,
                2,
                3,
                4,
                5,
                6
            ],
            "Module": [
                "EU ETS carbon price",
                "TTF gas benchmark",
                "Automatic alerts",
                "Forecasting model",
                "Sector exposure model",
                "Dashboard design upgrade"
            ],
            "Why it matters": [
                "Carbon cost is highly relevant for steel, cement, chemicals and power generation.",
                "TTF is one of the most important gas price benchmarks in Europe.",
                "Alerts turn the dashboard into a monitoring and decision-support tool.",
                "Forecasting connects the monitor directly to econometric research.",
                "Different sectors react differently to electricity, gas and carbon price shocks.",
                "A cleaner interface makes the tool more professional for supervisors and companies."
            ],
            "Suggested status": [
                "Next",
                "Next",
                "After price benchmarks",
                "Later",
                "Later",
                "Continuous"
            ]
        }
    )

    st.dataframe(roadmap_df, use_container_width=True)

    st.subheader("Recommended next build order")

    st.markdown(
        """
        1. **Add EU ETS carbon price**  
        2. **Add TTF gas benchmark**  
        3. **Improve the Energy Stress Index using historical percentiles**  
        4. **Add automatic alerts**  
        5. **Create sector-specific stress scores for steel, chemicals, cement, aluminium and fertilizer**  
        6. **Add forecasting and scenario analysis**
        """
    )

    st.info(
        "The dashboard already contains the core monitoring structure. "
        "The next major improvement should be adding market benchmarks: EU ETS and TTF gas."
    )