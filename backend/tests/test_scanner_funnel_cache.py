"""Caché de optionabilidad en `app/scanner/funnel.py`.

Cubre justo la parte con lógica SQL real (corte por TTL, no tocar el timestamp
en un cache-hit): lo demás del funnel ya está cubierto sin DB en
test_scanner_universe.py.
"""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Instrument
from app.scanner.funnel import _get_or_create_instruments, _load_known_optionable
from app.scanner.universe import OPTIONABLE_CACHE_TTL_DAYS, UniverseCandidate


class KnownOptionableCacheTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()

    def _instrument(self, symbol, is_optionable, days_ago):
        checked_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        self.db.add(Instrument(symbol=symbol, is_optionable=is_optionable, optionable_checked_at=checked_at))
        self.db.commit()

    def test_fresh_confirmation_is_cached(self):
        self._instrument("FRESH", True, days_ago=1)
        cache = _load_known_optionable(self.db)
        self.assertEqual(cache.get("FRESH"), True)

    def test_stale_confirmation_is_not_cached(self):
        self._instrument("STALE", True, days_ago=OPTIONABLE_CACHE_TTL_DAYS + 1)
        cache = _load_known_optionable(self.db)
        self.assertNotIn("STALE", cache)

    def test_never_checked_is_not_cached(self):
        self.db.add(Instrument(symbol="NEW", is_optionable=None, optionable_checked_at=None))
        self.db.commit()
        cache = _load_known_optionable(self.db)
        self.assertNotIn("NEW", cache)

    def test_confirmed_false_is_cached_too(self):
        """No optionable también es una respuesta válida — no solo se cachea el True."""
        self._instrument("NOPT", False, days_ago=2)
        cache = _load_known_optionable(self.db)
        self.assertEqual(cache.get("NOPT"), False)

    def test_live_check_bumps_checked_at(self):
        candidate = UniverseCandidate(
            symbol="LIVE", name=None, exchange=None, stage_reached="OPTIONABLE",
            rejected_reason=None, is_optionable=True, optionable_from_cache=False,
        )
        _get_or_create_instruments(self.db, [candidate])
        row = self.db.query(Instrument).filter_by(symbol="LIVE").first()
        self.assertIsNotNone(row.optionable_checked_at)

    def test_cache_hit_does_not_bump_checked_at(self):
        old_ts = datetime.now(timezone.utc) - timedelta(days=5)
        self.db.add(Instrument(symbol="CACHED", is_optionable=True, optionable_checked_at=old_ts))
        self.db.commit()

        candidate = UniverseCandidate(
            symbol="CACHED", name=None, exchange=None, stage_reached="OPTIONABLE",
            rejected_reason=None, is_optionable=True, optionable_from_cache=True,
        )
        _get_or_create_instruments(self.db, [candidate])
        row = self.db.query(Instrument).filter_by(symbol="CACHED").first()
        # sigue siendo el timestamp viejo, no se tocó. sqlite en memoria no
        # conserva tzinfo en el roundtrip (Postgres en prod sí, vía TIMESTAMPTZ);
        # se compara en naive para no acoplar el test a esa particularidad.
        stored = row.optionable_checked_at.replace(tzinfo=None)
        expected = old_ts.replace(tzinfo=None)
        self.assertLess(abs((stored - expected).total_seconds()), 1)
