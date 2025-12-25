# Bagel Store Chatbot Architecture

## Overview

A modular, LangChain-based conversational ordering system with specialized sub-chains for each domain of the ordering process.

---

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                                │
│                    (Intent Router + State Manager)                  │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
        ┌─────────────┬─────────────┬─────────────┬─────────────┐
        │             │             │             │             │
        ▼             ▼             ▼             ▼             ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ GREETING│  │ ADDRESS │  │  BAGEL  │  │ COFFEE  │  │CHECKOUT │
   │  CHAIN  │  │  CHAIN  │  │  CHAIN  │  │  CHAIN  │  │  CHAIN  │
   └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘
        │             │             │             │             │
        └─────────────┴─────────────┴─────────────┴─────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │      ORDER STATE        │
                    │   (Pydantic Models)     │
                    └─────────────────────────┘
```

---

## Core Components

### 1. Orchestrator (Router Agent)
The brain that determines user intent and delegates to appropriate sub-chains.

**Responsibilities:**
- Classify incoming message intent
- Route to appropriate sub-chain
- Manage conversation state transitions
- Handle interruptions (e.g., user changes topic mid-order)

**Intents to Route:**
| Intent | Route To |
|--------|----------|
| greeting, hours, location | `GreetingChain` |
| delivery address, pickup | `AddressChain` |
| bagel, toast, cream cheese, lox | `BagelChain` |
| coffee, espresso, latte | `CoffeeChain` |
| done, checkout, pay, confirm | `CheckoutChain` |
| modify order, remove item | `ModifyOrderChain` |
| cancel | `CancelChain` |

---

### 2. Address Chain
Captures and validates delivery/pickup information.

**State Schema:**
```python
class AddressState(BaseModel):
    order_type: Literal["delivery", "pickup"] | None = None
    street: str | None = None
    city: str | None = None
    zip_code: str | None = None
    apt_unit: str | None = None
    delivery_instructions: str | None = None
    is_validated: bool = False
```

**Flow:**
```
START → Ask delivery/pickup
      → IF pickup: Confirm store location → COMPLETE
      → IF delivery: Collect street → city → zip → (optional) apt/instructions
      → Validate address (tool call to geocoding API)
      → Confirm with user → COMPLETE
```

**Tools:**
- `validate_address`: Geocoding API integration
- `check_delivery_zone`: Verify address is in delivery radius

---

### 3. Bagel Chain
Handles all bagel-related ordering.

**State Schema:**
```python
class BagelItem(BaseModel):
    bagel_type: str  # plain, everything, sesame, etc.
    quantity: int = 1
    toasted: bool = False
    spread: str | None = None  # cream cheese, butter, etc.
    spread_type: str | None = None  # plain, scallion, lox, etc.
    extras: list[str] = []  # bacon, tomato, capers, etc.
    sandwich_protein: str | None = None  # egg, bacon, lox, etc.
    
class BagelOrderState(BaseModel):
    items: list[BagelItem] = []
    current_item: BagelItem | None = None
    awaiting: str | None = None  # what info we're waiting for
```

**Flow:**
```
START → What kind of bagel?
      → How many?
      → Toasted?
      → Any spread? → (if yes) What type?
      → Anything else on it? (sandwich fixings)
      → Confirm item → Add to order
      → Another bagel? → (if yes) LOOP / (if no) COMPLETE
```

**Menu Data (RAG Source):**
- Bagel types + availability
- Spread options + pricing
- Sandwich combos
- Seasonal specials

---

### 4. Coffee Chain
Handles all beverage ordering.

**State Schema:**
```python
class CoffeeItem(BaseModel):
    drink_type: str  # drip, latte, espresso, cold brew, tea
    size: Literal["small", "medium", "large"]
    milk: str | None = None  # whole, skim, oat, almond, none
    sweetener: str | None = None
    shots: int | None = None  # extra espresso shots
    iced: bool = False
    
class CoffeeOrderState(BaseModel):
    items: list[CoffeeItem] = []
    current_item: CoffeeItem | None = None
    awaiting: str | None = None
```

**Flow:**
```
START → What drink?
      → Size?
      → Hot or iced?
      → (if applicable) Milk preference?
      → Any sweetener?
      → Confirm item → Add to order
      → Another drink? → (if yes) LOOP / (if no) COMPLETE
```

---

### 5. Checkout Chain
Finalizes and confirms the order.

**State Schema:**
```python
class CheckoutState(BaseModel):
    order_reviewed: bool = False
    total_calculated: bool = False
    payment_method: str | None = None
    tip_amount: float | None = None
    confirmed: bool = False
    order_number: str | None = None
```

**Flow:**
```
START → Summarize full order
      → Calculate total + tax
      → Confirm order correct?
      → (if changes needed) → Route to appropriate chain
      → Collect payment method
      → (optional) Add tip?
      → Final confirmation
      → Generate order number → COMPLETE
```

**Tools:**
- `calculate_total`: Pricing engine
- `submit_order`: POS/kitchen integration
- `send_confirmation`: SMS/email notification

---

## Master Order State

```python
class OrderState(BaseModel):
    """Complete order state passed between chains"""
    session_id: str
    started_at: datetime
    
    # Customer info
    customer_name: str | None = None
    customer_phone: str | None = None
    
    # Sub-states
    address: AddressState = AddressState()
    bagels: BagelOrderState = BagelOrderState()
    coffee: CoffeeOrderState = CoffeeOrderState()
    checkout: CheckoutState = CheckoutState()
    
    # Conversation tracking
    current_chain: str = "greeting"
    conversation_history: list[dict] = []
    
    # Order status
    status: Literal["in_progress", "confirmed", "cancelled"] = "in_progress"
```

---

## LangChain Implementation Pattern

### Chain Structure
Each sub-chain follows this pattern:

```python
class BagelChain:
    def __init__(self, llm, menu_retriever):
        self.llm = llm
        self.retriever = menu_retriever
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", BAGEL_SYSTEM_PROMPT),
            ("human", "{input}"),
        ])
        
    def invoke(self, state: OrderState, user_input: str) -> tuple[str, OrderState]:
        # 1. Retrieve relevant menu context
        context = self.retriever.get_relevant_documents(user_input)
        
        # 2. Build prompt with state + context
        messages = self.prompt.format_messages(
            input=user_input,
            current_item=state.bagels.current_item,
            menu_context=context,
        )
        
        # 3. Get LLM response with structured output
        response = self.llm.with_structured_output(BagelChainOutput).invoke(messages)
        
        # 4. Update state
        new_state = self._update_state(state, response)
        
        # 5. Return response text + updated state
        return response.message, new_state
```

---

## Tool Definitions

| Tool | Chain | Purpose |
|------|-------|---------|
| `validate_address` | Address | Geocode + validate delivery address |
| `check_delivery_zone` | Address | Verify in delivery radius |
| `get_menu_items` | Bagel/Coffee | RAG retrieval for menu |
| `check_availability` | Bagel/Coffee | Real-time inventory check |
| `calculate_price` | All | Get item/order pricing |
| `apply_promo_code` | Checkout | Validate and apply discounts |
| `submit_order` | Checkout | Send to POS/kitchen system |
| `send_confirmation` | Checkout | SMS/email order confirmation |

---

## Data Layer

### Menu RAG Index
```
/data
  /menu
    bagels.json       # Types, descriptions, prices
    spreads.json      # Cream cheese varieties, butters
    sandwiches.json   # Combo options
    beverages.json    # Coffee, tea, etc.
    specials.json     # Daily/seasonal items
  /policies
    hours.md          # Store hours
    delivery.md       # Delivery zones, minimums
    allergens.md      # Allergen information
```

### Vector Store
- **Recommended:** Chroma or Pinecone for menu/FAQ embeddings
- **Embedding model:** OpenAI `text-embedding-3-small` or local alternative

---

## Example Conversation Flow

```
USER: Hey, I want to order some bagels for delivery

ORCHESTRATOR: → GreetingChain (brief hello) → AddressChain

BOT: Hey! I'd love to help you with that. First, what's your delivery address?

USER: 123 Main St, Brooklyn 11201

ORCHESTRATOR: → AddressChain (continue)

BOT: Got it—123 Main St, Brooklyn 11201. Any apartment number or delivery instructions?

USER: Apt 4B, ring twice

ORCHESTRATOR: → AddressChain (complete) → Route based on next intent

BOT: Perfect, I've got that down. Now, what would you like to order?

USER: Two everything bagels toasted with scallion cream cheese

ORCHESTRATOR: → BagelChain

BOT: Nice choice! So that's 2 everything bagels, toasted, with scallion cream cheese. Anything else on them—tomato, lox, bacon?

USER: Nope, that's good. And a large iced coffee with oat milk

ORCHESTRATOR: → BagelChain (complete item) → CoffeeChain

BOT: Got it! One large iced coffee with oat milk. Any sweetener?

USER: No thanks. That's everything.

ORCHESTRATOR: → CoffeeChain (complete) → CheckoutChain

BOT: Here's your order:
- 2 Everything bagels, toasted, scallion cream cheese — $8.50
- 1 Large iced coffee, oat milk — $4.75
- Subtotal: $13.25
- Tax: $1.17
- Delivery fee: $2.99
- **Total: $17.41**

Delivering to: 123 Main St, Apt 4B, Brooklyn 11201

Does everything look good?
```

---

## Next Steps

1. **Define Pydantic models** for all state schemas
2. **Build menu data** (JSON files for RAG)
3. **Implement Orchestrator** with intent classification
4. **Build chains one at a time** (start with BagelChain)
5. **Add tool integrations** (address validation, pricing)
6. **Build simple UI** (Chainlit or Gradio for testing)
7. **Add persistence** (Redis or Postgres for session state)
