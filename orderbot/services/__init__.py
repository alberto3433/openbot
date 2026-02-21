"""
Services Package for Orderbot
=================================

This package contains service modules that encapsulate business logic and
infrastructure concerns.

Available Services:
-------------------
- **session**: Session cache management with database persistence
- **order**: Order persistence functions (pending and confirmed orders)
- **order_lifecycle**: Order status transitions and lifecycle management
- **payment_service**: Payment URL creation (Stripe/Square) and receipts
- **customer_service**: Customer lookup by phone and order history
- **store_service**: Store info lookup, caching, and warming
- **address_service**: Address completion and geocoding
- **email_service**: Email sending via AWS SES
- **notification_service**: Customer notification dispatcher
- **sms_service**: SMS sending via AWS SNS
- **stripe_service**: Stripe payment integration
- **tts**: Text-to-speech provider abstraction
- **vapi_session**: Voice session management for Vapi integration
"""
