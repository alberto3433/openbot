"""Trace test to find where unavailable_selections is lost."""
import pytest


def test_trace_handle_unavailable_selection_directly():
    """Trace handle_unavailable_selection directly."""
    from tests.test_tasks_integration import mock_get_item_type_attributes
    from orderbot.tasks.models import MenuItemTask, OrderTask
    from orderbot.tasks.config_question_builder import QuestionBuilder

    # Verify mock setup
    attrs = mock_get_item_type_attributes("sized_beverage")
    assert "size" in attrs, "Mock should have size attribute"

    item = MenuItemTask(
        menu_item_name="Hot Coffee",
        menu_item_type="sized_beverage",
        unit_price=0,
    )
    item.unavailable_selections = {"size": {"attempted_slug": "medium", "attempted_display": "Medium"}}

    order = OrderTask()
    builder = QuestionBuilder()
    size_attr = attrs["size"]

    result = builder.handle_unavailable_selection(item, order, size_attr)

    assert result is not None, "handle_unavailable_selection should return a result"
    assert "don't have" in result.message.lower(), f"Expected 'don't have', got: {result.message}"


def test_trace_e2e_with_state_machine(monkeypatch):
    """Trace the full E2E flow with explicit mock setup."""
    from orderbot.tasks.state_machine import OrderStateMachine
    from orderbot.tasks.models import OrderTask
    from orderbot.cache import menu_cache
    from tests.test_tasks_integration import (
        mock_get_item_type_attributes,
        mock_get_category_keyword_mapping,
        mock_get_signature_item_aliases,
        mock_get_known_menu_items,
        mock_get_configurable_item_type_slugs,
        mock_get_configurable_item_types,
        mock_get_item_type_triggers,
    )
    import orderbot.tasks.parsers.constants as parser_constants

    # Apply mocks (same as autouse fixture)
    monkeypatch.setattr(menu_cache, "_is_loaded", True)
    monkeypatch.setattr(menu_cache, "get_item_type_attributes", mock_get_item_type_attributes)
    monkeypatch.setattr(menu_cache, "get_category_keyword_mapping", mock_get_category_keyword_mapping)
    monkeypatch.setattr(menu_cache, "get_configurable_item_type_slugs", mock_get_configurable_item_type_slugs)
    monkeypatch.setattr(menu_cache, "get_configurable_item_types", mock_get_configurable_item_types)
    monkeypatch.setattr(menu_cache, "get_item_type_triggers", mock_get_item_type_triggers)
    monkeypatch.setattr(parser_constants, "get_signature_item_aliases", mock_get_signature_item_aliases)
    monkeypatch.setattr(parser_constants, "get_known_menu_items", mock_get_known_menu_items)

    sm = OrderStateMachine()
    order = OrderTask()

    # Trace what get_item_type_attributes returns
    attrs = menu_cache.get_item_type_attributes("sized_beverage")
    size_opts = attrs.get("size", {}).get("options", [])
    medium_opt = next((o for o in size_opts if o.get("slug") == "medium"), None)

    assert attrs, "get_item_type_attributes should return mock data"
    assert "size" in attrs, "Mock should have size attribute"
    assert medium_opt, "Mock should have medium option"
    assert medium_opt.get("is_available") is False, f"Medium should be unavailable, got: {medium_opt}"

    # Process the order
    result = sm.process("medium hot coffee", order)

    # This assertion tells us what's happening
    assert "don't have" in result.message.lower() or "no medium" in result.message.lower(), \
        f"Expected message about unavailable medium, got: {result.message}\n" \
        f"Item.unavailable_selections: {result.order.items.items[0].unavailable_selections if result.order.items.items else 'NO ITEMS'}"
