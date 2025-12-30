"""
Extended Menu Item Test Script - Round 2
Tests 30 additional menu items with varied ordering patterns.
Focus: Speed menu items, quantities, custom builds, modifications, and edge cases.
"""
import requests
import json
import os
from datetime import datetime

BASE_URL = 'http://localhost:8000'
STORE_ID = 'zuckers_tribeca'
OUTPUT_DIR = 'test_results_round2'

os.makedirs(OUTPUT_DIR, exist_ok=True)

def test_item(item_name, messages, filename):
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
        item_type = item.get('item_type', 'unknown')
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

    # Determine pass/fail
    has_items = len(items) > 0
    result = 'PASS' if has_items else 'FAIL'
    log()
    log(f'RESULT: {result}')
    if not has_items:
        log('REASON: No items in cart')

    # Save to file
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))

    print(f'\n>>> Saved to {filepath}\n')

    return has_items, final_order_state


# 30 New Test Cases - Round 2
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
        ]
    },
    {
        'name': 'The Chelsea Club',
        'filename': '54_chelsea_club.txt',
        'messages': [
            'chelsea club',
            'thats all',
            'pickup',
            'Diana',
            'yes',
            'email'
        ]
    },
    {
        'name': 'The Flatiron Traditional',
        'filename': '55_flatiron.txt',
        'messages': [
            'flatiron traditional please',
            'thats all',
            'pickup',
            'Edward',
            'yes',
            'text'
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
        ]
    },
    {
        'name': 'Three Coffees',
        'filename': '57_three_coffees.txt',
        'messages': [
            'three medium coffees',
            'thats all',
            'pickup',
            'George',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Dozen Bagels',
        'filename': '58_dozen_bagels.txt',
        'messages': [
            'a dozen everything bagels',
            'thats all',
            'pickup',
            'Hannah',
            'yes',
            'in store'
        ]
    },

    # === CUSTOM BUILD-YOUR-OWN BAGELS ===
    {
        'name': 'Bagel with Bacon Egg Cheese',
        'filename': '59_custom_bec.txt',
        'messages': [
            'everything bagel with bacon egg and cheese',
            'toasted',
            'thats all',
            'pickup',
            'Ivan',
            'yes',
            'text'
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
            'thats all',
            'pickup',
            'Mark',
            'yes',
            'text'
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
        ]
    },
    {
        'name': 'Cappuccino with Almond Milk',
        'filename': '69_almond_cappuccino.txt',
        'messages': [
            'small cappuccino with almond milk',
            'thats all',
            'pickup',
            'Steve',
            'yes',
            'text'
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
        ]
    },
    {
        'name': 'Chicken Salad Sandwich',
        'filename': '77_chicken_salad.txt',
        'messages': [
            'chicken salad sandwich please',
            'everything bagel',
            'thats all',
            'pickup',
            'Alice',
            'yes',
            'in store'
        ]
    },

    # === MULTI-ITEM COMPLEX ORDERS ===
    {
        'name': 'Bagel Coffee and Side',
        'filename': '78_combo_with_side.txt',
        'messages': [
            'everything bagel with cream cheese, a medium coffee, and home fries',
            'toasted',
            'thats all',
            'pickup',
            'Bob',
            'yes',
            'text'
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

        success, order_state = test_item(
            test['name'],
            test['messages'],
            test['filename']
        )
        results.append({
            'name': test['name'],
            'filename': test['filename'],
            'success': success
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

    print(f'\nSummary saved to: {summary_path}')
