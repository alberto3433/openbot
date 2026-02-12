"""
Email service for sending payment links.

Sends real emails via SMTP when configured, falls back to logging in mock mode.

Environment variables:
- SMTP_HOST: SMTP server hostname (e.g., smtp.gmail.com)
- SMTP_PORT: SMTP server port (default: 587 for TLS)
- SMTP_USERNAME: SMTP authentication username
- SMTP_PASSWORD: SMTP authentication password (for Gmail, use App Password)
- SMTP_FROM_EMAIL: Sender email address
"""

import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)

# SMTP configuration from environment
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")


def is_email_configured() -> bool:
    """Check if SMTP is properly configured."""
    return all([SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL])


def send_payment_link_email(
    to_email: str,
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    order_type: Optional[str] = None,
    items: Optional[list] = None,
    subtotal: Optional[float] = None,
    city_tax: Optional[float] = None,
    state_tax: Optional[float] = None,
    delivery_fee: Optional[float] = None,
    payment_url: Optional[str] = None,
) -> dict:
    """
    Send an email with a payment link to the customer.

    Args:
        to_email: Customer's email address
        order_id: The order ID for reference
        amount: The amount to charge (total)
        store_name: Name of the store for the message
        customer_name: Optional customer name for personalization
        customer_phone: Optional customer phone number
        order_type: Optional order type (pickup/delivery)
        items: Optional list of order items
        subtotal: Optional subtotal before tax
        city_tax: Optional city tax amount (only shown if > 0)
        state_tax: Optional state tax amount (only shown if > 0)
        delivery_fee: Optional delivery fee (only shown if > 0)
        payment_url: Optional Stripe checkout URL. Falls back to mock URL if not provided.

    Returns:
        dict with status and details
    """
    # Use provided Stripe URL or fall back to mock URL
    if not payment_url:
        payment_url = f"https://pay.example.com/order/{order_id}"

    # Build the email content
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

    # Build order details section
    order_details_text = ""
    order_details_html = ""

    if customer_name or customer_phone or order_type:
        order_details_text = "\nOrder Details:\n"
        order_details_html = "<h3 style='margin: 16px 0 8px 0; font-size: 16px;'>Order Details</h3>"
        order_details_html += "<table style='border-collapse: collapse; width: 100%; max-width: 400px;'>"

        if customer_name:
            order_details_text += f"  Name: {customer_name}\n"
            order_details_html += f"<tr><td style='padding: 4px 8px; color: #666;'>Name:</td><td style='padding: 4px 8px;'>{customer_name}</td></tr>"
        if customer_phone:
            order_details_text += f"  Phone: {customer_phone}\n"
            order_details_html += f"<tr><td style='padding: 4px 8px; color: #666;'>Phone:</td><td style='padding: 4px 8px;'>{customer_phone}</td></tr>"
        if order_type:
            order_details_text += f"  Order Type: {order_type.title()}\n"
            order_details_html += f"<tr><td style='padding: 4px 8px; color: #666;'>Order Type:</td><td style='padding: 4px 8px;'>{order_type.title()}</td></tr>"

        order_details_html += "</table>"

    # Build items section
    items_text = ""
    items_html = ""

    if items:
        items_text = "\nItems:\n"
        items_html = "<h3 style='margin: 16px 0 8px 0; font-size: 16px;'>Items</h3>"
        items_html += "<table style='border-collapse: collapse; width: 100%; max-width: 500px; border: 1px solid #eee;'>"
        items_html += "<tr style='background: #f5f5f5;'><th style='padding: 8px; text-align: left; border-bottom: 1px solid #ddd;'>Item</th><th style='padding: 8px; text-align: left; border-bottom: 1px solid #ddd;'>Details</th><th style='padding: 8px; text-align: right; border-bottom: 1px solid #ddd;'>Price</th></tr>"

        for item in items:
            # Use pre-computed display fields from adapter (data-driven)
            item_name = item.get("display_name") or item.get("menu_item_name", "Item")
            quantity = item.get("quantity", 1)
            line_total = item.get("line_total", 0)
            base_price = item.get("base_price") or item.get("unit_price") or line_total

            # Get pre-computed modifiers list from adapter
            modifiers = item.get("modifiers") or []

            # Separate priced modifiers (shown as line items) from free ones (shown as details)
            priced_modifiers = [m for m in modifiers if m.get("price", 0) > 0]
            free_modifiers = [m.get("name", "") for m in modifiers if m.get("price", 0) == 0 and m.get("name")]

            # Combine with any explicit free_details from adapter
            free_details = list(item.get("free_details") or []) + free_modifiers
            details_str = ", ".join(free_details) if free_details else ""

            if priced_modifiers:
                # Itemized display: show base item, then free details, then priced modifiers
                free_details_str = " • ".join(free_details) if free_details else ""

                # Plain text - show base item, then free details, then priced modifiers
                items_text += f"  {quantity}x {item_name} - ${base_price:.2f}\n"
                if free_details_str:
                    items_text += f"    {free_details_str}\n"
                for mod in priced_modifiers:
                    mod_price = mod.get("price", 0)
                    items_text += f"    + {mod['name']} ${mod_price:.2f}\n"

                # HTML - show base item row, free details, then priced modifier rows
                items_html += f"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'>{quantity}x {item_name}</td>"
                items_html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; color: #666; font-size: 13px;'>{free_details_str}</td>"
                items_html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right;'>${base_price:.2f}</td></tr>"
                for mod in priced_modifiers:
                    mod_price = mod.get("price", 0)
                    items_html += f"<tr><td style='padding: 8px 8px 8px 24px; border-bottom: 1px solid #eee; color: #666;'>+ {mod['name']}</td>"
                    items_html += f"<td style='padding: 8px; border-bottom: 1px solid #eee;'></td>"
                    items_html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right; color: #666;'>${mod_price:.2f}</td></tr>"
            else:
                # Standard item display (no priced modifiers)
                # Plain text
                items_text += f"  {quantity}x {item_name}"
                if details_str:
                    items_text += f" ({details_str})"
                items_text += f" - ${line_total:.2f}\n"

                # HTML
                items_html += f"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'>{quantity}x {item_name}</td>"
                items_html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; color: #666; font-size: 13px;'>{details_str}</td>"
                items_html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right;'>${line_total:.2f}</td></tr>"

        # Build totals section
        # Subtotal row (if provided)
        if subtotal is not None:
            items_html += f"<tr><td colspan='2' style='padding: 8px; text-align: right; border-top: 1px solid #ddd;'>Subtotal:</td><td style='padding: 8px; text-align: right; border-top: 1px solid #ddd;'>${subtotal:.2f}</td></tr>"
            items_text += f"\nSubtotal: ${subtotal:.2f}\n"

            # Tax rows (only show non-zero taxes)
            if city_tax and city_tax > 0 and state_tax and state_tax > 0:
                # Both taxes - show breakdown
                items_html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>City Tax:</td><td style='padding: 8px; text-align: right;'>${city_tax:.2f}</td></tr>"
                items_html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>State Tax:</td><td style='padding: 8px; text-align: right;'>${state_tax:.2f}</td></tr>"
                items_text += f"City Tax: ${city_tax:.2f}\n"
                items_text += f"State Tax: ${state_tax:.2f}\n"
            elif city_tax and city_tax > 0:
                # Only city tax
                items_html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>Tax:</td><td style='padding: 8px; text-align: right;'>${city_tax:.2f}</td></tr>"
                items_text += f"Tax: ${city_tax:.2f}\n"
            elif state_tax and state_tax > 0:
                # Only state tax
                items_html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>Tax:</td><td style='padding: 8px; text-align: right;'>${state_tax:.2f}</td></tr>"
                items_text += f"Tax: ${state_tax:.2f}\n"

            # Delivery fee (only show if > 0)
            if delivery_fee and delivery_fee > 0:
                items_html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>Delivery Fee:</td><td style='padding: 8px; text-align: right;'>${delivery_fee:.2f}</td></tr>"
                items_text += f"Delivery Fee: ${delivery_fee:.2f}\n"

        # Total row
        items_html += f"<tr style='background: #f9f9f9;'><td colspan='2' style='padding: 8px; text-align: right;'><strong>Total:</strong></td><td style='padding: 8px; text-align: right;'><strong>${amount:.2f}</strong></td></tr>"
        items_html += "</table>"
        items_text += f"Total: ${amount:.2f}\n"

    subject = f"Payment Link for Your {store_name} Order #{order_id}"

    body_text = f"""{greeting}

Thank you for your order at {store_name}!
{order_details_text}{items_text}
Click here to complete your payment:
{payment_url}

If you have any questions, please call us.

Thanks,
{store_name}
"""

    body_html = f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
<p>{greeting}</p>
<p>Thank you for your order at <strong>{store_name}</strong>!</p>
{order_details_html}
{items_html}
<p style="margin-top: 24px;"><a href="{payment_url}" style="background-color: #1976d2; color: white; padding: 14px 28px; text-decoration: none; display: inline-block; border-radius: 4px; font-weight: 500;">Complete Payment - ${amount:.2f}</a></p>
<p style="color: #666; font-size: 13px;">Or copy this link: {payment_url}</p>
<p>If you have any questions, please call us.</p>
<p>Thanks,<br><strong>{store_name}</strong></p>
</body>
</html>
"""

    if not is_email_configured():
        # Mock mode - just log the email
        logger.info(
            "MOCK EMAIL to %s: Subject: %s | Body: %s",
            to_email,
            subject,
            body_text[:200] + "..."
        )
        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "payment_url": payment_url,
            "mock": True,
            "message": "Email logged (SMTP not configured)",
        }

    # Send real email via SMTP
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = to_email

        # Attach both plain text and HTML versions
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Connect and send with secure SSL context
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())

        logger.info("Email sent successfully to %s for order %d", to_email, order_id)

        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "payment_url": payment_url,
            "mock": False,
            "message": "Email sent successfully",
        }

    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, str(e))
        return {
            "status": "error",
            "to_email": to_email,
            "error": str(e),
            "mock": False,
            "message": f"Failed to send email: {str(e)}",
        }


