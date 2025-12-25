"""
Pydantic state models for the conversation flow architecture.

These models define the state that is passed between chains and
persisted throughout the conversation session.
"""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


# -----------------------------------------------------------------------------
# Address State
# -----------------------------------------------------------------------------

class AddressState(BaseModel):
    """State for address/delivery information collection."""

    order_type: Literal["delivery", "pickup"] | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    apt_unit: str | None = None
    delivery_instructions: str | None = None
    is_validated: bool = False

    # For pickup orders
    store_location_confirmed: bool = False

    def is_complete(self) -> bool:
        """Check if address collection is complete."""
        if self.order_type == "pickup":
            return self.store_location_confirmed
        elif self.order_type == "delivery":
            return bool(self.street and self.city and self.zip_code and self.is_validated)
        return False

    def get_formatted_address(self) -> str | None:
        """Return formatted address string for delivery orders."""
        if self.order_type != "delivery":
            return None
        if not self.street:
            return None
        parts = [self.street]
        if self.apt_unit:
            parts.append(f"Apt {self.apt_unit}")
        city_state_zip = f"{self.city or ''}, {self.state or ''} {self.zip_code or ''}".strip().strip(",").strip()
        if city_state_zip:
            parts.append(city_state_zip)
        return ", ".join(parts)


# -----------------------------------------------------------------------------
# Bagel State
# -----------------------------------------------------------------------------

class BagelItem(BaseModel):
    """A single bagel item in the order."""

    bagel_type: str  # plain, everything, sesame, etc.
    quantity: int = 1
    toasted: bool | None = None  # None = not asked yet, True = toasted, False = not toasted
    spread: str | None = None  # cream cheese, butter, etc.
    spread_type: str | None = None  # plain, scallion, lox, etc.
    extras: list[str] = Field(default_factory=list)  # bacon, tomato, capers, etc.
    sandwich_protein: str | None = None  # egg, bacon, lox, etc.

    # Pricing
    unit_price: float = 0.0

    def get_description(self) -> str:
        """Return human-readable description of this bagel."""
        parts = []
        if self.quantity > 1:
            parts.append(f"{self.quantity}x")
        parts.append(self.bagel_type)
        if self.toasted:
            parts.append("toasted")
        if self.spread:
            if self.spread.lower() == "none":
                parts.append("with nothing on it")
            else:
                spread_desc = self.spread
                if self.spread_type:
                    spread_desc = f"{self.spread_type} {self.spread}"
                parts.append(f"with {spread_desc}")
        if self.sandwich_protein:
            parts.append(f"with {self.sandwich_protein}")
        if self.extras:
            parts.append(f"+ {', '.join(self.extras)}")
        return " ".join(parts)


class BagelOrderState(BaseModel):
    """State for bagel ordering flow."""

    items: list[BagelItem] = Field(default_factory=list)
    current_item: BagelItem | None = None
    awaiting: str | None = None  # what info we're waiting for: bagel_type, quantity, toasted, spread, etc.

    def add_current_item(self) -> None:
        """Add current item to items list and reset current_item."""
        if self.current_item:
            self.items.append(self.current_item)
            self.current_item = None
            self.awaiting = None

    def get_total(self) -> float:
        """Calculate total for all bagel items."""
        return sum(item.unit_price * item.quantity for item in self.items)


# -----------------------------------------------------------------------------
# Coffee State
# -----------------------------------------------------------------------------

class CoffeeItem(BaseModel):
    """A single coffee/beverage item in the order."""

    drink_type: str  # drip, latte, espresso, cold brew, tea
    size: Literal["small", "medium", "large"] | None = None
    milk: str | None = None  # whole, skim, oat, almond, none
    sweetener: str | None = None  # sugar, splenda, stevia, honey, etc.
    sweetener_quantity: int = 1  # number of sweetener packets (e.g., 2 splendas)
    flavor_syrup: str | None = None  # vanilla, caramel, hazelnut, mocha, etc.
    shots: int | None = None  # extra espresso shots
    iced: bool | None = None  # None = not asked yet, True = iced, False = hot

    # Pricing
    unit_price: float = 0.0

    def get_description(self) -> str:
        """Return human-readable description of this drink."""
        parts = []
        if self.size:
            parts.append(self.size)
        if self.iced:
            parts.append("iced")
        parts.append(self.drink_type)
        # Add flavor syrup
        if self.flavor_syrup:
            parts.append(f"with {self.flavor_syrup} syrup")
        if self.milk:
            # "none" or "black" means no milk - show as "black" for clarity
            if self.milk.lower() in ("none", "black"):
                parts.append("black")
            else:
                parts.append(f"with {self.milk} milk")
        # Add sweetener with quantity
        if self.sweetener:
            if self.sweetener_quantity > 1:
                parts.append(f"with {self.sweetener_quantity} {self.sweetener}s")
            else:
                parts.append(f"with {self.sweetener}")
        if self.shots and self.shots > 0:
            parts.append(f"({self.shots} extra shot{'s' if self.shots > 1 else ''})")
        return " ".join(parts)


class CoffeeOrderState(BaseModel):
    """State for coffee/beverage ordering flow."""

    items: list[CoffeeItem] = Field(default_factory=list)
    current_item: CoffeeItem | None = None
    awaiting: str | None = None  # what info we're waiting for: drink_type, size, milk, etc.

    def add_current_item(self) -> None:
        """Add current item to items list and reset current_item."""
        if self.current_item:
            self.items.append(self.current_item)
            self.current_item = None
            self.awaiting = None

    def get_total(self) -> float:
        """Calculate total for all coffee items."""
        return sum(item.unit_price for item in self.items)


# -----------------------------------------------------------------------------
# Checkout State
# -----------------------------------------------------------------------------

class CheckoutState(BaseModel):
    """State for checkout flow."""

    order_reviewed: bool = False
    total_calculated: bool = False
    subtotal: float = 0.0
    city_tax: float = 0.0  # City/local tax amount
    state_tax: float = 0.0  # State tax amount
    tax: float = 0.0  # Total tax (city + state) - kept for backward compatibility
    delivery_fee: float = 0.0
    tip_amount: float | None = None
    total: float = 0.0
    payment_method: str | None = None  # card, cash, pay_later
    confirmed: bool = False
    order_number: str | None = None
    awaiting: str | None = None  # Track what info we're waiting for: name, contact, confirmation
    name_collected: bool = False
    contact_collected: bool = False

    def calculate_total(
        self,
        subtotal: float,
        is_delivery: bool = False,
        city_tax_rate: float = 0.0,
        state_tax_rate: float = 0.0,
        delivery_fee: float = 2.99,
        tax_rate: float = None,  # Deprecated: use city_tax_rate and state_tax_rate
    ) -> None:
        """Calculate order total with tax and fees.

        Args:
            subtotal: Order subtotal before tax
            is_delivery: Whether this is a delivery order
            city_tax_rate: City/local tax rate (e.g., 0.04 for 4%)
            state_tax_rate: State tax rate (e.g., 0.04 for 4%)
            delivery_fee: Delivery fee amount
            tax_rate: Deprecated - combined tax rate for backward compatibility
        """
        self.subtotal = subtotal

        # Handle backward compatibility: if tax_rate is provided and no separate rates
        if tax_rate is not None and city_tax_rate == 0.0 and state_tax_rate == 0.0:
            # Old-style combined rate
            self.city_tax = 0.0
            self.state_tax = 0.0
            self.tax = round(subtotal * tax_rate, 2)
        else:
            # New-style separate rates
            self.city_tax = round(subtotal * city_tax_rate, 2) if city_tax_rate > 0 else 0.0
            self.state_tax = round(subtotal * state_tax_rate, 2) if state_tax_rate > 0 else 0.0
            self.tax = round(self.city_tax + self.state_tax, 2)

        self.delivery_fee = delivery_fee if is_delivery else 0.0
        self.total = round(self.subtotal + self.tax + self.delivery_fee + (self.tip_amount or 0), 2)
        self.total_calculated = True

    def generate_order_number(self) -> str:
        """Generate a unique order number.

        Format: ORD-{6 hex chars}-{2 digits}
        Example: ORD-AB12CD-45

        The last 2 characters are always digits (00-99) for easy voice readout.
        """
        import random
        hex_part = uuid.uuid4().hex[:6].upper()
        digit_suffix = f"{random.randint(0, 99):02d}"
        self.order_number = f"ORD-{hex_part}-{digit_suffix}"
        return self.order_number


# -----------------------------------------------------------------------------
# Master Order State
# -----------------------------------------------------------------------------

class OrderStatus(str, Enum):
    """Status of the overall order."""
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ChainName(str, Enum):
    """Names of available chains for routing."""
    GREETING = "greeting"
    ADDRESS = "address"
    BAGEL = "bagel"
    COFFEE = "coffee"
    CHECKOUT = "checkout"
    MODIFY = "modify"
    CANCEL = "cancel"


class OrderState(BaseModel):
    """
    Complete order state passed between chains.

    This is the master state object that contains all sub-states
    and tracks the overall conversation flow.
    """

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=datetime.utcnow)

    # Customer info
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None

    # Sub-states
    address: AddressState = Field(default_factory=AddressState)
    bagels: BagelOrderState = Field(default_factory=BagelOrderState)
    coffee: CoffeeOrderState = Field(default_factory=CoffeeOrderState)
    checkout: CheckoutState = Field(default_factory=CheckoutState)

    # Conversation tracking
    current_chain: ChainName = ChainName.GREETING
    previous_chain: ChainName | None = None
    conversation_history: list[dict] = Field(default_factory=list)

    # Pending intents - track items user mentioned but haven't ordered yet
    pending_coffee: bool = False  # User mentioned coffee in initial request

    # Order status
    status: OrderStatus = OrderStatus.IN_PROGRESS

    # Store context
    store_id: str | None = None

    def get_subtotal(self) -> float:
        """Calculate order subtotal from all items."""
        return self.bagels.get_total() + self.coffee.get_total()

    def has_items(self) -> bool:
        """Check if order has any items."""
        return bool(self.bagels.items or self.coffee.items)

    def get_item_count(self) -> int:
        """Get total number of items in order."""
        bagel_count = sum(item.quantity for item in self.bagels.items)
        coffee_count = len(self.coffee.items)
        return bagel_count + coffee_count

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_order_summary(self) -> str:
        """Generate human-readable order summary."""
        lines = []

        # Bagels
        for item in self.bagels.items:
            lines.append(f"- {item.get_description()} — ${item.unit_price * item.quantity:.2f}")

        # Coffee
        for item in self.coffee.items:
            lines.append(f"- {item.get_description()} — ${item.unit_price:.2f}")

        if not lines:
            return "No items in order yet."

        return "\n".join(lines)

    def transition_to(self, chain: ChainName) -> None:
        """Transition to a new chain."""
        self.previous_chain = self.current_chain
        self.current_chain = chain


# -----------------------------------------------------------------------------
# Chain Result
# -----------------------------------------------------------------------------

class ChainResult(BaseModel):
    """
    Result returned from a chain invocation.

    Contains the response message and updated state, plus metadata
    about what action to take next.
    """

    message: str  # Response message to show user
    state: OrderState  # Updated state
    chain_complete: bool = False  # True if this chain's work is done
    next_chain: ChainName | None = None  # Suggested next chain (Orchestrator can override)
    needs_user_input: bool = True  # False if chain should continue without user input

    class Config:
        arbitrary_types_allowed = True
