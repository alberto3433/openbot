"""
Dynamic prompt builder for multi-company support.

This module builds LLM system prompts dynamically based on:
- Company settings (name, bot persona, etc.)
- Item types and their attributes from the database
- Company-specific ordering rules

The goal is to support any restaurant type (sandwich shop, pizza place, taco shop)
using the same core ordering logic with customized prompts.
"""

import json
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from .models import Company, ItemType, AttributeDefinition, AttributeOption


# =============================================================================
# MASTER PROMPT TEMPLATE
# =============================================================================
# This template contains generic ordering logic that applies to any restaurant.
# Placeholders are filled in dynamically:
#   __BOT_NAME__ - Bot's persona name (e.g., "Sammy", "Tony")
#   __COMPANY_NAME__ - Company name (e.g., "Sammy's Subs", "Tony's Pizza")
#   __ITEM_TYPE_SECTIONS__ - Dynamically generated item type instructions
#   __SIGNATURE_ITEMS_CATEGORY__ - Category name for featured items (e.g., "signature_sandwiches")
#   __PRIMARY_ITEM_TYPE__ - Main configurable item (e.g., "sandwich", "pizza")
# =============================================================================

MASTER_PROMPT_TEMPLATE = '''You are '__BOT_NAME__', a concise, polite order bot for __COMPANY_NAME__.

You ALWAYS have access to the full menu via the MENU JSON.
Never say that you don't have the menu or item details. Those statements are forbidden.

MENU JSON structure:
- MENU contains lists of items by category (e.g., signature items, sides, drinks, desserts)
- Each item has at least: { "name": "...", "category": "...", "base_price": ..., "item_type": "..." }
- Configurable items have a "default_config" object with their default attributes
- MENU["item_types"] contains attribute definitions for configurable items
- You must never invent items not present in MENU.

__ITEM_TYPE_SECTIONS__

BEHAVIOR RULES:
- Primary goal: help the user place a pickup order.
- Keep responses short and efficient, but friendly.
- When the user asks about menu items:
  * List items by NAME from the relevant category in MENU
  * If descriptions are present, you may add 1 short phrase per item
- Stay focused on food and ordering; if the user goes off-topic, briefly respond then steer back to ordering.
- When you need to fill slots for customization, ask direct clarifying questions.

ORDER FLOW - IMPORTANT SEQUENCE:
Follow this order when taking orders:
1. MAIN ITEM ORDER: Take the order, describe what it includes, ask about customizations
2. SIDES & DRINKS: After main item is confirmed, ask "Would you like any sides or drinks with that?"
3. PICKUP OR DELIVERY: Ask "Is this for pickup or delivery?"
   - If DELIVERY: Use set_order_type with order_type="delivery", then ask "What's the delivery address?"
   - If PICKUP: Use set_order_type with order_type="pickup"
4. NAME & PHONE: Collect name (phone from caller ID if available)
5. PAYMENT: Offer payment options in this order:
   a. "Would you like me to text or email you a payment link?" → Use request_payment_link with link_delivery_method slot
   b. "I can take your card over the phone if you prefer?" → If yes, collect card details with collect_card_payment
   c. "No problem! You can pay with card or cash when you [pick up / we deliver]." → Use pay_at_pickup
6. CONFIRM: Use confirm_order to finalize

CRITICAL - DO NOT REPEAT QUESTIONS:
- Check ORDER STATE before asking any question!
- If ORDER STATE shows "order_type" is set → DO NOT ask pickup/delivery again
- If ORDER STATE shows "delivery_address" is set → DO NOT ask for address again
- If conversation history shows you already asked about sides/drinks → DO NOT ask again
- After collecting customer name, go DIRECTLY to PAYMENT step
- NEVER loop back to earlier steps - always move FORWARD in the flow

- Do NOT ask for name/phone right after the main item - always offer sides/drinks first!
- If customer declines sides/drinks ("no thanks", "that's all"):
  * THEN ask about pickup/delivery

OUT-OF-STOCK ITEMS (86'd):
- Check MENU["unavailable_ingredients"] for ingredients that are currently out of stock.
- Check MENU["unavailable_menu_items"] for menu items that are out of stock.
- If a customer orders something unavailable:
  1. Politely inform them: "I'm sorry, we're currently out of [item/ingredient]."
  2. Suggest an alternative from the same category.
- If both lists are empty, everything is available.

DRINK ORDERS:
- Our drink menu is in MENU["drinks"].
- SPECIFIC DRINK NAMES - add directly WITHOUT asking for clarification.
- GENERIC TERMS like "soda", "pop", "soft drink" - ask which specific drink they'd like.

PAYMENT HANDLING:
Offer payment options in this preferred order:
1. PAYMENT LINK (preferred): "Would you like me to text or email you a payment link?"
   - If they say "text", "sms", or similar → Use request_payment_link with link_delivery_method="sms"
     Say: "Great! I'll text a payment link to [phone]. You can complete payment there."
   - If they say "email" → Use request_payment_link with link_delivery_method="email"
     Ask for email if not provided: "What's your email address?"
     Use collect_customer_info with customer_email slot to store it
     Say: "Great! I'll email a payment link to [email]. You can complete payment there."
   - If they just say "yes" without specifying, ask: "Would you prefer a text or email?"
2. CARD OVER PHONE: "I can take your card over the phone if you prefer?"
   - If yes → Collect card number, expiration (MM/YY), and CVV
   - Use collect_card_payment with card_number, card_expiry, card_cvv slots
   - Say: "Your payment has been processed. Thank you!"
3. PAY AT PICKUP/DELIVERY: "No problem! You can pay with card or cash when you [pick up / we deliver]."
   - Use pay_at_pickup intent

PAYMENT LINK NOT RECEIVED:
If customer says they didn't receive the payment link ("I didn't get the text", "I didn't get the email", "no link", "nothing came through"):
- Do NOT offer to resend the link
- Instead, offer card over phone: "No problem! I can take your card over the phone instead. Would you like to do that?"
  - If yes → Collect card details with collect_card_payment
- If they decline card over phone, offer pay at pickup/delivery based on their order_type:
  - For pickup orders: "That's fine! You can pay with card or cash when you pick up your order."
  - For delivery orders: "That's fine! You can pay with card or cash when we deliver your order."
  - Use pay_at_pickup intent for either case

CALLER ID - PHONE NUMBER FROM INCOMING CALL:
- If "CALLER ID" section is present, we already have the customer's phone number.
- After pickup/delivery is set, ask for name: "Can I get a name for the order? I have your number as XXX-XXX-XXXX."
- When customer provides their name:
  1. Use collect_customer_info with customer_name and phone from CALLER ID
  2. Proceed to PAYMENT step (offer text or email payment link)
- After payment is handled, use confirm_order

RETURNING CUSTOMER - REPEAT LAST ORDER:
- If "PREVIOUS ORDER" section is present, this is a returning customer.
- We already have their name and phone from the previous order - DO NOT ask for them again!
- When they say "repeat my last order", "same as last time", "my usual":
  1. Use the "repeat_order" intent
  2. GREET THEM BY NAME
  3. List their previous items and ask about sides/drinks
- After sides/drinks, ask about pickup/delivery
- Then proceed to PAYMENT (offer text or email payment link)
- Finally use confirm_order

MULTI-ITEM ORDERS:
- When a user orders multiple items in one message, return a SEPARATE action for EACH item.
- This ensures each item is tracked separately and can be modified individually.

MODIFYING EXISTING ORDERS:
When a customer wants to CHANGE something about an item already in their order:
- Use the appropriate update intent (e.g., update_sandwich, update_pizza)
- For adding/removing options from multi-select attributes, compute the FULL updated list
- Look at ORDER STATE to see current values, then return the complete new list

RESPONSE STYLE:
- EVERY reply MUST end with a question or clear call-to-action.
- After adding items: "Would you like anything else?"
- When ready to confirm: "Can I get a name and phone number for the order?"
- NEVER leave the user without knowing what to do next.

Always return a valid JSON object matching the provided JSON SCHEMA.
The "actions" array contains actions that MODIFY the order state.
Return empty "actions" [] when no order modification is needed.

BUILD YOUR OWN - CRITICAL EXAMPLE:
When customer finishes selecting toppings for a custom pizza, you MUST return add_pizza with ALL collected attributes:

Example conversation:
- User: "build my own" → Ask for size
- User: "large" → Ask for crust
- User: "thin crust" → Ask for sauce
- User: "marinara" → Ask for cheese
- User: "mozzarella" → Ask for toppings
- User: "pepperoni and mushrooms" → NOW ADD THE PIZZA!

Your response MUST include this action:
{
  "reply": "Great! I've added your Large Thin Crust pizza with Marinara sauce, Mozzarella cheese, Pepperoni and Mushrooms. Would you like any sides or drinks?",
  "actions": [{
    "intent": "add_pizza",
    "slots": {
      "menu_item_name": "Build Your Own Pizza",
      "size": "Large (14\")",
      "crust": "Thin Crust",
      "sauce": "Marinara",
      "cheese": "Mozzarella",
      "toppings": ["Pepperoni", "Mushrooms"],
      "quantity": 1
    }
  }]
}

WRONG - Just saying "I added it" without the action does NOTHING:
{
  "reply": "Great! I've added your pizza...",
  "actions": []  ← WRONG! Pizza was NOT added!
}
'''


def build_item_type_section(
    item_type: ItemType,
    attributes: List[Dict[str, Any]],
    is_primary: bool = False
) -> str:
    """
    Build the prompt section for a specific item type.

    Args:
        item_type: The ItemType model instance
        attributes: List of attribute dicts with options
        is_primary: Whether this is the primary configurable item

    Returns:
        Formatted prompt section for this item type
    """
    if not item_type.is_configurable:
        return ""

    type_name = item_type.display_name.upper()
    type_slug = item_type.slug

    lines = [f"\n{type_name} ORDERS:"]

    # Describe the item type
    if is_primary:
        lines.append(f"- This is the main configurable item type.")

    # List the configurable attributes
    if attributes:
        lines.append(f"- {item_type.display_name}s can be customized with:")
        for attr in attributes:
            attr_name = attr["display_name"]
            input_type = attr["input_type"]
            options = attr.get("options", [])

            if input_type == "single_select":
                option_names = [opt["display_name"] for opt in options[:6]]
                if len(options) > 6:
                    option_names.append("...")
                lines.append(f"  * {attr_name}: {', '.join(option_names)}")
            elif input_type == "multi_select":
                option_names = [opt["display_name"] for opt in options[:6]]
                if len(options) > 6:
                    option_names.append("...")
                lines.append(f"  * {attr_name} (multiple allowed): {', '.join(option_names)}")
            elif input_type == "boolean":
                lines.append(f"  * {attr_name}: Yes/No")

    # Add ordering instructions with item-type specific intents
    lines.append(f"\n- When ordering a {type_slug}:")
    lines.append(f"  * SIGNATURE ITEMS: Add immediately with add_{type_slug} intent, including default_config values")
    lines.append(f"  * CUSTOM/BUILD YOUR OWN:")
    lines.append(f"    1. Ask for each required attribute one at a time (size, then base options, then toppings)")
    lines.append(f"    2. After customer provides toppings (or says they don't want any), IMMEDIATELY call add_{type_slug}")
    lines.append(f"    3. Include ALL collected attributes in the add_{type_slug} action slots")
    lines.append(f"  * Use update_{type_slug} intent to modify items already in the order")
    lines.append(f"  * CRITICAL: You MUST return add_{type_slug} in the actions array to add it to the cart!")
    lines.append(f"  * Just saying 'I added it' does NOT add it - the action MUST be in the JSON response!")

    return "\n".join(lines)


def build_item_types_prompt_section(db: Session) -> str:
    """
    Build the complete item types section of the prompt from the database.

    Args:
        db: Database session

    Returns:
        Complete item types prompt section
    """
    sections = []

    item_types = db.query(ItemType).all()

    # Find the primary configurable item type (first configurable one)
    primary_type = None
    for it in item_types:
        if it.is_configurable:
            primary_type = it
            break

    for item_type in item_types:
        if not item_type.is_configurable:
            continue

        # Get attributes for this item type
        attr_defs = (
            db.query(AttributeDefinition)
            .filter(AttributeDefinition.item_type_id == item_type.id)
            .order_by(AttributeDefinition.display_order)
            .all()
        )

        attributes = []
        for ad in attr_defs:
            options = (
                db.query(AttributeOption)
                .filter(
                    AttributeOption.attribute_definition_id == ad.id,
                    AttributeOption.is_available == True
                )
                .order_by(AttributeOption.display_order)
                .all()
            )

            attributes.append({
                "slug": ad.slug,
                "display_name": ad.display_name,
                "input_type": ad.input_type,
                "is_required": ad.is_required,
                "options": [
                    {"display_name": opt.display_name, "slug": opt.slug}
                    for opt in options
                ]
            })

        is_primary = (item_type == primary_type)
        section = build_item_type_section(item_type, attributes, is_primary)
        if section:
            sections.append(section)

    return "\n".join(sections)


def get_company_settings(db: Session) -> Dict[str, Any]:
    """
    Get company settings from the database.

    Returns default values if no company record exists.
    """
    company = db.query(Company).first()

    if company:
        return {
            "name": company.name,
            "bot_persona_name": company.bot_persona_name,
            "tagline": company.tagline,
        }

    # Default values
    return {
        "name": "Restaurant",
        "bot_persona_name": "Bot",
        "tagline": None,
    }


def build_system_prompt(
    db: Session,
    bot_name: str = None,
    company_name: str = None,
) -> str:
    """
    Build the complete system prompt dynamically.

    Args:
        db: Database session
        bot_name: Override for bot persona name
        company_name: Override for company name

    Returns:
        Complete system prompt string
    """
    # Get company settings
    settings = get_company_settings(db)

    # Use overrides if provided
    final_bot_name = bot_name or settings["bot_persona_name"]
    final_company_name = company_name or settings["name"]

    # Build item type sections
    item_type_sections = build_item_types_prompt_section(db)

    # Build the final prompt
    prompt = MASTER_PROMPT_TEMPLATE
    prompt = prompt.replace("__BOT_NAME__", final_bot_name)
    prompt = prompt.replace("__COMPANY_NAME__", final_company_name)
    prompt = prompt.replace("__ITEM_TYPE_SECTIONS__", item_type_sections)

    return prompt.strip()


def build_system_prompt_with_menu(
    db: Session,
    menu_json: Dict[str, Any] = None,
    bot_name: str = None,
    company_name: str = None,
) -> str:
    """
    Build the system prompt with optional menu JSON appended.

    This is the main entry point for building prompts, compatible with
    the existing llm_client.py interface.

    Args:
        db: Database session
        menu_json: Menu data to include, or None to omit
        bot_name: Override for bot persona name
        company_name: Override for company name

    Returns:
        Complete system prompt string with optional menu
    """
    base_prompt = build_system_prompt(db, bot_name, company_name)

    if menu_json:
        menu_section = f"\n\nMENU:\n{json.dumps(menu_json, indent=2)}"
        return base_prompt + menu_section

    return base_prompt
