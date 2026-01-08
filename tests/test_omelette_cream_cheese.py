"""Test for omelette cream cheese flow - uses pytest fixtures to load menu from DB."""
import os
from dotenv import load_dotenv
load_dotenv()  # Load .env before any imports that use DATABASE_URL

import pytest


def test_omelette_cream_cheese_pricing(menu_cache_loaded):
    """Test that cream cheese spread on omelette side bagel is captured with correct price."""
    from sandwich_bot.tasks.bagel_config_handler import BagelConfigHandler
    from sandwich_bot.tasks.models import OrderTask, MenuItemTask
    from sandwich_bot.tasks.state_machine import OrderPhase
    from sandwich_bot.tasks.pricing import PricingEngine
    from sandwich_bot.menu_data_cache import menu_cache

    # Get menu data from cache
    menu_data = menu_cache.get_menu_index()

    # Create pricing engine
    def menu_lookup(name: str) -> dict | None:
        for item in menu_data.get('all_items', []):
            if item.get('name', '').lower() == name.lower():
                return item
        return None

    pricing = PricingEngine(menu_data, menu_lookup)

    # Create handler with dummy callback
    from sandwich_bot.tasks.state_machine import StateMachineResult
    def dummy_next_question(order):
        return StateMachineResult(message="Anything else?", order=order)

    handler = BagelConfigHandler(menu_data=menu_data, pricing=pricing)
    handler._get_next_question = dummy_next_question

    # Create order with omelette already set up for spread choice
    order = OrderTask()
    order.phase = OrderPhase.CONFIGURING_ITEM.value

    # Find an omelette in the menu - items are stored in items_by_type
    omelette_items = menu_data.get('items_by_type', {}).get('omelette', [])
    if not omelette_items:
        pytest.skip("No omelette found in menu")
    omelette_item = omelette_items[0]

    # Pre-create the omelette item with bagel side configured
    omelette = MenuItemTask(
        menu_item_name=omelette_item['name'],
        menu_item_id=omelette_item.get('id', 500),
        unit_price=omelette_item.get('base_price', 12.50),
        requires_side_choice=True,
        menu_item_type='omelette',
    )
    # Side choice already made - bagel, plain, toasted
    omelette.side_choice = 'bagel'
    omelette.bagel_choice = 'plain'
    omelette.toasted = True
    omelette.mark_in_progress()
    order.items.add_item(omelette)

    # Set up pending field for spread choice
    order.pending_field = 'spread'
    order.pending_item_id = omelette.id

    initial_price = omelette.unit_price

    print(f"\n=== BEFORE spread choice ===")
    print(f"Spread: {omelette.spread}")
    print(f"Spread Price: {getattr(omelette, 'spread_price', None)}")
    print(f"Unit Price: {omelette.unit_price}")

    # Process cream cheese choice
    result = handler.handle_spread_choice('cream cheese', omelette, order)
    print(f"\nResponse: {result.message[:100]}...")
    order = result.order

    # Get the item after processing
    items = order.items.get_active_items()
    assert items, "No items found in order"

    item = items[0]
    print(f"\n=== AFTER spread choice ===")
    print(f"Spread: {item.spread}")
    print(f"Spread Price: {getattr(item, 'spread_price', None)}")
    print(f"Unit Price: {item.unit_price}")

    # Assertions
    assert item.spread == 'cream cheese', f"Spread not captured correctly: {item.spread}"

    spread_price = getattr(item, 'spread_price', None)
    assert spread_price is not None, "Spread price not set"
    assert spread_price > 0, f"Spread price should be > 0, got {spread_price}"

    # Unit price should have increased by spread price
    assert item.unit_price == initial_price + spread_price, \
        f"Unit price wrong: {item.unit_price} (expected {initial_price} + {spread_price} = {initial_price + spread_price})"

    print(f"\n=== ALL TESTS PASSED ===")
    print(f"Spread price: ${spread_price}")
    print(f"Total price: ${item.unit_price}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
