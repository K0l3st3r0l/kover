from datetime import datetime

from app.api.chilean_markets import _drop_partial_rows


def _row(date_str, n_afp, n_slots=7, avg=100.0):
    return {
        "date": datetime.strptime(date_str, "%Y-%m-%d"),
        "date_str": date_str,
        "avg_value": avg,
        "total_patrimonio": 1.0,
        "n_afp": n_afp,
        "n_slots": n_slots,
    }


def test_drops_the_trailing_partial_row():
    """The SP feed publishes the newest date before every AFP has filed."""
    records = [_row(f"2026-09-{d:02d}", 7) for d in range(10, 21)]
    records.append(_row("2026-09-21", 1, avg=144495.92))

    kept = _drop_partial_rows(records)

    assert [r["date_str"] for r in kept] == [r["date_str"] for r in records[:-1]]


def test_keeps_full_rows_across_a_composition_change():
    """AFP UNO joined on 2019-10-01: 6-AFP rows are complete for their era."""
    six = [_row(f"2019-09-{d:02d}", 6, n_slots=6) for d in range(20, 31)]
    seven = [_row(f"2019-10-{d:02d}", 7) for d in range(1, 12)]

    kept = _drop_partial_rows(six + seven)

    assert len(kept) == len(six) + len(seven)


def test_partial_row_dropped_within_its_own_era():
    six = [_row(f"2019-09-{d:02d}", 6, n_slots=6) for d in range(20, 31)]
    six.append(_row("2019-09-30", 2, n_slots=6))
    seven = [_row(f"2019-10-{d:02d}", 7) for d in range(1, 12)]

    kept = _drop_partial_rows(six + seven)

    assert len(kept) == len(six) - 1 + len(seven)
    assert all(r["n_afp"] >= 6 for r in kept)


def test_rows_without_a_count_are_kept():
    """Cache files written before this filter existed carry no n_afp."""
    legacy = [
        {"date": datetime(2026, 9, 20), "date_str": "2026-09-20", "avg_value": 100.0}
    ]

    assert _drop_partial_rows(legacy) == legacy


def test_output_stays_sorted_by_date():
    records = [_row("2026-09-15", 7), _row("2026-09-10", 7), _row("2026-09-12", 7)]

    kept = _drop_partial_rows(records)

    assert [r["date_str"] for r in kept] == ["2026-09-10", "2026-09-12", "2026-09-15"]
