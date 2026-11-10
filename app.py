import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import streamlit as st
import pandas as pd
import plotly.express as px


def get_api_json(url):
    with urlopen(url, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


@st.cache_data(ttl=30)
def get_price_bars(api_url, ticker):
    query = urlencode({"symbol": ticker, "limit": 100})
    try:
        result = get_api_json(f"{api_url}/price-bars?{query}")
        return result.get("items", []), None
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        return [], str(error)

# App configuration
st.set_page_config(page_title="Stock Market Dashboard", layout="wide")

st.title("Stock Market Intelligence Dashboard")
st.write("Real-time stock analytics, sentiment tracking, and research assistant.")

# Sidebar controls
st.sidebar.subheader("Settings")
ticker = st.sidebar.text_input("Enter Ticker", value="AAPL")
default_api_url = os.getenv("BACKEND_API_URL", "http://localhost:8605")
api_url = st.sidebar.text_input("Backend API URL", value=default_api_url).strip().rstrip("/")

try:
    get_api_json(f"{api_url}/health")
    st.sidebar.success("Backend connected")
    backend_connected = True
except (HTTPError, URLError, TimeoutError, ValueError):
    st.sidebar.warning("Backend unavailable")
    backend_connected = False

# Main layout tabs
tab1, tab2 = st.tabs(["Chat Assistant", "News Timeline"])

# Tab 1: Chat interface
with tab1:
    st.subheader(f"Analysis Assistant - {ticker}")
    
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": f"Hey! Ask me anything about {ticker} stock or recent news."}
        ]

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    if prompt := st.chat_input("Type your question here..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
            
        reply = "The assistant is a UI demo. A chat service is not connected yet."
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.write(reply)

# Tab 2: Timeline graph and table
with tab2:
    st.subheader(f"News & Event Timeline for {ticker}")
    

    st.markdown("#### Saved market history")
    if backend_connected and ticker.strip():
        price_bars, price_error = get_price_bars(api_url, ticker.strip().upper())
        if price_bars:
            prices = pd.DataFrame(price_bars)
            prices["bar_date"] = pd.to_datetime(prices["bar_date"])
            prices = prices.sort_values("bar_date")
            st.line_chart(prices.set_index("bar_date")["close"], y_label="Closing price")
            with st.expander("View saved price-bar records"):
                st.dataframe(prices, width="stretch", hide_index=True)
        elif price_error:
            st.info("Could not load saved prices from the API. " + price_error)
        else:
            st.info("The backend is connected, but there are no saved price bars for this ticker yet.")
    else:
        st.info("Start the project backend to load saved price bars. The event timeline below is sample data.")

    st.markdown("#### Sample news and event timeline")
    st.caption("News ingestion is not connected to the backend yet.")
    
    # Sample data for testing UI
    df = pd.DataFrame([
        {"Date": "2026-11-01", "Event": "Q3 Earnings Beat", "Impact": 0.8, "Category": "Earnings"},
        {"Date": "2026-11-03", "Event": "Fed Rate Announcement", "Impact": -0.3, "Category": "Macro"},
        {"Date": "2026-11-05", "Event": "Product Release", "Impact": 0.6, "Category": "Product"},
        {"Date": "2026-11-07", "Event": "Analyst Upgrade", "Impact": 0.9, "Category": "Analyst"},
    ])

    # Scatter plot for timeline
    fig = px.scatter(
        df, 
        x="Date", 
        y="Impact", 
        color="Category",
        hover_name="Event",
        title=f"Sentiment Impact Over Time ({ticker})"
    )
    st.plotly_chart(fig, width="stretch")
    
    # Data table view
    st.dataframe(df, width="stretch")
