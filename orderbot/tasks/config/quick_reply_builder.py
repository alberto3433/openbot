"""
Quick Reply Builder for Menu Item Configuration.

Builds quick reply option lists for attribute configuration questions,
including attribute options, component slot options, deduplication,
and label-to-question-text synchronization.

Extracted from MenuItemConfigHandler._ask_attribute_question.
"""

from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize
from ..utils.text import extract_question_phrase

__all__ = ["QuickReplyBuilder"]


class QuickReplyBuilder:
    """Builds quick reply option lists for attribute configuration questions."""

    def build(
        self,
        attr: dict,
        base_question: str,
        item_type: str | None,
    ) -> tuple[list[dict[str, str]] | None, str | None, str | None]:
        """Build quick reply options and optional question suffix for an attribute.

        Handles:
        - Building QR from attribute options (single_select, multi_select, boolean)
        - Category-level QR for multi_select with grouped options
        - Fallback linkification when no QR label matches question text
        - Component slot options from item type config
        - Deduplication by label
        - Label-to-question-text synchronization (rebuilding inline options)

        Args:
            attr: The attribute definition dict (must have 'input_type', may have 'options').
            base_question: The base question text (without prefix/notes).
            item_type: The item type slug (for component slot lookup).

        Returns:
            Tuple of (quick_replies, question_suffix, rebuilt_base_question):
            - quick_replies: List of {label, value} dicts or None
            - question_suffix: Optional suffix to append to question (e.g., " Yes or no?")
            - rebuilt_base_question: Replacement base question if labels didn't match, or None
        """
        qr: list[dict[str, str]] = []
        question_suffix = None
        input_type = attr.get("input_type", "single_select")

        # Source 1: Attribute options (data-driven)
        if input_type in ("single_select", "multi_select"):
            options = attr.get("options", [])
            available_opts = [o for o in options if o.get("is_available", True)]
            # Single option with allow_none is effectively a yes/no question
            # (e.g., "Would you like an espresso shot?") -- use Yes/No replies
            # instead of the option name to avoid false inline linking
            if len(available_opts) == 1 and attr.get("allow_none", False):
                qr.append({"label": "Yes", "value": "yes"})
                qr.append({"label": "No", "value": "no"})
            else:
                for o in available_opts:
                    qr.append({"label": o["display_name"], "value": o["display_name"]})
                # For multi_select with category-grouped options, use category-level
                # quick replies when the question mentions those categories.
                # e.g., "Any milk, sweetener, or syrup?" -> clicking "milk" sends
                # "What kind of milk do you have?" which triggers options inquiry.
                if input_type == "multi_select":
                    categories = list(dict.fromkeys(
                        o.get("ingredient_category") for o in available_opts
                        if o.get("ingredient_category")
                    ))
                    if len(categories) > 1:
                        base_lower = base_question.lower()
                        cat_qr: list[dict[str, str]] = []
                        for cat in categories:
                            if cat.lower() in base_lower:
                                cat_qr.append({
                                    "label": cat,
                                    "value": f"What {pluralize(cat.lower())} do you have?",
                                })
                        if cat_qr:
                            qr = cat_qr
        elif input_type == "boolean":
            question_suffix = " Yes or no?"
            qr.append({"label": "Yes", "value": "yes"})
            qr.append({"label": "No", "value": "no"})

        # For select attributes where no QR label matches the question text,
        # linkify the attribute display name itself so users can click to see options
        # (e.g., "spread" in "Any spread on that?" -> "what kind of spread do you have?")
        if qr and input_type in ("single_select", "multi_select"):
            base_lower = base_question.lower()
            has_match = any(e["label"].lower() in base_lower for e in qr)
            if not has_match:
                trigger = extract_question_phrase(base_question)
                if trigger and trigger.lower() in base_lower:
                    qr = [{"label": trigger, "value": f"What {pluralize(trigger.lower())} do you have?"}]
                else:
                    display = attr.get("display_name") or attr["slug"]
                    if display.lower() in base_lower:
                        qr = [{"label": display, "value": f"What {pluralize(display.lower())} do you have?"}]

        # Source 2: Component slot options (e.g., side_choice -> side slot)
        # Always merge slot options so both attribute options AND slot display names
        # are clickable. Quick replies are inline-only (frontend only highlights text
        # that appears in the message), so extra labels are harmless -- they simply
        # won't be highlighted. Deduplication below removes any duplicates.
        if item_type:
            slots = menu_cache.get_component_slots(item_type)
            for _slot_name, slot_config in slots.items():
                for o in slot_config.get("options", []):
                    label = o.get("display_name")
                    if not label and o.get("allowed_item_type"):
                        label = menu_cache.get_item_type_display_name(o["allowed_item_type"])
                    if not label:
                        label = o.get("allowed_item_type", "")
                    if label:
                        qr.append({"label": label, "value": label})

        # Deduplicate by label (case-insensitive), preserving order
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for entry in qr:
            key = entry["label"].lower()
            if key not in seen:
                seen.add(key)
                deduped.append(entry)
        qr_result = deduped or None

        # Ensure quick reply labels appear in the question text so the frontend
        # can linkify them inline.  When the DB question_text has baked-in option
        # names that differ from the attribute option display_names (e.g. "1/4 pound"
        # in question vs "1/4 lb" in display_name), the frontend can't match them.
        # Fix: rebuild the question's inline options using the actual display names.
        # Check against base_question (without prefix) to avoid false positives
        # from the prefix containing a label (e.g. "with 1/4 lb").
        rebuilt_base_question = None
        if qr_result and input_type in ("single_select", "multi_select"):
            base_lower = base_question.lower()
            any_label_in_base = any(
                entry["label"].lower() in base_lower for entry in qr_result
            )
            if not any_label_in_base and base_question.count("?") > 1:
                # Base question has inline options that don't match labels.
                # Rebuild: keep first sentence, replace options with labels.
                first_part = base_question.split("?")[0].rstrip() + "?"
                label_names = [entry["label"] for entry in qr_result]
                rebuilt_base_question = first_part + " " + "? ".join(label_names) + "?"

        return qr_result, question_suffix, rebuilt_base_question
