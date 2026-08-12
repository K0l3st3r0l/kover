"""Tests de Stage 1 (universo). Sin red: el fetch de precios/volumen y el
directorio de optionabilidad de CBOE se reemplazan por dobles inyectados.
"""

from app.providers.base import ProviderError
from app.providers.nasdaq_universe import NasdaqListing
from app.scanner import universe as scanner_universe
from app.scanner.universe import (
    REASON_LOW_VOLUME,
    REASON_NOT_OPTIONABLE,
    REASON_OPTIONABLE_CHECK_FAILED,
    STAGE_LIQUIDITY,
    STAGE_OPTIONABLE,
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


class FakeOptionableProvider:
    def __init__(self, symbols=None, error=None):
        self._symbols = symbols or set()
        self._error = error

    def get_optionable_symbols(self):
        if self._error:
            raise self._error
        return self._symbols


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
            listing("INRG"),   # precio ok, volumen ok, en el directorio CBOE -> califica
            listing("ILLQ"),  # precio ok, volumen bajo -> se cae en liquidez
            listing("NOOPT"),     # precio ok, volumen ok, no está en CBOE
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

        candidates, counts = run_universe_scan(
            provider, optionable_provider=FakeOptionableProvider({"INRG"})
        )
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

        fetched = []
        provider_double = FakeOptionableProvider({"INRG"})
        provider_double.get_optionable_symbols = lambda: fetched.append(1) or {"INRG"}

        candidates, counts = run_universe_scan(provider, check_optionable=False, optionable_provider=provider_double)
        assert fetched == []  # el provider ni se llama si check_optionable=False
        assert candidates[0].stage_reached == STAGE_LIQUIDITY
        assert candidates[0].rejected_reason is None

    def test_cboe_provider_failure_leaves_candidates_pending_not_rejected(self, monkeypatch):
        """Un solo request que falla no debe volverse 'confirmado sin opciones'."""
        listings = [listing("INRG")]
        provider = FakeProvider(listings)
        monkeypatch.setattr(
            scanner_universe,
            "_fetch_price_volume_batch",
            lambda symbols: {"INRG": {"price": 15.0, "avg_volume": 1_000_000, "avg_dollar_volume": 15_000_000}},
        )

        candidates, counts = run_universe_scan(
            provider,
            optionable_provider=FakeOptionableProvider(error=ProviderError("cboe_symbol_directory", "caído")),
        )
        assert candidates[0].stage_reached == STAGE_LIQUIDITY
        assert candidates[0].rejected_reason == REASON_OPTIONABLE_CHECK_FAILED
        assert candidates[0].is_optionable is None
        assert counts.optionable_check_failed == 1
        assert counts.qualified == 0
        assert counts.not_optionable == 0

    def test_single_request_covers_the_whole_liquid_pool(self, monkeypatch):
        """El punto entero del cambio: un request de CBOE, no uno por símbolo."""
        listings = [listing(f"SY{chr(65 + i)}") for i in range(20)]  # SYA..SYT
        provider = FakeProvider(listings)
        price_data = {
            l.symbol: {"price": 15.0, "avg_volume": 1_000_000, "avg_dollar_volume": 15_000_000}
            for l in listings
        }
        monkeypatch.setattr(scanner_universe, "_fetch_price_volume_batch", lambda symbols: price_data)

        calls = []

        class CountingProvider(FakeOptionableProvider):
            def get_optionable_symbols(self):
                calls.append(1)
                return super().get_optionable_symbols()

        candidates, counts = run_universe_scan(
            provider, optionable_provider=CountingProvider({l.symbol for l in listings[:10]})
        )
        assert len(calls) == 1
        assert counts.optionable_checked == 20
        assert counts.qualified == 10
        assert counts.not_optionable == 10
