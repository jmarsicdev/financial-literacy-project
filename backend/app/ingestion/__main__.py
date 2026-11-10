from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from dotenv import load_dotenv

from .config import load_settings
from .pipeline import Ingestor, IngestResult
from .tickers import DEFAULT_TICKERS, parse_ticker_list


def _print_results(results: list[IngestResult], as_json: bool) -> None:
    if as_json:
        print(json.dumps([r.to_dict() for r in results], indent=2, default=str))
        return
    width = max((len(r.target) for r in results), default=6)
    for r in results:
        extra = []
        if r.rejected:
            extra.append(f"{r.rejected} rejected")
        if r.duplicates:
            extra.append(f"{r.duplicates} dup")
        if r.message:
            extra.append(r.message)
        unit = {"prices": "bars", "news": "results", "metadata": "row"}.get(r.kind, "rows")
        print(
            f"{r.target:<{width}}  {r.status:<8} {r.source:<5} {str(r.provider or '-'):<14} "
            f"{r.records:>6} {unit}" + (f"  ({'; '.join(extra)})" if extra else "")
        )
    ok = sum(1 for r in results if r.succeeded)
    print(f"-- {ok}/{len(results)} succeeded")


def _print_dict(data: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return
    for key, value in data.items():
        print(f"{key}: {value}")


def cmd_budget(ingestor: Ingestor, args: argparse.Namespace) -> int:
    _print_dict(ingestor.av_budget().to_dict(), args.json)
    return 0


def cmd_status(ingestor: Ingestor, args: argparse.Namespace) -> int:
    _print_dict(ingestor.store.table_counts(), args.json)
    return 0


def cmd_seed_prices(ingestor: Ingestor, args: argparse.Namespace) -> int:
    tickers = parse_ticker_list(args.tickers)
    if args.dry_run:
        plan = ingestor.plan_prices(tickers, refresh=args.refresh, allow_fallback=not args.no_fallback)
        budget = ingestor.av_budget()
        if args.json:
            print(json.dumps({"budget": budget.to_dict(), "plan": plan}, indent=2))
        else:
            print(f"alpha_vantage budget: {budget.used}/{budget.limit} used, {budget.remaining} remaining")
            for step in plan:
                print(f"{step['symbol']:<6} {step['action']}")
            api_calls = sum(1 for s in plan if s["action"].startswith("api:alpha_vantage"))
            print(f"-- would spend {api_calls} alpha_vantage call(s); no network activity performed")
        return 0
    results = [
        ingestor.ingest_prices(symbol, refresh=args.refresh, allow_fallback=not args.no_fallback)
        for symbol in tickers
    ]
    _print_results(results, args.json)
    budget = ingestor.av_budget()
    if not args.json:
        print(f"alpha_vantage budget now: {budget.used}/{budget.limit} used, {budget.remaining} remaining")
    return 0 if all(r.succeeded for r in results) else 1


def cmd_seed_metadata(ingestor: Ingestor, args: argparse.Namespace) -> int:
    tickers = parse_ticker_list(args.tickers)
    results = [ingestor.ingest_metadata(symbol, refresh=args.refresh) for symbol in tickers]
    _print_results(results, args.json)
    return 0 if all(r.succeeded for r in results) else 1


def cmd_news(ingestor: Ingestor, args: argparse.Namespace) -> int:
    results = [
        ingestor.ingest_news(
            query, topic=args.topic, days=args.days, max_results=args.max_results, refresh=args.refresh,
        )
        for query in args.query
    ]
    _print_results(results, args.json)
    return 0 if all(r.succeeded for r in results) else 1


def cmd_replay(ingestor: Ingestor, args: argparse.Namespace) -> int:
    results = ingestor.replay()
    _print_results(results, args.json)
    return 0 if all(r.succeeded for r in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("budget", help="alpha vantage calls used / remaining").set_defaults(func=cmd_budget)
    sub.add_parser("status", help="row counts per table").set_defaults(func=cmd_status)

    p = sub.add_parser("seed-prices", help="load daily bars (cache first, budget guarded)")
    p.add_argument("--tickers", help=f"comma separated; default {len(DEFAULT_TICKERS)} ai/tech tickers")
    p.add_argument("--refresh", action="store_true", help="ignore cache and call the api")
    p.add_argument("--no-fallback", action="store_true", help="don't fall back to yfinance")
    p.add_argument("--dry-run", action="store_true", help="show the plan, no network")
    p.set_defaults(func=cmd_seed_prices)

    p = sub.add_parser("seed-metadata", help="company metadata from yfinance (free)")
    p.add_argument("--tickers")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_seed_metadata)

    p = sub.add_parser("news", help="tavily search -> search_results")
    p.add_argument("--query", action="append", required=True, help="repeatable")
    p.add_argument("--topic", choices=["news", "general"], default="news")
    p.add_argument("--days", type=int, default=7, help="news recency window (topic=news only)")
    p.add_argument("--max-results", type=int, default=10)
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_news)

    sub.add_parser("replay", help="re-normalize every cached payload, zero api calls").set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO line includes the api key
    load_dotenv()
    from .store import PostgresStore  # after load_dotenv

    ingestor = Ingestor(PostgresStore(), load_settings())
    return args.func(ingestor, args)


if __name__ == "__main__":
    sys.exit(main())
