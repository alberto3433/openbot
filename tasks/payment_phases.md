# Payment Flow Improvement Phases

## Phase 1: Payment Link in Chatbot + Smart Email (CURRENT)
- Show Stripe payment link directly in the chatbot after order confirmation
- If user pays via chatbot link → email becomes a receipt ("Your order is paid")
- If user doesn't pay in chat → email has the payment link as fallback
- Requires rethinking email timing (delay or send receipt on Stripe webhook)

## Phase 2: Configurable Payment Processor
- Add `payment_processor` field to Company model ("stripe", "square", "none")
- Admin UI dropdown on company page to select processor
- Abstract payment interface so Stripe and Square are interchangeable
- Store per-company credentials (Square OAuth tokens, Stripe keys)

## Phase 3: Square Checkout Integration
- Build Square Checkout API integration behind the payment abstraction
- Square payment link generation
- Square payment webhooks for confirmation
- Square payment status tracking on orders
- Both Stripe and Square fully interchangeable per-company
