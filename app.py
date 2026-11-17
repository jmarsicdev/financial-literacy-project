import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import streamlit as st
import pandas as pd

API_ERRORS = (HTTPError, URLError, TimeoutError, ValueError)


def get_api_json(url, timeout=4):
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_api_json(url, payload=None, timeout=180):
    data = json.dumps(payload or {}).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@st.cache_data(ttl=30)
def get_price_bars(api_url, ticker):
    query = urlencode({"symbol": ticker, "limit": 100})
    try:
        result = get_api_json(f"{api_url}/price-bars?{query}")
        return result.get("items", []), None
    except API_ERRORS as error:
        return [], str(error)


@st.cache_data(ttl=300)
def get_risk_profile(api_url, ticker):
    """Historical risk profile from the Spark clustering job. None when not computed."""
    try:
        return get_api_json(f"{api_url}/risk-profiles/{quote(ticker)}?history=12"), None
    except HTTPError as error:
        return None, None if error.code == 404 else str(error)
    except API_ERRORS as error:
        return None, str(error)


@st.cache_data(ttl=60)
def get_stored_news(api_url, limit=50):
    try:
        result = get_api_json(f"{api_url}/search-results?{urlencode({'dated_only': 'true', 'limit': limit})}")
        return result.get("items", []), None
    except API_ERRORS as error:
        return [], str(error)


def ask_assistant(api_url, question):
    """Send a question to the governed assistant (POST /ask)."""
    try:
        return post_api_json(f"{api_url}/ask", {"query": question}), None
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail")
        except ValueError:
            detail = None
        return None, detail if isinstance(detail, str) else f"The assistant returned HTTP {error.code}."
    except API_ERRORS as error:
        return None, f"Could not reach the assistant: {error}"


STATUS_NOTES = {
    "PASS": "Passed governance checks.",
    "REVIEW": "Returned with caveats: some sources are journalism or unverified, or some claims lack a citation. "
              "Verify important figures with a primary source.",
    "BLOCK": "The generated answer was rejected for advice-like language; showing glossary definitions instead.",
    "SKIPPED": "No answer was generated for this kind of request.",
}


def render_assistant_message(message):
    st.write(message["content"])
    status = message.get("status")
    if status:
        st.caption(f"{status} · {STATUS_NOTES.get(status, '')}")
    sources = message.get("sources") or []
    if sources:
        with st.expander(f"Sources ({len(sources)})"):
            for source in sources:
                cited = "" if source.get("cited") else " (not cited in the answer)"
                published = f" · {source['published_at'][:10]}" if source.get("published_at") else ""
                st.markdown(f"{source['n']}. [{source['title']}]({source['url']}) · {source['publisher']}{published}{cited}")


# App configuration
st.set_page_config(page_title="Stock Market Dashboard", layout="wide")

st.title("Stock Market Intelligence Dashboard")
st.write("Stored market history, historical risk profiles, saved news, and a cited research assistant.")

# Sidebar controls
st.sidebar.subheader("Settings")
ticker = st.sidebar.text_input("Enter Ticker", value="AAPL").strip().upper()
# Docker Compose publishes the backend on host port 8000 (the container listens on 8605)
default_api_url = os.getenv("BACKEND_API_URL", "http://localhost:8000")
api_url = st.sidebar.text_input("Backend API URL", value=default_api_url).strip().rstrip("/")

try:
    get_api_json(f"{api_url}/health")
    st.sidebar.success("Backend connected")
    backend_connected = True
except API_ERRORS:
    st.sidebar.warning("Backend unavailable")
    backend_connected = False

st.sidebar.caption(
    "Educational use only. The assistant explains and summarizes sources; it does not give personal "
    "investment advice or place trades."
)

# Main layout tabs
tab1, tab2, tab3 = st.tabs(["Chat Assistant", "Prices & Risk Profile", "Saved News"])

# Tab 1: Chat interface
with tab1:
    st.subheader("Research Assistant")

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Ask about a financial term, a company, or recent market news."}
        ]

    examples = [
        "What is an ETF and how is it different from a mutual fund?",
        f"How volatile has {ticker or 'NVDA'} been historically?",
        f"Should I put $5000 into {ticker or 'NVDA'} for my retirement?",
    ]
    example_columns = st.columns(len(examples))
    picked = None
    for column, example in zip(example_columns, examples):
        if column.button(example, use_container_width=True):
            picked = example

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_assistant_message(message)
            else:
                st.write(message["content"])

    prompt = st.chat_input("Type your question here...") or picked
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        if not backend_connected:
            reply = {"role": "assistant", "content": "The backend is not connected, so the assistant is unavailable."}
        else:
            with st.spinner("Classifying the question, retrieving sources, and generating an answer..."):
                result, error = ask_assistant(api_url, prompt)
            if error:
                reply = {"role": "assistant", "content": error}
            else:
                reply = {
                    "role": "assistant",
                    "content": result["answer"],
                    "status": result["governance"]["status"],
                    "sources": result.get("citations", []),
                }

        st.session_state.messages.append(reply)
        with st.chat_message("assistant"):
            render_assistant_message(reply)

# Tab 2: Stored prices and the Spark risk profile
with tab2:
    st.subheader(f"Saved market history for {ticker}")

    if backend_connected and ticker:
        if st.button(f"Fetch or refresh {ticker} prices"):
            try:
                outcome = post_api_json(f"{api_url}/ingest/prices/{quote(ticker)}", timeout=120)
                get_price_bars.clear()
                st.success(f"{outcome['records']} price records loaded from {outcome['provider']} ({outcome['source']}).")
            except API_ERRORS as error:
                st.error(f"Could not load prices: {error}")

        price_bars, price_error = get_price_bars(api_url, ticker)
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
            st.info("There are no saved price bars for this ticker yet. Use the button above to fetch them.")

        st.markdown("#### Historical risk profile")
        profile, profile_error = get_risk_profile(api_url, ticker)
        if profile:
            latest = profile["latest"]
            year, month = latest["quarter_start"][:7].split("-")
            quarter = f"{year} Q{(int(month) - 1) // 3 + 1}"
            st.write(f"In **{quarter}**, {ticker} was in the **{latest['risk_profile']}** group.")
            col1, col2, col3 = st.columns(3)
            col1.metric("Volatility (annualized)", f"{latest['annualized_volatility'] * 100:.1f}%")
            col2.metric("Largest drop in the quarter", f"{latest['max_drawdown'] * 100:.1f}%")
            col3.metric(f"Beta vs {latest['benchmark']}", f"{latest['beta_vs_benchmark']:.2f}")

            history = pd.DataFrame(profile["history"])
            history["quarter_start"] = pd.to_datetime(history["quarter_start"])
            history["Volatility %"] = history["annualized_volatility"] * 100
            st.bar_chart(history.sort_values("quarter_start").set_index("quarter_start")["Volatility %"],
                         y_label="Annualized volatility by quarter (%)")
            mix = ", ".join(f"{m['pct_of_quarters']:.0f}% {m['risk_profile']}" for m in profile["profile_mix"])
            st.caption(f"Across {profile['quarters_total']} quarters: {mix}. {profile['disclaimer']}")
        elif profile_error:
            st.info("Risk profiles are unavailable. " + profile_error)
        else:
            st.info(f"No risk profile has been computed for {ticker} yet. It appears after the Spark clustering job runs.")
    else:
        st.info("Start the project backend to load saved price bars and risk profiles.")

# Tab 3: News stored by the ingestion layer
with tab3:
    st.subheader("Saved financial news")
    st.caption("Articles collected by the ingestion layer (Tavily), deduplicated by URL. Newest first.")

    if backend_connected:
        news, news_error = get_stored_news(api_url)
        if news:
            table = pd.DataFrame(news)
            table["Published"] = pd.to_datetime(table["published_at"]).dt.date
            table = table.rename(columns={"title": "Title", "source_domain": "Source", "query_text": "Found by query", "url": "Link"})
            st.dataframe(
                table[["Published", "Title", "Source", "Found by query", "Link"]],
                width="stretch",
                hide_index=True,
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")},
            )
            per_day = table.groupby("Published").size().rename("Articles")
            st.bar_chart(per_day, y_label="Articles saved per day")
        elif news_error:
            st.info("Could not load saved news. " + news_error)
        else:
            st.info("No news has been saved yet. Asking the assistant a market question collects some.")
    else:
        st.info("Start the project backend to load saved news.")
