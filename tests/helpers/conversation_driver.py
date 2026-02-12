"""
Conversation Driver - Multi-turn conversation test helper.

Simplifies end-to-end conversation tests by managing the OrderTask
and OrderStateMachine lifecycle automatically.

Usage:
    driver = ConversationDriver()
    driver.say("I'd like a plain bagel")
    assert driver.item_count == 1
    driver.say("toasted please")
    assert driver.last_item["toasted"] is True

    # Chain calls
    driver.say("add a large iced latte").say("yes please")

    # Start in a specific phase
    driver = ConversationDriver(phase=OrderPhase.CHECKOUT)
"""

from typing import Optional

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask, MenuItemTask


class ConversationDriver:
    """Multi-turn conversation test helper.

    Manages the OrderTask and OrderStateMachine state so tests only need
    to call .say() and check results, eliminating boilerplate.
    """

    def __init__(
        self,
        phase: OrderPhase = OrderPhase.TAKING_ITEMS,
        order: Optional[OrderTask] = None,
    ):
        """Initialize the driver.

        Args:
            phase: Starting order phase (default: TAKING_ITEMS)
            order: Optional pre-configured OrderTask (overrides phase)
        """
        if order is not None:
            self.order = order
        else:
            self.order = OrderTask()
            self.order.phase = phase.value
        self.sm = OrderStateMachine()
        self.last_result = None

    def say(self, text: str) -> "ConversationDriver":
        """Send user input and advance state.

        Args:
            text: User input text

        Returns:
            Self for chaining
        """
        self.last_result = self.sm.process(text, self.order)
        self.order = self.last_result.order
        return self

    def add_item(self, item: MenuItemTask) -> "ConversationDriver":
        """Add a pre-configured item to the order.

        Args:
            item: MenuItemTask to add

        Returns:
            Self for chaining
        """
        self.order.items.add_item(item)
        return self

    # ── Response properties ──

    @property
    def message(self) -> str:
        """The bot's last response message."""
        return self.last_result.message if self.last_result else ""

    @property
    def phase(self) -> str:
        """Current order phase."""
        return self.order.phase

    # ── Item access properties ──

    @property
    def items(self) -> list[MenuItemTask]:
        """All active (non-cancelled) items."""
        return self.order.items.get_active_items()

    @property
    def item_count(self) -> int:
        """Number of active items."""
        return len(self.items)

    @property
    def last_item(self) -> Optional[MenuItemTask]:
        """The most recently added item, or None."""
        active = self.items
        return active[-1] if active else None

    def get_items_by_type(self, item_type: str) -> list[MenuItemTask]:
        """Get all active items of a specific type.

        Args:
            item_type: Item type slug (e.g., "bagel", "sized_beverage")
        """
        return [i for i in self.items if i.item_type == item_type]

    def get_items_by_name(self, name: str) -> list[MenuItemTask]:
        """Get all active items matching a menu item name (case-insensitive).

        Args:
            name: Menu item name to match
        """
        name_lower = name.lower()
        return [i for i in self.items if i.menu_item_name and i.menu_item_name.lower() == name_lower]
