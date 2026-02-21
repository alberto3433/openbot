"""
Tests for Scheduled Orders & After-Hours Handling.

Covers:
- Store hours parsing and open/closed detection
- Time expression parsing
- After-hours greeting modification
- Scheduled pickup time validation
- Edge cases (past time, closed time, too far ahead)
"""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from orderbot.services.store_hours import (
    HoursConfig,
    parse_hours_config,
    is_store_open_now,
    get_next_open_time,
    get_next_open_time_display,
    validate_scheduled_time,
)
from orderbot.tasks.parsers.time_parser import ParsedTime, parse_time_expression


# =============================================================================
# Test Store Hours Service
# =============================================================================

class TestParseHoursConfig:
    """Test parse_hours_config with various input formats."""

    def test_compact_string_format(self):
        raw = {"mon": "7-5", "tue": "7:00-17:00", "wed": "8-6"}
        result = parse_hours_config(raw)
        assert result is not None
        assert 0 in result  # Monday
        assert result[0] == (time(7, 0), time(17, 0))
        assert result[1] == (time(7, 0), time(17, 0))
        assert result[2] == (time(8, 0), time(18, 0))

    def test_structured_dict_format(self):
        raw = {
            "mon": {"open": "07:00", "close": "17:00"},
            "fri": {"open": "06:00", "close": "20:00"},
        }
        result = parse_hours_config(raw)
        assert result is not None
        assert result[0] == (time(7, 0), time(17, 0))
        assert result[4] == (time(6, 0), time(20, 0))

    def test_ampm_format(self):
        raw = {"monday": "7am-5pm", "saturday": "8am-3pm"}
        result = parse_hours_config(raw)
        assert result is not None
        assert result[0] == (time(7, 0), time(17, 0))
        assert result[5] == (time(8, 0), time(15, 0))

    def test_closed_day(self):
        raw = {"mon": "7-5", "sun": "closed"}
        result = parse_hours_config(raw)
        assert result is not None
        assert 0 in result  # Monday present
        assert 6 not in result  # Sunday excluded

    def test_none_input(self):
        assert parse_hours_config(None) is None

    def test_empty_dict(self):
        assert parse_hours_config({}) is None

    def test_non_dict_input(self):
        assert parse_hours_config("9-5") is None

    def test_full_day_names(self):
        raw = {"tuesday": "9-5", "wednesday": "10-6"}
        result = parse_hours_config(raw)
        assert result is not None
        assert 1 in result
        assert 2 in result


class TestIsStoreOpenNow:
    """Test is_store_open_now with mocked times."""

    @pytest.fixture
    def weekday_hours(self) -> HoursConfig:
        """Standard Mon-Fri 7am-5pm hours."""
        return {i: (time(7, 0), time(17, 0)) for i in range(5)}

    def test_open_during_hours(self, weekday_hours):
        # Mock: Wednesday at 10am
        with patch("orderbot.services.store_hours.datetime") as mock_dt:
            tz = ZoneInfo("America/New_York")
            mock_dt.now.return_value = datetime(2026, 2, 18, 10, 0, tzinfo=tz)  # Wednesday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert is_store_open_now(weekday_hours, "America/New_York") is True

    def test_closed_after_hours(self, weekday_hours):
        with patch("orderbot.services.store_hours.datetime") as mock_dt:
            tz = ZoneInfo("America/New_York")
            mock_dt.now.return_value = datetime(2026, 2, 18, 20, 0, tzinfo=tz)  # Wednesday 8pm
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert is_store_open_now(weekday_hours, "America/New_York") is False

    def test_closed_on_weekend(self, weekday_hours):
        with patch("orderbot.services.store_hours.datetime") as mock_dt:
            tz = ZoneInfo("America/New_York")
            mock_dt.now.return_value = datetime(2026, 2, 21, 10, 0, tzinfo=tz)  # Saturday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert is_store_open_now(weekday_hours, "America/New_York") is False

    def test_none_hours_assumes_open(self):
        assert is_store_open_now(None, "America/New_York") is True


class TestGetNextOpenTime:
    """Test get_next_open_time calculations."""

    @pytest.fixture
    def weekday_hours(self) -> HoursConfig:
        return {i: (time(7, 0), time(17, 0)) for i in range(5)}

    def test_next_open_when_closed_evening(self, weekday_hours):
        with patch("orderbot.services.store_hours.datetime") as mock_dt:
            tz = ZoneInfo("America/New_York")
            # Wednesday evening → next open is Thursday 7am
            mock_dt.now.return_value = datetime(2026, 2, 18, 20, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_next_open_time(weekday_hours, "America/New_York")
            assert result is not None
            assert result.weekday() == 3  # Thursday
            assert result.hour == 7

    def test_next_open_on_weekend(self, weekday_hours):
        with patch("orderbot.services.store_hours.datetime") as mock_dt:
            tz = ZoneInfo("America/New_York")
            # Saturday → next open is Monday 7am
            mock_dt.now.return_value = datetime(2026, 2, 21, 10, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_next_open_time(weekday_hours, "America/New_York")
            assert result is not None
            assert result.weekday() == 0  # Monday
            assert result.hour == 7

    def test_none_hours(self):
        assert get_next_open_time(None, "America/New_York") is None


class TestValidateScheduledTime:
    """Test validate_scheduled_time for various edge cases."""

    @pytest.fixture
    def weekday_hours(self) -> HoursConfig:
        return {i: (time(7, 0), time(17, 0)) for i in range(5)}

    def test_valid_time(self, weekday_hours):
        tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        # Pick next weekday at 10am
        for offset in range(1, 4):
            candidate = now + timedelta(days=offset)
            if candidate.weekday() < 5:
                requested = candidate.replace(hour=10, minute=0, second=0, microsecond=0)
                is_valid, error = validate_scheduled_time(
                    requested, weekday_hours, "America/New_York",
                )
                assert is_valid is True
                assert error is None
                break

    def test_past_time_rejected(self, weekday_hours):
        tz = ZoneInfo("America/New_York")
        past = datetime.now(tz) - timedelta(hours=2)
        is_valid, error = validate_scheduled_time(past, weekday_hours, "America/New_York")
        assert is_valid is False
        assert "already passed" in error

    def test_too_far_ahead_rejected(self, weekday_hours):
        tz = ZoneInfo("America/New_York")
        far_future = datetime.now(tz) + timedelta(days=10)
        is_valid, error = validate_scheduled_time(far_future, weekday_hours, "America/New_York")
        assert is_valid is False
        assert "3 days" in error

    def test_closed_day_rejected(self, weekday_hours):
        tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        # Find next Saturday
        days_to_saturday = (5 - now.weekday()) % 7
        if days_to_saturday == 0:
            days_to_saturday = 7
        saturday = now + timedelta(days=days_to_saturday)
        if days_to_saturday <= 3:
            requested = saturday.replace(hour=10, minute=0, second=0, microsecond=0)
            is_valid, error = validate_scheduled_time(
                requested, weekday_hours, "America/New_York",
            )
            assert is_valid is False
            assert "closed" in error.lower()

    def test_outside_hours_rejected(self, weekday_hours):
        tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        # Find next weekday
        for offset in range(1, 4):
            candidate = now + timedelta(days=offset)
            if candidate.weekday() < 5:
                requested = candidate.replace(hour=2, minute=0, second=0, microsecond=0)
                is_valid, error = validate_scheduled_time(
                    requested, weekday_hours, "America/New_York",
                )
                assert is_valid is False
                assert "open from" in error.lower()
                break

    def test_none_hours_always_valid(self):
        tz = ZoneInfo("America/New_York")
        future = datetime.now(tz) + timedelta(hours=2)
        is_valid, error = validate_scheduled_time(future, None, "America/New_York")
        assert is_valid is True
        assert error is None


# =============================================================================
# Test Time Expression Parser
# =============================================================================

class TestTimeParser:
    """Test parse_time_expression with various input formats."""

    def test_asap_explicit(self):
        result = parse_time_expression("ASAP please")
        assert result is not None
        assert result.is_asap is True
        assert result.time_value is None

    def test_as_soon_as_possible(self):
        result = parse_time_expression("as soon as possible")
        assert result is not None
        assert result.is_asap is True

    def test_right_now(self):
        result = parse_time_expression("right now")
        assert result is not None
        assert result.is_asap is True

    def test_absolute_time_with_ampm(self):
        result = parse_time_expression("3pm")
        assert result is not None
        assert result.is_asap is False
        assert result.time_value.hour == 15

    def test_absolute_time_with_minutes(self):
        result = parse_time_expression("3:30 PM")
        assert result is not None
        assert result.time_value.hour == 15
        assert result.time_value.minute == 30

    def test_relative_hours(self):
        result = parse_time_expression("in 2 hours")
        assert result is not None
        assert result.is_asap is False
        # Should be approximately 2 hours from now
        now = datetime.now(ZoneInfo("America/New_York"))
        diff = result.time_value - now
        assert 1.9 * 3600 <= diff.total_seconds() <= 2.1 * 3600

    def test_relative_minutes(self):
        result = parse_time_expression("in 30 minutes")
        assert result is not None
        now = datetime.now(ZoneInfo("America/New_York"))
        diff = result.time_value - now
        assert 29 * 60 <= diff.total_seconds() <= 31 * 60

    def test_in_an_hour(self):
        result = parse_time_expression("in an hour")
        assert result is not None
        now = datetime.now(ZoneInfo("America/New_York"))
        diff = result.time_value - now
        assert 0.9 * 3600 <= diff.total_seconds() <= 1.1 * 3600

    def test_tomorrow_at_time(self):
        result = parse_time_expression("tomorrow at 3pm")
        assert result is not None
        now = datetime.now(ZoneInfo("America/New_York"))
        assert result.time_value.date() == (now + timedelta(days=1)).date()
        assert result.time_value.hour == 15

    def test_tomorrow_morning(self):
        result = parse_time_expression("tomorrow morning")
        assert result is not None
        now = datetime.now(ZoneInfo("America/New_York"))
        assert result.time_value.date() == (now + timedelta(days=1)).date()
        assert result.time_value.hour == 7  # morning default

    def test_day_name_with_time(self):
        result = parse_time_expression("Saturday at noon")
        assert result is not None
        assert result.time_value.weekday() == 5  # Saturday
        assert result.time_value.hour == 12

    def test_pickup_at_time(self):
        result = parse_time_expression("pickup at 3")
        assert result is not None
        assert result.time_value.hour == 15  # 3 without AM/PM + heuristic

    def test_for_time(self):
        result = parse_time_expression("for 2pm")
        assert result is not None
        assert result.time_value.hour == 14

    def test_no_time_expression(self):
        result = parse_time_expression("I'd like a bagel")
        assert result is None

    def test_plain_number_no_match(self):
        # Bare numbers without scheduling context or AM/PM should not match
        result = parse_time_expression("I want 2 bagels")
        assert result is None


# =============================================================================
# Test Scheduling Data Serialization
# =============================================================================

class TestSchedulingAdapter:
    """Test scheduling data in adapter serialization/deserialization."""

    def test_scheduling_dict_in_output(self):
        from orderbot.tasks.adapter import order_task_to_dict
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        order.delivery_method.pickup_time = "2026-02-22T07:00:00-05:00"

        result = order_task_to_dict(order)
        assert "scheduling" in result
        sched = result["scheduling"]
        assert sched["pickup_time"] == "2026-02-22T07:00:00-05:00"
        assert sched["is_scheduled"] is True
        assert sched["pickup_time_display"] is not None
        assert sched["editable"] is True

    def test_scheduling_dict_asap(self):
        from orderbot.tasks.adapter import order_task_to_dict
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        # No pickup_time set → ASAP
        result = order_task_to_dict(order)
        sched = result["scheduling"]
        assert sched["pickup_time"] is None
        assert sched["is_scheduled"] is False
        assert sched["pickup_time_display"] is None

    def test_pickup_time_in_customer_block(self):
        from orderbot.tasks.adapter import order_task_to_dict
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        order.delivery_method.pickup_time = "2026-02-22T10:00:00-05:00"

        result = order_task_to_dict(order)
        assert result["customer"]["pickup_time"] == "2026-02-22T10:00:00-05:00"

    def test_round_trip_preserves_pickup_time(self):
        from orderbot.tasks.adapter import order_task_to_dict, dict_to_order_task
        from orderbot.tasks.models import OrderTask

        order = OrderTask()
        order.delivery_method.pickup_time = "2026-02-22T07:00:00-05:00"

        serialized = order_task_to_dict(order)
        restored = dict_to_order_task(serialized)
        assert restored.delivery_method.pickup_time == "2026-02-22T07:00:00-05:00"


# =============================================================================
# Test DeliveryMethodTask with pickup_time
# =============================================================================

class TestDeliveryMethodTaskPickupTime:
    """Test that pickup_time doesn't affect is_complete logic."""

    def test_pickup_time_does_not_affect_completion(self):
        from orderbot.tasks.models.order_flow import DeliveryMethodTask

        task = DeliveryMethodTask()
        task.order_type = "pickup"
        assert task.is_complete() is True

        task.pickup_time = "2026-02-22T07:00:00-05:00"
        assert task.is_complete() is True  # Still complete

    def test_default_pickup_time_is_none(self):
        from orderbot.tasks.models.order_flow import DeliveryMethodTask

        task = DeliveryMethodTask()
        assert task.pickup_time is None


# =============================================================================
# Test Order Summary with Scheduled Time
# =============================================================================

class TestOrderSummaryScheduling:
    """Test that scheduled time appears in order summary."""

    def test_summary_includes_scheduled_time(self):
        from orderbot.tasks.message_builder import MessageBuilder
        from orderbot.tasks.models import OrderTask, MenuItemTask

        builder = MessageBuilder()
        order = OrderTask()

        # Add an item so summary has content
        item = MenuItemTask(
            menu_item_name="Plain Bagel",
            menu_item_type="bagel",
            unit_price=2.50,
        )
        item.mark_complete()
        order.items.add_item(item)

        # Set pickup time
        tz = ZoneInfo("America/New_York")
        tomorrow = datetime.now(tz) + timedelta(days=1)
        pickup = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        order.delivery_method.pickup_time = pickup.isoformat()

        summary = builder.build_order_summary(order)
        assert "Scheduled for:" in summary
        assert "10:00 AM" in summary

    def test_summary_no_scheduled_time_for_asap(self):
        from orderbot.tasks.message_builder import MessageBuilder
        from orderbot.tasks.models import OrderTask, MenuItemTask

        builder = MessageBuilder()
        order = OrderTask()

        item = MenuItemTask(
            menu_item_name="Plain Bagel",
            menu_item_type="bagel",
            unit_price=2.50,
        )
        item.mark_complete()
        order.items.add_item(item)

        summary = builder.build_order_summary(order)
        assert "Scheduled for:" not in summary
