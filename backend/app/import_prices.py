import pandas as pd
import yfinance as yf

from app.db import get_connection


def import_prices(symbol="AAPL"):
    prices = yf.Ticker(symbol).history(
        period="1mo",
        interval="1d",
        auto_adjust=False,
        raise_errors=True,
    )

    if prices.empty:
        raise ValueError(f"No prices returned for {symbol}")

    columns = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]

    if prices[columns].isna().any().any():
        raise ValueError("Prices contain missing values. Nothing was saved.")

    rows = []

    for date, row in prices.iterrows():
        rows.append((
            symbol,
            date.date(),
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
            float(row["Adj Close"]),
            int(row["Volume"]),
            "yfinance",
        ))

    sql = """
        INSERT INTO price_bars (
            symbol, bar_date, open, high, low, close,
            adjusted_close, volume, provider
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, bar_date)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            adjusted_close = EXCLUDED.adjusted_close,
            volume = EXCLUDED.volume,
            provider = EXCLUDED.provider,
            updated_at = now()
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)

    print(f"Saved or updated {len(rows)} price records for {symbol}.")


if __name__ == "__main__":
    import_prices()