"""
Extended Menu Item Test Script - Round 2
Tests 30 additional menu items with varied ordering patterns.
Focus: Speed menu items, quantities, custom builds, modifications, and edge cases.

VALIDATION: Tests now validate that the CORRECT items are ordered, not just ANY items.
"""
import requests
import json
import os
from datetime import datetime

BASE_URL = 'http://localhost:8000'
STORE_ID = 'zuckers_tribeca'
OUTPUT_DIR = 'test_results_round2'

os.makedirs(OUTPUT_DIR, exist_ok=True)


def validate_items(actual_items: list, expected_items: list) -> tuple[bool, list[str]]:
    """
    Validate that actual items match expected items.

    Args:
        actual_items: List of items from order state
        expected_items: List of expected item specs, each with:
            - name: substring to match in menu_item_name or display_name (required)
            - type: expected item_type or menu_item_type (optional)
            - quantity: expected quantity (optional, defaults to 1)
            - min_count: minimum number of matching items (optional)

    Returns:
        Tuple of (passed, list of failure reasons)
    """
    failures = []

    if not expected_items:
        # No expected items specified - just check that something was ordered
        if not actual_items:
            failures.append("No items in cart")
        return len(failures) == 0, failures

    # Track which expected items have been matched
    matched_expected = [False] * len(expected_items)

    for exp_idx, expected in enumerate(expected_items):
        exp_name = expected.get('name', '').lower()
        exp_type = expected.get('type')
        exp_quantity = expected.get('quantity', 1)
        exp_min_count = expected.get('min_count', 1)

        # Find matching actual items
        match_count = 0
        for actual in actual_items:
            actual_name = (actual.get('menu_item_name') or actual.get('display_name') or '').lower()
            actual_type = actual.get('menu_item_type') or actual.get('item_type')
            actual_qty = actual.get('quantity', 1)

            # Check name match (substring)
            if exp_name not in actual_name:
                continue

            # Check type match if specified
            if exp_type and actual_type != exp_type:
                continue

            # Check quantity if specified (for individual item)
            if exp_quantity > 1 and actual_qty != exp_quantity:
                continue

            match_count += 1

        if match_count >= exp_min_count:
            matched_expected[exp_idx] = True
        else:
            type_str = f" (type={exp_type})" if exp_type else ""
            if exp_min_count > 1:
                failures.append(f"Expected at least {exp_min_count} items matching '{expected.get('name')}'{type_str}, found {match_count}")
            else:
                failures.append(f"Missing expected item: '{expected.get('name')}'{type_str}")

    return len(failures) == 0, failures


def test_item(item_name, messages, filename, expected_items=None):
    """Test ordering a specific item and save results to file."""
    output_lines = []

    def log(line=''):
        output_lines.append(line)
        print(line)

    log('=' * 70)
    log(f'TEST: {item_name}')
    log(f'TIME: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    log('=' * 70)

    r = requests.post(f'{BASE_URL}/chat/start', params={'store_id': STORE_ID})
    data = r.json()
    session_id = data['session_id']

    log()
    log('CONVERSATION:')
    log('-' * 70)
    log(f'BOT:    {data["message"]}')
    log()

    final_order_state = {}

    for msg in messages:
        log(f'TESTER: {msg}')
        r = requests.post(f'{BASE_URL}/chat/message', json={
            'session_id': session_id,
            'message': msg
        })
        resp = r.json()
        log(f'BOT:    {resp["reply"]}')
        log()
        final_order_state = resp.get('order_state', {})

    log('-' * 70)

    log()
    log('ORDER DETAILS:')
    log('-' * 70)
    log(f'Status:     {final_order_state.get("status", "unknown")}')
    log(f'Order Type: {final_order_state.get("order_type", "not set")}')

    items = final_order_state.get('items', [])
    log(f'Items:      {len(items)}')
    for i, item in enumerate(items, 1):
        name = item.get('display_name') or item.get('menu_item_name', 'Unknown')
        price = item.get('line_total') or item.get('unit_price', 0)
        item_type = item.get('menu_item_type') or item.get('item_type', 'unknown')
        qty = item.get('quantity', 1)
        log(f'  [{i}] {name} x{qty} - ${price:.2f} ({item_type})')

        details = []
        if item.get('toasted'):
            details.append('toasted')
        if item.get('spread'):
            details.append(f'spread: {item.get("spread")}')
        if item.get('bagel_choice'):
            details.append(f'bagel: {item.get("bagel_choice")}')
        if item.get('side_choice'):
            details.append(f'side: {item.get("side_choice")}')
        if item.get('item_config'):
            cfg = item['item_config']
            if cfg.get('size'):
                details.append(f'size: {cfg["size"]}')
            if cfg.get('style'):
                details.append(cfg['style'])
            if cfg.get('milk'):
                details.append(f'milk: {cfg["milk"]}')
            if cfg.get('sweetener'):
                details.append(f'sweetener: {cfg["sweetener"]}')
        if details:
            log(f'      > {", ".join(details)}')

    customer = final_order_state.get('customer', {})
    if customer.get('name'):
        log(f'Customer:   {customer.get("name")}')

    log(f'Total:      ${final_order_state.get("total_price", 0):.2f}')
    log('-' * 70)

    # Validate expected items
    passed, failures = validate_items(items, expected_items)

    log()
    log('EXPECTED ITEMS:')
    if expected_items:
        for exp in expected_items:
            type_str = f" ({exp.get('type')})" if exp.get('type') else ""
            qty_str = f" x{exp.get('min_count', 1)}" if exp.get('min_count', 1) > 1 else ""
            log(f'  - {exp.get("name")}{type_str}{qty_str}')
    else:
        log('  (any items)')

    log()
    result = 'PASS' if passed else 'FAIL'
    log(f'RESULT: {result}')

    if failures:
        log('FAILURES:')
        for f in failures:
            log(f'  - {f}')

    # Save to file
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))

    print(f'\n>>> Saved to {filepath}\n')

    return passed, final_order_state, failures


# 30 New Test Cases - Round 2
# Each test case now includes 'expected_items' for validation
TEST_CASES = [
    # === SPEED MENU ITEMS (not tested in round 1) ===
    {
        'name': 'The Classic Speed Menu',
        'filename': '51_the_classic.txt',
        'messages': [
            'The Classic please',
            'everything bagel',
            'toasted',
            'thats all',
            'pickup',
            'Alex',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'The Classic', 'type': 'speed_menu_bagel'}
        ]
    },
    {
        'name': 'The Traditional',
        'filename': '52_the_traditional.txt',
        'messages': [
            'I want the traditional',
            'sesame',
            'not toasted',
            'thats all',
            'pickup',
            'Beth',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'The Traditional', 'type': 'speed_menu_bagel'}
        ]
    },
    {
        'name': 'The Max Zucker',
        'filename': '53_max_zucker.txt',
        'messages': [
            'max zucker sandwich',
            'toasted please',
            'thats all',
            'pickup',
            'Carl',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'Max Zucker', 'type': 'speed_menu_bagel'}
        ]
    },
    {
        'name': 'The Chelsea Club',
        'filename': '54_chelsea_club.txt',
        'messages': [
            'chelsea club',
            'toasted',  # Answer the toasted question properly
            'thats all',
            'pickup',
            'Diana',
            'yes',
            'email'
        ],
        'expected_items': [
            {'name': 'Chelsea Club', 'type': 'speed_menu_bagel'}
        ]
    },
    {
        'name': 'The Flatiron Traditional',
        'filename': '55_flatiron.txt',
        'messages': [
            'flatiron traditional please',
            'toasted',  # Answer the toasted question properly
            'thats all',
            'pickup',
            'Edward',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'Flatiron Traditional', 'type': 'speed_menu_bagel'}
        ]
    },

    # === QUANTITY ORDERS ===
    {
        'name': 'Two Plain Bagels',
        'filename': '56_two_bagels.txt',
        'messages': [
            'two plain bagels with cream cheese',
            'both toasted',
            'thats all',
            'pickup',
            'Fiona',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'plain bagel', 'type': 'bagel', 'min_count': 2}
        ]
    },
    {
        'name': 'Three Coffees',
        'filename': '57_three_coffees.txt',
        'messages': [
            'three medium coffees',
            'hot',  # Answer the hot/iced question
            'thats all',
            'pickup',
            'George',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'coffee', 'type': 'drink', 'min_count': 3}
        ]
    },
    {
        'name': 'Dozen Bagels',
        'filename': '58_dozen_bagels.txt',
        'messages': [
            'a dozen everything bagels',
            'not toasted',  # Answer the toasted question
            'nothing',  # Answer the spread question
            'thats all',
            'pickup',
            'Hannah',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'everything bagel', 'type': 'bagel', 'min_count': 12}
        ]
    },

    # === CUSTOM BUILD-YOUR-OWN BAGELS ===
    {
        'name': 'Bagel with Bacon Egg Cheese',
        'filename': '59_custom_bec.txt',
        'messages': [
            'everything bagel with bacon egg and cheese',
            'toasted',
            'american',  # Answer the cheese question
            'thats all',
            'pickup',
            'Ivan',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'everything bagel', 'type': 'bagel'}
        ]
    },
    {
        'name': 'Bagel with Nova and Capers',
        'filename': '60_nova_capers.txt',
        'messages': [
            'sesame bagel with nova, cream cheese, and capers',
            'not toasted',
            'thats all',
            'pickup',
            'Julia',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'sesame bagel', 'type': 'bagel'}
        ]
    },
    {
        'name': 'Bagel with Turkey and Swiss',
        'filename': '61_turkey_swiss.txt',
        'messages': [
            'onion bagel with turkey and swiss cheese',
            'toasted',
            'thats all',
            'pickup',
            'Kevin',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'onion bagel', 'type': 'bagel'}
        ]
    },

    # === MORE OMELETTES ===
    {
        'name': 'Western Omelette',
        'filename': '62_western_omelette.txt',
        'messages': [
            'western omelette',
            'toast',
            'thats all',
            'pickup',
            'Linda',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'Western Omelette', 'type': 'omelette'}
        ]
    },
    {
        'name': 'Veggie Omelette',
        'filename': '63_veggie_omelette.txt',
        'messages': [
            'veggie omelette please',
            'bagel',
            'plain',
            'toasted',
            'butter',  # Answer spread question for side bagel
            'thats all',
            'pickup',
            'Mark',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'Veggie Omelette', 'type': 'omelette'}
        ]
    },
    {
        'name': 'Spinach Feta Omelette',
        'filename': '64_spinach_feta.txt',
        'messages': [
            'spinach and feta omelette',
            'home fries',
            'thats all',
            'pickup',
            'Nancy',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'Spinach', 'type': 'omelette'}  # Match "Spinach" in item name
        ]
    },

    # === SANDWICHES ===
    {
        'name': 'Turkey Club Sandwich',
        'filename': '65_turkey_club.txt',
        'messages': [
            'turkey club',
            'thats all',
            'pickup',
            'Oscar',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'Turkey Club'}
        ]
    },
    {
        'name': 'Hot Pastrami Sandwich',
        'filename': '66_hot_pastrami.txt',
        'messages': [
            'hot pastrami sandwich',
            'thats all',
            'pickup',
            'Paula',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'Pastrami'}
        ]
    },

    # === COFFEE WITH MODIFIERS ===
    {
        'name': 'Latte with Vanilla Syrup',
        'filename': '67_vanilla_latte.txt',
        'messages': [
            'large iced latte with vanilla syrup',
            'thats all',
            'pickup',
            'Quinn',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'latte', 'type': 'drink'}
        ]
    },
    {
        'name': 'Coffee with Sugar',
        'filename': '68_coffee_sugar.txt',
        'messages': [
            'medium hot coffee with two sugars',
            'thats all',
            'pickup',
            'Rita',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'coffee', 'type': 'drink'}
        ]
    },
    {
        'name': 'Cappuccino with Almond Milk',
        'filename': '69_almond_cappuccino.txt',
        'messages': [
            'small cappuccino with almond milk',
            'hot',  # Answer hot/iced if asked
            'thats all',
            'pickup',
            'Steve',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'cappuccino', 'type': 'drink'}
        ]
    },

    # === CASUAL/CONVERSATIONAL ORDERS ===
    {
        'name': 'Casual Bagel Order',
        'filename': '70_casual_bagel.txt',
        'messages': [
            'hey can I get an everything bagel',
            'yeah with scallion cream cheese',
            'toasted please',
            'thats it',
            'pickup',
            'Tom',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'everything bagel', 'type': 'bagel'}
        ]
    },
    {
        'name': 'Casual Coffee Order',
        'filename': '71_casual_coffee.txt',
        'messages': [
            'yeah just a coffee',
            'medium',
            'hot',
            'thats all',
            'pickup',
            'Uma',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'coffee', 'type': 'drink'}
        ]
    },

    # === DELIVERY ORDERS ===
    {
        'name': 'Delivery to Tribeca',
        'filename': '72_delivery_tribeca.txt',
        'messages': [
            'The Leo please',
            'toasted',
            'thats all',
            'delivery',
            '100 Hudson Street, New York, NY 10013',
            'Victor',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'The Leo', 'type': 'speed_menu_bagel'}
        ]
    },
    {
        'name': 'Delivery with Apartment',
        'filename': '73_delivery_apt.txt',
        'messages': [
            'classic BEC',
            'toasted',
            'thats all',
            'delivery',
            '75 Greenwich Street Apt 4B, New York, NY 10006',
            'Wendy',
            'yes',
            'email'
        ],
        'expected_items': [
            {'name': 'BEC'}  # Should match "The Classic BEC" or similar
        ]
    },

    # === TOFU/SPECIALTY SPREADS ===
    {
        'name': 'Tofu Veggie Spread',
        'filename': '74_tofu_veggie.txt',
        'messages': [
            'plain bagel with tofu vegetable cream cheese',
            'not toasted',
            'thats all',
            'pickup',
            'Xavier',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'plain bagel', 'type': 'bagel'}
        ]
    },
    {
        'name': 'Honey Walnut Cream Cheese',
        'filename': '75_honey_walnut.txt',
        'messages': [
            'cinnamon raisin bagel with honey walnut cream cheese',
            'toasted',
            'thats all',
            'pickup',
            'Yolanda',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'cinnamon raisin bagel', 'type': 'bagel'}
        ]
    },

    # === SALAD SANDWICHES ===
    {
        'name': 'Tuna Salad Sandwich',
        'filename': '76_tuna_salad.txt',
        'messages': [
            'tuna salad on a sesame bagel',
            'not toasted',
            'thats all',
            'pickup',
            'Zach',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'Tuna Salad', 'type': 'salad_sandwich'}
        ]
    },
    {
        'name': 'Chicken Salad Sandwich',
        'filename': '77_chicken_salad.txt',
        'messages': [
            'chicken salad sandwich please',
            'everything bagel',
            'toasted',  # Answer the toasted question
            'thats all',
            'pickup',
            'Alice',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'Chicken Salad', 'type': 'salad_sandwich'}
        ]
    },

    # === MULTI-ITEM COMPLEX ORDERS ===
    {
        'name': 'Bagel Coffee and Side',
        'filename': '78_combo_with_side.txt',
        'messages': [
            'everything bagel with cream cheese, a medium coffee, and home fries',
            'toasted',
            'hot',  # Answer coffee hot/iced
            'thats all',
            'pickup',
            'Bob',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'everything bagel', 'type': 'bagel'},
            {'name': 'coffee', 'type': 'drink'},
            {'name': 'home fries'}
        ]
    },
    {
        'name': 'Two Different Items',
        'filename': '79_two_different.txt',
        'messages': [
            'The Leo and a large iced latte',
            'toasted',
            'thats all',
            'pickup',
            'Carol',
            'yes',
            'in store'
        ],
        'expected_items': [
            {'name': 'The Leo', 'type': 'speed_menu_bagel'},
            {'name': 'latte', 'type': 'drink'}
        ]
    },
    {
        'name': 'Family Order',
        'filename': '80_family_order.txt',
        'messages': [
            'two plain bagels with butter and two chocolate milks',
            'not toasted',
            'thats all',
            'pickup',
            'Dan',
            'yes',
            'text'
        ],
        'expected_items': [
            {'name': 'plain bagel', 'type': 'bagel', 'min_count': 2},
            {'name': 'chocolate milk', 'min_count': 2}
        ]
    },
]


if __name__ == '__main__':
    print(f'Running {len(TEST_CASES)} extended menu item tests (Round 2)...')
    print(f'Results will be saved to: {OUTPUT_DIR}/')
    print()

    results = []

    for i, test in enumerate(TEST_CASES, 1):
        print(f'\n{"#" * 70}')
        print(f'# TEST {i}/{len(TEST_CASES)}: {test["name"]}')
        print(f'{"#" * 70}')

        success, order_state, failures = test_item(
            test['name'],
            test['messages'],
            test['filename'],
            test.get('expected_items')
        )
        results.append({
            'name': test['name'],
            'filename': test['filename'],
            'success': success,
            'failures': failures
        })

    # Print summary
    print('\n' + '=' * 70)
    print('SUMMARY')
    print('=' * 70)
    passed = sum(1 for r in results if r['success'])
    failed = len(results) - passed
    print(f'PASSED: {passed}/{len(results)}')
    print(f'FAILED: {failed}/{len(results)}')
    print()

    if failed > 0:
        print('Failed tests:')
        for r in results:
            if not r['success']:
                print(f'  - {r["name"]} ({r["filename"]})')
                for f in r.get('failures', []):
                    print(f'      {f}')

    # Save summary
    summary_path = os.path.join(OUTPUT_DIR, '00_summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write('EXTENDED MENU ITEM TEST SUMMARY - ROUND 2\n')
        f.write(f'Run at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write('=' * 70 + '\n\n')
        f.write(f'PASSED: {passed}/{len(results)}\n')
        f.write(f'FAILED: {failed}/{len(results)}\n\n')
        f.write('Results:\n')
        for r in results:
            status = 'PASS' if r['success'] else 'FAIL'
            f.write(f'  [{status}] {r["name"]} -> {r["filename"]}\n')
            if not r['success'] and r.get('failures'):
                for failure in r['failures']:
                    f.write(f'         REASON: {failure}\n')
        f.write('\n')

    print(f'\nSummary saved to: {summary_path}')
