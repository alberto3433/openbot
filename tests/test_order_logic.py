from sandwich_bot.order_logic import apply_intent_to_order_state


# Helper to create properly structured menu_index
def _make_menu_index(items):
    """Create a properly structured menu_index from a list of items."""
    menu = {
        "signature_sandwiches": [],
        "sides": [],
        "drinks": [],
        "desserts": [],
        "other": [],
    }
    for item in items:
        category = item.get("category", "other")
        if category == "drink":
            menu["drinks"].append(item)
        elif category == "side":
            menu["sides"].append(item)
        elif category == "sandwich":
            if item.get("is_signature"):
                menu["signature_sandwiches"].append(item)
            else:
                menu["other"].append(item)
        elif category == "dessert":
            menu["desserts"].append(item)
        else:
            menu["other"].append(item)
    return menu


def test_add_drink():
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {"menu_item_name": "Soda", "quantity": 1}
    menu = _make_menu_index([
        {"name": "Soda", "category": "drink", "base_price": 2.5}
    ])
    new = apply_intent_to_order_state(state, "add_drink", slots, menu)
    assert new["items"][0]["line_total"] == 2.5
    assert new["items"][0]["item_type"] == "drink"


def test_add_side():
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {"menu_item_name": "Chips", "quantity": 2}
    menu = _make_menu_index([
        {"name": "Chips", "category": "side", "base_price": 1.50}
    ])
    new = apply_intent_to_order_state(state, "add_side", slots, menu)
    assert new["items"][0]["item_type"] == "side"
    assert new["items"][0]["menu_item_name"] == "Chips"
    assert new["items"][0]["quantity"] == 2
    assert new["items"][0]["unit_price"] == 1.50
    assert new["items"][0]["line_total"] == 3.00
    assert new["status"] == "collecting_items"


def test_add_side_default_quantity():
    """Test that quantity defaults to 1 if not provided."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {"menu_item_name": "Cookie"}
    menu = _make_menu_index([
        {"name": "Cookie", "category": "side", "base_price": 1.79}
    ])
    new = apply_intent_to_order_state(state, "add_side", slots, menu)
    assert new["items"][0]["quantity"] == 1
    assert new["items"][0]["line_total"] == 1.79


# ---- Tests for update_sandwich ----


def test_update_sandwich_changes_bread():
    """Test updating a sandwich's bread type."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "white",
                "cheese": "cheddar",
                "toppings": ["lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    slots = {"item_index": 0, "bread": "wheat"}
    menu = {"Turkey Club": {"base_price": 8.0}}

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["bread"] == "wheat"
    # Other fields should be unchanged
    assert new["items"][0]["cheese"] == "cheddar"
    assert new["items"][0]["toppings"] == ["lettuce"]


def test_update_sandwich_changes_multiple_fields():
    """Test updating multiple fields at once."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "white",
                "cheese": "cheddar",
                "toppings": ["lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    slots = {
        "item_index": 0,
        "bread": "wheat",
        "cheese": "swiss",
        "toasted": True,
        "toppings": ["lettuce", "tomato", "onion"],
    }
    menu = {"Turkey Club": {"base_price": 8.0}}

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["bread"] == "wheat"
    assert new["items"][0]["cheese"] == "swiss"
    assert new["items"][0]["toasted"] is True
    assert new["items"][0]["toppings"] == ["lettuce", "tomato", "onion"]


def test_update_sandwich_finds_last_sandwich_when_no_index():
    """Test that update finds the last sandwich when no item_index is provided."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "white",
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            },
            {
                "item_type": "drink",
                "menu_item_name": "Soda",
                "quantity": 1,
                "unit_price": 2.0,
                "line_total": 2.0,
            },
            {
                "item_type": "sandwich",
                "menu_item_name": "Italian",
                "bread": "italian",
                "quantity": 1,
                "unit_price": 9.0,
                "line_total": 9.0,
            },
        ],
        "customer": {},
    }
    # No item_index provided - should update the last sandwich (Italian)
    slots = {"bread": "wheat"}
    menu = {"Italian": {"base_price": 9.0}}

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    # First sandwich should be unchanged
    assert new["items"][0]["bread"] == "white"
    # Last sandwich should be updated
    assert new["items"][2]["bread"] == "wheat"


def test_update_sandwich_changes_quantity_and_recalculates_total():
    """Test that updating quantity recalculates line_total."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "white",
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    slots = {"item_index": 0, "quantity": 3}
    menu = {"Turkey Club": {"base_price": 8.0}}

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["quantity"] == 3
    assert new["items"][0]["line_total"] == 24.0


def test_update_sandwich_invalid_index_does_nothing():
    """Test that invalid item_index returns state unchanged."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "white",
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    slots = {"item_index": 5, "bread": "wheat"}  # Index out of bounds
    menu = {}

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    # Should be unchanged
    assert new["items"][0]["bread"] == "white"


# ---- Tests for remove_item ----


def test_remove_item_by_index():
    """Test removing an item by index."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
            {"item_type": "drink", "menu_item_name": "Soda"},
            {"item_type": "side", "menu_item_name": "Chips"},
        ],
        "customer": {},
    }
    slots = {"item_index": 1}  # Remove the drink

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 2
    assert new["items"][0]["menu_item_name"] == "Turkey Club"
    assert new["items"][1]["menu_item_name"] == "Chips"


def test_remove_item_removes_last_when_no_index():
    """Test that remove_item removes the last item when no index provided."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
            {"item_type": "drink", "menu_item_name": "Soda"},
        ],
        "customer": {},
    }
    slots = {}  # No item_index

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 1
    assert new["items"][0]["menu_item_name"] == "Turkey Club"


def test_remove_item_sets_pending_when_cart_empty():
    """Test that status becomes 'pending' when all items are removed."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
        ],
        "customer": {},
    }
    slots = {"item_index": 0}

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 0
    assert new["status"] == "pending"


def test_remove_item_invalid_index_does_nothing():
    """Test that invalid index returns state unchanged."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
        ],
        "customer": {},
    }
    slots = {"item_index": 10}  # Out of bounds

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 1


def test_remove_item_from_empty_cart_does_nothing():
    """Test that removing from empty cart does nothing."""
    state = {
        "status": "pending",
        "items": [],
        "customer": {},
    }
    slots = {}

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 0
    assert new["status"] == "pending"


def test_remove_item_by_name():
    """Test removing an item by menu_item_name."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
            {"item_type": "side", "menu_item_name": "Chips"},
            {"item_type": "drink", "menu_item_name": "Soda"},
        ],
        "customer": {},
    }
    slots = {"menu_item_name": "Chips"}

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 2
    assert new["items"][0]["menu_item_name"] == "Turkey Club"
    assert new["items"][1]["menu_item_name"] == "Soda"


def test_remove_item_by_name_case_insensitive():
    """Test that remove by name is case-insensitive."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
            {"item_type": "side", "menu_item_name": "Chips"},
        ],
        "customer": {},
    }
    slots = {"menu_item_name": "CHIPS"}  # Uppercase

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    assert len(new["items"]) == 1
    assert new["items"][0]["menu_item_name"] == "Turkey Club"


def test_remove_item_by_name_not_found_does_nothing():
    """Test that if item name not found, nothing is removed."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
            {"item_type": "drink", "menu_item_name": "Soda"},
        ],
        "customer": {},
    }
    slots = {"menu_item_name": "Chips"}  # Not in order

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    # Nothing should be removed
    assert len(new["items"]) == 2
    assert new["items"][0]["menu_item_name"] == "Turkey Club"
    assert new["items"][1]["menu_item_name"] == "Soda"


def test_remove_item_index_takes_priority_over_name():
    """Test that item_index takes priority over menu_item_name."""
    state = {
        "status": "collecting_items",
        "items": [
            {"item_type": "sandwich", "menu_item_name": "Turkey Club"},
            {"item_type": "side", "menu_item_name": "Chips"},
            {"item_type": "drink", "menu_item_name": "Soda"},
        ],
        "customer": {},
    }
    # Both provided - index 0 (Turkey Club), but name says Chips
    slots = {"item_index": 0, "menu_item_name": "Chips"}

    new = apply_intent_to_order_state(state, "remove_item", slots, {})

    # Should remove by index (Turkey Club), not by name (Chips)
    assert len(new["items"]) == 2
    assert new["items"][0]["menu_item_name"] == "Chips"
    assert new["items"][1]["menu_item_name"] == "Soda"


# ---- Tests for price modifiers ----


def _make_sandwich_menu_with_extras():
    """Create a menu with sandwich customization options that have extra prices."""
    return _make_menu_index([
        {
            "name": "Turkey Club",
            "category": "sandwich",
            "is_signature": True,
            "base_price": 8.0,
            "recipe": {
                "choice_groups": [
                    {
                        "name": "Bread",
                        "options": [
                            {"name": "White", "extra_price": 0.0},
                            {"name": "Wheat", "extra_price": 0.50},
                            {"name": "Sourdough", "extra_price": 1.00},
                        ]
                    },
                    {
                        "name": "Cheese",
                        "options": [
                            {"name": "American", "extra_price": 0.0},
                            {"name": "Swiss", "extra_price": 0.50},
                            {"name": "Provolone", "extra_price": 0.75},
                        ]
                    },
                    {
                        "name": "Protein",
                        "options": [
                            {"name": "Turkey", "extra_price": 0.0},
                            {"name": "Double Turkey", "extra_price": 2.50},
                        ]
                    },
                    {
                        "name": "Toppings",
                        "options": [
                            {"name": "Lettuce", "extra_price": 0.0},
                            {"name": "Tomato", "extra_price": 0.0},
                            {"name": "Avocado", "extra_price": 1.50},
                            {"name": "Bacon", "extra_price": 1.00},
                        ]
                    },
                    {
                        "name": "Sauce",
                        "options": [
                            {"name": "Mayo", "extra_price": 0.0},
                            {"name": "Chipotle Mayo", "extra_price": 0.25},
                        ]
                    },
                ]
            }
        }
    ])


def test_add_sandwich_with_no_extras():
    """Test adding a sandwich with default options (no extra charges)."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",
        "quantity": 1,
        "bread": "White",
        "cheese": "American",
        "toppings": ["Lettuce", "Tomato"],
        "sauces": ["Mayo"],
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Base price only - all options have extra_price of 0.0
    assert new["items"][0]["unit_price"] == 8.0
    assert new["items"][0]["line_total"] == 8.0


def test_add_sandwich_with_premium_bread():
    """Test that premium bread adds extra cost."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",
        "quantity": 1,
        "bread": "Sourdough",  # +$1.00
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # 8.0 base + 1.0 sourdough = 9.0
    assert new["items"][0]["unit_price"] == 9.0
    assert new["items"][0]["line_total"] == 9.0


def test_add_sandwich_with_multiple_extras():
    """Test sandwich with multiple premium options."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",
        "quantity": 1,
        "bread": "Wheat",      # +$0.50
        "cheese": "Swiss",     # +$0.50
        "protein": "Double Turkey",  # +$2.50
        "toppings": ["Avocado", "Bacon"],  # +$1.50 + $1.00
        "sauces": ["Chipotle Mayo"],  # +$0.25
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # 8.0 base + 0.50 + 0.50 + 2.50 + 1.50 + 1.00 + 0.25 = 14.25
    assert new["items"][0]["unit_price"] == 14.25
    assert new["items"][0]["line_total"] == 14.25


def test_add_sandwich_with_extras_and_quantity():
    """Test that extras are multiplied by quantity."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",
        "quantity": 2,
        "bread": "Sourdough",  # +$1.00
        "cheese": "Provolone",  # +$0.75
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # 8.0 base + 1.0 + 0.75 = 9.75 per sandwich
    assert new["items"][0]["unit_price"] == 9.75
    # 9.75 * 2 = 19.50
    assert new["items"][0]["line_total"] == 19.50


def test_update_sandwich_recalculates_extras():
    """Test that updating a sandwich recalculates price with new extras."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": [],
                "sauces": [],
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    slots = {
        "item_index": 0,
        "bread": "Sourdough",  # +$1.00
        "cheese": "Swiss",     # +$0.50
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    # 8.0 base + 1.0 sourdough + 0.50 swiss = 9.50
    assert new["items"][0]["unit_price"] == 9.50
    assert new["items"][0]["line_total"] == 9.50


def test_confirm_order_recalculates_all_extras():
    """Test that confirm_order recalculates prices for all items."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "Wheat",       # +$0.50
                "cheese": "Provolone",  # +$0.75
                "protein": None,
                "toppings": ["Bacon"],  # +$1.00
                "sauces": [],
                "quantity": 2,
                "unit_price": 0,  # Will be recalculated
                "line_total": 0,
            }
        ],
        "customer": {"name": "Test"},
    }
    slots = {"confirm": True}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "confirm_order", slots, menu)

    # 8.0 base + 0.50 + 0.75 + 1.00 = 10.25 per sandwich
    assert new["items"][0]["unit_price"] == 10.25
    # 10.25 * 2 = 20.50
    assert new["items"][0]["line_total"] == 20.50
    assert new["total_price"] == 20.50
    assert new["status"] == "confirmed"


def test_price_modifier_case_insensitive():
    """Test that extra price lookup is case-insensitive."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",
        "quantity": 1,
        "bread": "SOURDOUGH",  # Uppercase but should still match
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Should still find the extra price
    assert new["items"][0]["unit_price"] == 9.0  # 8.0 + 1.0


def test_price_modifier_unknown_option_no_extra():
    """Test that unknown customization options don't add extra charges."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",
        "quantity": 1,
        "bread": "Gluten-Free",  # Not in menu - should be 0 extra
    }
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Only base price since unknown option has no extra
    assert new["items"][0]["unit_price"] == 8.0


# ---- Tests for mid-order modifications (Modify/Edit Support) ----


def test_update_sandwich_add_topping():
    """Test adding a topping to an existing sandwich (simulates 'add pickles')."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce", "Tomato"],  # Current toppings
                "sauces": ["Mayo"],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    # LLM should compute new list: existing + Pickles
    slots = {"toppings": ["Lettuce", "Tomato", "Pickles"]}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["toppings"] == ["Lettuce", "Tomato", "Pickles"]
    # Other fields unchanged
    assert new["items"][0]["bread"] == "White"
    assert new["items"][0]["sauces"] == ["Mayo"]


def test_update_sandwich_remove_topping():
    """Test removing a topping from an existing sandwich (simulates 'no tomato')."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce", "Tomato", "Onion"],
                "sauces": [],
                "toasted": True,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    # LLM should compute new list: existing minus Tomato
    slots = {"toppings": ["Lettuce", "Onion"]}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["toppings"] == ["Lettuce", "Onion"]
    # Other fields unchanged
    assert new["items"][0]["toasted"] is True


def test_update_sandwich_add_and_remove_toppings():
    """Test both adding and removing toppings (simulates 'add onions, remove tomato')."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "Wheat",
                "cheese": "Swiss",
                "protein": None,
                "toppings": ["Lettuce", "Tomato"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 9.0,
                "line_total": 9.0,
            }
        ],
        "customer": {},
    }
    # LLM computes: remove Tomato, add Onion → ["Lettuce", "Onion"]
    slots = {"toppings": ["Lettuce", "Onion"]}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["toppings"] == ["Lettuce", "Onion"]


def test_update_sandwich_change_to_different_sandwich():
    """Test changing the sandwich type (simulates 'actually make that a BLT')."""
    menu = _make_menu_index([
        {
            "name": "Turkey Club",
            "category": "sandwich",
            "is_signature": True,
            "base_price": 8.0,
            "recipe": {"choice_groups": []}
        },
        {
            "name": "BLT",
            "category": "sandwich",
            "is_signature": True,
            "base_price": 7.0,
            "recipe": {"choice_groups": []}
        }
    ])

    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": None,
                "protein": None,
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    slots = {"menu_item_name": "BLT"}

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["menu_item_name"] == "BLT"
    assert new["items"][0]["unit_price"] == 7.0
    assert new["items"][0]["line_total"] == 7.0


def test_update_first_sandwich_by_index():
    """Test modifying the first sandwich when multiple exist (simulates 'change my first sandwich')."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            },
            {
                "item_type": "sandwich",
                "menu_item_name": "BLT",
                "bread": "Wheat",
                "cheese": None,
                "protein": None,
                "toppings": ["Lettuce", "Tomato"],
                "sauces": ["Mayo"],
                "toasted": True,
                "quantity": 1,
                "unit_price": 7.0,
                "line_total": 7.0,
            },
        ],
        "customer": {},
    }
    # Modify first sandwich (index 0)
    slots = {"item_index": 0, "bread": "Sourdough", "toasted": True}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    # First sandwich should be updated
    assert new["items"][0]["bread"] == "Sourdough"
    assert new["items"][0]["toasted"] is True
    # Second sandwich should be unchanged
    assert new["items"][1]["bread"] == "Wheat"
    assert new["items"][1]["toasted"] is True


# ---- Tests for Custom Sandwich Pricing ----


def _make_custom_sandwich_menu():
    """Create a menu index with custom sandwich support."""
    return {
        "signature_sandwiches": [
            {
                "name": "Turkey Club",
                "category": "sandwich",
                "is_signature": True,
                "base_price": 8.99,
                "recipe": {"choice_groups": []},
            },
        ],
        "custom_sandwiches": [
            {
                "name": "Custom Sandwich",
                "category": "sandwich",
                "is_signature": False,
                "base_price": 5.99,
                "recipe": {"choice_groups": []},
            },
        ],
        "sides": [],
        "drinks": [],
        "desserts": [],
        "other": [],
        "protein_types": ["Turkey", "Ham", "Roast Beef", "Chicken", "Steak"],
        "protein_prices": {
            "turkey": 2.50,
            "ham": 2.50,
            "roast beef": 3.50,
            "chicken": 3.00,
            "steak": 4.00,
        },
        "bread_types": ["White", "Wheat", "Ciabatta"],
        "bread_prices": {
            "white": 0.0,
            "wheat": 0.0,
            "ciabatta": 1.00,
        },
    }


def test_custom_sandwich_by_protein_name():
    """Test that 'turkey sandwich' is treated as a custom sandwich with correct pricing."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Sandwich",
        "bread": "White",
        "protein": "Turkey",
        "cheese": "American",
        "toppings": ["Lettuce"],
        "sauces": ["Mayo"],
        "toasted": True,
        "quantity": 1,
    }
    menu = _make_custom_sandwich_menu()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Should be treated as custom sandwich
    assert new["items"][0]["is_custom"] is True
    # Price should be: base (5.99) + turkey (2.50) + white bread (0.00) = 8.49
    assert new["items"][0]["unit_price"] == 8.49
    assert new["items"][0]["menu_item_name"] == "Custom Turkey Sandwich"


def test_custom_sandwich_with_premium_bread():
    """Test custom sandwich pricing with premium bread."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Ham Sub",
        "bread": "Ciabatta",
        "protein": "Ham",
        "cheese": "Swiss",
        "toppings": [],
        "sauces": [],
        "toasted": False,
        "quantity": 1,
    }
    menu = _make_custom_sandwich_menu()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Price should be: base (5.99) + ham (2.50) + ciabatta (1.00) = 9.49
    assert new["items"][0]["unit_price"] == 9.49
    assert new["items"][0]["is_custom"] is True


def test_custom_sandwich_protein_extracted_from_name():
    """Test that protein is extracted from item name when not explicitly provided."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Steak Sandwich",  # Protein in name, not in slots
        "bread": "Wheat",
        "protein": None,  # Not provided explicitly
        "cheese": None,
        "toppings": [],
        "sauces": [],
        "toasted": True,
        "quantity": 1,
    }
    menu = _make_custom_sandwich_menu()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Should extract "Steak" from the name
    assert new["items"][0]["protein"] == "Steak"
    # Price should be: base (5.99) + steak (4.00) + wheat (0.00) = 9.99
    assert new["items"][0]["unit_price"] == 9.99
    assert new["items"][0]["is_custom"] is True


def test_signature_sandwich_not_treated_as_custom():
    """Test that signature sandwiches are NOT treated as custom."""
    state = {"status": "draft", "items": [], "customer": {}}
    slots = {
        "menu_item_name": "Turkey Club",  # This is a signature sandwich
        "bread": "Wheat",
        "protein": None,
        "cheese": None,
        "toppings": ["Lettuce"],
        "sauces": [],
        "toasted": True,
        "quantity": 1,
    }
    menu = _make_custom_sandwich_menu()

    new = apply_intent_to_order_state(state, "add_sandwich", slots, menu)

    # Should NOT be custom - it's a signature sandwich
    assert new["items"][0].get("is_custom") is False
    # Price should be the signature base price
    assert new["items"][0]["unit_price"] == 8.99
    assert new["items"][0]["menu_item_name"] == "Turkey Club"


def test_repeat_order_copies_previous_order_items():
    """Test that repeat_order copies all items from the customer's previous order."""
    state = {"status": "pending", "items": [], "customer": {"name": None, "phone": None}, "total_price": 0.0}
    menu = _make_menu_index([])

    # Simulated returning customer with previous order
    returning_customer = {
        "name": "John",
        "phone": "555-123-4567",
        "order_count": 2,
        "last_order_items": [
            {
                "menu_item_name": "Turkey Club",
                "item_type": "sandwich",
                "bread": "Wheat",
                "protein": "Turkey",
                "toppings": ["Lettuce", "Tomato"],
                "price": 8.00,
                "quantity": 1,
            },
            {
                "menu_item_name": "Chips",
                "item_type": "side",
                "price": 1.29,
                "quantity": 1,
            },
            {
                "menu_item_name": "Coke",
                "item_type": "drink",
                "price": 2.50,
                "quantity": 2,
            },
        ],
    }

    new = apply_intent_to_order_state(state, "repeat_order", {}, menu, returning_customer)

    # Should have 3 items
    assert len(new["items"]) == 3

    # Check each item was copied correctly
    assert new["items"][0]["menu_item_name"] == "Turkey Club"
    assert new["items"][0]["bread"] == "Wheat"
    assert new["items"][0]["toppings"] == ["Lettuce", "Tomato"]
    assert new["items"][0]["unit_price"] == 8.00

    assert new["items"][1]["menu_item_name"] == "Chips"
    assert new["items"][1]["unit_price"] == 1.29

    assert new["items"][2]["menu_item_name"] == "Coke"
    assert new["items"][2]["quantity"] == 2
    assert new["items"][2]["unit_price"] == 2.50

    # Total price should be calculated correctly (8.00 + 1.29 + 2.50*2 = 14.29)
    assert new["total_price"] == 14.29

    # Customer info should be copied
    assert new["customer"]["name"] == "John"
    assert new["customer"]["phone"] == "555-123-4567"

    # Status should be "building"
    assert new["status"] == "building"


def test_repeat_order_with_no_previous_order():
    """Test that repeat_order does nothing if no previous order exists."""
    state = {"status": "pending", "items": [], "customer": {"name": None, "phone": None}, "total_price": 0.0}
    menu = _make_menu_index([])

    # Returning customer with no previous order items
    returning_customer = {
        "name": "Jane",
        "phone": "555-999-8888",
        "order_count": 0,
        "last_order_items": [],
    }

    new = apply_intent_to_order_state(state, "repeat_order", {}, menu, returning_customer)

    # Should have no items (order unchanged)
    assert len(new["items"]) == 0
    assert new["status"] == "pending"


# ---- Additional tests for Modify/Edit Support scenarios ----


def test_update_sandwich_change_bread_mid_order():
    """Test 'change the bread to wheat' scenario."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": "Turkey",
                "toppings": ["Lettuce", "Tomato"],
                "sauces": ["Mayo"],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    # User says "change the bread to wheat"
    slots = {"bread": "Wheat"}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["bread"] == "Wheat"
    # Other fields should be unchanged
    assert new["items"][0]["cheese"] == "American"
    assert new["items"][0]["toppings"] == ["Lettuce", "Tomato"]
    assert new["items"][0]["sauces"] == ["Mayo"]
    assert new["items"][0]["toasted"] is False


def test_update_sandwich_change_cheese_mid_order():
    """Test 'change the cheese to Swiss' scenario."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "Wheat",
                "cheese": "American",
                "protein": "Turkey",
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": True,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    # User says "make it Swiss cheese"
    slots = {"cheese": "Swiss"}
    menu = _make_sandwich_menu_with_extras()

    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["cheese"] == "Swiss"
    # Other fields unchanged
    assert new["items"][0]["bread"] == "Wheat"
    assert new["items"][0]["toasted"] is True
    # Price should include Swiss extra ($0.50)
    assert new["items"][0]["unit_price"] == 9.0  # 8.0 base + 0.50 wheat + 0.50 swiss


def test_update_sandwich_toggle_toasted():
    """Test 'make that toasted' and 'don't toast it' scenarios."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    menu = _make_sandwich_menu_with_extras()

    # First: "make that toasted"
    slots = {"toasted": True}
    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)
    assert new["items"][0]["toasted"] is True

    # Then: "actually, don't toast it"
    slots = {"toasted": False}
    new = apply_intent_to_order_state(new, "update_sandwich", slots, menu)
    assert new["items"][0]["toasted"] is False


def test_update_sandwich_change_sauces():
    """Test 'add chipotle mayo' and 'no mayo' scenarios."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce", "Tomato"],
                "sauces": ["Mayo"],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    menu = _make_sandwich_menu_with_extras()

    # User says "add chipotle mayo instead of regular mayo"
    # LLM computes new sauces list
    slots = {"sauces": ["Chipotle Mayo"]}
    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["sauces"] == ["Chipotle Mayo"]
    # Price should include chipotle mayo extra ($0.25)
    assert new["items"][0]["unit_price"] == 8.25  # 8.0 base + 0.25 chipotle


def test_update_sandwich_extra_protein():
    """Test 'extra cheese' or 'double turkey' scenario with price update."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": "Turkey",
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    menu = _make_sandwich_menu_with_extras()

    # User says "make it double turkey"
    slots = {"protein": "Double Turkey"}
    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["protein"] == "Double Turkey"
    # Price should include double turkey extra ($2.50)
    assert new["items"][0]["unit_price"] == 10.50  # 8.0 base + 2.50 double turkey


def test_update_sandwich_premium_toppings_with_price():
    """Test adding premium toppings like avocado and bacon updates price."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce", "Tomato"],  # Free toppings
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    menu = _make_sandwich_menu_with_extras()

    # User says "add avocado and bacon"
    # LLM computes new list with premium toppings
    slots = {"toppings": ["Lettuce", "Tomato", "Avocado", "Bacon"]}
    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["toppings"] == ["Lettuce", "Tomato", "Avocado", "Bacon"]
    # Price should include avocado ($1.50) and bacon ($1.00)
    assert new["items"][0]["unit_price"] == 10.50  # 8.0 base + 1.50 + 1.00


def test_update_sandwich_multiple_changes_at_once():
    """Test making multiple changes in one request (bread, cheese, and toasted)."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            }
        ],
        "customer": {},
    }
    menu = _make_sandwich_menu_with_extras()

    # User says "change to wheat bread with Swiss cheese and make it toasted"
    slots = {
        "bread": "Wheat",
        "cheese": "Swiss",
        "toasted": True,
    }
    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    assert new["items"][0]["bread"] == "Wheat"
    assert new["items"][0]["cheese"] == "Swiss"
    assert new["items"][0]["toasted"] is True
    # Price: 8.0 base + 0.50 wheat + 0.50 swiss = 9.0
    assert new["items"][0]["unit_price"] == 9.0


def test_update_second_sandwich_by_index():
    """Test modifying second sandwich when multiple exist."""
    state = {
        "status": "collecting_items",
        "items": [
            {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "bread": "White",
                "cheese": "American",
                "protein": None,
                "toppings": ["Lettuce"],
                "sauces": [],
                "toasted": False,
                "quantity": 1,
                "unit_price": 8.0,
                "line_total": 8.0,
            },
            {
                "item_type": "sandwich",
                "menu_item_name": "BLT",
                "bread": "White",
                "cheese": None,
                "protein": "Bacon",
                "toppings": ["Lettuce", "Tomato"],
                "sauces": ["Mayo"],
                "toasted": False,
                "quantity": 1,
                "unit_price": 7.0,
                "line_total": 7.0,
            },
        ],
        "customer": {},
    }
    menu = _make_sandwich_menu_with_extras()

    # User says "make the second one toasted on wheat"
    slots = {"item_index": 1, "bread": "Wheat", "toasted": True}
    new = apply_intent_to_order_state(state, "update_sandwich", slots, menu)

    # First sandwich unchanged
    assert new["items"][0]["bread"] == "White"
    assert new["items"][0]["toasted"] is False

    # Second sandwich updated
    assert new["items"][1]["bread"] == "Wheat"
    assert new["items"][1]["toasted"] is True
