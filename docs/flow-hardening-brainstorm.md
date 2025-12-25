# Brainstorm: Hardening the Order Flow

## The Problem

The LLM-based bot is inconsistent:
- Sometimes asks for name when it already has it
- Skips steps or asks questions out of order
- Doesn't reliably check ORDER STATE before asking questions
- Prompt instructions get ignored or misinterpreted

**Root cause:** We're relying entirely on prompt engineering to control flow, but LLMs are probabilistic and don't follow instructions 100% reliably.

---

## Option 1: Verification Agent (Post-Response Check)

**How it works:**
- After the main bot generates a response, a second "guardian" agent reviews it
- Guardian checks: "Does this response ask for information already in ORDER STATE?"
- If violation detected, either fix the response or regenerate

**Pros:**
- Catches errors before they reach the customer
- Can enforce hard rules that prompts can't guarantee
- Relatively simple to implement

**Cons:**
- Doubles LLM latency (bad for voice)
- Adds cost (2x API calls)
- Guardian agent could also make mistakes

**Verdict:** Interesting but latency is a killer for voice.

---

## Option 2: State Machine / Flow Engine

**How it works:**
- Define the order flow as explicit states: `GREETING → TAKING_ORDER → SIDES_DRINKS → ORDER_TYPE → CUSTOMER_INFO → PAYMENT → CONFIRM`
- Each state has:
  - Entry conditions (what must be true to enter)
  - Exit conditions (what must be collected to leave)
  - Allowed transitions
- The LLM generates responses, but the **flow engine** controls what step we're in
- LLM can't skip steps or ask wrong questions because the engine won't let it

**Example:**
```
State: CUSTOMER_INFO
  Required before entry: items in cart, order_type set
  Required to exit: customer.name, customer.phone
  Skip condition: IF customer.name AND customer.phone already set → skip to PAYMENT
```

**Pros:**
- Deterministic flow control
- LLM only handles natural language, not flow logic
- Easy to visualize and debug
- Can guarantee certain behaviors

**Cons:**
- More rigid (less "conversational")
- Requires building the state machine
- Edge cases (customer asks unrelated question mid-flow)

**Verdict:** Strong option. Separates concerns - LLM does language, code does flow.

---

## Option 3: Flow Definition UI

**How it works:**
- Visual editor to define conversation flows (like a flowchart)
- Drag-and-drop states, define transitions
- Auto-generates the state machine or prompt constraints
- Could show real conversation traces overlaid on the flow

**Pros:**
- Non-technical users can modify flows
- Visual debugging - see where conversations went wrong
- Self-documenting

**Cons:**
- Significant UI development effort
- Still need the underlying engine (Option 2)
- May oversimplify complex conversations

**Verdict:** Nice-to-have on top of Option 2, but not the core solution.

---

## Option 4: Structured Output with Validation

**How it works:**
- Instead of just `{reply, actions}`, LLM also outputs `{current_step, next_step, skipped_checks}`
- Backend validates: "You said next_step is PAYMENT but customer.name is empty - rejected"
- Force regeneration with explicit error feedback

**Pros:**
- Keeps conversational flexibility
- Adds guardrails without full state machine
- LLM learns from rejection feedback

**Cons:**
- Still probabilistic (might keep failing)
- Regeneration adds latency
- Complex validation logic

**Verdict:** Good middle ground, but can get messy.

---

## Option 5: Hybrid - Soft State Machine

**How it works:**
- Define "checkpoints" rather than strict states
- Before responding, code checks: "What info do we have? What's missing?"
- Inject a **dynamic instruction** into the prompt: "You have: name, phone. You need: nothing - proceed to payment."
- LLM still generates naturally but gets explicit, current-state guidance

**Example injection:**
```
CURRENT STATUS:
- Customer name: Herbert ✓
- Customer phone: 732-813-9409 ✓
- Customer email: herbert@email.com ✓
- Order type: pickup ✓
- Items: 2 ✓

NEXT STEP: Offer payment options. DO NOT ask for name/phone/email.
```

**Pros:**
- Minimal architecture change
- Very explicit guidance reduces LLM confusion
- Still conversational
- Easy to implement incrementally

**Cons:**
- Still relies on LLM following instructions
- More token usage per request

**Verdict:** Quick win. Could implement today.

---

## My Recommendation

**Short-term (this week):** Option 5 - Hybrid/Dynamic Instructions
- Add a function that analyzes ORDER STATE and generates explicit "what you have / what you need / what to do next" instructions
- Inject this at the top of every prompt
- Much harder for LLM to ignore explicit "DO NOT ask for X - you already have it"

**Medium-term (next month):** Option 2 - State Machine
- Build a proper flow engine that controls conversation state
- LLM becomes a "language generator" within controlled states
- Eliminates entire categories of flow bugs

**Long-term (if needed):** Option 3 - Flow UI
- Visual editor for defining and debugging flows
- Useful once you have multiple different order flows or clients

---

## Quick Win Implementation

For Option 5, we'd add something like this before calling the LLM:

```python
def generate_flow_guidance(order_state: dict, caller_id: str) -> str:
    """Generate explicit guidance about what to do next."""
    customer = order_state.get("customer", {})
    items = order_state.get("items", [])
    order_type = order_state.get("order_type")
    payment_status = order_state.get("payment_status")

    lines = ["CURRENT ORDER STATUS:"]

    # What we have
    if customer.get("name"):
        lines.append(f"  ✓ Customer name: {customer['name']} - DO NOT ASK")
    else:
        lines.append(f"  ✗ Customer name: MISSING - need to collect")

    if customer.get("phone"):
        lines.append(f"  ✓ Customer phone: {customer['phone'][-4:]} - DO NOT ASK")
    else:
        lines.append(f"  ✗ Customer phone: MISSING - need to collect")

    # ... etc for email, order_type, payment

    # Explicit next step
    if not items:
        lines.append("\nNEXT: Take their order")
    elif not order_type:
        lines.append("\nNEXT: Ask pickup or delivery")
    elif not customer.get("name"):
        lines.append("\nNEXT: Ask for name")
    elif not payment_status:
        lines.append("\nNEXT: Offer payment options")
    else:
        lines.append("\nNEXT: Confirm order with confirm_order intent")

    return "\n".join(lines)
```

This gets injected right before the user's message in the prompt, making it impossible to miss.

---

## Questions for You

1. How important is "conversational flexibility" vs "predictable flow"?
2. Are there other flows beyond ordering (e.g., checking order status, complaints)?
3. Would you want to define different flows for different scenarios?
4. What's your tolerance for development time vs quick fixes?
