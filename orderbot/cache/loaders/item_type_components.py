"""
Item Type Components Loader Mixin.

Contains loader methods for component slots (sub-items within item types).
"""

import logging

logger = logging.getLogger(__name__)


class ItemTypeComponentsLoaderMixin:
    """Mixin for loading component slot configurations."""

    def _load_component_slots_from_bulk(self, bulk_data: dict) -> None:
        """Load component slots from bulk data.

        Component slots define how item types can include configurable sub-items.
        For example, omelettes have a "side" slot that accepts bagels or fruit salad.
        """
        slots = bulk_data.get("component_slots", [])

        # Build lookup dicts for resolving default_modifiers IDs to slugs
        # Use global_attrs (which eagerly load options with attribute relationship)
        gao_by_id: dict[int, tuple] = {}  # id -> (attribute_slug, option_slug)
        for ga in bulk_data.get("global_attrs", []):
            for opt in ga.options:
                gao_by_id[opt.id] = (ga.slug, opt.slug)
        ing_by_id: dict[int, object] = {}
        for ing in bulk_data.get("ingredients", []):
            ing_by_id[ing.id] = ing

        component_slots: dict[str, dict[str, dict]] = {}

        for slot in slots:
            parent_type_slug = slot.parent_item_type.slug

            if parent_type_slug not in component_slots:
                component_slots[parent_type_slug] = {}

            # Build options list
            options = []
            for opt in slot.slot_options:
                option_dict = {
                    "price_rule": opt.price_rule,
                    "fixed_price": opt.fixed_price,
                    "included_price_cents": opt.included_price_cents,
                    "display_name": opt.display_name,
                    "display_order": opt.display_order,
                }

                if opt.allowed_item_type:
                    option_dict["allowed_item_type"] = opt.allowed_item_type.slug
                if opt.allowed_menu_item:
                    option_dict["allowed_menu_item_id"] = opt.allowed_menu_item.id
                    option_dict["allowed_menu_item_name"] = opt.allowed_menu_item.name

                # Resolve default_modifiers from IDs to slugs for handler use
                option_dict["default_modifiers"] = self._resolve_default_modifiers_for_cache(
                    opt.default_modifiers, gao_by_id, ing_by_id
                )

                options.append(option_dict)

            # Sort options by display_order
            options.sort(key=lambda x: x.get("display_order", 0))

            component_slots[parent_type_slug][slot.slot_name] = {
                "display_name": slot.display_name,
                "prompt_text": slot.prompt_text,
                "is_required": slot.is_required,
                "min_quantity": slot.min_quantity,
                "max_quantity": slot.max_quantity,
                "display_order": slot.display_order,
                "options": options,
            }

        self._component_slots = component_slots

        logger.debug(
            "Loaded component slots for %d item types: %s",
            len(component_slots),
            list(component_slots.keys()),
        )

    @staticmethod
    def _resolve_default_modifiers_for_cache(
        raw_modifiers: list | None,
        gao_by_id: dict[int, tuple],
        ing_by_id: dict,
    ) -> list[dict]:
        """Resolve default modifier IDs to slugs for handler use at cache load time.

        Args:
            raw_modifiers: Raw JSONB list from the database.
            gao_by_id: Maps GlobalAttributeOption.id -> (attribute_slug, option_slug).
            ing_by_id: Maps Ingredient.id -> Ingredient ORM object.
        """
        if not raw_modifiers:
            return []

        resolved = []
        for entry in raw_modifiers:
            entry_type = entry.get("type")

            if entry_type == "attribute_option":
                gao_tuple = gao_by_id.get(entry.get("global_attribute_option_id"))
                if gao_tuple:
                    attr_slug, opt_slug = gao_tuple
                    resolved.append({
                        "type": "attribute_option",
                        "attribute_slug": attr_slug,
                        "option_slug": opt_slug,
                    })

            elif entry_type == "ingredient":
                ing = ing_by_id.get(entry.get("ingredient_id"))
                if ing:
                    resolved.append({
                        "type": "ingredient",
                        "ingredient_slug": ing.slug,
                        "ingredient_category": ing.category,
                        "quantity": entry.get("quantity", 1),
                    })

        return resolved
