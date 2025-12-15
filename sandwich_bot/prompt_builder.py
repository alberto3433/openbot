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
3. NAME & PHONE: Only AFTER they've had a chance to add sides/drinks (or declined), ask for name and phone
4. CONFIRM: Summarize complete order and confirm

- Do NOT ask for name/phone right after the main item - always offer sides/drinks first!
- If customer declines sides/drinks ("no thanks", "that's all"):
  * THEN ask for name and phone to complete the order

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

ORDER CONFIRMATION - CRITICAL:
- You MUST have the customer's name AND phone number BEFORE confirming any order.
- CHECK ORDER STATE for existing customer info first - don't ask again if already provided.
- When ORDER STATE has customer info and user confirms, use confirm_order immediately.

CALLER ID - PHONE NUMBER FROM INCOMING CALL:
- If "CALLER ID" section is present, we already have the customer's phone number.
- Confirm the number is correct and ask for their name.

RETURNING CUSTOMER - REPEAT LAST ORDER:
- If "PREVIOUS ORDER" section is present, this is a returning customer.
- When they say "repeat my last order", "same as last time", "my usual":
  1. Use the "repeat_order" intent
  2. GREET THEM BY NAME
  3. List their previous items and confirm

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

    # Add ordering instructions
    lines.append(f"\n- When ordering a {type_slug}:")
    lines.append(f"  * SIGNATURE ITEMS: Add immediately with add_{type_slug} intent, including default_config values")
    lines.append(f"  * CUSTOM ITEMS: Ask for required attributes before adding")
    lines.append(f"  * Use update_{type_slug} intent to modify items already in the order")

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
