"""
Test Menu Data Factory Functions.

Factory functions for creating mock menu data structures for testing.
These provide consistent menu configurations without requiring database access.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven from the database.
"""


def create_minimal_menu_data() -> dict:
    """Create minimal menu data for basic tests.

    Returns a bare-bones menu structure with just enough to run simple tests.
    Use this when you need any valid menu_data but don't care about specific items.
    """
    return {
        "all_items": [
            {"id": 1, "name": "Bagel", "base_price": 2.20, "category": "custom_bagels"},
        ],
        "custom_bagels": [
            {"id": 1, "name": "Bagel", "base_price": 2.20},
        ],
        "item_types": {
            "bagel": {
                "attributes": [
                    {
                        "slug": "bread",
                        "options": [
                            {"slug": "plain", "display_name": "Plain", "price_modifier": 0.0},
                        ]
                    },
                ]
            },
        },
    }


def create_bagel_menu_data() -> dict:
    """Create menu data focused on bagels with various types and spreads.

    Returns menu data with:
    - Multiple bagel types including gluten free (with upcharge)
    - Common spreads with pricing
    - Protein options

    Use this for bagel-specific tests including pricing.
    """
    return {
        "all_items": [
            {"id": 1, "name": "Bagel", "base_price": 2.20, "category": "custom_bagels"},
            {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00, "category": "custom_bagels"},
            {"id": 3, "name": "Plain Bagel", "base_price": 2.20, "category": "custom_bagels"},
            {"id": 4, "name": "Everything Bagel", "base_price": 2.20, "category": "custom_bagels"},
        ],
        "custom_bagels": [
            {"id": 1, "name": "Bagel", "base_price": 2.20},
            {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00},
            {"id": 3, "name": "Plain Bagel", "base_price": 2.20},
            {"id": 4, "name": "Everything Bagel", "base_price": 2.20},
        ],
        "bagels": {
            "plain": {"id": 3, "name": "Plain Bagel", "base_price": 2.20},
            "everything": {"id": 4, "name": "Everything Bagel", "base_price": 2.20},
            "gluten free": {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00},
        },
        "item_types": {
            "bagel": {
                "attributes": [
                    {
                        "slug": "bread",
                        "options": [
                            {"slug": "plain", "display_name": "Plain", "price_modifier": 0.0},
                            {"slug": "everything", "display_name": "Everything", "price_modifier": 0.0},
                            {"slug": "sesame", "display_name": "Sesame", "price_modifier": 0.0},
                            {"slug": "gluten_free", "display_name": "Gluten Free", "price_modifier": 0.80},
                        ]
                    },
                    {
                        "slug": "spread",
                        "options": [
                            {"slug": "cream_cheese", "display_name": "Cream Cheese", "price_modifier": 1.50},
                            {"slug": "butter", "display_name": "Butter", "price_modifier": 0.50},
                            {"slug": "scallion_cream_cheese", "display_name": "Scallion Cream Cheese", "price_modifier": 1.75},
                        ]
                    },
                    {
                        "slug": "protein",
                        "options": [
                            {"slug": "ham", "display_name": "Ham", "price_modifier": 2.00},
                            {"slug": "bacon", "display_name": "Bacon", "price_modifier": 2.00},
                            {"slug": "egg", "display_name": "Egg", "price_modifier": 1.50},
                            {"slug": "nova_scotia_salmon", "display_name": "Nova Scotia Salmon", "price_modifier": 6.00},
                            {"slug": "turkey", "display_name": "Turkey", "price_modifier": 2.50},
                        ]
                    },
                    {
                        "slug": "cheese",
                        "options": [
                            {"slug": "american", "display_name": "American", "price_modifier": 0.75},
                            {"slug": "swiss", "display_name": "Swiss", "price_modifier": 0.75},
                        ]
                    },
                    {
                        "slug": "topping",
                        "options": [
                            {"slug": "tomato", "display_name": "Tomato", "price_modifier": 0.50},
                            {"slug": "onion", "display_name": "Onion", "price_modifier": 0.50},
                            {"slug": "capers", "display_name": "Capers", "price_modifier": 0.75},
                        ]
                    },
                ]
            },
        },
    }


def create_beverage_menu_data() -> dict:
    """Create menu data focused on beverages with sizes and milk options.

    Returns menu data with:
    - Coffee and espresso drinks
    - Size options with pricing
    - Milk options with upcharges
    - Syrup options

    Use this for beverage-specific tests including pricing.
    """
    return {
        "all_items": [
            {"id": 101, "name": "Coffee", "base_price": 2.50, "category": "drinks"},
            {"id": 102, "name": "Iced Coffee", "base_price": 3.00, "category": "drinks"},
            {"id": 103, "name": "Latte", "base_price": 4.50, "category": "drinks"},
            {"id": 104, "name": "Cappuccino", "base_price": 4.50, "category": "drinks"},
        ],
        "drinks": [
            {"id": 101, "name": "Coffee", "base_price": 2.50},
            {"id": 102, "name": "Iced Coffee", "base_price": 3.00},
            {"id": 103, "name": "Latte", "base_price": 4.50},
            {"id": 104, "name": "Cappuccino", "base_price": 4.50},
        ],
        "item_types": {
            "coffee_based_beverage": {
                "attributes": [
                    {
                        "slug": "size",
                        "options": [
                            {"slug": "small", "display_name": "Small", "price_modifier": 0.0},
                            {"slug": "medium", "display_name": "Medium", "price_modifier": 0.0},
                            {"slug": "large", "display_name": "Large", "price_modifier": 0.90},
                        ]
                    },
                    {
                        "slug": "milk",
                        "options": [
                            {"slug": "whole", "display_name": "Whole Milk", "price_modifier": 0.0},
                            {"slug": "oat", "display_name": "Oat Milk", "price_modifier": 0.50},
                            {"slug": "almond", "display_name": "Almond Milk", "price_modifier": 0.50},
                        ]
                    },
                    {
                        "slug": "syrup",
                        "options": [
                            {"slug": "vanilla", "display_name": "Vanilla", "price_modifier": 0.65},
                            {"slug": "hazelnut", "display_name": "Hazelnut", "price_modifier": 0.65},
                        ]
                    },
                ]
            },
            "espresso": {
                "attributes": [
                    {
                        "slug": "size",
                        "options": [
                            {"slug": "small", "display_name": "Small", "price_modifier": 0.0},
                            {"slug": "medium", "display_name": "Medium", "price_modifier": 0.0},
                            {"slug": "large", "display_name": "Large", "price_modifier": 0.90},
                        ]
                    },
                    {
                        "slug": "milk",
                        "options": [
                            {"slug": "whole", "display_name": "Whole Milk", "price_modifier": 0.0},
                            {"slug": "oat", "display_name": "Oat Milk", "price_modifier": 0.50},
                            {"slug": "almond", "display_name": "Almond Milk", "price_modifier": 0.50},
                        ]
                    },
                    {
                        "slug": "syrup",
                        "options": [
                            {"slug": "vanilla", "display_name": "Vanilla", "price_modifier": 0.65},
                            {"slug": "hazelnut", "display_name": "Hazelnut", "price_modifier": 0.65},
                        ]
                    },
                ]
            },
        },
    }


def create_test_menu_data() -> dict:
    """Create comprehensive menu data for adapter/pricing tests.

    Returns menu data with:
    - Bagels with types and spreads
    - Beverages with sizes and milk options
    - Omelettes with side choices

    This is the standard menu data for adapter and pricing tests.
    """
    return {
        "all_items": [
            {"id": 1, "name": "Bagel", "base_price": 2.20, "category": "custom_bagels"},
            {"id": 2, "name": "Gluten Free Bagel", "base_price": 3.00, "category": "custom_bagels"},
            {"id": 3, "name": "Coffee", "base_price": 2.50, "category": "drinks"},
        ],
        "custom_bagels": [
            {"id": 1, "name": "Bagel", "base_price": 2.20},
        ],
        "item_types": {
            "bagel": {
                "attributes": [
                    {
                        "slug": "bread",
                        "options": [
                            {"slug": "plain", "display_name": "Plain", "price_modifier": 0.0},
                            {"slug": "everything", "display_name": "Everything", "price_modifier": 0.0},
                            {"slug": "sesame", "display_name": "Sesame", "price_modifier": 0.0},
                            {"slug": "gluten_free", "display_name": "Gluten Free", "price_modifier": 0.80},
                        ]
                    },
                    {
                        "slug": "spread",
                        "options": [
                            {"slug": "cream_cheese", "display_name": "Cream Cheese", "price_modifier": 1.50},
                            {"slug": "butter", "display_name": "Butter", "price_modifier": 0.50},
                            {"slug": "scallion_cream_cheese", "display_name": "Scallion Cream Cheese", "price_modifier": 1.75},
                        ]
                    },
                    {
                        "slug": "protein",
                        "options": [
                            {"slug": "ham", "display_name": "Ham", "price_modifier": 2.00},
                            {"slug": "bacon", "display_name": "Bacon", "price_modifier": 2.00},
                            {"slug": "egg", "display_name": "Egg", "price_modifier": 1.50},
                            {"slug": "nova_scotia_salmon", "display_name": "Nova Scotia Salmon", "price_modifier": 6.00},
                            {"slug": "turkey", "display_name": "Turkey", "price_modifier": 2.50},
                        ]
                    },
                    {
                        "slug": "cheese",
                        "options": [
                            {"slug": "american", "display_name": "American", "price_modifier": 0.75},
                            {"slug": "swiss", "display_name": "Swiss", "price_modifier": 0.75},
                        ]
                    },
                    {
                        "slug": "topping",
                        "options": [
                            {"slug": "tomato", "display_name": "Tomato", "price_modifier": 0.50},
                            {"slug": "onion", "display_name": "Onion", "price_modifier": 0.50},
                            {"slug": "capers", "display_name": "Capers", "price_modifier": 0.75},
                        ]
                    },
                ]
            },
            "coffee_based_beverage": {
                "attributes": [
                    {
                        "slug": "size",
                        "options": [
                            {"slug": "small", "display_name": "Small", "price_modifier": 0.0},
                            {"slug": "large", "display_name": "Large", "price_modifier": 0.90},
                        ]
                    },
                    {
                        "slug": "milk",
                        "options": [
                            {"slug": "whole", "display_name": "Whole Milk", "price_modifier": 0.0},
                            {"slug": "oat", "display_name": "Oat Milk", "price_modifier": 0.50},
                            {"slug": "almond", "display_name": "Almond Milk", "price_modifier": 0.50},
                        ]
                    },
                    {
                        "slug": "syrup",
                        "options": [
                            {"slug": "vanilla", "display_name": "Vanilla", "price_modifier": 0.65},
                            {"slug": "hazelnut", "display_name": "Hazelnut", "price_modifier": 0.65},
                        ]
                    },
                ]
            },
            "omelette": {
                "attributes": [
                    {
                        "slug": "side_choice",
                        "options": [
                            {"slug": "bagel", "display_name": "Bagel", "price_modifier": 0.0},
                            {"slug": "toast", "display_name": "Toast", "price_modifier": 0.0},
                        ]
                    },
                    {
                        "slug": "spread",
                        "options": [
                            {"slug": "cream_cheese", "display_name": "Cream Cheese", "price_modifier": 1.50},
                            {"slug": "butter", "display_name": "Butter", "price_modifier": 0.50},
                        ]
                    },
                ]
            },
        },
    }


def create_full_menu_data() -> dict:
    """Create comprehensive menu data for integration tests.

    Returns menu data with:
    - Full drink menu including disambiguation-prone items
    - Bagels with all types
    - Muffins and desserts
    - Signature/speed menu items

    Use this for end-to-end and integration tests that need realistic menu variety.
    """
    return {
        "all_items": [
            # Drinks with disambiguation potential
            {"id": 101, "name": "Coffee", "base_price": 2.50, "category": "drinks"},
            {"id": 102, "name": "Iced Coffee", "base_price": 3.00, "category": "drinks"},
            {"id": 103, "name": "Decaf Coffee", "base_price": 2.75, "category": "drinks"},
            {"id": 104, "name": "Latte", "base_price": 4.50, "category": "drinks"},
            {"id": 105, "name": "Cappuccino", "base_price": 4.50, "category": "drinks"},
            # Orange juice variants
            {"id": 106, "name": "Orange Juice Small", "base_price": 3.00, "category": "drinks"},
            {"id": 107, "name": "Orange Juice Large", "base_price": 5.00, "category": "drinks"},
            {"id": 108, "name": "Fresh Squeezed Orange Juice", "base_price": 6.00, "category": "drinks"},
            # Bagels
            {"id": 201, "name": "Plain Bagel", "base_price": 2.50, "category": "custom_bagels"},
            {"id": 202, "name": "Everything Bagel", "base_price": 2.75, "category": "custom_bagels"},
            {"id": 203, "name": "Sesame Bagel", "base_price": 2.50, "category": "custom_bagels"},
            # Muffins (disambiguation)
            {"id": 301, "name": "Blueberry Muffin", "base_price": 3.50, "category": "desserts"},
            {"id": 302, "name": "Chocolate Chip Muffin", "base_price": 3.50, "category": "desserts"},
            {"id": 303, "name": "Corn Muffin", "base_price": 3.00, "category": "desserts"},
            # Speed menu items
            {"id": 401, "name": "The Classic BEC", "base_price": 9.50, "category": "signature_sandwiches"},
            {"id": 402, "name": "The Leo", "base_price": 14.00, "category": "signature_sandwiches"},
        ],
        "drinks": [
            {"id": 101, "name": "Coffee", "base_price": 2.50},
            {"id": 102, "name": "Iced Coffee", "base_price": 3.00},
            {"id": 103, "name": "Decaf Coffee", "base_price": 2.75},
            {"id": 104, "name": "Latte", "base_price": 4.50},
            {"id": 105, "name": "Cappuccino", "base_price": 4.50},
            {"id": 106, "name": "Orange Juice Small", "base_price": 3.00},
            {"id": 107, "name": "Orange Juice Large", "base_price": 5.00},
            {"id": 108, "name": "Fresh Squeezed Orange Juice", "base_price": 6.00},
        ],
        "desserts": [
            {"id": 301, "name": "Blueberry Muffin", "base_price": 3.50},
            {"id": 302, "name": "Chocolate Chip Muffin", "base_price": 3.50},
            {"id": 303, "name": "Corn Muffin", "base_price": 3.00},
        ],
        "signature_sandwiches": [
            {"id": 401, "name": "The Classic BEC", "base_price": 9.50, "requires_bagel_choice": True},
            {"id": 402, "name": "The Leo", "base_price": 14.00, "requires_bagel_choice": True},
        ],
        "custom_bagels": [
            {"id": 201, "name": "Plain Bagel", "base_price": 2.50},
            {"id": 202, "name": "Everything Bagel", "base_price": 2.75},
            {"id": 203, "name": "Sesame Bagel", "base_price": 2.50},
        ],
        "bagels": {
            "plain": {"id": 201, "name": "Plain Bagel", "base_price": 2.50},
            "everything": {"id": 202, "name": "Everything Bagel", "base_price": 2.75},
            "sesame": {"id": 203, "name": "Sesame Bagel", "base_price": 2.50},
        },
        "signature_items": {
            "the classic bec": {"id": 401, "name": "The Classic BEC", "base_price": 9.50},
            "classic bec": {"id": 401, "name": "The Classic BEC", "base_price": 9.50},
            "the leo": {"id": 402, "name": "The Leo", "base_price": 14.00},
            "leo": {"id": 402, "name": "The Leo", "base_price": 14.00},
        },
        "categories": ["custom_bagels", "drinks", "desserts", "signature_sandwiches"],
        "store_id": "test_store",
        # Item types with attribute options for pricing lookups
        "item_types": {
            "bagel": {
                "attributes": [
                    {
                        "slug": "bread",
                        "options": [
                            {"slug": "plain", "display_name": "Plain", "price_modifier": 0.0},
                            {"slug": "everything", "display_name": "Everything", "price_modifier": 0.0},
                            {"slug": "sesame", "display_name": "Sesame", "price_modifier": 0.0},
                            {"slug": "gluten_free", "display_name": "Gluten Free", "price_modifier": 0.80},
                        ]
                    },
                    {
                        "slug": "spread",
                        "options": [
                            {"slug": "cream_cheese", "display_name": "Cream Cheese", "price_modifier": 1.50},
                            {"slug": "butter", "display_name": "Butter", "price_modifier": 0.50},
                        ]
                    },
                ]
            },
            "coffee_based_beverage": {
                "attributes": [
                    {
                        "slug": "size",
                        "options": [
                            {"slug": "small", "display_name": "Small", "price_modifier": 0.0},
                            {"slug": "medium", "display_name": "Medium", "price_modifier": 0.0},
                            {"slug": "large", "display_name": "Large", "price_modifier": 0.90},
                        ]
                    },
                    {
                        "slug": "milk",
                        "options": [
                            {"slug": "whole", "display_name": "Whole Milk", "price_modifier": 0.0},
                            {"slug": "oat", "display_name": "Oat Milk", "price_modifier": 0.50},
                            {"slug": "almond", "display_name": "Almond Milk", "price_modifier": 0.50},
                        ]
                    },
                ]
            },
        },
    }
