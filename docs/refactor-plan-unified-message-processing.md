# Refactoring Plan: Unified Message Processing

## Problem Statement

The codebase has three endpoints that process chat messages:
1. `main.py` - `/api/chat/message` (non-streaming web)
2. `main.py` - `/api/chat/message/stream` (streaming web)
3. `voice_vapi.py` - `/vapi/chat/completions` (voice)

Each duplicates the same post-processing logic:
- Session loading/saving
- Customer lookup
- Order persistence
- Analytics logging
- Payment link emails

This duplication caused bugs (analytics not logged in one path) and makes maintenance difficult.

## Goal

Move all shared logic into a single `MessageProcessor` class. Endpoints become thin wrappers that only handle request/response format differences.

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ENDPOINTS                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ /chat/message│  │/chat/stream  │  │/vapi/chat/completions│  │
│  │   (web)      │  │   (web)      │  │      (voice)         │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         │  Parse request, │  Parse request,      │ Parse VAPI   │
│         │  format response│  handle streaming    │ format       │
└─────────┼─────────────────┼──────────────────────┼──────────────┘
          │                 │                      │
          ▼                 ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MessageProcessor                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ process(context) -> result                                  │ │
│  │   1. Load/create session                                    │ │
│  │   2. Lookup returning customer                              │ │
│  │   3. Call state machine (via integration layer)             │ │
│  │   4. Persist confirmed order                                │ │
│  │   5. Log analytics                                          │ │
│  │   6. Send payment email (if applicable)                     │ │
│  │   7. Save session                                           │ │
│  │   8. Return unified result                                  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│              State Machine (unchanged)                           │
│  OrderStateMachine.process() -> StateMachineResult              │
└─────────────────────────────────────────────────────────────────┘
```

## New Module: `sandwich_bot/message_processor.py`

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

@dataclass
class ProcessingContext:
    """Input context for message processing."""
    user_message: str
    session_id: str
    db: Session

    # Optional context
    caller_id: Optional[str] = None
    store_id: Optional[str] = None

    # For streaming (callback to yield tokens)
    token_callback: Optional[Callable[[str], None]] = None


@dataclass
class ProcessingResult:
    """Output from message processing."""
    reply: str
    order_state: Dict[str, Any]
    actions: List[Dict[str, Any]]

    # Session data for response
    history: List[Dict[str, str]] = field(default_factory=list)

    # Status flags
    order_persisted: bool = False
    analytics_logged: bool = False
    payment_email_sent: bool = False

    # For backward compatibility
    primary_intent: str = "unknown"
    primary_slots: Dict[str, Any] = field(default_factory=dict)


class MessageProcessor:
    """
    Unified message processing for all endpoints.

    Handles the complete lifecycle:
    - Session management
    - Customer lookup
    - State machine processing
    - Order persistence
    - Analytics logging
    - Payment emails
    """

    def __init__(self, db: Session):
        self.db = db
        self._menu_index = None
        self._store_info = None

    def process(self, ctx: ProcessingContext) -> ProcessingResult:
        """Process a message and return the result."""

        # 1. Load or create session
        session = self._load_or_create_session(ctx.session_id, ctx.caller_id, ctx.store_id)

        # 2. Get returning customer info
        returning_customer = self._get_returning_customer(session, ctx.caller_id)

        # 3. Build context for state machine
        history = session.get("history", [])
        order_state = session.get("order", {})

        # 4. Process through state machine
        reply, updated_order_state, actions = self._call_state_machine(
            ctx.user_message, order_state, history, ctx.session_id, returning_customer
        )

        # 5. Update history
        history.append({"role": "user", "content": ctx.user_message})
        history.append({"role": "assistant", "content": reply})

        # 6. Handle confirmed order
        order_persisted = False
        analytics_logged = False
        payment_sent = False

        if self._is_order_confirmed(updated_order_state):
            order_persisted = self._persist_order(updated_order_state, session)
            analytics_logged = self._log_analytics(ctx, updated_order_state, history, reply)
            payment_sent = self._send_payment_email(updated_order_state, session)

        # 7. Save session
        session["history"] = history
        session["order"] = updated_order_state
        self._save_session(ctx.session_id, session)

        # 8. Build result
        return ProcessingResult(
            reply=reply,
            order_state=updated_order_state,
            actions=actions,
            history=history,
            order_persisted=order_persisted,
            analytics_logged=analytics_logged,
            payment_email_sent=payment_sent,
            primary_intent=actions[0].get("intent", "unknown") if actions else "unknown",
            primary_slots=actions[0].get("slots", {}) if actions else {},
        )

    # ... private methods for each step
```

## Refactored Endpoints

### Web Chat (non-streaming)

```python
@app.post("/api/chat/message")
def chat_message(req: ChatRequest, db: Session = Depends(get_db)):
    processor = MessageProcessor(db)

    ctx = ProcessingContext(
        user_message=req.message,
        session_id=req.session_id,
        db=db,
        caller_id=req.caller_id,
    )

    result = processor.process(ctx)

    return {
        "reply": result.reply,
        "order_state": result.order_state,
        "intent": result.primary_intent,
        "slots": result.primary_slots,
        "actions": result.actions,
    }
```

### Web Chat (streaming)

```python
@app.post("/api/chat/message/stream")
def chat_message_stream(req: ChatRequest, db: Session = Depends(get_db)):
    processor = MessageProcessor(db)

    def generate():
        # For streaming, we process first then stream the reply
        ctx = ProcessingContext(
            user_message=req.message,
            session_id=req.session_id,
            db=db,
            caller_id=req.caller_id,
        )

        result = processor.process(ctx)

        # Stream tokens
        for word in result.reply.split():
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"

        # Final result
        yield f"data: {json.dumps({'done': True, 'reply': result.reply, ...})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### VAPI Voice

```python
@app.post("/vapi/chat/completions")
def vapi_chat(request: Request, db: Session = Depends(get_db)):
    body = await request.json()

    # Parse VAPI format
    user_message = extract_last_user_message(body["messages"])
    call_id = body["call"]["id"]
    phone_number = body["call"]["customer"]["number"]

    processor = MessageProcessor(db)

    ctx = ProcessingContext(
        user_message=user_message,
        session_id=call_id,
        db=db,
        caller_id=phone_number,
    )

    result = processor.process(ctx)

    # Format as OpenAI-compatible response
    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result.reply},
            "finish_reason": "stop"
        }]
    }
```

## Migration Steps

### Phase 1: Create MessageProcessor (Low Risk)
1. Create `sandwich_bot/message_processor.py` with the new class
2. Extract helper methods from `main.py`:
   - `_load_or_create_session()`
   - `_get_returning_customer()` (rename from `_lookup_customer_by_phone`)
   - `_persist_order()` (extract from inline code)
   - `_log_analytics()` (extract from inline code)
   - `_save_session()` (use existing `save_session`)
3. Write tests for `MessageProcessor` in isolation

### Phase 2: Migrate Non-Streaming Web Endpoint
1. Update `/api/chat/message` to use `MessageProcessor`
2. Keep old code commented out temporarily
3. Test thoroughly
4. Remove old code

### Phase 3: Migrate Streaming Web Endpoint
1. Update `/api/chat/message/stream` to use `MessageProcessor`
2. Handle streaming-specific logic (token yielding) in endpoint
3. Test thoroughly

### Phase 4: Migrate VAPI Endpoint
1. Update `/vapi/chat/completions` to use `MessageProcessor`
2. Keep VAPI-specific format handling in endpoint
3. Test with actual VAPI calls

### Phase 5: Cleanup
1. Remove duplicated helper functions from `main.py` and `voice_vapi.py`
2. Remove `chains/integration.py` if fully superseded
3. Update imports across codebase

## What Stays in Endpoints

Each endpoint still handles:
- **Request parsing**: Different input formats (JSON vs VAPI)
- **Response formatting**: Different output formats
- **Streaming**: Web streaming is endpoint-specific
- **VAPI metadata**: Call recording, transcripts, etc.
- **Rate limiting**: May differ per endpoint
- **Authentication**: May differ per endpoint

## Benefits

1. **Single source of truth** for order processing logic
2. **Bugs fixed once** apply everywhere
3. **Easier testing** - test MessageProcessor in isolation
4. **Clearer separation** - endpoints handle HTTP, processor handles business logic
5. **Easier to add new endpoints** - just wrap MessageProcessor

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing behavior | Migrate one endpoint at a time, keep old code until verified |
| Streaming complexity | Keep streaming logic in endpoint, processor just returns result |
| VAPI-specific features | Document what stays in VAPI endpoint |
| Database transaction scope | Ensure processor works with passed-in db session |

## Open Questions

1. Should `MessageProcessor` be a class or module with functions?
2. How to handle the streaming case where we want to stream tokens as they're generated (true LLM streaming)?
3. Should we keep the integration layer (`chains/integration.py`) or fold it into MessageProcessor?
