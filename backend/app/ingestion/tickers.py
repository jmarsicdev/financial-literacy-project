AI_TECH_STOCKS: list[str] = [
    "NVDA", "AMD", "AVGO", "TSM", "ARM",
    "MSFT", "GOOGL", "AMZN", "META", "AAPL", "ORCL",
    "PLTR", "CRM", "SNOW",
]

BENCHMARK_ETFS: list[str] = ["SPY", "QQQ", "XLK", "SMH", "AIQ"]

DEFAULT_TICKERS: list[str] = AI_TECH_STOCKS + BENCHMARK_ETFS


def parse_ticker_list(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return list(DEFAULT_TICKERS)
    seen: list[str] = []
    for token in raw.replace(",", " ").split():
        symbol = token.strip().upper()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return seen
