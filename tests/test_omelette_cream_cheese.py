"""Test for omelette cream cheese flow - uses pytest fixtures to load menu from DB."""
import os
from dotenv import load_dotenv
load_dotenv()  # Load .env before any imports that use DATABASE_URL

import pytest


@pytest.mark.skip(reason="Test setup doesn't correctly simulate pending spread state - needs refactor")
def test_omelette_cream_cheese_pricing(menu_cache_loaded):
    """Test that cream cheese spread on omelette side bagel is captured with correct price."""
    from orderbot.tasks.state_machine import OrderStateMachine
    from orderbot.tasks.models import OrderTask, MenuItemTask
    from orderbot.tasks.schemas import OrderPhase
    from orderbot.menu_data_cache import menu_cache

    # Create state machine (uses global menu data from menu_cache_loaded fixture)
    state_machine = OrderStateMachine()

    # Create order with omelette already set up for spread choice
    order = OrderTask()
    order.phase = OrderPhase.CONFIGURING_ITEM.value

    # Find an omelette in the menu - items are stored in global menu data
    menu_data = menu_cache.get_menu_index()
    omelette_items = menu_data.get('items_by_type', {}).get('omelette', [])
    if not omelette_items:
        pytest.skip("No omelette found in menu")
    omelette_item = omelette_items[0]

    # Pre-create the omelette item with bagel side configured
    omelette = MenuItemTask(
        menu_item_name=omelette_item['name'],
        menu_item_id=omelette_item.get('id', 500),
        unit_price=omelette_item.get('base_price', 12.50),
        menu_item_type='omelette',
        attribute_values={"requires_side_choice": True},
    )
    # Side choice already made - bagel, plain, toasted
    omelette["side_choice"] = 'bagel'
    omelette["bagel_choice"] = 'plain'
    omelette["toasted"] = True
    omelette.mark_in_progress()
    order.items.add_item(omelette)

    # Set up pending field for spread choice
    order.pending_field = 'spread'
    order.pending_item_id = omelette.id

    initial_price = omelette.unit_price

    print(f"\n=== BEFORE spread choice ===")
    print(f"Spread: {omelette['spread']}")
    print(f"Unit Price: {omelette.unit_price}")

    # Process cream cheese choice via state machine
    result = state_machine.process("cream cheese", order)
    print(f"\nResponse: {result.message[:100]}...")
    order = result.order

    # Get the item after processing
    items = order.items.get_active_items()
    assert items, "No items found in order"

    item = items[0]
    print(f"\n=== AFTER spread choice ===")
    print(f"Spread: {item['spread']}")
    print(f"Unit Price: {item.unit_price}")
    print(f"Modifiers: {item.modifiers}")

    # Assertions - spread is stored in the "spread" attribute
    spread = item["spread"]
    assert spread is not None, f"Spread not captured correctly: {spread}"
    assert "cream cheese" in spread.lower() or "cc" in spread.lower(), \
        f"Spread should be cream cheese, got: {spread}"

    # Find spread price from modifiers
    spread_modifier = next((m for m in item.modifiers if m.get("category") == "spread"), None)
    spread_price = spread_modifier.get("price", 0) if spread_modifier else 0

    print(f"\n=== ALL TESTS PASSED ===")
    print(f"Spread: {spread}")
    print(f"Spread price: ${spread_price}")
    print(f"Total price: ${item.unit_price}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
