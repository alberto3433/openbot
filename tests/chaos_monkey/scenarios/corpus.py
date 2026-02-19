"""Conversation pattern corpus for realistic chaos monkey testing.

Contains ~45 conversation patterns across 8 categories that model how real
bagel shop customers order. Slot placeholders get filled from menu data at
runtime by the generator.
"""

from dataclasses import dataclass, field
from enum import Enum


class PatternCategory(Enum):
    """Categories of ordering patterns."""

    INLINE_SPEC = "inline_spec"
    SHORTHAND = "shorthand"
    BATCH_ORDER = "batch_order"
    CORRECTION = "correction"
    CONTEXT_REFERENCE = "context_reference"
    DISCOVERY = "discovery"
    ADDON_DURING_CONFIG = "addon_during_config"
    QUANTITY = "quantity"


class SlotType(Enum):
    """Types of slots in conversation templates."""

    ITEM = "item"                         # Any menu item
    CONFIGURABLE_ITEM = "configurable_item"  # Item type that has config questions
    BREAD_OPTION = "bread_option"         # A bread/bagel type (plain, everything, etc.)
    SIZE_OPTION = "size_option"           # A size (small, large, etc.)
    MODIFIER = "modifier"                 # An ingredient/modifier (lox, butter, etc.)
    BOOLEAN_ATTR = "boolean_attr"         # A boolean attribute value (toasted, scooped)
    QUANTITY_WORD = "quantity_word"        # A quantity (two, three, 2, 3)
    CATEGORY_NAME = "category_name"       # A menu category (bagels, sandwiches, etc.)


@dataclass
class SlotDef:
    """Definition of a slot in a pattern template.

    Attributes:
        slot_type: What kind of menu data to fill this slot with.
        same_item_as: If set, constrain modifiers to be valid for the item in
            this other slot (ensures e.g. lox is valid for the bagel we ordered).
    """

    slot_type: SlotType
    same_item_as: str | None = None


@dataclass
class TurnTemplate:
    """A single turn template in a conversation pattern.

    Attributes:
        template: Template string with {slot_name} placeholders.
        is_menu_inquiry: If True, this turn is a question about the menu,
            not an order action. "Not found" responses are acceptable.
    """

    template: str
    is_menu_inquiry: bool = False


@dataclass
class ConversationPattern:
    """A realistic conversation pattern with slot placeholders.

    Attributes:
        id: Unique pattern identifier.
        category: Which category of ordering behavior this tests.
        description: Human-readable description of what this pattern tests.
        turns: Ordered list of turn templates.
        slots: Dict mapping slot names to their type definitions.
        weight: Relative selection weight (higher = more likely to be chosen).
        needs_reactive_loop: Whether the executor should run the reactive
            answer loop after the scripted turns.
        expected_item_slots: Slot names whose filled values should appear in
            the cart after execution.
    """

    id: str
    category: PatternCategory
    description: str
    turns: list[TurnTemplate]
    slots: dict[str, SlotDef]
    weight: float = 1.0
    needs_reactive_loop: bool = True
    expected_item_slots: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pattern corpus
# ---------------------------------------------------------------------------

PATTERNS: list[ConversationPattern] = [
    # -----------------------------------------------------------------------
    # INLINE SPECS — user specifies config details in the initial order
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="inline_bread_toasted",
        category=PatternCategory.INLINE_SPEC,
        description="Order a bagel with bread type and toasted inline",
        turns=[TurnTemplate("{bread} bagel toasted please")],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="inline_bread_modifier",
        category=PatternCategory.INLINE_SPEC,
        description="Order a bagel with bread and modifier inline",
        turns=[TurnTemplate("{bread} toasted with {mod}")],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
            "mod": SlotDef(SlotType.MODIFIER),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="inline_size_iced",
        category=PatternCategory.INLINE_SPEC,
        description="Order a sized drink with size and iced inline",
        turns=[TurnTemplate("a {size} iced {item}")],
        slots={
            "size": SlotDef(SlotType.SIZE_OPTION),
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="inline_size_hot",
        category=PatternCategory.INLINE_SPEC,
        description="Order a sized drink with size and hot inline",
        turns=[TurnTemplate("{size} hot {item} please")],
        slots={
            "size": SlotDef(SlotType.SIZE_OPTION),
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="inline_item_with_modifier",
        category=PatternCategory.INLINE_SPEC,
        description="Order a specific item with a modifier inline",
        turns=[TurnTemplate("I'll have a {item} with {mod}")],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="inline_item_no_modifier",
        category=PatternCategory.INLINE_SPEC,
        description="Order an item with a removed modifier",
        turns=[TurnTemplate("a {item} no {mod}")],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="inline_full_spec",
        category=PatternCategory.INLINE_SPEC,
        description="Fully specified bagel in one shot",
        turns=[TurnTemplate("{bread} bagel toasted with {mod}")],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
            "mod": SlotDef(SlotType.MODIFIER),
        },
        expected_item_slots=[],
    ),

    # -----------------------------------------------------------------------
    # SHORTHAND — terse ordering patterns real customers use
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="shorthand_mod_on_bread",
        category=PatternCategory.SHORTHAND,
        description="Modifier on a bread type",
        turns=[TurnTemplate("{mod} on a {bread}")],
        slots={
            "mod": SlotDef(SlotType.MODIFIER),
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="shorthand_item_on_bread_toasted",
        category=PatternCategory.SHORTHAND,
        description="Item on specific bread, toasted",
        turns=[TurnTemplate("{item} on {bread} toasted")],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="shorthand_just_item",
        category=PatternCategory.SHORTHAND,
        description="Just the item name, no preamble",
        turns=[TurnTemplate("{item}")],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="shorthand_bread_with_mod",
        category=PatternCategory.SHORTHAND,
        description="Bread type with modifier, no verb",
        turns=[TurnTemplate("{bread} with {mod}")],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
            "mod": SlotDef(SlotType.MODIFIER),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="shorthand_give_me",
        category=PatternCategory.SHORTHAND,
        description="Casual 'lemme get' phrasing",
        turns=[TurnTemplate("lemme get a {item}")],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),

    # -----------------------------------------------------------------------
    # BATCH ORDERS — multiple items in one turn
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="batch_two_breads",
        category=PatternCategory.BATCH_ORDER,
        description="Two different bagels by bread type",
        turns=[TurnTemplate("a {bread1} and a {bread2} bagel")],
        slots={
            "bread1": SlotDef(SlotType.BREAD_OPTION),
            "bread2": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="batch_three_items",
        category=PatternCategory.BATCH_ORDER,
        description="Three items in a single turn",
        turns=[TurnTemplate("a {item1}, a {item2}, and a {item3}")],
        slots={
            "item1": SlotDef(SlotType.ITEM),
            "item2": SlotDef(SlotType.ITEM),
            "item3": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item1", "item2", "item3"],
    ),
    ConversationPattern(
        id="batch_qty_breads",
        category=PatternCategory.BATCH_ORDER,
        description="Quantity of bagels with different bread types",
        turns=[TurnTemplate("{qty1} {bread1} and {qty2} {bread2} bagels")],
        slots={
            "qty1": SlotDef(SlotType.QUANTITY_WORD),
            "bread1": SlotDef(SlotType.BREAD_OPTION),
            "qty2": SlotDef(SlotType.QUANTITY_WORD),
            "bread2": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="batch_item_and_drink",
        category=PatternCategory.BATCH_ORDER,
        description="A food item and a drink together",
        turns=[TurnTemplate("I'll have a {item1} and a {size} {item2}")],
        slots={
            "item1": SlotDef(SlotType.ITEM),
            "size": SlotDef(SlotType.SIZE_OPTION),
            "item2": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item1", "item2"],
    ),
    ConversationPattern(
        id="batch_with_also",
        category=PatternCategory.BATCH_ORDER,
        description="Two items with 'also' connector",
        turns=[TurnTemplate("Can I get a {item1}? Also a {item2}")],
        slots={
            "item1": SlotDef(SlotType.ITEM),
            "item2": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item1", "item2"],
    ),
    ConversationPattern(
        id="batch_oh_and",
        category=PatternCategory.BATCH_ORDER,
        description="Two items with 'oh and' connector",
        turns=[TurnTemplate("a {item1}, oh and a {item2}")],
        slots={
            "item1": SlotDef(SlotType.ITEM),
            "item2": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item1", "item2"],
    ),

    # -----------------------------------------------------------------------
    # CORRECTIONS — changing something after ordering
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="correction_switch_bread",
        category=PatternCategory.CORRECTION,
        description="Switch bread type after ordering a bagel",
        turns=[
            TurnTemplate("I'll have a {bread1} bagel"),
            TurnTemplate("actually make that {bread2}"),
        ],
        slots={
            "bread1": SlotDef(SlotType.BREAD_OPTION),
            "bread2": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="correction_switch_item",
        category=PatternCategory.CORRECTION,
        description="Switch to a different item entirely",
        turns=[
            TurnTemplate("I'll have a {item1}"),
            TurnTemplate("actually, switch that to a {item2}"),
        ],
        slots={
            "item1": SlotDef(SlotType.ITEM),
            "item2": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item2"],
    ),
    ConversationPattern(
        id="correction_change_size",
        category=PatternCategory.CORRECTION,
        description="Change the size after ordering",
        turns=[
            TurnTemplate("a {size1} {item}"),
            TurnTemplate("wait, make that a {size2}"),
        ],
        slots={
            "size1": SlotDef(SlotType.SIZE_OPTION),
            "item": SlotDef(SlotType.ITEM),
            "size2": SlotDef(SlotType.SIZE_OPTION),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="correction_nevermind_modifier",
        category=PatternCategory.CORRECTION,
        description="Remove a modifier after adding it",
        turns=[
            TurnTemplate("a {item} with {mod}"),
            TurnTemplate("actually, no {mod}"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="correction_add_modifier_after",
        category=PatternCategory.CORRECTION,
        description="Add a modifier after the initial order",
        turns=[
            TurnTemplate("I'd like a {item}"),
            TurnTemplate("oh and can you add {mod}"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),

    # -----------------------------------------------------------------------
    # CONTEXT REFERENCES — referring to a previous item
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="context_same_but_bread",
        category=PatternCategory.CONTEXT_REFERENCE,
        description="Same item but different bread",
        turns=[
            TurnTemplate("I'll have a {bread1} bagel"),
            TurnTemplate("same thing but on {bread2}"),
        ],
        slots={
            "bread1": SlotDef(SlotType.BREAD_OPTION),
            "bread2": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="context_another_one",
        category=PatternCategory.CONTEXT_REFERENCE,
        description="Order another of the same item",
        turns=[
            TurnTemplate("a {item} please"),
            TurnTemplate("another one"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="context_add_mod_to_that",
        category=PatternCategory.CONTEXT_REFERENCE,
        description="Add modifier to the current item via reference",
        turns=[
            TurnTemplate("I'll have a {item}"),
            TurnTemplate("put {mod} on that too"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="context_make_it_toasted",
        category=PatternCategory.CONTEXT_REFERENCE,
        description="Request toasting via context reference",
        turns=[
            TurnTemplate("{bread} bagel please"),
            TurnTemplate("make it toasted"),
        ],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="context_same_for_me",
        category=PatternCategory.CONTEXT_REFERENCE,
        description="Order the same as a previous item",
        turns=[
            TurnTemplate("a {item}"),
            TurnTemplate("I'll have the same"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="context_that_plus_item",
        category=PatternCategory.CONTEXT_REFERENCE,
        description="Add another item referencing the first",
        turns=[
            TurnTemplate("a {item1}"),
            TurnTemplate("and a {item2} with that"),
        ],
        slots={
            "item1": SlotDef(SlotType.ITEM),
            "item2": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item1", "item2"],
    ),

    # -----------------------------------------------------------------------
    # DISCOVERY — asking about the menu, then ordering
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="discovery_what_category",
        category=PatternCategory.DISCOVERY,
        description="Ask what's in a category, then order",
        turns=[
            TurnTemplate("what {cat} do you have?", is_menu_inquiry=True),
            TurnTemplate("I'll do a {item}"),
        ],
        slots={
            "cat": SlotDef(SlotType.CATEGORY_NAME),
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="discovery_whats_popular",
        category=PatternCategory.DISCOVERY,
        description="Ask for recommendations, then order",
        turns=[
            TurnTemplate("what's popular?", is_menu_inquiry=True),
            TurnTemplate("I'll try a {item}"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="discovery_do_you_have",
        category=PatternCategory.DISCOVERY,
        description="Ask if a specific item exists, then order",
        turns=[
            TurnTemplate("do you have {item}?", is_menu_inquiry=True),
            TurnTemplate("great, I'll take one"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="discovery_what_spreads",
        category=PatternCategory.DISCOVERY,
        description="Ask about spreads, then order a bagel with one",
        turns=[
            TurnTemplate("what kind of spreads do you have?", is_menu_inquiry=True),
            TurnTemplate("{bread} bagel with {mod}"),
        ],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
            "mod": SlotDef(SlotType.MODIFIER),
        },
        expected_item_slots=[],
    ),

    # -----------------------------------------------------------------------
    # ADD-ONS DURING CONFIG — answering a config Q with extra info
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="addon_yes_and_modifier",
        category=PatternCategory.ADDON_DURING_CONFIG,
        description="Answer yes and add a modifier in the same turn",
        turns=[
            TurnTemplate("I'll have a {item}"),
            TurnTemplate("yes, and add {mod}"),
        ],
        slots={
            "item": SlotDef(SlotType.CONFIGURABLE_ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="addon_bread_and_toasted",
        category=PatternCategory.ADDON_DURING_CONFIG,
        description="Answer bread question with toasted in same breath",
        turns=[
            TurnTemplate("I'll have a bagel"),
            TurnTemplate("{bread} toasted"),
        ],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="addon_size_and_iced",
        category=PatternCategory.ADDON_DURING_CONFIG,
        description="Answer size question with iced preference",
        turns=[
            TurnTemplate("a {item} please"),
            TurnTemplate("{size} iced"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "size": SlotDef(SlotType.SIZE_OPTION),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="addon_bread_with_mod",
        category=PatternCategory.ADDON_DURING_CONFIG,
        description="Answer bread question with modifier attached",
        turns=[
            TurnTemplate("a bagel please"),
            TurnTemplate("{bread} with {mod}"),
        ],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
            "mod": SlotDef(SlotType.MODIFIER),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="addon_no_but_add",
        category=PatternCategory.ADDON_DURING_CONFIG,
        description="Decline current question but add something else",
        turns=[
            TurnTemplate("I'll have a {item}"),
            TurnTemplate("no, but add {mod}"),
        ],
        slots={
            "item": SlotDef(SlotType.CONFIGURABLE_ITEM),
            "mod": SlotDef(SlotType.MODIFIER, same_item_as="item"),
        },
        expected_item_slots=["item"],
    ),

    # -----------------------------------------------------------------------
    # QUANTITY — quantity changes and multi-quantity orders
    # -----------------------------------------------------------------------
    ConversationPattern(
        id="qty_multiple_items",
        category=PatternCategory.QUANTITY,
        description="Order multiple of the same item",
        turns=[TurnTemplate("{qty} {item} please")],
        slots={
            "qty": SlotDef(SlotType.QUANTITY_WORD),
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="qty_make_it_number",
        category=PatternCategory.QUANTITY,
        description="Change quantity after ordering",
        turns=[
            TurnTemplate("a {item}"),
            TurnTemplate("actually make it {qty}"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
            "qty": SlotDef(SlotType.QUANTITY_WORD),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="qty_one_more",
        category=PatternCategory.QUANTITY,
        description="Add one more of the same item",
        turns=[
            TurnTemplate("a {item}"),
            TurnTemplate("one more of the same"),
        ],
        slots={
            "item": SlotDef(SlotType.ITEM),
        },
        expected_item_slots=["item"],
    ),
    ConversationPattern(
        id="qty_multiple_breads",
        category=PatternCategory.QUANTITY,
        description="Multiple bagels of a specific bread",
        turns=[TurnTemplate("{qty} {bread} bagels")],
        slots={
            "qty": SlotDef(SlotType.QUANTITY_WORD),
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
    ConversationPattern(
        id="qty_dozen",
        category=PatternCategory.QUANTITY,
        description="Order a large quantity shorthand",
        turns=[TurnTemplate("half dozen {bread} bagels")],
        slots={
            "bread": SlotDef(SlotType.BREAD_OPTION),
        },
        expected_item_slots=[],
    ),
]
