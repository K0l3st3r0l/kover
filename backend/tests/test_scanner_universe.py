"""Tests de Stage 1 (universo). Sin red: el fetch de precios/volumen y el
check de optionabilidad se reemplazan por dobles inyectados vía monkeypatch.
"""

from app.providers.nasdaq_universe import NasdaqListing
from app.scanner import universe as scanner_universe
from app.scanner.universe import (
    REASON_LOW_VOLUME,
    REASON_NOT_OPTIONABLE,
    STAGE_LIQUIDITY,
    STAGE_OPTIONABLE,
    STAGE_PRICE_RANGE,
    run_universe_scan,
)


def listing(symbol, name="Some Corp Common Stock", exchange="Q", etf=False, test_issue=False):
    return NasdaqListing(
        symbol=symbol,
        security_name=name,
        listing_exchange=exchange,
        is_etf=etf,
        is_test_issue=test_issue,
        round_lot_size=100,
    )


class FakeProvider:
    def __init__(self, listings):
        self._listings = listings

    def get_listings(self):
        return self._listings


class TestNasdaqListingHeuristic:
    def test_common_stock_passes(self):
        assert listing("ANEB").looks_like_common_stock() is True

    def test_warrant_name_excluded(self):
        assert listing("ANEBW", name="Anebulo Pharmaceuticals Warrant").looks_like_common_stock() is False

    def test_preferred_name_excluded(self):
        assert listing("BAC-P", name="Bank of America Depositary Shares Preferred").looks_like_common_stock() is False

    def test_non_alpha_symbol_excluded(self):
        assert listing("BRK.A").looks_like_common_stock() is False

    def test_long_symbol_excluded(self):
        assert listing("ABCDEF").looks_like_common_stock() is False


class TestFilterListing:
    def test_counts_exclusions_correctly(self):
        listings = [
            listing("AAAA"),
            listing("SPY", etf=True),
            listing("TEST", test_issue=True),
            listing("WARR", name="Foo Warrant"),
            listing("BBBB"),
        ]
        passed, counts = scanner_universe._filter_listing(FakeProvider(listings))
        assert counts.listed_total == 5
        assert counts.excluded_etf == 1
        assert counts.excluded_test_issue == 1
        assert counts.excluded_not_common == 1
        assert counts.listing_passed == 2
        assert {l.symbol for l in passed} == {"AAAA", "BBBB"}


class TestRunUniverseScan:
    def test_full_funnel_with_stubbed_price_and_optionability(self, monkeypatch):
        listings = [
            listing("INRG"),   # precio ok, volumen ok, optionable -> califica
            listing("ILLQ"),  # precio ok, volumen bajo -> se cae en liquidez
            listing("NOOPT"),     # precio ok, volumen ok, sin opciones
            listing("CHEAP"),     # precio fuera de banda (muy bajo)
            listing("NODAT"),    # sin datos de precio
        ]
        provider = FakeProvider(listings)

        price_data = {
            "INRG": {"price": 15.0, "avg_volume": 1_000_000, "avg_dollar_volume": 15_000_000},
            "ILLQ": {"price": 12.0, "avg_volume": 10_000, "avg_dollar_volume": 120_000},
            "NOOPT": {"price": 18.0, "avg_volume": 800_000, "avg_dollar_volume": 14_000_000},
            "CHEAP": {"price": 3.0, "avg_volume": 5_000_000, "avg_dollar_volume": 15_000_000},
        }
        monkeypatch.setattr(scanner_universe, "_fetch_price_volume_batch", lambda symbols: price_data)
        monkeypatch.setattr(
            scanner_universe, "_check_optionable", lambda symbol: symbol != "NOOPT"
        )

        candidates, counts = run_universe_scan(provider)
        by_symbol = {c.symbol: c for c in candidates}

        assert counts.listing_passed == 5
        assert counts.price_no_data == 1
        assert counts.price_out_of_range == 1
        assert counts.price_in_range == 3
        assert counts.low_volume == 1
        assert counts.not_optionable == 1
        assert counts.qualified == 1

        assert by_symbol["INRG"].qualified is True
        assert by_symbol["INRG"].stage_reached == STAGE_OPTIONABLE
        assert by_symbol["INRG"].rejected_reason is None

        assert by_symbol["ILLQ"].qualified is False
        assert by_symbol["ILLQ"].stage_reached == STAGE_LIQUIDITY
        assert by_symbol["ILLQ"].rejected_reason == REASON_LOW_VOLUME

        assert by_symbol["NOOPT"].qualified is False
        assert by_symbol["NOOPT"].stage_reached == STAGE_OPTIONABLE
        assert by_symbol["NOOPT"].rejected_reason == REASON_NOT_OPTIONABLE

        assert "CHEAP" not in by_symbol
        assert "NODAT" not in by_symbol

    def test_skips_optionability_check_when_disabled(self, monkeypatch):
        listings = [listing("INRG")]
        provider = FakeProvider(listings)
        monkeypatch.setattr(
            scanner_universe,
            "_fetch_price_volume_batch",
            lambda symbols: {"INRG": {"price": 15.0, "avg_volume": 1_000_000, "avg_dollar_volume": 15_000_000}},
        )
        called = []
        monkeypatch.setattr(scanner_universe, "_check_optionable", lambda s: called.append(s) or True)

        candidates, counts = run_universe_scan(provider, check_optionable=False)
        assert called == []
        assert candidates[0].stage_reached == STAGE_LIQUIDITY
        assert candidates[0].rejected_reason is None
