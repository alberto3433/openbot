# Vapi.ai Voice Integration

This document describes the architecture and setup for integrating Vapi.ai with the Sandwich Bot, enabling customers to place orders via phone calls.

## Overview

[Vapi.ai](https://vapi.ai) is a voice AI platform that handles:
- Phone number provisioning
- Speech-to-Text (STT) transcription
- Text-to-Speech (TTS) synthesis
- Call management and routing

Our integration uses Vapi's **Custom LLM** feature, which sends transcribed speech to our server and expects responses in OpenAI-compatible format.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              VAPI.AI                                     │
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │   Twilio     │    │     STT      │    │      Custom LLM          │  │
│  │  Phone #     │───▶│  (Deepgram)  │───▶│      Integration         │  │
│  │              │    │              │    │                          │  │
│  │  Receives    │    │  Transcribes │    │  POST to your server     │  │
│  │  calls       │    │  speech      │    │  with OpenAI format      │  │
│  └──────────────┘    └──────────────┘    └────────────┬─────────────┘  │
│                                                       │                 │
│  ┌──────────────┐    ┌──────────────┐                │                 │
│  │     TTS      │    │   Response   │                │                 │
│  │  (ElevenLabs │◀───│   Handler    │◀───────────────┘                 │
│  │   or OpenAI) │    │              │                                   │
│  │              │    │  Streams     │    OpenAI-compatible response     │
│  │  Speaks to   │    │  response    │                                   │
│  │  caller      │    │  to TTS      │                                   │
│  └──────────────┘    └──────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTPS POST
                                │ /voice/vapi/chat/completions
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         YOUR SERVER                                      │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    voice_vapi.py                                  │   │
│  │                                                                   │   │
│  │  1. Receive OpenAI-format request from Vapi                      │   │
│  │  2. Extract phone number from call.customer.number               │   │
│  │  3. Map phone → session (create if new caller)                   │   │
│  │  4. Extract user message from messages array                     │   │
│  │  5. Call existing bot logic (call_sandwich_bot)                  │   │
│  │  6. Apply order state changes                                    │   │
│  │  7. Return OpenAI-format response (streaming SSE)                │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│                              ▼                                           │
│  ┌────────────────┐  ┌───────────────┐  ┌────────────────────────────┐ │
│  │  Phone-Session │  │  Bot Logic    │  │     Database               │ │
│  │  Mapping       │  │  (existing)   │  │     (existing)             │ │
│  │                │  │               │  │                            │ │
│  │  Maps caller   │  │  llm_client   │  │  - ChatSession             │ │
│  │  phone to      │  │  order_logic  │  │  - Orders                  │ │
│  │  session_id    │  │  menu_index   │  │  - Menu                    │ │
│  └────────────────┘  └───────────────┘  └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Incoming Call

```
Customer dials phone number
        │
        ▼
Vapi answers and plays greeting (from assistant config)
        │
        ▼
Customer speaks: "I'd like a turkey club"
        │
        ▼
Vapi transcribes via Deepgram STT
        │
        ▼
Vapi POSTs to /voice/vapi/chat/completions
```

### 2. Request Processing

**Vapi sends:**
```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant..."},
    {"role": "assistant", "content": "Hi, welcome to Sammy's Subs!"},
    {"role": "user", "content": "I'd like a turkey club"}
  ],
  "stream": true,
  "call": {
    "id": "call_abc123",
    "customer": {
      "number": "+19083077148"
    }
  }
}
```

**Our server:**
1. Extracts phone number: `+19083077148`
2. Looks up or creates session for this phone
3. Gets latest user message: `"I'd like a turkey club"`
4. Calls `call_sandwich_bot()` with conversation history
5. Applies resulting actions to order state
6. Returns streaming response

**Server returns (SSE):**
```
data: {"id":"chatcmpl-abc","choices":[{"delta":{"content":"Great"}}]}

data: {"id":"chatcmpl-abc","choices":[{"delta":{"content":" choice"}}]}

data: {"id":"chatcmpl-abc","choices":[{"delta":{"content":"!"}}]}

data: {"id":"chatcmpl-abc","choices":[{"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### 3. Response to Caller

```
Vapi receives streamed response
        │
        ▼
Vapi sends text to TTS (ElevenLabs/OpenAI)
        │
        ▼
Audio streamed back to caller
        │
        ▼
Customer hears: "Great choice! Would you like that toasted?"
```

## Endpoints

### `POST /voice/vapi/chat/completions`

Main endpoint for Vapi Custom LLM integration.

- **Input:** OpenAI-compatible chat completion request
- **Output:** OpenAI-compatible response (streaming or non-streaming)
- **Authentication:** None (Vapi handles call authentication)

### `POST /voice/vapi/webhook`

Optional webhook for Vapi server events.

Receives:
- `end-of-call-report` - Call summary, transcript, duration
- `status-update` - Call status changes
- `hang` - Warning when assistant is slow to respond

### `GET /voice/vapi/health`

Health check for Vapi to verify server availability.

## Session Management

### Phone-to-Session Mapping

Sessions are mapped by phone number with a 30-minute TTL:

```python
_phone_sessions = {
    "+19083077148": {
        "session_id": "uuid-...",
        "last_access": 1702847123.45,
        "store_id": "store_nb_002",
        "session_data": {...}
    }
}
```

**Benefits:**
- Returning callers resume their session within 30 minutes
- Customer info (name, phone) persists across calls
- Order state maintained if caller hangs up and calls back

### Session Lifecycle

```
New Call from +1908...
        │
        ▼
Check _phone_sessions for existing session
        │
        ├─── Found & not expired ───▶ Resume session
        │
        └─── Not found ───▶ Create new session
                                │
                                ├── Check for returning customer (past orders)
                                │
                                ├── Personalize greeting if known
                                │
                                └── Save to DB and cache
```

## Setup Instructions

### 1. Sign Up for Vapi

1. Go to [vapi.ai](https://vapi.ai) and create an account
2. You get $10 free credit (~100 minutes of calls)

### 2. Configure Your Server

Add optional environment variables to `.env`:

```bash
# Optional: Webhook authentication secret
VAPI_SECRET_KEY=your-secret-key

# Session TTL for phone mapping (default 30 minutes)
VAPI_SESSION_TTL=1800
```

### 3. Expose Your Server

For development, use ngrok to expose your local server:

```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)

### 4. Create Vapi Assistant

In Vapi Dashboard:

1. **Create New Assistant**
   - Name: "Sammy's Subs Order Bot"

2. **Model Configuration**
   - Provider: Custom LLM
   - URL: `https://your-server.com/voice/vapi/chat/completions`
   - (Or ngrok URL for testing)

3. **Voice Configuration**
   - Provider: ElevenLabs or OpenAI
   - Voice: Choose a friendly voice
   - Speed: 1.0

4. **First Message** (optional - our server provides greeting):
   - Leave empty to use server-generated greeting

5. **Server URL** (optional - for webhooks):
   - URL: `https://your-server.com/voice/vapi/webhook`
   - Events: `end-of-call-report`, `hang`

### 5. Get a Phone Number

In Vapi Dashboard:

1. Go to Phone Numbers
2. Buy a number (~$2/month)
3. Assign your assistant to the number

### 6. Test

1. **Web Test:** Use Vapi's built-in web caller (no phone needed)
2. **Phone Test:** Call your Vapi number

## Configuration Options

### Store Selection

Pass store_id via assistant metadata in Vapi:

```json
{
  "metadata": {
    "store_id": "store_nb_002"
  }
}
```

This routes the call to the correct store's menu and availability.

### Multiple Assistants

For multi-location setups, create one Vapi assistant per store:

- Sammy's East Brunswick: `store_id: store_eb_001`
- Sammy's New Brunswick: `store_id: store_nb_002`
- Sammy's Princeton: `store_id: store_pr_003`

Each can have its own phone number.

## Cost Estimates

| Component | Cost |
|-----------|------|
| Vapi Platform | ~$0.05/min |
| Vapi STT (Deepgram) | Included |
| Vapi TTS (OpenAI/ElevenLabs) | ~$0.01-0.02/min |
| Your OpenAI API | ~$0.01-0.03/min |
| Phone Number | ~$2/month |
| **Total per minute** | **~$0.08-0.12/min** |

For a typical 3-minute order call: **~$0.25-0.35 per order**

## Monitoring

### Logs

Voice sessions are logged with `[Voice]` prefix:

```
INFO: Created new voice session for phone ...7148 (session: abc123, store: store_nb_002)
INFO: Voice message from ...7148: I'd like a turkey club
INFO: Voice reply to ...7148: Great choice! Would you like...
```

### Vapi Dashboard

Monitor in Vapi Dashboard:
- Call logs and recordings
- Transcripts
- Latency metrics
- Error rates

### End-of-Call Webhooks

The `/voice/vapi/webhook` endpoint receives call summaries:

```json
{
  "message": {
    "type": "end-of-call-report",
    "endedReason": "hangup",
    "call": {"id": "...", "duration": 180},
    "artifact": {
      "transcript": "AI: Hi, welcome... User: I'd like..."
    }
  }
}
```

## Troubleshooting

### "No phone number in request"

Vapi isn't sending the call object. Check:
1. You're using Custom LLM (not Server URL)
2. The assistant is configured correctly

### Slow Responses / "hang" Webhooks

Vapi expects responses within ~5 seconds. If you see "hang" webhooks:
1. Check LLM latency (OpenAI API response time)
2. Consider using streaming (already enabled)
3. Simplify system prompt if too long

### Session Not Persisting

Check:
1. Phone number format is consistent
2. Session TTL hasn't expired (default 30 min)
3. Database is accessible

### Caller Not Recognized as Returning

The system looks up past orders by phone number. Ensure:
1. Previous orders have `customer_phone` saved
2. Phone format matches (system normalizes +1, dashes, etc.)

## Files

| File | Purpose |
|------|---------|
| `sandwich_bot/voice_vapi.py` | Vapi integration adapter |
| `sandwich_bot/main.py` | Includes vapi_router |
| `VAPI_INTEGRATION.md` | This documentation |

## What's NOT Changed

The Vapi integration is purely additive. These remain unchanged:

- Web chat UI (`index.html`)
- Chat API endpoints (`/chat/start`, `/chat/message`)
- Order logic (`order_logic.py`)
- LLM client (`llm_client.py`)
- Database models (`models.py`)
- All existing tests

## Future Enhancements

1. **Outbound Calls** - "Your order is ready" notifications
2. **Call Transfer** - Transfer to human if bot can't help
3. **Multi-language** - Spanish support via Vapi language detection
4. **Call Recording Storage** - Save recordings to S3
5. **Analytics Dashboard** - Voice order metrics
