# VAPI Configuration for App Runner Deployment

## URLs to Configure in VAPI

### 1. Custom LLM URL (Already Configured)
```
https://8mtpznn4nh.us-east-1.awsapprunner.com/voice/vapi/chat/completions
```

### 2. Server/Webhook URL (NEW - Required for Analytics)
```
https://8mtpznn4nh.us-east-1.awsapprunner.com/voice/vapi/webhook
```

---

## How to Set the Server URL in VAPI Dashboard

### Option A: Set at Organization Level (Recommended - Easiest)

1. Go to **https://dashboard.vapi.ai/vapi-api**
2. Find the Server URL field
3. Enter: `https://8mtpznn4nh.us-east-1.awsapprunner.com/voice/vapi/webhook`
4. Save

This will apply to all assistants that don't have their own server URL set.

### Option B: Set at Assistant Level

1. Go to https://dashboard.vapi.ai/assistants
2. Click on your assistant (the one using the Custom LLM)
3. Click the **"Advanced"** tab
4. Look for **"Server URL"** or **"Server"** section
5. Enter: `https://8mtpznn4nh.us-east-1.awsapprunner.com/voice/vapi/webhook`
6. Save

**Note:** Some users report the Server URL field not appearing in the Advanced tab. If this happens, use Option A or Option C.

### Option C: Set via VAPI API (If UI options don't work)

If you can't find the Server URL field in the dashboard, you can set it via the API:

```bash
curl -X PATCH https://api.vapi.ai/assistant/YOUR_ASSISTANT_ID \
  -H "Authorization: Bearer YOUR_VAPI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "server": {
      "url": "https://8mtpznn4nh.us-east-1.awsapprunner.com/voice/vapi/webhook"
    }
  }'
```

Replace `YOUR_ASSISTANT_ID` with your assistant's ID (found in the dashboard URL when viewing the assistant) and `YOUR_VAPI_API_KEY` with your VAPI API key.

---

## What Each URL Does

- **Custom LLM URL**: Handles the conversation - receives transcribed speech and returns bot responses
- **Server/Webhook URL**: Receives call events (call started, call ended, etc.) - used for analytics tracking

## Analytics Data Captured from Voice Calls

When a call ends, the webhook saves:
- Session ID and duration
- Message count
- Items in cart and cart total
- Order status (completed vs abandoned)
- End reason (customer hangup, silence timeout, etc.)
- Full conversation history
- Customer phone number
- Store ID
