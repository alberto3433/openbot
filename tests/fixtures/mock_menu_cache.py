"""
Mock menu cache data for integration tests.

Contains mock attribute data and monkeypatch setup functions used
by test_tasks_integration.py and its split-off test modules.
"""


# =============================================================================
# Mock attribute data for unified handler tests
# =============================================================================

def get_mock_bagel_attributes():
    """Return mock attribute data for bagel item type."""
    return {
        "bread": {
            "slug": "bread",
            "display_name": "Bread",
            "question_text": "What kind of bagel?",
            "ask_in_conversation": True,
            "input_type": "single_select",
            "display_order": 1,
            "options": [
                {"slug": "plain", "display_name": "Plain", "price": 0},
                {"slug": "everything", "display_name": "Everything", "price": 0},
                {"slug": "sesame", "display_name": "Sesame", "price": 0},
                {"slug": "poppy", "display_name": "Poppy", "price": 0},
                {"slug": "onion", "display_name": "Onion", "price": 0},
            ],
        },
        "toasted": {
            "slug": "toasted",
            "display_name": "Toasted",
            "question_text": "Would you like it toasted?",
            "ask_in_conversation": True,
            "input_type": "boolean",
            "display_order": 2,
        },
        "spread_type": {
            "slug": "spread_type",
            "display_name": "Spread",
            "question_text": "Any spread?",
            "ask_in_conversation": True,
            "input_type": "single_select",
            "display_order": 3,
            "allow_none": True,
            "options": [
                {"slug": "plain_cc", "display_name": "Plain Cream Cheese", "price": 2.00},
                {"slug": "scallion_cc", "display_name": "Scallion Cream Cheese", "price": 2.25},
                {"slug": "butter", "display_name": "Butter", "price": 0.50},
            ],
        },
        "cheese": {
            "slug": "cheese",
            "display_name": "Cheese",
            "question_text": "What kind of cheese?",
            "ask_in_conversation": False,
            "input_type": "single_select",
            "display_order": 4,
            "allow_none": True,
            "options": [
                {"slug": "american", "display_name": "American", "price": 0.50},
                {"slug": "cheddar", "display_name": "Cheddar", "price": 0.50},
                {"slug": "swiss", "display_name": "Swiss", "price": 0.50},
                {"slug": "muenster", "display_name": "Muenster", "price": 0.50, "aliases": "munster"},
            ],
        },
    }


def get_mock_coffee_attributes():
    """Return mock attribute data for coffee_based_beverage and espresso item types.

    NOTE: Temperature (hot/iced) is NO LONGER a separate attribute.
    It's now baked into the menu item name (e.g., "Hot Latte", "Iced Coffee").

    Display orders match the real database:
    - size: display_order=1
    - espresso_shots: display_order=2
    - milk_sweetener_syrup: display_order=3
    - decaf: display_order=4
    """
    return {
        "size": {
            "slug": "size",
            "display_name": "Size",
            "question_text": "What size?",
            "ask_in_conversation": True,
            "input_type": "single_select",
            "display_order": 1,
            "options": [
                {"slug": "small", "display_name": "Small", "price": 0, "is_available": True},
                {"slug": "medium", "display_name": "Medium", "price": 0.50, "is_available": False},
                {"slug": "large", "display_name": "Large", "price": 1.00, "is_available": True},
            ],
        },
        "espresso_shots": {
            "slug": "espresso_shots",
            "display_name": "Extra Shots",
            "question_text": "Any extra shots?",
            "ask_in_conversation": True,
            "input_type": "single_select",
            "display_order": 2,
            "allow_none": True,
            "options": [
                {"slug": "regular", "display_name": "Regular", "price": 0},
                {"slug": "extra_shot", "display_name": "Extra Shot", "price": 1.00},
                {"slug": "double_shot", "display_name": "Double Shot", "price": 2.00},
            ],
        },
        "milk_sweetener_syrup": {
            "slug": "milk_sweetener_syrup",
            "display_name": "Milk, Sweetener, or Syrup",
            "question_text": "Any milk, sweetener, or syrup?",
            "ask_in_conversation": True,
            "input_type": "multi_select",
            "display_order": 3,
            "allow_none": True,
            "is_global_attribute": True,
            "options": [
                {"slug": "whole_milk", "display_name": "Whole Milk", "price": 0, "category": "milk", "must_match": []},
                {"slug": "skim_milk", "display_name": "Skim Milk", "price": 0, "category": "milk", "must_match": ["skim milk"]},
                {"slug": "oat_milk", "display_name": "Oat Milk", "price": 0.75, "category": "milk", "must_match": ["oat milk"]},
                {"slug": "sugar", "display_name": "Sugar", "price": 0, "category": "sweetener"},
                {"slug": "splenda", "display_name": "Splenda", "price": 0, "category": "sweetener", "aliases": ["splendas"]},
                {"slug": "sweet_n_low", "display_name": "Sweet N Low", "price": 0, "category": "sweetener"},
                {"slug": "vanilla_syrup", "display_name": "Vanilla Syrup", "price": 0.75, "category": "syrup"},
                {"slug": "caramel_syrup", "display_name": "Caramel Syrup", "price": 0.75, "category": "syrup"},
                {"slug": "hazelnut_syrup", "display_name": "Hazelnut Syrup", "price": 0.75, "category": "syrup"},
            ],
        },
        "decaf": {
            "slug": "decaf",
            "display_name": "Decaf",
            "question_text": "",
            "ask_in_conversation": True,
            "listen_only": True,
            "input_type": "boolean",
            "display_order": 4,
        },
        "style": {
            "slug": "style",
            "display_name": "Style",
            "question_text": None,
            "ask_in_conversation": False,
            "input_type": "single_select",
            "display_order": 5,
        },
    }


def get_mock_spread_sandwich_attributes():
    """Return mock attribute data for spread_sandwich item type."""
    return {
        "toasted": {
            "slug": "toasted",
            "display_name": "Toasted",
            "question_text": "Would you like it toasted?",
            "ask_in_conversation": True,
            "input_type": "boolean",
            "display_order": 1,
        },
    }


def get_mock_egg_bagel_attributes():
    """Return mock attributes for egg_bagel item type."""
    return {
        "toasted": {
            "slug": "toasted",
            "display_name": "Toasted",
            "is_required": False,
            "ask_in_conversation": True,
            "input_type": "boolean",
            "display_order": 1,
        },
    }


def mock_get_item_type_attributes(item_type_slug):
    """Mock menu_cache.get_item_type_attributes for tests."""
    if item_type_slug == "bagel":
        return get_mock_bagel_attributes()
    elif item_type_slug in ("coffee_based_beverage", "cocoa_based_beverage", "espresso", "espresso_based_beverage"):
        return get_mock_coffee_attributes()
    elif item_type_slug == "spread_sandwich":
        return get_mock_spread_sandwich_attributes()
    elif item_type_slug == "egg_bagel":
        return get_mock_egg_bagel_attributes()
    return {}


def mock_get_category_keyword_mapping(keyword: str):
    """Mock menu_cache.get_category_keyword_mapping for tests.

    Maps user-friendly category terms to item_type slugs.
    This replaces the database lookup for category keywords in tests.
    """
    keyword_lower = keyword.lower().strip()

    # Category keyword -> item_type mapping (mirrors database item_types/categories)
    # lookup_type determines query method:
    #   "item_type" - Query MenuItems by item_type_id
    #   "category" - Query MenuItems via MenuItemCategory join table
    category_mappings = {
        # Bagel keywords
        "bagel": {"slug": "bagel", "lookup_type": "item_type"},
        "bagels": {"slug": "bagel", "lookup_type": "item_type"},
        # Coffee/beverage keywords (coffee_based_beverage = coffee, tea, cold brew, etc.)
        "coffee": {"slug": "coffee_based_beverage", "lookup_type": "item_type"},
        "coffees": {"slug": "coffee_based_beverage", "lookup_type": "item_type"},
        "drink": {"slug": "coffee_based_beverage", "lookup_type": "item_type"},
        "drinks": {"slug": "coffee_based_beverage", "lookup_type": "item_type"},
        "beverage": {"slug": "coffee_based_beverage", "lookup_type": "item_type"},
        "beverages": {"slug": "coffee_based_beverage", "lookup_type": "item_type"},
        # Espresso-based drinks (latte, cappuccino, americano) have their own item type
        "latte": {"slug": "espresso_based_beverage", "lookup_type": "item_type"},
        "lattes": {"slug": "espresso_based_beverage", "lookup_type": "item_type"},
        "cappuccino": {"slug": "espresso_based_beverage", "lookup_type": "item_type"},
        "americano": {"slug": "espresso_based_beverage", "lookup_type": "item_type"},
        # Plain espresso has no size attribute
        "espresso": {"slug": "espresso", "lookup_type": "item_type"},
        # Sandwich keywords - sandwich is a category that groups subtypes via join table
        "sandwich": {
            "slug": "sandwich",
            "display_name": "sandwich",
            "display_name_plural": "sandwiches",
            "lookup_type": "category",
        },
        "sandwiches": {
            "slug": "sandwich",
            "display_name": "sandwich",
            "display_name_plural": "sandwiches",
            "lookup_type": "category",
        },
        # Sandwich subtypes - both underscore and space versions
        "egg_sandwich": {
            "slug": "egg_sandwich",
            "display_name": "egg sandwich",
            "display_name_plural": "egg sandwiches",
            "lookup_type": "item_type",
        },
        "egg sandwich": {
            "slug": "egg_sandwich",
            "display_name": "egg sandwich",
            "display_name_plural": "egg sandwiches",
            "lookup_type": "item_type",
        },
        "fish_sandwich": {
            "slug": "fish_sandwich",
            "display_name": "fish sandwich",
            "display_name_plural": "fish sandwiches",
            "lookup_type": "item_type",
        },
        "fish sandwich": {
            "slug": "fish_sandwich",
            "display_name": "fish sandwich",
            "display_name_plural": "fish sandwiches",
            "lookup_type": "item_type",
        },
        # Omelette keywords
        "omelette": {
            "slug": "omelette",
            "display_name": "omelette",
            "display_name_plural": "omelettes",
            "lookup_type": "item_type",
        },
        "omelettes": {
            "slug": "omelette",
            "display_name": "omelette",
            "display_name_plural": "omelettes",
            "lookup_type": "item_type",
        },
    }

    return category_mappings.get(keyword_lower)


# =============================================================================
# Mock functions for parser constants (signature items, known menu items, etc.)
# =============================================================================

def mock_get_signature_item_aliases():
    """Return mock signature item aliases for deterministic parser.

    Maps user input variations to actual menu item names.
    """
    return {
        "bec": "Bacon Egg & Cheese",
        "bacon egg cheese": "Bacon Egg & Cheese",
        "bacon egg and cheese": "Bacon Egg & Cheese",
        "sausage egg cheese": "Sausage Egg & Cheese",
        "sec": "Sausage Egg & Cheese",
        "the classic": "The Classic",
        "classic": "The Classic",
        "the leo": "The Leo",
        "leo": "The Leo",
    }


def mock_get_known_menu_items():
    """Return mock known menu item names for deterministic parser."""
    return {
        "bagel", "plain bagel", "everything bagel", "sesame bagel",
        "latte", "cappuccino", "espresso", "americano",
        "hot coffee", "iced coffee", "hot latte", "iced latte",
        "bacon egg & cheese", "sausage egg & cheese",
        "the classic", "the leo",
        "chips", "cookie", "brownie",
        "bagel chips", "latkes", "fruit cup", "fruit salad",
    }


def mock_get_configurable_item_type_slugs():
    """Return mock set of configurable item type slugs."""
    return {"bagel", "coffee_based_beverage", "cocoa_based_beverage", "espresso", "espresso_based_beverage", "spread_sandwich", "egg_bagel", "fruit_salad"}


def mock_get_configurable_item_types():
    """Return mock set of configurable item types (same as slugs for tests)."""
    return {"bagel", "coffee_based_beverage", "cocoa_based_beverage", "espresso", "espresso_based_beverage", "spread_sandwich", "egg_bagel", "fruit_salad"}


def mock_get_item_type_triggers(item_type_slug: str | None = None):
    """Return mock item type triggers for parser detection.

    Args:
        item_type_slug: If provided, returns triggers for just that type.
                       If None, returns all triggers as a dict.

    Note: These must match the actual database item types. In the DB:
    - coffee_based_beverage: coffee, chai, cold brew, etc.
    - espresso: standalone espresso drink
    - espresso_based_beverage: latte, cappuccino, americano, etc. (drinks based on espresso)
    """
    triggers = {
        "bagel": {"bagel", "bagels"},
        "coffee_based_beverage": {"coffee", "coffees", "chai", "cold brew"},
        "cocoa_based_beverage": {"hot chocolate"},
        "espresso": {"espresso", "espressos"},
        "espresso_based_beverage": {
            "latte", "lattes", "hot latte", "iced latte",
            "cappuccino", "cappuccinos", "hot cappuccino", "iced cappuccino",
            "americano", "cafe americano", "iced americano",
            "macchiato", "machiato",
        },
        "spread_sandwich": {"sandwich", "sandwiches"},
        "egg_bagel": {"egg bagel", "egg bagels"},
        "fruit_salad": {"fruit cup", "fruit salad", "fruit"},
    }
    if item_type_slug is not None:
        return triggers.get(item_type_slug, set())
    return triggers


# =============================================================================
# Monkeypatch setup
# =============================================================================

def apply_mock_menu_cache(monkeypatch):
    """Apply all menu cache mocks to the given monkeypatch instance.

    This is the core setup function. Call from a pytest fixture:

        @pytest.fixture(autouse=True)
        def mock_menu_cache_attributes(mock_menu_cache_integration):
            pass
    """
    from orderbot.cache import menu_cache

    # Set _is_loaded to True so methods return mock data instead of empty sets
    monkeypatch.setattr(menu_cache, "_is_loaded", True)
    monkeypatch.setattr(menu_cache, "get_item_type_attributes", mock_get_item_type_attributes)
    monkeypatch.setattr(menu_cache, "get_category_keyword_mapping", mock_get_category_keyword_mapping)
    # Mock configurable item type detection - required for parser to detect "coffee" as coffee_based_beverage
    monkeypatch.setattr(menu_cache, "get_configurable_item_type_slugs", mock_get_configurable_item_type_slugs)
    monkeypatch.setattr(menu_cache, "get_configurable_item_types", mock_get_configurable_item_types)
    monkeypatch.setattr(menu_cache, "get_item_type_triggers", mock_get_item_type_triggers)
    monkeypatch.setattr(menu_cache, "get_items_with_defaults_aliases", mock_get_signature_item_aliases)
    # Mock item_has_default_ingredients based on signature items
    signature_items = set(mock_get_signature_item_aliases().values())
    monkeypatch.setattr(menu_cache, "item_has_default_ingredients", lambda name: name in signature_items)
    # Mock unavailable size terms for "We don't have medium" detection
    monkeypatch.setattr(menu_cache, "get_unavailable_size_terms", lambda: {"medium": "Medium"})
    # Mock known menu items on the cache - needed by parser_constants
    monkeypatch.setattr(menu_cache, "get_known_menu_items", mock_get_known_menu_items)
    # Mock attribute option words for unrecognized word detection
    mock_attr_option_words = {
        "small": "size", "large": "size", "medium": "size",
        "splenda": "milk_sweetener_syrup", "splendas": "milk_sweetener_syrup",
        "sugar": "milk_sweetener_syrup", "whole_milk": "milk_sweetener_syrup",
        "oat_milk": "milk_sweetener_syrup", "oat": "milk_sweetener_syrup",
        "hot": "iced", "iced": "iced",
    }
    monkeypatch.setattr(menu_cache, "get_all_attribute_option_words", lambda: mock_attr_option_words)
    # Mock modifier words (empty for now - we're not testing ingredient modifiers here)
    monkeypatch.setattr(menu_cache, "get_all_modifier_words", lambda: set())
    # Mock the functions in parsers.constants module
    import orderbot.tasks.parsers.constants as parser_constants
    # Mock known menu items - required for multi-item parsing
    monkeypatch.setattr(parser_constants, "get_known_menu_items", mock_get_known_menu_items)
