"""
Extended Menu Item Test Script
Tests 30 additional menu items with varied ordering patterns.
"""
import requests
import json
import os
from datetime import datetime

BASE_URL = 'http://localhost:8000'
STORE_ID = 'zuckers_tribeca'
OUTPUT_DIR = 'test_results_extended'

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
        log(f'  [{i}] {name} - ${price:.2f} ({item_type})')

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


# 30 Extended Test Cases - Varied patterns to exercise the app
TEST_CASES = [
    # === SIGNATURE SANDWICHES ===
    {
        'name': 'The Reuben Sandwich',
        'filename': '21_reuben.txt',
        'messages': [
            'Can I get a Reuben',
            'thats all',
            'pickup',
            'John Smith',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Grilled Cheese on Rye',
        'filename': '22_grilled_cheese.txt',
        'messages': [
            'grilled cheese on rye bread please',
            'thats all',
            'pickup',
            'Sarah',
            'yes',
            'email'
        ]
    },
    {
        'name': 'BLT Sandwich',
        'filename': '23_blt.txt',
        'messages': [
            'I want a BLT',
            'thats all',
            'delivery',
            '123 Main Street, New York, NY 10001',
            'Mike',
            'yes',
            'text'
        ]
    },

    # === SMOKED FISH ===
    {
        'name': 'Gravlax on Bagel',
        'filename': '24_gravlax.txt',
        'messages': [
            'gravlax on a sesame bagel',
            'toasted',
            'thats all',
            'pickup',
            'Lisa',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Belly Lox Platter',
        'filename': '25_belly_lox.txt',
        'messages': [
            'belly lox please',
            'everything bagel',
            'not toasted',
            'thats all',
            'pickup',
            'David',
            'yes',
            'text'
        ]
    },

    # === EGG SANDWICHES ===
    {
        'name': 'The Delancey',
        'filename': '26_delancey.txt',
        'messages': [
            'The Delancey please',
            'toasted',
            'thats all',
            'pickup',
            'Rachel',
            'yes',
            'email'
        ]
    },
    {
        'name': 'The Mulberry',
        'filename': '27_mulberry.txt',
        'messages': [
            'can I get The Mulberry egg sandwich',
            'yes please toast it',
            'thats all',
            'pickup',
            'Tony',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Scrambled Eggs on Bagel',
        'filename': '28_scrambled_eggs.txt',
        'messages': [
            'scrambled eggs on an everything bagel',
            'toasted',
            'thats all',
            'pickup',
            'Amy',
            'yes',
            'in store'
        ]
    },

    # === OMELETTES (require side choice) ===
    {
        'name': 'Lox and Onion Omelette',
        'filename': '29_lox_omelette.txt',
        'messages': [
            'lox and onion omelette',
            'fruit salad',
            'thats all',
            'pickup',
            'Ben',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Salami Omelette with Bagel',
        'filename': '30_salami_omelette.txt',
        'messages': [
            'salami omelette please',
            'bagel',
            'sesame',
            'toasted',
            'thats all',
            'pickup',
            'Chris',
            'yes',
            'in store'
        ]
    },

    # === COFFEE DRINKS (size/style variations) ===
    {
        'name': 'Large Iced Latte with Oat Milk',
        'filename': '31_large_iced_latte.txt',
        'messages': [
            'large iced latte with oat milk',
            'thats all',
            'pickup',
            'Emma',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Small Hot Cappuccino',
        'filename': '32_small_cappuccino.txt',
        'messages': [
            'small hot cappuccino',
            'thats all',
            'pickup',
            'Frank',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Decaf Coffee',
        'filename': '33_decaf.txt',
        'messages': [
            'decaf coffee please',
            'medium',
            'thats all',
            'pickup',
            'Grace',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Double Espresso',
        'filename': '34_espresso.txt',
        'messages': [
            'double espresso',
            'thats all',
            'pickup',
            'Henry',
            'yes',
            'in store'
        ]
    },

    # === HOT DRINKS ===
    {
        'name': 'Hot Chocolate',
        'filename': '35_hot_chocolate.txt',
        'messages': [
            'hot chocolate please',
            'thats all',
            'pickup',
            'Ivy',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Chai Tea',
        'filename': '36_chai_tea.txt',
        'messages': [
            'chai tea',
            'thats all',
            'pickup',
            'Jack',
            'yes',
            'in store'
        ]
    },

    # === BAGELS WITH SPECIALTY SPREADS ===
    {
        'name': 'Poppy Bagel with Veggie CC',
        'filename': '37_poppy_veggie.txt',
        'messages': [
            'poppy bagel with vegetable cream cheese',
            'toasted',
            'thats all',
            'pickup',
            'Kate',
            'yes',
            'text'
        ]
    },
    {
        'name': 'Cinnamon Raisin with Strawberry CC',
        'filename': '38_cinnamon_strawberry.txt',
        'messages': [
            'cinnamon raisin bagel with strawberry cream cheese',
            'not toasted',
            'thats all',
            'pickup',
            'Leo',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Onion Bagel with Lox Spread',
        'filename': '39_onion_nova.txt',
        'messages': [
            'onion bagel with nova cream cheese',
            'toasted please',
            'thats all',
            'pickup',
            'Maria',
            'yes',
            'text'
        ]
    },

    # === DELI SALADS ON BAGELS ===
    {
        'name': 'Egg Salad Sandwich',
        'filename': '40_egg_salad.txt',
        'messages': [
            'egg salad sandwich',
            'plain bagel',
            'not toasted',
            'thats all',
            'pickup',
            'Nick',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Whitefish Salad on Everything',
        'filename': '41_whitefish.txt',
        'messages': [
            'whitefish salad on everything bagel',
            'not toasted',
            'thats all',
            'pickup',
            'Olivia',
            'yes',
            'text'
        ]
    },

    # === BREAKFAST ITEMS ===
    {
        'name': 'Oatmeal',
        'filename': '42_oatmeal.txt',
        'messages': [
            'oatmeal please',
            'thats all',
            'pickup',
            'Pete',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Yogurt Parfait',
        'filename': '43_yogurt_parfait.txt',
        'messages': [
            'yogurt granola parfait',
            'thats all',
            'pickup',
            'Quinn',
            'yes',
            'text'
        ]
    },

    # === SIDES ===
    {
        'name': 'Potato Latkes',
        'filename': '44_latkes.txt',
        'messages': [
            'potato latkes',
            'thats all',
            'pickup',
            'Rose',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Side of Sausage',
        'filename': '45_sausage.txt',
        'messages': [
            'side of sausage',
            'thats all',
            'pickup',
            'Sam',
            'yes',
            'text'
        ]
    },

    # === BEVERAGES ===
    {
        'name': 'Snapple Iced Tea',
        'filename': '46_snapple.txt',
        'messages': [
            'snapple iced tea',
            'thats all',
            'pickup',
            'Tina',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Dr Browns Cream Soda',
        'filename': '47_dr_browns.txt',
        'messages': [
            "Dr Brown's cream soda",
            'thats all',
            'pickup',
            'Uma',
            'yes',
            'text'
        ]
    },

    # === MULTI-ITEM ORDERS ===
    {
        'name': 'Bagel and Coffee Combo',
        'filename': '48_bagel_coffee_combo.txt',
        'messages': [
            'plain bagel with cream cheese and a medium coffee',
            'toasted',
            'thats all',
            'pickup',
            'Victor',
            'yes',
            'in store'
        ]
    },
    {
        'name': 'Breakfast Combo Order',
        'filename': '49_breakfast_combo.txt',
        'messages': [
            'classic BEC and a large iced latte',
            'toasted',
            'large',
            'iced',
            'thats all',
            'pickup',
            'Wendy',
            'yes',
            'text'
        ]
    },

    # === CASUAL/VAGUE ORDERS ===
    {
        'name': 'Just a Plain Bagel',
        'filename': '50_just_bagel.txt',
        'messages': [
            'just a plain bagel',
            'no spread',
            'not toasted',
            'thats all',
            'pickup',
            'Xavier',
            'yes',
            'in store'
        ]
    },
]


if __name__ == '__main__':
    print(f'Running {len(TEST_CASES)} extended menu item tests...')
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
        f.write('EXTENDED MENU ITEM TEST SUMMARY\n')
        f.write(f'Run at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write('=' * 70 + '\n\n')
        f.write(f'PASSED: {passed}/{len(results)}\n')
        f.write(f'FAILED: {failed}/{len(results)}\n\n')
        f.write('Results:\n')
        for r in results:
            status = 'PASS' if r['success'] else 'FAIL'
            f.write(f'  [{status}] {r["name"]} -> {r["filename"]}\n')

    print(f'\nSummary saved to: {summary_path}')
