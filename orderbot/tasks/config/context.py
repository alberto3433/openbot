"""
Configuration Handler Context.

Provides a shared context object that holds dependencies for config sub-handlers,
replacing the callback jungle pattern where each sub-handler received 10+ callbacks.

Sub-handlers now receive a single ConfigHandlerContext and access what they need.
"""

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from ..schemas import StateMachineResult
    from ..utils import OptionMatcher, InputNormalizer


@dataclass
class ConfigHandlerContext:
    """
    Shared context for menu item configuration sub-handlers.

    Groups related callbacks and dependencies that are passed to sub-handlers,
    eliminating the need for each sub-handler to declare 10+ __init__ parameters.

    Sub-handlers access what they need via this single context object.

    Example:
        # Before (callback jungle):
        handler = CustomizationCheckpointHandler(
            options_inquiry_handler=self._options_inquiry_handler,
            option_matcher=self._option_matcher,
            recalculate_item_price=self._recalculate_item_price,
            get_unanswered_optional=self._get_unanswered_optional,
            ... 10 more callbacks ...
        )

        # After (context object):
        ctx = ConfigHandlerContext(...)
        handler = CustomizationCheckpointHandler(ctx)
    """

    # Core dependencies
    pricing: "PricingEngine | None" = None
    option_matcher: "OptionMatcher | None" = None
    input_normalizer: "InputNormalizer | None" = None

    # Attribute resolution callbacks (from attribute_resolver.py)
    get_item_type_attributes: Callable[[str], dict] | None = None
    get_optional_attributes: Callable[[str], list[dict]] | None = None
    get_unanswered_optional: Callable[["MenuItemTask", str], list[dict]] | None = None

    # Display/formatting callbacks
    format_display_list: Callable[[list[dict]], str] | None = None

    # Navigation callbacks
    advance_to_next_question: Callable[
        ["MenuItemTask", "OrderTask", dict, str | None], "StateMachineResult"
    ] | None = None
    get_next_question: Callable[["OrderTask"], "StateMachineResult | None"] | None = None

    # Matching callbacks
    match_attribute_from_input: Callable[[str, list[dict]], list[dict]] | None = None
    extract_quantity_from_input: Callable[[str], tuple[int, str]] | None = None
    extract_qualifier_for_option: Callable[[str, str], str | None] | None = None

    # Price callbacks
    recalculate_item_price: Callable[["MenuItemTask"], None] | None = None

    # Question/action callbacks
    ask_disambiguation_for_options: Callable[
        ["MenuItemTask", "OrderTask", dict, dict, str], "StateMachineResult"
    ] | None = None
    ask_customization_checkpoint: Callable[
        ["MenuItemTask", "OrderTask", str | None], "StateMachineResult"
    ] | None = None
    ask_optional_attribute: Callable[
        ["MenuItemTask", "OrderTask", dict], "StateMachineResult"
    ] | None = None
    ask_more_customizations: Callable[
        ["MenuItemTask", "OrderTask", str | None], "StateMachineResult"
    ] | None = None
    try_direct_option_match: Callable[
        [str, list[dict], "MenuItemTask", "OrderTask"], "StateMachineResult | None"
    ] | None = None

    # Optional callbacks (may be set after init to avoid circular deps)
    process_pending_parsed_items: Callable[
        ["OrderTask"], "StateMachineResult | None"
    ] | None = None
