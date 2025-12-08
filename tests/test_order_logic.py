from sandwich_bot.order_logic import apply_intent_to_order_state

def test_add_drink():
    state = {"status":"draft","items":[],"customer":{}}
    slots = {"menu_item_name":"soda","quantity":1}
    menu = {"soda":{"base_price":2.5}}
    new = apply_intent_to_order_state(state,"add_drink",slots,menu)
    assert new["items"][0]["line_total"] == 2.5
