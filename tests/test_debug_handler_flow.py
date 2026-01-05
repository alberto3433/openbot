"""Debug test for handler flow with modifiers."""


from sandwich_bot.tasks.parsers.deterministic import (
    _parse_bagel_with_modifiers,
    _parse_multi_item_order,
)
from sandwich_bot.tasks.parsers import parse_open_input


def test_multi_item_path():
    """Test if multi-item parsing is being triggered incorrectly."""
    user_input = "plain bagel with Egg Whites, Swiss, and Spinach"

    print(f"\n{'='*60}")
    print(f"INPUT: {user_input}")
    print(f"{'='*60}")

    # Check what multi-item parsing returns
    multi_result = _parse_multi_item_order(user_input)
    print(f"\n1. _parse_multi_item_order result:")
    if multi_result:
        print(f"   new_bagel: {multi_result.new_bagel}")
        print(f"   new_bagel_proteins: {multi_result.new_bagel_proteins}")
        print(f"   parsed_items: {len(multi_result.parsed_items) if multi_result.parsed_items else 0}")
        if multi_result.parsed_items:
            for i, item in enumerate(multi_result.parsed_items):
                print(f"   parsed_items[{i}]: type={type(item).__name__}")
                if hasattr(item, 'proteins'):
                    print(f"      proteins: {item.proteins}")
    else:
        print("   RETURNED NONE")

    # Check what bagel_with_modifiers parsing returns
    bagel_result = _parse_bagel_with_modifiers(user_input)
    print(f"\n2. _parse_bagel_with_modifiers result:")
    if bagel_result:
        print(f"   new_bagel: {bagel_result.new_bagel}")
        print(f"   new_bagel_proteins: {bagel_result.new_bagel_proteins}")
        print(f"   new_bagel_cheeses: {bagel_result.new_bagel_cheeses}")
        print(f"   new_bagel_toppings: {bagel_result.new_bagel_toppings}")
        print(f"   parsed_items: {len(bagel_result.parsed_items) if bagel_result.parsed_items else 0}")
        if bagel_result.parsed_items:
            item = bagel_result.parsed_items[0]
            print(f"   parsed_items[0]: proteins={item.proteins}, cheeses={item.cheeses}, toppings={item.toppings}")
    else:
        print("   RETURNED NONE")

    # Check the cleaned text that parse_open_input uses
    input_lower = user_input.lower()
    cleaned = input_lower
    for phrase in [
        "bacon egg and cheese", "ham egg and cheese", "sausage egg and cheese",
        "bacon and egg and cheese", "ham and egg and cheese",
        "bacon eggs and cheese", "ham eggs and cheese", "egg and cheese",
        "egg cheese and bacon", "egg, cheese and bacon",
        "ham and cheese", "ham and egg", "bacon and egg", "egg and bacon",
        "lox and cream cheese", "salt and pepper", "cream cheese and lox",
        "eggs and bacon", "black and white", "spinach and feta",
    ]:
        cleaned = cleaned.replace(phrase, "")

    print(f"\n3. Cleaned text for multi-item check:")
    print(f"   Original: {input_lower}")
    print(f"   Cleaned: {cleaned}")
    print(f"   Has ' and ': {' and ' in cleaned}")
    print(f"   Has ', ': {', ' in cleaned}")

    # If multi-item gets triggered, which parser is used?
    if " and " in cleaned or ", " in cleaned:
        print("\n   -> MULTI-ITEM PATH WILL BE TRIGGERED")
    else:
        print("\n   -> SINGLE-ITEM PATH WILL BE USED")


def test_compare_inputs():
    """Compare what parse_open_input returns for both inputs."""
    from sandwich_bot.tasks.parsers.constants import get_bagel_spreads
    spread_types = get_bagel_spreads()

    inputs = [
        "plain bagel with Egg Whites, Swiss, and Spinach",
        "everything bagel with bacon and egg",
    ]

    for user_input in inputs:
        print(f"\n{'='*60}")
        print(f"INPUT: {user_input}")
        print(f"{'='*60}")

        # Test multi-item path
        multi_result = _parse_multi_item_order(user_input)
        print(f"_parse_multi_item_order: {'MATCHED' if multi_result else 'None'}")
        if multi_result and multi_result.parsed_items:
            for i, item in enumerate(multi_result.parsed_items):
                if hasattr(item, 'proteins'):
                    print(f"  parsed_items[{i}].proteins: {item.proteins}")

        # Test bagel_with_modifiers path
        bagel_result = _parse_bagel_with_modifiers(user_input)
        print(f"_parse_bagel_with_modifiers: {'MATCHED' if bagel_result else 'None'}")
        if bagel_result and bagel_result.parsed_items:
            for i, item in enumerate(bagel_result.parsed_items):
                if hasattr(item, 'proteins'):
                    print(f"  parsed_items[{i}].proteins: {item.proteins}")

        # Test parse_open_input (the actual function used)
        result = parse_open_input(user_input, spread_types=spread_types)
        print(f"parse_open_input:")
        print(f"  new_bagel_proteins: {result.new_bagel_proteins}")
        if result.parsed_items:
            for i, item in enumerate(result.parsed_items):
                if hasattr(item, 'proteins'):
                    print(f"  parsed_items[{i}].proteins: {item.proteins}")
