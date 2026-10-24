import yfinance as yf

from app.db import get_connection


def import_metadata(symbol="AAPL"):
    info = yf.Ticker(symbol).get_info()

    company_name = info.get("longName") or info.get("shortName")

    if not company_name:
        raise ValueError(f"No company information returned for {symbol}")

    values = (
        symbol,
        company_name,
        info.get("sector"),
        info.get("industry"),
        info.get("exchange"),
        info.get("marketCap"),
        info.get("longBusinessSummary"),
        "yfinance",
    )

    sql = """
        INSERT INTO ticker_metadata (
            symbol, company_name, sector, industry,
            exchange, market_cap, business_summary, provider
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol)
        DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector = EXCLUDED.sector,
            industry = EXCLUDED.industry,
            exchange = EXCLUDED.exchange,
            market_cap = EXCLUDED.market_cap,
            business_summary = EXCLUDED.business_summary,
            provider = EXCLUDED.provider,
            updated_at = now()
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, values)

    print(f"Saved company information for {symbol}: {company_name}")


if __name__ == "__main__":
    import_metadata()