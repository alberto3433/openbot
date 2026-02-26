"""
Integration tests for menu questions, price inquiries, store info, and recommendations.

Split from test_tasks_integration.py for maintainability.
"""

import pytest
from unittest.mock import patch, MagicMock

from orderbot.tasks.models import OrderTask
from orderbot.tasks.handler_config import HandlerConfig

from tests.fixtures.mock_menu_cache import apply_mock_menu_cache


@pytest.fixture(autouse=True)
def mock_menu_cache_attributes(monkeypatch):
    """Auto-use fixture to mock menu_cache methods for all tests."""
    apply_mock_menu_cache(monkeypatch)


class TestMenuQuery:
    """Tests for _handle_menu_query."""

    def test_generic_menu_query_lists_categories(self):
        """Test generic 'what do you have' lists display groups from database.

        Display groups are high-level categories like "breads", "sandwiches", "drinks"
        that consolidate the more granular item types.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine(menu_data={
            "items_by_type": {
                "bagel": [{"name": "Plain Bagel"}],
                "beverage": [{"name": "Coffee"}],
                "sandwich": [{"name": "Turkey Club"}],
            }
        })
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_menu_query(None, order)

        # Should list display groups (from menu_display_groups table)
        msg_lower = result.message.lower()
        assert "we have" in msg_lower
        # Display groups: breads, sandwiches, omelettes, drinks,
        # pastries, sides, food by the pound
        assert "breads" in msg_lower or "sandwiches" in msg_lower or "drinks" in msg_lower
        # Should prompt user to choose
        assert "what" in msg_lower  # "What are you in the mood for?" or similar

    def test_display_group_query_returns_items_from_group(self):
        """Test querying a display group returns items from all item types in that group.

        When user asks 'what breads do you have?', should return items from all
        item types mapped to the 'breads' display group (e.g., bagel items).
        """
        from orderbot.cache import menu_cache
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        # Get real menu data from cache (display groups are DB-driven)
        menu_data = menu_cache.get_menu_index()

        sm = OrderStateMachine(menu_data=menu_data)
        order = OrderTask()

        # Query the 'breads' display group
        result = sm.menu_inquiry_handler.handle_menu_query("breads", order)

        # Should list items from the breads group (bagels)
        assert "include" in result.message.lower()
        # Breads group contains bagel item type
        assert "bagel" in result.message.lower() or "Bagel" in result.message

    def test_beverage_query_uses_database_mapping(self):
        """Test that 'beverage' query uses database-driven category mapping.

        The database maps "beverage" keyword to the "coffee_based_beverage" item type,
        so items from that type should be returned.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine(menu_data={
            "items_by_type": {
                "espresso_based_beverage": [{"name": "Latte", "base_price": 4.50}],
                "coffee_based_beverage": [{"name": "Hot Coffee", "base_price": 3.00}],
                "beverage": [{"name": "Coke", "base_price": 2.00}],
            }
        })
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_menu_query("beverage", order)

        # Should return items from beverage-related types
        assert "include" in result.message.lower()
        assert "Latte" in result.message or "Coffee" in result.message

    def test_beverage_query_with_prices(self):
        """Test beverage query shows prices when requested."""
        import re
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_menu_query("beverage", order, show_prices=True)

        # Should show at least one price in $X.XX format
        assert re.search(r'\$\d+\.\d{2}', result.message), f"Expected price in message, got: {result.message}"

    def test_sandwich_query_lists_matching_items(self):
        """Test that 'sandwich' query returns a relevant response.

        With the data-driven approach, querying 'sandwich' should either:
        - List sandwich categories (deli, egg, fish, etc.)
        - Or return the general menu listing which includes sandwich types
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_menu_query("sandwich", order)

        # Should mention sandwiches or list categories that include sandwich types
        assert "sandwich" in result.message.lower() or "we have" in result.message.lower()

    def test_generic_menu_query_with_no_type(self):
        """Test handling when no specific menu query type is provided.

        When query type is None, the system should list available categories.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_menu_query(None, order)

        # Should list categories or ask what they want
        assert "we have" in result.message.lower() or "what would you like" in result.message.lower()

    def test_coffee_alias_maps_to_coffee_based_beverage(self):
        """Test that 'coffee' query maps to coffee_based_beverage type."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine(menu_data={
            "items_by_type": {
                "coffee_based_beverage": [
                    {"name": "Drip Coffee", "base_price": 2.50},
                    {"name": "Latte", "base_price": 4.50},
                ],
            }
        })
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_menu_query("coffee", order)

        assert "Drip Coffee" in result.message or "Latte" in result.message


# =============================================================================
# Tax Question and Order Status Handler Tests
# =============================================================================

class TestTaxAndOrderStatus:
    """Tests for handle_tax_question and handle_order_status in OrderUtilsHandler."""

    def test_tax_question_with_tax_rates(self):
        """Test tax calculation with configured rates."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        sm.order_utils_handler.set_context(OrderContext(store_info={
            "city_tax_rate": 0.045,  # 4.5%
            "state_tax_rate": 0.04,  # 4%
        }))

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", unit_price=3.00)
        bagel.mark_complete()
        order.items.add_item(bagel)

        result = sm.order_utils_handler.handle_tax_question(order)

        # Subtotal $3.00, tax 8.5% = $0.255, total = $3.255 -> $3.26
        assert "subtotal" in result.message.lower()
        assert "$3.00" in result.message
        assert "tax" in result.message.lower()

    def test_tax_question_no_tax_configured(self):
        """Test tax question when no tax rates configured."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        sm.order_utils_handler.set_context(OrderContext(store_info={}))  # No tax rates

        order = OrderTask()
        bagel = BagelItemTask(bagel_type="plain", unit_price=5.00)
        bagel.mark_complete()
        order.items.add_item(bagel)

        result = sm.order_utils_handler.handle_tax_question(order)

        # Should just show total without tax breakdown
        assert "$5.00" in result.message

    def test_order_status_empty_order(self):
        """Test order status with no items."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.order_utils_handler.handle_order_status(order)

        assert "haven't ordered anything" in result.message.lower()

    def test_order_status_with_items(self):
        """Test order status shows current items."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask, CoffeeItemTask

        sm = OrderStateMachine()
        order = OrderTask()

        bagel = BagelItemTask(bagel_type="plain", spread="cream cheese", unit_price=4.00)
        bagel.mark_complete()
        order.items.add_item(bagel)

        coffee = CoffeeItemTask(drink_type="Latte", size="medium", unit_price=4.50)
        coffee.mark_complete()
        order.items.add_item(coffee)

        result = sm.order_utils_handler.handle_order_status(order)

        assert "So far you have" in result.message
        # Should show the items
        assert "•" in result.message  # Bullet points

    def test_order_status_consolidates_duplicates(self):
        """Test that identical items are consolidated with count."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Add two identical bagels
        for _ in range(2):
            bagel = BagelItemTask(bagel_type="plain", spread="butter", unit_price=3.00)
            bagel.mark_complete()
            order.items.add_item(bagel)

        result = sm.order_utils_handler.handle_order_status(order)

        # Should consolidate and show "2 ..."
        assert "2" in result.message


# =============================================================================
# Store Info Inquiry Tests
# =============================================================================

class TestStoreInfoInquiries:
    """Tests for store hours, location, and delivery zone inquiries."""

    def test_store_hours_inquiry(self):
        """Test store hours inquiry with preferred store returns that store's hours (Tier 2)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={
            "hours": "Mon-Fri 7:00 AM - 4:00 PM, Sat-Sun 8:00 AM - 3:00 PM",
            "name": "Test Bagels",
            "status": "open",
            "all_stores": [
                {
                    "store_id": "s1", "name": "Test Bagels",
                    "hours": {"monday": [{"open": "07:00", "close": "16:00"}]},
                    "hours_display": "Mon-Fri 7:00 AM - 4:00 PM",
                    "status": "open",
                },
            ],
        }))

        order = OrderTask()
        result = sm.store_info_handler.handle_store_hours_inquiry(order)

        assert "Test Bagels" in result.message
        assert "open" in result.message.lower()
        assert "7:00 AM" in result.message

    def test_store_hours_preferred_store_closed(self):
        """Test store hours when preferred store is temporarily closed (Tier 2)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={
            "hours": "Mon-Fri 7:00 AM - 4:00 PM",
            "name": "East Brunswick",
            "status": "closed",
            "all_stores": [],
        }))

        order = OrderTask()
        result = sm.store_info_handler.handle_store_hours_inquiry(order)

        assert "temporarily closed" in result.message.lower()
        assert "East Brunswick" in result.message
        assert "7:00 AM" in result.message

    def test_store_hours_no_info(self):
        """Test store hours when not configured."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={}))

        order = OrderTask()
        result = sm.store_info_handler.handle_store_hours_inquiry(order)

        # Should have some fallback message
        assert result.message is not None
        assert "hours" in result.message.lower()

    def test_store_hours_all_same(self):
        """Test Tier 1: all stores have identical hours → single-line answer."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        same_hours = {"monday": [{"open": "07:00", "close": "21:00"}]}
        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={
            "all_stores": [
                {
                    "store_id": "s1", "name": "Store A",
                    "hours": same_hours, "hours_display": "Mon 7:00 AM - 9:00 PM",
                    "status": "open",
                },
                {
                    "store_id": "s2", "name": "Store B",
                    "hours": same_hours, "hours_display": "Mon 7:00 AM - 9:00 PM",
                    "status": "open",
                },
            ],
        }))

        order = OrderTask()
        result = sm.store_info_handler.handle_store_hours_inquiry(order)

        assert "all our locations" in result.message.lower()
        assert "7:00 AM" in result.message

    def test_store_hours_vary_no_preferred(self):
        """Test Tier 3: hours vary, no preferred store → inline list."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={
            "all_stores": [
                {
                    "store_id": "s1", "name": "Borough - East Brunswick",
                    "hours": {"monday": [{"open": "07:00", "close": "21:00"}]},
                    "hours_display": "Mon 7:00 AM - 9:00 PM",
                    "status": "open",
                },
                {
                    "store_id": "s2", "name": "Borough - Downtown",
                    "hours": {"monday": [{"open": "06:00", "close": "22:00"}]},
                    "hours_display": "Mon 6:00 AM - 10:00 PM",
                    "status": "open",
                },
            ],
        }))

        order = OrderTask()
        result = sm.store_info_handler.handle_store_hours_inquiry(order)

        assert "vary by location" in result.message.lower()
        assert "East Brunswick" in result.message
        assert "Downtown" in result.message
        assert "7:00 AM - 9:00 PM" in result.message
        assert "6:00 AM - 10:00 PM" in result.message

    def test_store_hours_pagination(self):
        """Test Tier 3 with >5 stores triggers pagination."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        stores = []
        for i in range(7):
            stores.append({
                "store_id": f"s{i}", "name": f"Store {i}",
                "hours": {"monday": [{"open": f"{7 + i:02d}:00", "close": "21:00"}]},
                "hours_display": f"Mon {7 + i}:00 AM - 9:00 PM",
                "status": "open",
            })

        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={
            "all_stores": stores,
        }))

        order = OrderTask()
        result = sm.store_info_handler.handle_store_hours_inquiry(order)

        # Should show first 5 stores
        assert "Store 0" in result.message
        assert "Store 4" in result.message
        # Should NOT show stores beyond page 1
        assert "Store 5" not in result.message
        # Pagination state set
        assert order.pending_store_hours_inquiry is True
        assert order.pending_store_hours_page == 1
        # Quick reply for more
        assert result.quick_replies is not None
        assert any("More" in qr["label"] for qr in result.quick_replies)

    def test_store_hours_show_more(self):
        """Test pagination follow-up advances to next page."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.context import OrderContext

        stores = []
        for i in range(7):
            stores.append({
                "store_id": f"s{i}", "name": f"Store {i}",
                "hours": {"monday": [{"open": f"{7 + i:02d}:00", "close": "21:00"}]},
                "hours_display": f"Mon {7 + i}:00 AM - 9:00 PM",
                "status": "open",
            })

        sm = OrderStateMachine()
        sm.store_info_handler.set_context(OrderContext(store_info={
            "all_stores": stores,
        }))

        order = OrderTask()
        # First page
        result1 = sm.store_info_handler.handle_store_hours_inquiry(order)
        assert order.pending_store_hours_inquiry is True

        # Show more
        result2 = sm.store_info_handler.handle_store_hours_followup("more", order)
        assert result2 is not None
        assert "Store 5" in result2.message
        assert "Store 6" in result2.message
        # Last page — no more pagination
        assert order.pending_store_hours_inquiry is False
        assert "Can I help you with an order?" in result2.message

    def test_store_location_inquiry(self):
        """Test store location inquiry."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm._store_info = {
            "address": "123 Main St, New York, NY 10001",
            "name": "Test Bagels",
        }

        order = OrderTask()
        result = sm.store_info_handler.handle_store_location_inquiry(order)

        assert "123 Main St" in result.message or "location" in result.message.lower()

    def test_delivery_zone_inquiry_valid_zip(self):
        """Test delivery zone inquiry with valid ZIP."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm._store_info = {
            "delivery_zip_codes": ["10001", "10002", "10003"],
        }

        order = OrderTask()
        result = sm.store_info_handler.handle_delivery_zone_inquiry("10001", order)

        # Should confirm delivery is available
        assert "deliver" in result.message.lower()

    def test_delivery_zone_inquiry_invalid_zip(self):
        """Test delivery zone inquiry with ZIP outside delivery area."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm._store_info = {
            "delivery_zip_codes": ["10001", "10002"],
        }

        order = OrderTask()
        result = sm.store_info_handler.handle_delivery_zone_inquiry("90210", order)

        # Should indicate delivery not available
        assert "deliver" in result.message.lower() or "pickup" in result.message.lower()


# =============================================================================
# Customer Service Inquiry Tests
# =============================================================================

class TestCustomerServiceInquiries:
    """Tests for customer service escalation pattern detection and handling."""

    # TODO: Add back customer service pattern detection tests when feature is improved
    # Removed tests:
    # - test_customer_service_pattern_detection_manager
    # - test_customer_service_pattern_detection_order_wrong
    # - test_customer_service_pattern_detection_refund
    # - test_customer_service_pattern_detection_complaint
    # - test_customer_service_handler_with_contact_info
    # - test_customer_service_handler_minimal_info

    def test_normal_order_not_detected_as_customer_service(self):
        """Test that normal orders don't trigger customer service pattern."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic

        result = parse_open_input_deterministic("I want to order a plain bagel")
        assert result.wants_customer_service is False


# =============================================================================
# Recommendation Inquiry Handler Tests
# =============================================================================

class TestRecommendationInquiry:
    """Tests for _handle_recommendation_inquiry and related recommendation methods."""

    def test_bagel_recommendation(self):
        """Test bagel-specific recommendation."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.store_info_handler.recommendation_handler.handle_recommendation_inquiry(
            match_type="item_type",
            order=order,
            item_type_slug="bagel",
        )

        # Should recommend popular bagels (from bread ingredient category)
        assert "bagel" in result.message.lower()
        assert "would you like" in result.message.lower()
        # Should NOT modify the order
        assert len(order.items.items) == 0

    def test_sandwich_recommendation(self):
        """Test sandwich-specific recommendation."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.store_info_handler.recommendation_handler.handle_recommendation_inquiry(
            match_type="item_type",
            order=order,
            item_type_slug="egg_sandwich",
        )

        # Should return some recommendation (either items or generic)
        # The exact content depends on database data
        assert result.message is not None
        assert len(result.message) > 0
        # Should NOT modify the order
        assert len(order.items.items) == 0

    def test_coffee_recommendation(self):
        """Test coffee-specific recommendation."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.store_info_handler.recommendation_handler.handle_recommendation_inquiry(
            match_type="item_type",
            order=order,
            item_type_slug="coffee_based_beverage",
        )

        # Should return some recommendation (either items or generic)
        assert result.message is not None
        assert len(result.message) > 0
        # Should NOT modify the order
        assert len(order.items.items) == 0

    def test_general_recommendation(self):
        """Test general recommendation returns generic message."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.store_info_handler.recommendation_handler.handle_recommendation_inquiry(
            match_type="general",
            order=order,
        )

        # Should give generic recommendation
        assert "selection" in result.message.lower() or "mood" in result.message.lower()
        # Should NOT modify the order
        assert len(order.items.items) == 0

    def test_breakfast_recommendation(self):
        """Test breakfast-specific recommendation."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.store_info_handler.recommendation_handler.handle_recommendation_inquiry(
            match_type="item_type",
            order=order,
            item_type_slug="breakfast",
        )

        # Should return some response (either items or generic)
        assert result.message is not None
        assert len(result.message) > 0
        # Should NOT modify the order
        assert len(order.items.items) == 0


# =============================================================================
# Coffee Size Handler Tests
# =============================================================================

class TestPriceInquiry:
    """Tests for _handle_price_inquiry.

    Note: These tests mock menu_cache.resolve_price_inquiry since the handler
    uses the global menu_cache for price lookups, not the menu_data passed to
    OrderStateMachine.
    """

    def test_no_menu_data_returns_apology(self):
        """Test that no menu data returns appropriate message."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return "not_found"
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={"type": "not_found", "query": "latte"}):
            result = sm.menu_inquiry_handler.handle_price_inquiry("latte", order)

        assert "not sure" in result.message.lower() or "help" in result.message.lower()

    def test_generic_sandwich_asks_for_type(self):
        """Test that 'sandwich' asks what kind when there are multiple types."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.cache import menu_cache

        sm = OrderStateMachine()
        order = OrderTask()

        # Check if sandwich category exists in the database
        category_info = menu_cache.get_category_keyword_mapping("sandwich")
        if not category_info:
            pytest.skip("No sandwich category in database")

        result = sm.menu_inquiry_handler.handle_price_inquiry("sandwich", order)
        msg_lower = result.message.lower()

        # Should either list sandwich types or give a starting price
        # The exact response depends on the data in the database
        assert (
            "what kind" in msg_lower
            or "several kinds" in msg_lower
            or "start at" in msg_lower
            or "sandwich" in msg_lower
        ), f"Expected sandwich-related response, got: {result.message}"

    def test_generic_category_returns_starting_price(self):
        """Test generic category inquiry returns starting price."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return a category result
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={
                       "type": "category",
                       "display_name": "coffee",
                       "min_price": 4.25,
                       "items": [],
                   }):
            result = sm.menu_inquiry_handler.handle_price_inquiry("coffee", order)

        assert "start at" in result.message.lower()
        assert "$4.25" in result.message

    def test_specific_sandwich_type_returns_price(self):
        """Test specific sandwich type returns starting price."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return a category result
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={
                       "type": "category",
                       "display_name": "egg sandwiches",
                       "min_price": 6.99,
                       "items": [],
                   }):
            result = sm.menu_inquiry_handler.handle_price_inquiry("egg sandwich", order)

        assert "start at" in result.message.lower()
        assert "$6.99" in result.message

    def test_exact_item_match_returns_price(self):
        """Test exact item name match returns specific price."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return an item result
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={
                       "type": "item",
                       "name": "The Classic",
                       "price": 12.99,
                   }):
            result = sm.menu_inquiry_handler.handle_price_inquiry("the classic", order)

        assert "classic" in result.message.lower()
        assert "$12.99" in result.message
        assert "would you like one" in result.message.lower()

    def test_partial_match_returns_price(self):
        """Test partial name match returns price."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine(menu_data={
            "items_by_type": {
                "beverage": [
                    {"name": "Diet Coke", "base_price": 2.50},
                    {"name": "Sprite", "base_price": 2.50},
                ],
            }
        })
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_price_inquiry("diet coke", order)

        assert "diet coke" in result.message.lower()
        assert "$2.50" in result.message

    def test_strips_article_from_query(self):
        """Test that 'a' and 'an' are stripped from query."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return an item result
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={
                       "type": "item",
                       "name": "Espresso",
                       "price": 3.00,
                   }):
            result = sm.menu_inquiry_handler.handle_price_inquiry("an espresso", order)

        assert "espresso" in result.message.lower()
        assert "$3.00" in result.message

    def test_bagel_price_lookup(self):
        """Test bagel-specific price lookup."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return an item result
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={
                       "type": "item",
                       "name": "Plain Bagel",
                       "price": 2.50,
                   }):
            result = sm.menu_inquiry_handler.handle_price_inquiry("plain bagel", order)

        # Should return a price (uses lookup_base_price)
        assert "$" in result.message
        assert "bagel" in result.message.lower()

    def test_no_match_returns_helpful_message(self):
        """Test no match returns helpful response."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine(menu_data={
            "items_by_type": {
                "beverage": [
                    {"name": "Coke", "base_price": 2.50},
                ],
            }
        })
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_price_inquiry("flying saucer", order)

        assert "not sure" in result.message.lower() or "help" in result.message.lower()

    def test_omelette_category_returns_price(self):
        """Test omelette category inquiry returns starting price."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock resolve_price_inquiry to return a category result
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.resolve_price_inquiry",
                   return_value={
                       "type": "category",
                       "display_name": "omelettes",
                       "min_price": 10.99,
                       "items": [],
                   }):
            result = sm.menu_inquiry_handler.handle_price_inquiry("omelette", order)

        assert "start at" in result.message.lower()
        assert "$10.99" in result.message


# =============================================================================
# Item Description Inquiry Handler Tests
# =============================================================================

class TestItemDescriptionInquiry:
    """Tests for _handle_item_description_inquiry."""

    def test_no_item_query_asks_which_item(self):
        """Test that no item query asks which item to describe."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry(None, order)

        assert "which item" in result.message.lower()

    def test_exact_match_returns_description(self):
        """Test exact match in ITEM_DESCRIPTIONS returns description."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("the classic bec", order)

        assert "eggs" in result.message.lower()
        assert "bacon" in result.message.lower()
        assert "would you like to order one" in result.message.lower()

    def test_partial_match_returns_description(self):
        """Test partial match in ITEM_DESCRIPTIONS returns description."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # "health nut" should match "the health nut"
        result = sm.menu_inquiry_handler.handle_item_description_inquiry("health nut", order)

        assert "egg whites" in result.message.lower()
        assert "spinach" in result.message.lower()

    def test_signature_sandwich_description(self):
        """Test signature sandwich description."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("the flatiron", order)

        assert "salmon" in result.message.lower()
        assert "avocado" in result.message.lower()

    def test_unknown_item_returns_helpful_message(self):
        """Test unknown item returns helpful message."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("mystery sandwich", order)

        assert "don't have" in result.message.lower() or "not" in result.message.lower()
        # Should offer to tell user what categories are available (data-driven)
        assert "would you like" in result.message.lower() or "we have" in result.message.lower()

    def test_does_not_modify_order(self):
        """Test that description inquiry does NOT add item to order."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("the leo", order)

        # Should describe the item
        assert "salmon" in result.message.lower() or "eggs" in result.message.lower()
        # But NOT add to order
        assert len(order.items.items) == 0

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("THE DELANCEY", order)

        assert "eggs" in result.message.lower()
        assert "corned beef" in result.message.lower() or "pastrami" in result.message.lower()

    def test_traditional_sandwich_description(self):
        """Test the traditional (borough) sandwich description."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("traditional", order)

        assert "salmon" in result.message.lower()
        assert "cream cheese" in result.message.lower()

    def test_formats_item_name_in_response(self):
        """Test that item name is properly formatted in response."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_item_description_inquiry("the mulberry", order)

        # Should have title case formatting
        assert "Mulberry" in result.message or "mulberry" in result.message.lower()
        assert "has" in result.message.lower()


# =============================================================================
# Delivery Handler Tests
# =============================================================================

class TestSignatureMenuInquiryHandler:
    """Tests for _handle_signature_menu_inquiry."""

    def test_no_items_returns_build_your_own(self):
        """Test that no signature items suggests building your own."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {"items_by_type": {}}  # No items
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry(None, order)

        assert "build your own" in result.message.lower()

    def test_all_signature_items_listed(self):
        """Test that all signature items are listed when no type specified."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Turkey Club"},
                    {"name": "Italian Sub"},
                    {"name": "The Classic"},
                    {"name": "The Leo"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry(None, order)

        assert "turkey club" in result.message.lower()
        assert "italian sub" in result.message.lower()
        assert "the classic" in result.message.lower()
        assert "the leo" in result.message.lower()
        assert "signature items" in result.message.lower()

    def test_specific_type_lists_only_that_type(self):
        """Test that specific type only lists items of that type."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Turkey Club"},
                ],
                "signature_item": [
                    {"name": "The Classic"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_items", order)

        assert "turkey club" in result.message.lower()
        assert "the classic" not in result.message.lower()
        assert "signature items" in result.message.lower()

    def test_single_item_formatted_correctly(self):
        """Test that single item is formatted without 'and'."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Turkey Club"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_items", order)

        assert "turkey club" in result.message.lower()
        assert " and " not in result.message.lower().split("are:")[1].split("would")[0]

    def test_two_items_formatted_with_and(self):
        """Test that two items are formatted with 'and'."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_item": [
                    {"name": "The Classic"},
                    {"name": "The Leo"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_item", order)

        assert "the classic and the leo" in result.message.lower()

    def test_signature_item_type_pluralized(self):
        """Test that signature_item type is pluralized correctly."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_item": [
                    {"name": "The Classic"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_item", order)

        # "signature_item" should be pluralized to "signature items"
        assert "signature items" in result.message.lower()

    def test_signature_menu_pagination_shows_first_five(self):
        """Test that signature menu shows first 5 items with 'and X more'."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Item 1"},
                    {"name": "Item 2"},
                    {"name": "Item 3"},
                    {"name": "Item 4"},
                    {"name": "Item 5"},
                    {"name": "Item 6"},
                    {"name": "Item 7"},
                    {"name": "Item 8"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_items", order)

        # Should show first 5 items plus "and 3 more"
        assert "item 1" in result.message.lower()
        assert "item 5" in result.message.lower()
        assert "item 6" not in result.message.lower()
        assert "and 3 more" in result.message.lower()

        # Should set pagination state
        pagination = result.order.get_menu_pagination()
        assert pagination is not None
        assert pagination["category"] == "signature_items"
        assert pagination["offset"] == 5
        assert pagination["total_items"] == 8

    def test_signature_menu_pagination_what_else_shows_remaining(self):
        """Test that 'what else' shows remaining items after first batch."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Item 1"},
                    {"name": "Item 2"},
                    {"name": "Item 3"},
                    {"name": "Item 4"},
                    {"name": "Item 5"},
                    {"name": "Item 6"},
                    {"name": "Item 7"},
                    {"name": "Item 8"},
                ],
            }
        }
        order = OrderTask()

        # First request - shows first 5
        result1 = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_items", order)

        # Second request - "what else" shows remaining
        result2 = sm.menu_inquiry_handler.handle_more_menu_items(result1.order)

        assert "item 6" in result2.message.lower()
        assert "item 7" in result2.message.lower()
        assert "item 8" in result2.message.lower()
        assert "that's all we have" in result2.message.lower()

        # Pagination should be cleared
        assert result2.order.get_menu_pagination() is None

    def test_signature_menu_no_pagination_when_fewer_than_five(self):
        """Test that fewer than 5 items shows all without pagination."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Item 1"},
                    {"name": "Item 2"},
                    {"name": "Item 3"},
                ],
            }
        }
        order = OrderTask()

        result = sm.menu_inquiry_handler.handle_signature_menu_inquiry("signature_items", order)

        # Should show all 3 items
        assert "item 1" in result.message.lower()
        assert "item 2" in result.message.lower()
        assert "item 3" in result.message.lower()
        assert "more" not in result.message.lower()

        # No pagination state
        assert result.order.get_menu_pagination() is None

    def test_what_other_signature_sandwiches_without_pagination_context(self):
        """Test that 'what other signature sandwiches' works without prior query.

        Regression test for bug where 'what other signature sandwiches do you have?'
        returned 'More of what?' because there was no pagination context.
        Now it should treat this as a fresh query for signature items.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.schemas.phases import OrderPhase

        sm = OrderStateMachine()
        sm.menu_data = {
            "items_by_type": {
                "signature_items": [
                    {"name": "Reuben"},
                    {"name": "BLT"},
                    {"name": "Club Sandwich"},
                ],
            }
        }
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS

        # User asks about signature sandwiches without any prior menu query
        result = sm.process("what other signature sandwiches do you have?", order)

        # Should NOT say "More of what?"
        assert "more of what" not in result.message.lower(), \
            f"Should list signature items, not ask 'more of what'. Got: {result.message}"

        # Should list the signature items
        assert "reuben" in result.message.lower() or "blt" in result.message.lower() or "signature" in result.message.lower(), \
            f"Should mention signature items. Got: {result.message}"


class TestIngredientSearchPagination:
    """Tests for ingredient search pagination ('what else' follow-up)."""

    def test_ingredient_search_what_else_shows_more_items(self):
        """Test that 'what else' shows remaining items after ingredient search."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        # Create 10 mock chicken items (more than the 6 shown initially)
        chicken_items = [
            {"id": i, "name": f"Chicken Item {i}", "description": f"Chicken dish #{i}"}
            for i in range(1, 11)
        ]
        sm.menu_data = {
            "ingredient_to_items": {
                "chicken": chicken_items,
            },
            "items_by_type": {},
            "item_name_to_id": {},
            "items_by_id": {},
        }
        order = OrderTask()

        # First request - "chicken" shows first 6 items
        result1 = sm.process("chicken", order)

        # Verify first batch and pagination state
        assert "chicken item 1" in result1.message.lower()
        assert "chicken item 6" in result1.message.lower()
        assert "and 4 more" in result1.message.lower()
        assert result1.order.pending_ingredient_search is not None
        assert result1.order.pending_ingredient_search.ingredient == "chicken"
        assert result1.order.pending_ingredient_search.offset == 6

        # Second request - "what else" shows remaining 4 items
        result2 = sm.process("what else", result1.order)

        assert "chicken item 7" in result2.message.lower()
        assert "chicken item 10" in result2.message.lower()
        assert "that's all" in result2.message.lower()

        # Pagination should be cleared
        assert result2.order.pending_ingredient_search is None

    def test_ingredient_search_pagination_cleared_on_new_request(self):
        """Test that non-'more' requests clear ingredient search pagination."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        chicken_items = [
            {"id": i, "name": f"Chicken Item {i}", "description": f"Chicken dish #{i}"}
            for i in range(1, 10)
        ]
        sm.menu_data = {
            "ingredient_to_items": {"chicken": chicken_items},
            "items_by_type": {"signature_items": []},
            "item_name_to_id": {},
            "items_by_id": {},
        }
        order = OrderTask()

        # First request - "chicken" sets up pagination
        result1 = sm.process("chicken", order)
        assert result1.order.pending_ingredient_search is not None

        # Second request - any non-"more" request should clear pagination
        # Using "hello" which won't match as a "wants_more_menu_items" request
        result2 = sm.process("hello", result1.order)
        assert result2.order.pending_ingredient_search is None


class TestSpecialsQuery:
    """Tests for specials/signature menu inquiries."""

    def test_specials_query_returns_signature_items(self):
        """Test that 'do you have any specials today' returns signature items."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Test various specials query phrasings
        result = sm.process("do you have any specials today", order)

        # Should return a list of signature items
        msg_lower = result.message.lower()
        # Check that it's responding with signature items, not asking for an order
        assert "signature" in msg_lower or "specials" in msg_lower or any(
            phrase in msg_lower for phrase in ["our", "we have", "are:"]
        ), f"Expected signature items response, got: {result.message}"

    def test_specials_query_parsing(self):
        """Test that specials queries are parsed with asking_signature_menu=True."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic

        test_inputs = [
            # Specials
            "do you have any specials today",
            "what are your specials",
            "any specials?",
            "got any specials today",
            "today's specials",
            # Signature items
            "what are your signature items?",
            "signature items",
            "show me your signature items",
            # Popular items
            "what are your popular items",
            "popular items",
            "what's popular",
            # Best sellers
            "best sellers",
            "what are your best sellers",
            # Favorites
            "what are your favorites",
            "house favorites",
            # Featured
            "featured items",
        ]

        for inp in test_inputs:
            result = parse_open_input_deterministic(inp)
            assert result is not None, f"Expected parse result for '{inp}'"
            assert result.asking_signature_menu, f"Expected asking_signature_menu=True for '{inp}', got {result}"


