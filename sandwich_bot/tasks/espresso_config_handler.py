"""
Espresso Configuration Handler for Order State Machine.

This module handles espresso ordering with a DATA-DRIVEN approach:
- Configuration questions and options come from the database (item_type_attributes)
- The handler reads the espresso item type's attributes and uses them to drive the flow

The espresso item type has these attributes (from DB):
- shots: Number of shots (single, double, triple, quad) - ask=False (parsed from initial order)
- drink_modifier: Milk, sweetener, syrup options - ask=True (consolidated attribute)
- decaf: Boolean for decaf - ask=False (parsed from initial order)
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import EspressoItemTask, OrderTask, TaskStatus
from .schemas import StateMachineResult
from .schemas.phases import OrderPhase
from .handler_config import HandlerConfig

if TYPE_CHECKING:
    from .pricing import PricingEngine
    from .menu_lookup import MenuLookup

logger = logging.getLogger(__name__)


class EspressoConfigHandler:
    """
    Handles espresso ordering flow with data-driven configuration.

    Reads item type attributes from the database to determine:
    - Which questions to ask (ask_in_conversation=True)
    - What the question text should be (question_text field)
    - What options are valid (attribute_options table)
    """

    def __init__(self, config: HandlerConfig | None = None, **kwargs):
        """
        Initialize the espresso config handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.pricing = config.pricing
            self.menu_lookup = config.menu_lookup
            self._get_next_question = config.get_next_question
            self._check_redirect = config.check_redirect
        else:
            self.pricing = kwargs.get("pricing")
            self.menu_lookup = kwargs.get("menu_lookup")
            self._get_next_question = kwargs.get("get_next_question")
            self._check_redirect = kwargs.get("check_redirect")

        # Cache for item type attributes (loaded on first use)
        self._espresso_attributes_cache: dict | None = None

    def _get_espresso_attributes(self) -> dict:
        """Load espresso item type attributes from database.

        Returns dict with structure:
        {
            "drink_modifier": {
                "question_text": "Any milk, sweetener, or syrup?",
                "options": [{"slug": "oat_milk", "display_name": "Oat Milk", "price": 0.50}, ...]
            },
            ...
        }
        """
        if self._espresso_attributes_cache is not None:
            return self._espresso_attributes_cache

        from ..db import SessionLocal
        from ..models import (
            ItemType, ItemTypeAttribute, AttributeOption,
            ItemTypeIngredient, Ingredient
        )

        db = SessionLocal()
        try:
            espresso_type = db.query(ItemType).filter(ItemType.slug == "espresso").first()
            if not espresso_type:
                logger.warning("Espresso item type not found in database")
                self._espresso_attributes_cache = {}
                return {}

            attrs = db.query(ItemTypeAttribute).filter(
                ItemTypeAttribute.item_type_id == espresso_type.id
            ).all()

            result = {}
            for attr in attrs:
                opts_data = []

                # Check if options should come from ingredients (new approach)
                if attr.loads_from_ingredients and attr.ingredient_group:
                    # Load options from item_type_ingredients + ingredients
                    ingredient_links = (
                        db.query(ItemTypeIngredient)
                        .join(Ingredient, ItemTypeIngredient.ingredient_id == Ingredient.id)
                        .filter(
                            ItemTypeIngredient.item_type_id == espresso_type.id,
                            ItemTypeIngredient.ingredient_group == attr.ingredient_group,
                            ItemTypeIngredient.is_available == True,
                        )
                        .order_by(ItemTypeIngredient.display_order)
                        .all()
                    )

                    for link in ingredient_links:
                        ingredient = link.ingredient
                        opt_data = {
                            "slug": ingredient.slug or ingredient.name.lower().replace(" ", "_"),
                            "display_name": link.display_name_override or ingredient.name,
                            "price": float(link.price_modifier or 0),
                            "category": ingredient.category,  # For filtering by type
                        }
                        # Include ingredient aliases for matching
                        if ingredient.aliases:
                            opt_data["ingredient_aliases"] = ingredient.aliases
                        opts_data.append(opt_data)

                    logger.debug(
                        "Loaded %d ingredient-based options for %s from group %s",
                        len(opts_data), attr.slug, attr.ingredient_group
                    )
                else:
                    # Load options from attribute_options (legacy approach)
                    options = db.query(AttributeOption).filter(
                        AttributeOption.item_type_attribute_id == attr.id
                    ).order_by(AttributeOption.display_order).all()

                    for opt in options:
                        opt_data = {
                            "slug": opt.slug,
                            "display_name": opt.display_name,
                            "price": float(opt.price_modifier or 0),
                        }
                        # Load ingredient aliases if linked
                        if opt.ingredient_links:
                            for link in opt.ingredient_links:
                                if link.ingredient and link.ingredient.aliases:
                                    opt_data["ingredient_aliases"] = link.ingredient.aliases
                                    break  # Use first linked ingredient's aliases
                        opts_data.append(opt_data)

                result[attr.slug] = {
                    "question_text": attr.question_text,
                    "ask_in_conversation": attr.ask_in_conversation,
                    "input_type": attr.input_type,
                    "options": opts_data,
                }

            self._espresso_attributes_cache = result
            logger.info("Loaded espresso attributes from DB: %s", list(result.keys()))
            return result

        finally:
            db.close()

    def _get_drink_modifier_question(self) -> str:
        """Get the drink modifier question from DB, with fallback."""
        attrs = self._get_espresso_attributes()
        drink_mod = attrs.get("drink_modifier", {})
        return drink_mod.get("question_text") or "Any milk, sweetener, or syrup?"

    def _get_drink_modifier_options(self) -> list[dict]:
        """Get valid drink modifier options from DB."""
        attrs = self._get_espresso_attributes()
        drink_mod = attrs.get("drink_modifier", {})
        return drink_mod.get("options", [])

    def _get_valid_modifier_names(self, category: str | None = None) -> set[str]:
        """Get valid modifier names for use as valid_answers in redirect checking.

        Returns a set of lowercase names that should NOT trigger a new order redirect.
        Includes display names, slugs (with underscores replaced), and ingredient aliases.

        Args:
            category: Optional category to filter by ('syrup', 'milk', 'sweetener')
        """
        options = self._get_drink_modifier_options()
        if category:
            options = [opt for opt in options if opt.get("category") == category]

        valid_names = set()
        for opt in options:
            # Add display name
            display = opt.get("display_name", "")
            if display:
                valid_names.add(display.lower())
                # Also add without "Syrup" suffix for matching just "peppermint"
                if display.lower().endswith(" syrup"):
                    valid_names.add(display.lower().replace(" syrup", ""))

            # Add slug (with underscores replaced by spaces)
            slug = opt.get("slug", "")
            if slug:
                valid_names.add(slug.lower().replace("_", " "))
                # Also just the flavor name without _syrup
                if slug.endswith("_syrup"):
                    valid_names.add(slug.replace("_syrup", "").replace("_", " "))

            # Add ingredient aliases
            aliases = opt.get("ingredient_aliases", "")
            if aliases:
                for alias in aliases.split(","):
                    alias = alias.strip().lower()
                    if alias:
                        valid_names.add(alias)
                        # Handle pipe-separated alternatives
                        for alt in alias.split("|"):
                            valid_names.add(alt.strip())

        return valid_names

    def _format_options_list(self, options: list[dict], conjunction: str = "and") -> str:
        """Format a list of options into a natural language string."""
        if not options:
            return ""
        names = [opt.get("display_name") or opt.get("slug", "").replace("_", " ") for opt in options]
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} {conjunction} {names[1]}"
        return ", ".join(names[:-1]) + f", {conjunction} {names[-1]}"

    def _match_modifier_from_input(self, user_input: str) -> list[dict]:
        """Match user input against valid drink modifier options from DB.

        Uses ingredient aliases for smart matching:
        - If ingredient has aliases with '|' (e.g., "sugar in the raw|raw sugar"),
          only match if one of those exact phrases is found (must-match mode)
        - If ingredient has a simple alias (e.g., "sugar"), match via word boundary
        - Fall back to slug-based matching if no ingredient alias

        Matching order:
        1. Must-match aliases (longer phrases) - processed first
        2. Simple aliases - only if words weren't already used in must-match
        3. Fallback slug matching - only if no aliases defined

        Returns list of matched modifiers with structure:
        [{"slug": "oat_milk", "display_name": "Oat Milk", "price": 0.50, "quantity": 1}, ...]
        """
        options = self._get_drink_modifier_options()
        user_lower = user_input.lower()
        matched = []
        matched_slugs = set()
        used_phrases = []  # Track which phrases were matched (to block simpler matches)

        # PASS 1: Check must-match aliases first (longer, more specific phrases)
        for opt in options:
            slug = opt.get("slug", "")
            display = opt.get("display_name", "")
            ingredient_aliases = opt.get("ingredient_aliases", "")

            if not ingredient_aliases or "|" not in ingredient_aliases:
                continue  # Skip - will handle in pass 2/3

            alias_patterns = [p.strip() for p in ingredient_aliases.split("|")]
            for alias in alias_patterns:
                if alias and re.search(rf'\b{re.escape(alias)}\b', user_lower):
                    qty_match = re.search(rf'(\d+)\s*{re.escape(alias)}', user_lower)
                    quantity = int(qty_match.group(1)) if qty_match else 1

                    matched.append({
                        "slug": slug,
                        "display_name": display or slug.replace("_", " ").title(),
                        "price": opt.get("price", 0),
                        "quantity": quantity,
                    })
                    matched_slugs.add(slug)
                    used_phrases.append(alias)  # Mark this phrase as used
                    break

        # PASS 2: Check simple aliases (only if words not already used)
        for opt in options:
            slug = opt.get("slug", "")
            if slug in matched_slugs:
                continue

            display = opt.get("display_name", "")
            ingredient_aliases = opt.get("ingredient_aliases", "")

            if not ingredient_aliases or "|" in ingredient_aliases:
                continue  # Skip must-match or no-alias options

            alias = ingredient_aliases.strip()

            # Skip if this alias word was part of a must-match phrase
            alias_used = any(alias in phrase for phrase in used_phrases)
            if alias_used:
                continue

            if alias and re.search(rf'\b{re.escape(alias)}s?\b', user_lower):
                qty_match = re.search(rf'(\d+)\s*{re.escape(alias)}s?', user_lower)
                quantity = int(qty_match.group(1)) if qty_match else 1

                matched.append({
                    "slug": slug,
                    "display_name": display or slug.replace("_", " ").title(),
                    "price": opt.get("price", 0),
                    "quantity": quantity,
                })
                matched_slugs.add(slug)

        # PASS 3: Fallback to slug-based matching (no ingredient aliases)
        for opt in options:
            slug = opt.get("slug", "")
            if slug in matched_slugs:
                continue

            display = opt.get("display_name", "")
            ingredient_aliases = opt.get("ingredient_aliases", "")

            # Skip if option has ingredient aliases (should have matched above)
            if ingredient_aliases:
                continue

            slug_pattern = slug.replace("_", " ")
            slug_no_space = slug.replace("_", "")

            patterns = [
                slug_pattern,  # "oat milk"
                slug_no_space,  # "oatmilk"
                display.lower(),  # "Oat Milk" -> "oat milk"
            ]

            first_word = slug.split("_")[0]
            if len(first_word) > 3:
                patterns.append(first_word)

            for pattern in patterns:
                if pattern and re.search(rf'\b{re.escape(pattern)}s?\b', user_lower):
                    qty_match = re.search(rf'(\d+)\s*{re.escape(pattern)}s?', user_lower)
                    quantity = int(qty_match.group(1)) if qty_match else 1

                    matched.append({
                        "slug": slug,
                        "display_name": display or slug.replace("_", " ").title(),
                        "price": opt.get("price", 0),
                        "quantity": quantity,
                    })
                    matched_slugs.add(slug)
                    break

        return matched

    def add_espresso(
        self,
        shots: int,
        quantity: int,
        order: OrderTask,
        decaf: bool | None = None,
        special_instructions: str | None = None,
        drink_modifiers: list[dict] | None = None,
    ) -> StateMachineResult:
        """
        Add espresso drink(s) to the order.

        Args:
            shots: Number of shots (1=single, 2=double, 3=triple)
            quantity: Number of espresso drinks to add
            order: The current order task
            decaf: Whether decaf (True=decaf, None=regular)
            special_instructions: Any special instructions
            drink_modifiers: Pre-parsed modifiers from initial order

        Returns:
            StateMachineResult with confirmation message and updated order
        """
        shots = max(1, min(4, shots))  # Clamp to 1-4 (quad supported)
        quantity = max(1, quantity)

        base_price = self._get_espresso_base_price()
        extra_shots_upcharge = self._get_shots_upcharge(shots)

        logger.info(
            "ADD ESPRESSO: shots=%d, quantity=%d, decaf=%s, base_price=%.2f, upcharge=%.2f, modifiers=%s",
            shots, quantity, decaf, base_price, extra_shots_upcharge, drink_modifiers
        )

        # Calculate modifier upcharge
        modifiers_upcharge = 0.0
        if drink_modifiers:
            for mod in drink_modifiers:
                modifiers_upcharge += mod.get("price", 0) * mod.get("quantity", 1)

        for _ in range(quantity):
            espresso = EspressoItemTask(
                shots=shots,
                decaf=decaf,
                unit_price=base_price + extra_shots_upcharge + modifiers_upcharge,
                extra_shots_upcharge=extra_shots_upcharge,
                modifiers_upcharge=modifiers_upcharge,
                special_instructions=special_instructions,
                drink_modifiers=drink_modifiers.copy() if drink_modifiers else [],
            )
            logger.info(
                "ESPRESSO CREATED: shots=%d, unit_price=%.2f, modifiers=%s",
                espresso.shots, espresso.unit_price, espresso.drink_modifiers
            )
            # Mark as in_progress to trigger modifier question if no modifiers yet
            espresso.mark_in_progress()
            order.items.add_item(espresso)

        return self.configure_next_incomplete_espresso(order)

    def configure_next_incomplete_espresso(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete espresso item (data-driven)."""
        all_espressos = [
            item for item in order.items.items
            if isinstance(item, EspressoItemTask)
        ]

        logger.info("CONFIGURE ESPRESSO: Found %d total espresso items", len(all_espressos))

        for espresso in all_espressos:
            if espresso.status != TaskStatus.IN_PROGRESS:
                continue

            logger.info(
                "CONFIGURE ESPRESSO: id=%s, shots=%d, modifiers=%s, status=%s",
                espresso.id, espresso.shots, espresso.drink_modifiers, espresso.status
            )

            # Check if pending syrup flavor selection
            if espresso.pending_modifier_slug:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = espresso.id
                order.pending_field = "espresso_syrup_flavor"
                logger.info("Espresso has pending modifier, asking for flavor")
                # Get syrup options from the drink_modifier options
                syrup_options = [
                    opt for opt in self._get_drink_modifier_options()
                    if "syrup" in opt.get("slug", "").lower()
                ]
                syrup_list = self._format_options_list(syrup_options, "and")
                return StateMachineResult(
                    message=f"Which flavor syrup would you like? We have {syrup_list}.",
                    order=order,
                )

            # Check if drink_modifier attribute needs to be asked (data-driven)
            attrs = self._get_espresso_attributes()
            drink_mod_attr = attrs.get("drink_modifier", {})

            if drink_mod_attr.get("ask_in_conversation", True) and not espresso.drink_modifiers:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = espresso.id
                order.pending_field = "espresso_modifiers"
                question = self._get_drink_modifier_question()
                return StateMachineResult(
                    message=question,
                    order=order,
                )

            # This espresso is complete
            espresso.mark_complete()

        # All espressos configured
        logger.info("CONFIGURE ESPRESSO: All espressos complete, going to next question")
        order.clear_pending()
        return self._get_next_question(order)

    def handle_espresso_modifiers(
        self,
        user_input: str,
        item: EspressoItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle drink modifier response for espresso (data-driven)."""
        question = self._get_drink_modifier_question()

        if self._check_redirect:
            # Pass valid modifier names so syrup/milk/sweetener answers don't trigger redirect
            valid_answers = self._get_valid_modifier_names()
            redirect = self._check_redirect(user_input, item, order, question, valid_answers)
            if redirect:
                return redirect

        user_lower = user_input.lower().strip()

        # Check if user is asking about available options
        if re.search(r"what.*(kind|type|have|option|choice)", user_lower):
            options = self._get_drink_modifier_options()

            # Filter by category if user asks about a specific type
            asked_category = None
            if re.search(r'\bsyrups?\b', user_lower):
                asked_category = 'syrup'
            elif re.search(r'\bmilks?\b', user_lower):
                asked_category = 'milk'
            elif re.search(r'\bsweeteners?\b', user_lower):
                asked_category = 'sweetener'

            if asked_category:
                options = [opt for opt in options if opt.get("category") == asked_category]
                category_name = asked_category + "s"  # pluralize
            else:
                category_name = "options"

            options_list = self._format_options_list(options, "and")
            return StateMachineResult(
                message=f"We have {options_list}. Would you like any of these?",
                order=order,
            )

        # Check for negative responses
        negative_patterns = [
            r'\bno\b', r'\bnope\b', r'\bnothing\b', r'\bnone\b',
            r"\bthat'?s? it\b", r"\bi'?m good\b", r"\bi'?m fine\b",
            r'\bjust that\b', r'\bno thanks\b', r'\bno thank you\b',
        ]
        is_negative = any(re.search(p, user_lower) for p in negative_patterns)

        # Check if user said "syrup" without specifying a flavor
        syrup_requested_no_flavor = (
            re.search(r'\bsyrups?\b', user_lower)
            and not any(
                re.search(rf'\b{re.escape(opt.get("slug", "").replace("_", " "))}\b', user_lower)
                for opt in self._get_drink_modifier_options()
                if "syrup" not in opt.get("slug", "").lower()  # Skip generic syrup options
            )
        )

        # Match modifiers from user input against DB options
        matched_modifiers = self._match_modifier_from_input(user_input)

        if syrup_requested_no_flavor and not any("syrup" in m.get("slug", "").lower() for m in matched_modifiers):
            # User wants syrup but didn't specify flavor
            logger.info("User requested syrup without flavor, asking for clarification")

            # Apply any other modifiers they mentioned
            for mod in matched_modifiers:
                if mod not in item.drink_modifiers:
                    item.drink_modifiers.append(mod)
                    logger.info(f"Added modifier: {mod}")

            # Extract quantity from "2 syrups"
            qty_match = re.search(r'(\d+)\s*syrups?', user_lower)
            item.pending_modifier_quantity = int(qty_match.group(1)) if qty_match else 1
            item.pending_modifier_slug = "syrup"

            order.pending_field = "espresso_syrup_flavor"
            syrup_options = [
                opt for opt in self._get_drink_modifier_options()
                if "syrup" in opt.get("slug", "").lower()
            ]
            syrup_list = self._format_options_list(syrup_options, "and")
            return StateMachineResult(
                message=f"Which flavor syrup would you like? We have {syrup_list}.",
                order=order,
            )

        # Apply matched modifiers
        if is_negative and not matched_modifiers:
            logger.info("User declined espresso modifiers")
        else:
            for mod in matched_modifiers:
                # Avoid duplicates
                existing_slugs = [m.get("slug") for m in item.drink_modifiers]
                if mod.get("slug") not in existing_slugs:
                    item.drink_modifiers.append(mod)
                    logger.info(f"Added modifier: {mod}")

        # Espresso is now complete
        item.mark_complete()
        order.clear_pending()

        return self.configure_next_incomplete_espresso(order)

    def handle_espresso_syrup_flavor(
        self,
        user_input: str,
        item: EspressoItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle syrup flavor selection for espresso."""
        if self._check_redirect:
            # Pass syrup names so flavor answers don't trigger redirect
            valid_answers = self._get_valid_modifier_names(category="syrup")
            redirect = self._check_redirect(
                user_input, item, order, "Which flavor syrup would you like?", valid_answers
            )
            if redirect:
                return redirect

        user_lower = user_input.lower().strip()

        # Check for negative/cancellation
        negative_patterns = [
            r'\bno\b', r'\bnope\b', r'\bnothing\b', r'\bnone\b',
            r'\bnevermind\b', r'\bnever mind\b', r'\bcancel\b',
            r'\bno thanks\b', r'\bno thank you\b', r"\bi'?m good\b",
        ]
        if any(re.search(p, user_lower) for p in negative_patterns):
            logger.info("User cancelled syrup selection for espresso")
            item.pending_modifier_slug = None
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_espresso(order)

        # Match syrup flavor from input
        matched = self._match_modifier_from_input(user_input)
        syrup_flavors = [m for m in matched if "syrup" in m.get("slug", "").lower()]

        if syrup_flavors:
            syrup = syrup_flavors[0]
            syrup["quantity"] = max(item.pending_modifier_quantity, syrup.get("quantity", 1))
            item.drink_modifiers.append(syrup)
            item.pending_modifier_slug = None
            logger.info(f"Added syrup from flavor selection: {syrup}")

            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_espresso(order)

        # Couldn't parse - ask again
        syrup_options = [
            opt for opt in self._get_drink_modifier_options()
            if "syrup" in opt.get("slug", "").lower()
        ]
        syrup_list = self._format_options_list(syrup_options, "or")
        return StateMachineResult(
            message=f"I didn't catch that. Which syrup flavor would you like - {syrup_list}?",
            order=order,
        )

    def _get_espresso_base_price(self) -> float:
        """Look up base espresso price from menu."""
        if self.menu_lookup:
            items = self.menu_lookup.lookup_menu_items("espresso")
            for item in items:
                if item.get("name", "").lower() == "espresso":
                    return item.get("base_price", 0)
        return 0

    def _get_shots_upcharge(self, shots: int) -> float:
        """Get upcharge for extra shots."""
        if shots <= 1:
            return 0.0
        if not self.pricing:
            return 0.0

        if shots == 2:
            return self.pricing.lookup_coffee_modifier_price("double_shot", "extras") or 0.0
        elif shots == 3:
            return self.pricing.lookup_coffee_modifier_price("triple_shot", "extras") or 0.0
        elif shots >= 4:
            return self.pricing.lookup_coffee_modifier_price("quad_shot", "extras") or 0.0
        return 0.0
