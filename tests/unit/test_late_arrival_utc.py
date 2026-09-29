"""Unit tests for late_arrival module helpers (Issue #15 regression suite).

Verifies that ``is_late_arrival`` and ``evaluate_record_delay`` always
compute latency in UTC so that results are identical whether the host clock
is set to UTC, IST, or any other timezone, and that no
``TypeError: can't compare offset-naive and offset-aware datetimes`` is
raised when the caller passes a naive datetime (assumed UTC by the pipeline).
"""

import pytest
from datetime import datetime, timedelta, timezone

import pytz

from aq_engine.quality.late_arrival import is_late_arrival, evaluate_record_delay

IST = pytz.timezone("Asia/Kolkata")


class TestIsLateArrival:
    """Tests for is_late_arrival()."""

    def test_very_recent_aware_utc_is_not_late(self):
        """A record 1 hour old is not late with the default 3-hour threshold."""
        record_time = datetime.now(timezone.utc) - timedelta(hours=1)
        assert is_late_arrival(record_time, max_delay_hours=3) is False

    def test_5_hour_old_record_is_late_with_3h_threshold(self):
        """A record 5 hours old exceeds the 3-hour default threshold."""
        record_time = datetime.now(timezone.utc) - timedelta(hours=5)
        assert is_late_arrival(record_time, max_delay_hours=3) is True

    def test_custom_threshold_respected(self):
        """max_delay_hours parameter is honoured."""
        record_time = datetime.now(timezone.utc) - timedelta(hours=2)
        assert is_late_arrival(record_time, max_delay_hours=1) is True
        assert is_late_arrival(record_time, max_delay_hours=3) is False

    def test_naive_datetime_treated_as_utc_no_type_error(self):
        """Passing a naive datetime must NOT raise TypeError (Issue #15).

        Before the fix, comparing a naive datetime with datetime.now(UTC)
        raised TypeError: can't compare offset-naive and offset-aware datetimes.
        """
        naive_recent = datetime.utcnow() - timedelta(hours=1)
        assert is_late_arrival(naive_recent, max_delay_hours=3) is False

    def test_naive_old_datetime_treated_as_utc(self):
        """A naive datetime 5 hours old (UTC) must be flagged as late."""
        naive_old = datetime.utcnow() - timedelta(hours=5)
        assert is_late_arrival(naive_old, max_delay_hours=3) is True

    def test_ist_aware_datetime_correctly_converted(self):
        """An IST-aware timestamp must be converted to UTC before comparison.

        Without proper UTC normalisation, the IST offset (+05:30) would make
        a fresh reading appear to be 5.5 hours old on a UTC host, causing a
        false-positive late-arrival flag.
        """
        one_hour_ago_utc = datetime.now(timezone.utc) - timedelta(hours=1)
        one_hour_ago_ist = one_hour_ago_utc.astimezone(IST)
        assert is_late_arrival(one_hour_ago_ist, max_delay_hours=3) is False

    def test_ist_old_aware_datetime_flagged_correctly(self):
        """An IST-aware timestamp 5 hours old (real UTC) must be flagged."""
        five_hours_ago_utc = datetime.now(timezone.utc) - timedelta(hours=5)
        five_hours_ago_ist = five_hours_ago_utc.astimezone(IST)
        assert is_late_arrival(five_hours_ago_ist, max_delay_hours=3) is True

    def test_non_datetime_raises_type_error(self):
        """Passing a string must raise TypeError."""
        with pytest.raises(TypeError):
            is_late_arrival("2026-03-12T12:00:00Z")  # type: ignore[arg-type]

    def test_none_raises_type_error(self):
        """Passing None must raise TypeError."""
        with pytest.raises(TypeError):
            is_late_arrival(None)  # type: ignore[arg-type]


class TestEvaluateRecordDelay:
    """Tests for evaluate_record_delay()."""

    def test_returns_timedelta(self):
        """Return type must be timedelta."""
        rec = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        ref = datetime(2026, 3, 12, 15, 0, 0, tzinfo=timezone.utc)
        assert isinstance(evaluate_record_delay(rec, reference_time=ref), timedelta)

    def test_three_hour_delay(self):
        """A record 3 hours before reference should give timedelta(hours=3)."""
        ref = datetime(2026, 3, 12, 15, 0, 0, tzinfo=timezone.utc)
        rec = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        assert evaluate_record_delay(rec, reference_time=ref) == timedelta(hours=3)

    def test_zero_delay_same_timestamp(self):
        """Identical timestamps yield a zero delay."""
        ts = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        assert evaluate_record_delay(ts, reference_time=ts) == timedelta(0)

    def test_future_record_gives_negative_delay(self):
        """A record after the reference time gives a negative timedelta."""
        ref = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        future_rec = datetime(2026, 3, 12, 14, 0, 0, tzinfo=timezone.utc)
        assert evaluate_record_delay(future_rec, reference_time=ref) < timedelta(0)

    def test_default_reference_uses_utc_now(self):
        """Without reference_time the delay is relative to the current UTC time."""
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        delay = evaluate_record_delay(recent)
        assert timedelta(hours=1, minutes=59) <= delay <= timedelta(hours=2, minutes=1)

    def test_naive_record_treated_as_utc_no_type_error(self):
        """A naive datetime must not raise TypeError (Issue #15)."""
        naive_rec = datetime(2026, 3, 12, 12, 0, 0)
        ref = datetime(2026, 3, 12, 15, 0, 0, tzinfo=timezone.utc)
        assert evaluate_record_delay(naive_rec, reference_time=ref) == timedelta(hours=3)

    def test_naive_reference_treated_as_utc(self):
        """A naive reference_time must not raise TypeError either."""
        rec = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        naive_ref = datetime(2026, 3, 12, 15, 0, 0)
        assert evaluate_record_delay(rec, reference_time=naive_ref) == timedelta(hours=3)

    def test_both_naive_gives_correct_delay(self):
        """Two naive datetimes (both assumed UTC) give the right delay."""
        naive_rec = datetime(2026, 3, 12, 10, 0, 0)
        naive_ref = datetime(2026, 3, 12, 14, 0, 0)
        assert evaluate_record_delay(naive_rec, reference_time=naive_ref) == timedelta(hours=4)

    def test_ist_aware_record_correctly_normalised(self):
        """An IST-aware record timestamp must be converted to UTC before subtraction.

        IST is UTC+05:30. 12:00 IST == 06:30 UTC.
        Reference is 09:30 UTC, so expected delay = 3 hours.
        """
        rec_ist = IST.localize(datetime(2026, 3, 12, 12, 0, 0))  # 06:30 UTC
        ref_utc = datetime(2026, 3, 12, 9, 30, 0, tzinfo=timezone.utc)
        assert evaluate_record_delay(rec_ist, reference_time=ref_utc) == timedelta(hours=3)

    def test_ist_aware_reference_correctly_normalised(self):
        """An IST-aware reference_time must also be converted to UTC."""
        rec_utc = datetime(2026, 3, 12, 6, 30, 0, tzinfo=timezone.utc)
        ref_ist = IST.localize(datetime(2026, 3, 12, 15, 0, 0))  # 09:30 UTC
        assert evaluate_record_delay(rec_utc, reference_time=ref_ist) == timedelta(hours=3)

    def test_non_datetime_record_raises_type_error(self):
        """Non-datetime record_time must raise TypeError."""
        with pytest.raises(TypeError):
            evaluate_record_delay("2026-03-12T12:00:00Z")  # type: ignore[arg-type]

    def test_non_datetime_reference_raises_type_error(self):
        """Non-datetime reference_time must raise TypeError."""
        rec = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(TypeError):
            evaluate_record_delay(rec, reference_time="2026-03-12T15:00:00Z")  # type: ignore[arg-type]
