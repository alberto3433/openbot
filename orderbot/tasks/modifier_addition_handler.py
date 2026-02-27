"""
Modifier Addition Handler for Order State Machine.

Handles adding modifiers and new items during item configuration.
Split from config_modification_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult
from .parsers.intent_patterns import strip_conversational_fillers, strip_leading_fillers
from .checkout_messages import modifier_not_available_for_item
from .pending_fields import PendingField
from .parsers.quantity_utils import extract_leading_quantity
from orderbot.cache import menu_cache
from .utils.pricing_utils import safe_recalculate_price
from .utils.option_matcher import OptionMatcher
from .utils.text import normalize_text, name_with_prefix
from .models.utilities import parse_pending_field
from .config.attribute_resolver import get_unanswered_mandatory
from .config_flow_utils import (
    continue_config_with_message as _continue_config,
    start_modifier_disambiguation as _start_disambig,
)

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)

# Pattern to detect "add modifier" requests during config
# Matches: "add X", "also add X", "can you add X", "could you add X", "please add X",
#           "with X", "also with X"
ADD_MODIFIER_PREFIXES = [
    r"(?:also\s+)?add\s+",
    r"(?:can|could)\s+you\s+add\s+",
    r"please\s+add\s+",
    r"(?:also\s+)?with\s+",
]
ADD_MODIFIER_PATTERN = re.compile(
    r"^(?:" + "|".join(ADD_MODIFIER_PREFIXES) + r")",
    re.IGNORECASE
)

# Pattern for "I'd like X on that" style phrases where modifier is in the middle
# Captures the modifier term in group 1
ADD_MODIFIER_MIDDLE_PATTERN = re.compile(
    r"^(?:"
    r"i'?d\s+like\s+(.+?)\s+on\s+(?:that|it|this|there)"
    r"|i\s+want\s+(.+?)\s+on\s+(?:that|it|this|there)"
    r"|(?:put|throw)\s+(?:some\s+)?(.+?)\s+on\s+(?:that|it|this|there)"
    r"|(?:can|could)\s+(?:you\s+)?(?:put|throw)\s+(?:some\s+)?(.+?)\s+on\s+(?:that|it|this|there)"
    r"|(?:can|could)\s+i\s+(?:get|have)\s+(.+?)\s+on\s+(?:that|it|this|there)"
    r")(?:\s+(?:too|also|as\s+well|please|thanks|thank\s+you))*[\s?!.,]*$",
    re.IGNORECASE
)

# Pattern for desire expressions without "add"/"with" keywords:
# "I want X", "I'd like X", "give me X", "for the [item] I want X"
# Group 1: optional item reference (e.g., "iced tea")
# Group 2: modifier text (e.g., "Domino Sugar")
DESIRE_MODIFIER_PATTERN = re.compile(
    r"^(?:for\s+(?:the|my)\s+(.+?)\s+)?"
    r"(?:"
    r"i\s+(?:want|need)\s+"
    r"|i'?d\s+like\s+"
    r"|(?:give|get)\s+me\s+"
    r"|let\s+me\s+(?:get|have)\s+"
    r"|i'?ll\s+(?:have|take|get)\s+"
    r")"
    r"(.+?)"
    r"(?:\s+(?:too|also|as\s+well|please|thanks|thank\s+you))*$",
    re.IGNORECASE,
)


class ModifierAdditionHandler:
    """
    Handles adding modifiers and new items during item configuration.
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
    ) -> None:
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler
        self._taking_items_handler: "TakingItemsHandler | None" = None

    @property
    def taking_items_handler(self) -> "TakingItemsHandler | None":
        return self._taking_items_handler

    @taking_items_handler.setter
    def taking_items_handler(self, handler: "TakingItemsHandler | None") -> None:
        self._taking_items_handler = handler

    def _start_attribute_option_selection(
        self,
        attr_slug: str,
        attr_config: dict,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Start selection flow for attribute options when modifier maps to an attribute."""
        order.pending_field = f"{item.menu_item_type}:{attr_slug}"

        from .handler_utils import get_option_display_name
        option_names = [get_option_display_name(opt) for opt in options[:6]]
        if len(option_names) > 1:
            options_text = ", ".join(option_names[:-1]) + ", and " + option_names[-1]
        else:
            options_text = option_names[0] if option_names else ""

        display_name = attr_config.get("display_name") or attr_slug.replace("_", " ")
        question = f"How would you like your {display_name}?"

        from .handler_utils import build_quick_replies
        qr = build_quick_replies(option_names)
        return StateMachineResult(
            message=f"We have {options_text}. {question}",
            order=order,
            quick_replies=qr,
        )

    def _find_target_item_by_suffix(
        self,
        suffix: str,
        order: OrderTask,
    ) -> MenuItemTask | None:
        """Find an order item matching a target description flexibly."""
        from .item_matching import find_matching_item
        return find_matching_item(normalize_text(suffix), order.items.items)

    def _find_item_accepting_modifier(
        self,
        modifier_slug: str,
        exclude_item: MenuItemTask,
        order: OrderTask,
    ) -> MenuItemTask | None:
        """Find exactly one other item in the order that accepts a modifier."""
        candidates = []
        for it in order.items.items:
            if not isinstance(it, MenuItemTask):
                continue
            if it.id == exclude_item.id:
                continue
            if it.menu_item_type and menu_cache.is_valid_modifier_for_item_type(
                modifier_slug, it.menu_item_type
            ):
                candidates.append(it)
        return candidates[0] if len(candidates) == 1 else None

    # ─── Group 5: Add Modifiers During Config ────────────────────────

    def handle_add_modifiers_during_config(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'add X' patterns during item configuration.

        When a user says "add bacon and cheese" while being asked about toasted,
        we should add the modifiers to the current item and continue with the
        pending configuration question.
        """
        modifier_text, target_item, explicit_target = self._extract_add_modifier_text(
            user_input, item, order,
        )
        if not modifier_text:
            return None

        modifier_terms = re.split(r"\s*(?:,\s*|\s+and\s+)\s*", modifier_text)
        modifier_terms = [t.strip() for t in modifier_terms if t.strip()]

        if not modifier_terms:
            return None

        logger.info(
            "ADD_DURING_CONFIG: Detected add pattern '%s' with terms: %s",
            user_input, modifier_terms
        )

        original_config_item = item
        added_names: list[str] = []
        modified_items: set[str] = set()
        for term in modifier_terms:
            result = self._process_single_modifier_term(
                term, target_item, original_config_item, order,
                explicit_target, added_names, modified_items,
            )
            if result:
                return result

        if not added_names:
            return None

        pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
        for order_item in order.items.items:
            if isinstance(order_item, MenuItemTask) and order_item.id in modified_items:
                safe_recalculate_price(pricing, order_item, "after adding modifiers")

        from .utils.text import format_english_list
        added_text = format_english_list(added_names)
        message = f"Sure, I've added {added_text}."

        return _continue_config(self.config_helper_handler, self.checkout_utils_handler,message, original_config_item, order)

    def _extract_add_modifier_text(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> tuple[str | None, MenuItemTask, bool]:
        """Extract modifier text from an 'add X' user input."""
        user_stripped = strip_conversational_fillers(user_input.strip())
        # Strip leading "and" connector left after filler stripping
        # e.g., "oh and can you add X" → "oh" stripped → "and can you add X" → "can you add X"
        user_stripped = re.sub(r"^and[,\s]+", "", user_stripped, flags=re.IGNORECASE).strip()
        user_lower = user_stripped.lower()

        logger.info("ADD_DURING_CONFIG: Checking input '%s'", user_stripped[:50])

        modifier_text = None
        explicit_target = False

        match = ADD_MODIFIER_PATTERN.match(user_lower)
        if match:
            modifier_text = user_lower[match.end():].strip()
            modifier_text = re.sub(r"\s*(?:too|also|as\s+well|please|thanks|thank you)$", "", modifier_text).strip()
            modifier_text = re.sub(
                r"\s+(?:to|on|for)\s+(?:that|it|this|there)(?:\s+(?:too|also|as\s+well))?$",
                "",
                modifier_text,
            ).strip()
            target_prepositions = (" to the ", " on the ", " for the ",
                                   " to my ", " on my ", " for my ")
            for prep in target_prepositions:
                prep_idx = modifier_text.find(prep)
                if prep_idx != -1:
                    suffix = modifier_text[prep_idx + len(prep):].strip()
                    matched_item = self._find_target_item_by_suffix(suffix, order)
                    if matched_item:
                        modifier_text = modifier_text[:prep_idx].strip()
                        item = matched_item
                        explicit_target = True
                    break
        else:
            middle_match = ADD_MODIFIER_MIDDLE_PATTERN.match(user_lower)
            if middle_match:
                modifier_text = next(
                    (g for g in middle_match.groups() if g is not None), None
                )
                if modifier_text:
                    logger.debug(
                        "ADD_DURING_CONFIG: Matched middle pattern, modifier='%s'",
                        modifier_text
                    )

        if not modifier_text:
            desire_match = DESIRE_MODIFIER_PATTERN.match(user_lower)
            if desire_match:
                item_ref = desire_match.group(1)
                modifier_text = desire_match.group(2).strip()
                if item_ref:
                    matched_item = self._find_target_item_by_suffix(
                        item_ref.strip(), order
                    )
                    if matched_item:
                        item = matched_item
                        explicit_target = True
                if modifier_text:
                    from .parsers import parse_open_input_deterministic
                    parsed = parse_open_input_deterministic(modifier_text)
                    if parsed and parsed.parsed_items:
                        logger.debug(
                            "ADD_DURING_CONFIG: Desire pattern text '%s' matches a menu item, "
                            "skipping modifier path",
                            modifier_text,
                        )
                        return (None, item, False)
                    logger.debug(
                        "ADD_DURING_CONFIG: Matched desire pattern, modifier='%s'",
                        modifier_text,
                    )

        if not modifier_text:
            logger.debug("ADD_DURING_CONFIG: Input doesn't match add pattern, skipping")
            return (None, item, False)

        return (modifier_text, item, explicit_target)

    def _process_single_modifier_term(
        self,
        term: str,
        item: MenuItemTask,
        original_config_item: MenuItemTask,
        order: OrderTask,
        explicit_target: bool,
        added_names: list[str],
        modified_items: set[str],
    ) -> StateMachineResult | None:
        """Process a single modifier term during add-modifier-during-config."""
        extracted_qty, search_term = extract_leading_quantity(term)
        quantity = extracted_qty or 1
        if not search_term.strip():
            search_term = term

        matches = menu_cache.find_matching_ingredients(search_term)
        # Fallback: if no matches, try resolving via modifier alias
        # e.g., "almond" -> "Almond Milk" (alias lookup succeeds even when must_match blocks)
        if not matches and menu_cache.is_known_modifier(search_term):
            canonical = menu_cache.normalize_modifier(search_term)
            if canonical != search_term:
                matches = menu_cache.find_matching_ingredients(canonical)
        logger.info(
            "ADD_DURING_CONFIG: Looking up term '%s' (qty=%d), found %d matches: %s",
            search_term, quantity, len(matches), [m.get("name") for m in matches[:5]] if matches else []
        )

        if len(matches) == 1:
            match = matches[0]

            result = self._try_modifier_as_attribute_answer(
                search_term, match, item, original_config_item, order
            )
            if result:
                return result

            result = self._try_modifier_attribute_options(
                match, item, order, quantity
            )
            if result:
                return result

            result = self._validate_and_add_modifier(
                match, item, original_config_item, order,
                explicit_target, added_names, modified_items, quantity
            )
            if result:
                return result

        elif len(matches) > 1:
            logger.info(
                "ADD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation",
                term
            )
            return _start_disambig(term, matches, item, order)
        else:
            logger.warning(
                "ADD_DURING_CONFIG: Could not find modifier '%s' in database",
                search_term
            )

        return None

    def _try_modifier_as_attribute_answer(
        self,
        search_term: str,
        match: dict,
        item: MenuItemTask,
        original_config_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check if a matched ingredient is an answer to the pending attribute question."""
        ingredient_slug = match["slug"]
        _, pending_attr = parse_pending_field(order.pending_field)

        if not pending_attr or match.get("category") != pending_attr:
            return None

        resolved_slug = ingredient_slug
        resolved_display = match.get("name")
        attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
        options = attrs.get(pending_attr, {}).get("options", [])
        if options:
            matcher = OptionMatcher()
            matched_opt, _ = matcher.match_single(search_term, options)
            if not matched_opt:
                matched_opt, _ = matcher.match_single(
                    match.get("name", ""), options
                )
            if matched_opt:
                resolved_slug = matched_opt["slug"]
                resolved_display = (
                    matched_opt.get("display_name") or resolved_display
                )
        item.remove_selection(pending_attr)
        item.add_selection(
            slug=resolved_slug,
            category=pending_attr,
            display_name=resolved_display,
        )
        pricing = (
            self.modifier_change_handler.pricing
            if self.modifier_change_handler else None
        )
        safe_recalculate_price(pricing, item, "after setting attribute via add")
        unanswered = get_unanswered_mandatory(item, item.menu_item_type)
        if unanswered:
            order.pending_field = f"{item.menu_item_type}:{unanswered[0]['slug']}"
        else:
            order.pending_field = None
        message = f"Got it, {match.get('name', ingredient_slug)}."
        return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
            message, original_config_item, order
        )

    def _try_modifier_attribute_options(
        self,
        match: dict,
        item: MenuItemTask,
        order: OrderTask,
        quantity: int,
    ) -> StateMachineResult | None:
        """Check if ingredient slug matches an attribute with multiple options."""
        ingredient_slug = match["slug"]
        attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
        attr_config = attrs.get(ingredient_slug, {})
        options = attr_config.get("options", [])

        if not options or len(options) <= 1:
            return None

        existing_value = item.attribute_values.get(ingredient_slug)
        is_additive = existing_value is not None
        logger.info(
            "ADD_DURING_CONFIG: Ingredient '%s' matches attribute '%s' with %d options (qty=%d, additive=%s), starting selection",
            match["name"], ingredient_slug, len(options), quantity, is_additive
        )
        order.pending_modifier_quantity = quantity
        order.pending_modifier_is_additive = is_additive
        return self._start_attribute_option_selection(
            ingredient_slug, attr_config, options, item, order
        )

    def _validate_and_add_modifier(
        self,
        match: dict,
        item: MenuItemTask,
        original_config_item: MenuItemTask,
        order: OrderTask,
        explicit_target: bool,
        added_names: list[str],
        modified_items: set[str],
        quantity: int,
    ) -> StateMachineResult | None:
        """Validate modifier is allowed for item type and add it."""
        ingredient_slug = match["slug"]
        target_item = item
        is_valid = menu_cache.is_valid_modifier_for_item_type(
            ingredient_slug, item.menu_item_type
        )

        if not is_valid:
            if explicit_target:
                msg = modifier_not_available_for_item(
                    match["name"], item.get_display_name()
                )
                return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                    msg, original_config_item, order
                )
            alt = self._find_item_accepting_modifier(
                ingredient_slug, item, order
            )
            if alt:
                target_item = alt
                logger.info(
                    "ADD_DURING_CONFIG: Redirecting '%s' from %s to %s",
                    match["name"],
                    item.get_display_name(),
                    alt.get_display_name(),
                )
            else:
                # Modifier not valid for any cart item — try adding as a new menu item
                # e.g., "earl gray" is a tea, not a sandwich modifier
                new_item_result = self.handle_add_item_during_config(
                    match["name"], original_config_item, order, require_prefix=False
                )
                if new_item_result:
                    return new_item_result
                msg = modifier_not_available_for_item(
                    match["name"], item.get_display_name()
                )
                return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                    msg, original_config_item, order
                )

        target_item.add_selection(
            slug=match["slug"],
            category=match["category"],
            display_name=match["name"],
            quantity=quantity,
            price=match.get("base_price", 0.0),
            increment_if_exists=True,
        )
        modified_items.add(target_item.id)
        if target_item is not item or item is not original_config_item:
            added_names.append(
                f"{match['name']} to {name_with_prefix('your', target_item.get_display_name())}"
            )
        else:
            added_names.append(match["name"])
        logger.info(
            "ADD_DURING_CONFIG: Added '%s' (category=%s, qty=%d) to %s",
            match["name"], match["category"], quantity,
            target_item.get_display_name(),
        )
        return None

    # ─── Group 6: Add Item During Config ─────────────────────────────

    def handle_add_item_during_config(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        require_prefix: bool = True,
    ) -> StateMachineResult | None:
        """Handle adding new items during configuration (e.g., 'and a latte')."""
        from .parsed_item_processor import ParsedItemProcessor
        from .models import TaskStatus

        extracted = self._extract_add_item_text(user_input, require_prefix)
        if not extracted:
            return None
        item_text, parsed = extracted

        original_pending_field = order.pending_field
        original_pending_item_ids = order.pending_item_ids[:]

        pricing = self._taking_items_handler.pricing if self._taking_items_handler else None
        processor = ParsedItemProcessor(
            item_adder_handler=self.item_adder_handler,
            pricing=pricing,
        )

        items_before = len(order.items.items)
        result = processor.process_items(parsed, order)
        items_after = len(order.items.items)
        items_added = items_after - items_before

        if items_added == 0:
            if result and result.message:
                return result
            return None

        new_items = order.items.items[items_before:]
        for new_item in new_items:
            if new_item.status == TaskStatus.IN_PROGRESS:
                order.queue_item_for_config(
                    new_item.id,
                    item_name=new_item.get_display_name()
                )
                logger.info(
                    "ADD_ITEM_DURING_CONFIG: Queued %s (%s) for later config",
                    new_item.get_display_name(), new_item.id[:8]
                )

        order.pending_field = original_pending_field
        order.pending_item_ids = original_pending_item_ids

        logger.info(
            "ADD_ITEM_DURING_CONFIG: Added %d item(s), continuing config for %s",
            items_added, item.get_display_name()
        )

        added_names = [
            f"{p.quantity} {p.item_name or p.item_type}s" if p.quantity > 1
            else (p.item_name or p.item_type)
            for p in parsed.parsed_items
        ]
        return self._build_add_during_config_ack(added_names, item, order)

    def _extract_add_item_text(
        self, user_input: str, require_prefix: bool,
    ) -> tuple[str, "OpenInputResponse"] | None:
        """Extract and parse item text from an 'add item during config' input."""
        from .parsers.intent_patterns import ADD_ITEM_DURING_CONFIG_PREFIX
        from .parsers import parse_open_input_deterministic

        raw_input = user_input.strip()
        prefix_match = ADD_ITEM_DURING_CONFIG_PREFIX.match(raw_input)
        if prefix_match:
            item_text = raw_input[prefix_match.end():].strip()
        else:
            leading_stripped = strip_leading_fillers(raw_input)
            prefix_match = ADD_ITEM_DURING_CONFIG_PREFIX.match(leading_stripped)
            if prefix_match:
                item_text = leading_stripped[prefix_match.end():].strip()
            else:
                cleaned_input = strip_conversational_fillers(raw_input)
                prefix_match = ADD_ITEM_DURING_CONFIG_PREFIX.match(cleaned_input)
                if not prefix_match:
                    if require_prefix:
                        return None
                    item_text = cleaned_input
                else:
                    item_text = cleaned_input[prefix_match.end():].strip()

        item_text = strip_conversational_fillers(item_text)
        if not item_text:
            return None

        logger.info(
            "ADD_ITEM_DURING_CONFIG: Detected prefix, parsing item text: '%s'",
            item_text[:50]
        )

        parsed = parse_open_input_deterministic(item_text)
        if not parsed or not parsed.parsed_items:
            logger.debug("ADD_ITEM_DURING_CONFIG: No items parsed from '%s'", item_text[:50])
            return None

        logger.info(
            "ADD_ITEM_DURING_CONFIG: Parsed %d item(s): %s",
            len(parsed.parsed_items),
            [p.item_name or p.item_type for p in parsed.parsed_items]
        )
        return item_text, parsed

    def _build_add_during_config_ack(
        self,
        added_names: list[str],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Build acknowledgment response after adding items during config."""
        from .utils.text import format_english_list

        current_item_name = item.get_display_name()
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        added_text = format_english_list(added_names)

        if not current_question:
            return StateMachineResult(
                message=f"Got it, I've added {added_text}.",
                order=order,
            )

        # Build quick replies from the current pending field's attribute options
        qr = self._build_qr_for_pending_field(order, item, current_question)

        # Rewrite question inline options to match QR labels for linkification
        if qr and current_question.count("?") > 1:
            question_lower = current_question.lower()
            any_label_match = any(e["label"].lower() in question_lower for e in qr)
            if not any_label_match:
                first_part = current_question.split("?")[0].rstrip() + "?"
                label_names = [e["label"] for e in qr]
                current_question = first_part + " " + "? ".join(label_names) + "?"

        message = f"Got it, I've added {added_text}. Now, for {name_with_prefix('your', current_item_name)}, {current_question.lower()}"
        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _build_qr_for_pending_field(
        self,
        order: OrderTask,
        item: MenuItemTask,
        question: str,
    ) -> list[dict[str, str]] | None:
        """Build quick replies from the current pending field's attribute options."""
        from .config_flow_utils import build_qr_for_pending_field
        return build_qr_for_pending_field(order, question)
