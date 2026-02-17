"""
Email service for sending payment links.

Sends real emails via AWS SES when configured, falls back to logging in mock mode.

Environment variables:
- AWS_ACCESS_KEY_ID: AWS IAM access key
- AWS_SECRET_ACCESS_KEY: AWS IAM secret key
- AWS_REGION: AWS region (default: us-east-1)
- AWS_SES_FROM_EMAIL: Verified sender email address
"""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from .config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_SES_FROM_EMAIL

logger = logging.getLogger(__name__)

# Lazy-initialize SES client
_ses_client = None


def _get_ses_client():
    """Lazy-load and configure the AWS SES client."""
    global _ses_client
    if _ses_client is None:
        try:
            import boto3
            _ses_client = boto3.client(
                "ses",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION,
            )
        except ImportError:
            logger.warning("boto3 package not installed; email features disabled")
            return None
    return _ses_client


def is_email_configured() -> bool:
    """Check if AWS SES email is properly configured."""
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_SES_FROM_EMAIL)


def _build_order_details_section(
    customer_name: Optional[str],
    customer_phone: Optional[str],
    order_type: Optional[str],
) -> tuple[str, str]:
    """Build order details text and HTML sections. Returns (text, html)."""
    if not customer_name and not customer_phone and not order_type:
        return "", ""

    text = "\nOrder Details:\n"
    html = "<h3 style='margin: 16px 0 8px 0; font-size: 16px;'>Order Details</h3>"
    html += "<table style='border-collapse: collapse; width: 100%; max-width: 400px;'>"

    if customer_name:
        text += f"  Name: {customer_name}\n"
        html += f"<tr><td style='padding: 4px 8px; color: #666;'>Name:</td><td style='padding: 4px 8px;'>{customer_name}</td></tr>"
    if customer_phone:
        text += f"  Phone: {customer_phone}\n"
        html += f"<tr><td style='padding: 4px 8px; color: #666;'>Phone:</td><td style='padding: 4px 8px;'>{customer_phone}</td></tr>"
    if order_type:
        text += f"  Order Type: {order_type.title()}\n"
        html += f"<tr><td style='padding: 4px 8px; color: #666;'>Order Type:</td><td style='padding: 4px 8px;'>{order_type.title()}</td></tr>"

    html += "</table>"
    return text, html


def _build_items_section(
    items: list,
    subtotal: Optional[float],
    city_tax: Optional[float],
    state_tax: Optional[float],
    delivery_fee: Optional[float],
    amount: float,
) -> tuple[str, str]:
    """Build items list with totals as text and HTML. Returns (text, html)."""
    if not items:
        return "", ""

    text = "\nItems:\n"
    html = "<h3 style='margin: 16px 0 8px 0; font-size: 16px;'>Items</h3>"
    html += "<table style='border-collapse: collapse; width: 100%; max-width: 500px; border: 1px solid #eee;'>"
    html += "<tr style='background: #f5f5f5;'><th style='padding: 8px; text-align: left; border-bottom: 1px solid #ddd;'>Item</th><th style='padding: 8px; text-align: left; border-bottom: 1px solid #ddd;'>Details</th><th style='padding: 8px; text-align: right; border-bottom: 1px solid #ddd;'>Price</th></tr>"

    for item in items:
        item_name = item.get("display_name") or item.get("menu_item_name", "Item")
        quantity = item.get("quantity", 1)
        line_total = item.get("line_total", 0)
        base_price = item.get("base_price") or item.get("unit_price") or line_total

        modifiers = item.get("modifiers") or []
        priced_modifiers = [m for m in modifiers if m.get("price", 0) > 0]
        free_modifiers = [m.get("name", "") for m in modifiers if m.get("price", 0) == 0 and m.get("name")]
        free_details = list(item.get("free_details") or []) + free_modifiers
        details_str = ", ".join(free_details) if free_details else ""

        if priced_modifiers:
            free_details_str = " • ".join(free_details) if free_details else ""
            text += f"  {quantity}x {item_name} - ${base_price:.2f}\n"
            if free_details_str:
                text += f"    {free_details_str}\n"
            for mod in priced_modifiers:
                mod_price = mod.get("price", 0)
                text += f"    + {mod['name']} ${mod_price:.2f}\n"

            html += f"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'>{quantity}x {item_name}</td>"
            html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; color: #666; font-size: 13px;'>{free_details_str}</td>"
            html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right;'>${base_price:.2f}</td></tr>"
            for mod in priced_modifiers:
                mod_price = mod.get("price", 0)
                html += f"<tr><td style='padding: 8px 8px 8px 24px; border-bottom: 1px solid #eee; color: #666;'>+ {mod['name']}</td>"
                html += f"<td style='padding: 8px; border-bottom: 1px solid #eee;'></td>"
                html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right; color: #666;'>${mod_price:.2f}</td></tr>"
        else:
            text += f"  {quantity}x {item_name}"
            if details_str:
                text += f" ({details_str})"
            text += f" - ${line_total:.2f}\n"

            html += f"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'>{quantity}x {item_name}</td>"
            html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; color: #666; font-size: 13px;'>{details_str}</td>"
            html += f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right;'>${line_total:.2f}</td></tr>"

    # Build totals section
    if subtotal is not None:
        html += f"<tr><td colspan='2' style='padding: 8px; text-align: right; border-top: 1px solid #ddd;'>Subtotal:</td><td style='padding: 8px; text-align: right; border-top: 1px solid #ddd;'>${subtotal:.2f}</td></tr>"
        text += f"\nSubtotal: ${subtotal:.2f}\n"

        if city_tax and city_tax > 0 and state_tax and state_tax > 0:
            html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>City Tax:</td><td style='padding: 8px; text-align: right;'>${city_tax:.2f}</td></tr>"
            html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>State Tax:</td><td style='padding: 8px; text-align: right;'>${state_tax:.2f}</td></tr>"
            text += f"City Tax: ${city_tax:.2f}\n"
            text += f"State Tax: ${state_tax:.2f}\n"
        elif city_tax and city_tax > 0:
            html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>Tax:</td><td style='padding: 8px; text-align: right;'>${city_tax:.2f}</td></tr>"
            text += f"Tax: ${city_tax:.2f}\n"
        elif state_tax and state_tax > 0:
            html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>Tax:</td><td style='padding: 8px; text-align: right;'>${state_tax:.2f}</td></tr>"
            text += f"Tax: ${state_tax:.2f}\n"

        if delivery_fee and delivery_fee > 0:
            html += f"<tr><td colspan='2' style='padding: 8px; text-align: right;'>Delivery Fee:</td><td style='padding: 8px; text-align: right;'>${delivery_fee:.2f}</td></tr>"
            text += f"Delivery Fee: ${delivery_fee:.2f}\n"

    html += f"<tr style='background: #f9f9f9;'><td colspan='2' style='padding: 8px; text-align: right;'><strong>Total:</strong></td><td style='padding: 8px; text-align: right;'><strong>${amount:.2f}</strong></td></tr>"
    html += "</table>"
    text += f"Total: ${amount:.2f}\n"

    return text, html


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

    # Build order details and items sections
    order_details_text, order_details_html = _build_order_details_section(
        customer_name, customer_phone, order_type,
    )
    items_text, items_html = _build_items_section(
        items, subtotal, city_tax, state_tax, delivery_fee, amount,
    )

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
            "message": "Email logged (AWS SES not configured)",
        }

    # Send real email via AWS SES
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = AWS_SES_FROM_EMAIL
        msg["To"] = to_email

        # Attach both plain text and HTML versions
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        client = _get_ses_client()
        if client is None:
            return {
                "status": "error",
                "to_email": to_email,
                "error": "boto3 not installed",
                "mock": False,
                "message": "Failed to send email: boto3 not installed",
            }

        client.send_raw_email(
            Source=AWS_SES_FROM_EMAIL,
            Destinations=[to_email],
            RawMessage={"Data": msg.as_string()},
        )

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


def send_report_email(
    session_id: str,
    store_id: Optional[str] = None,
    caller_id: Optional[str] = None,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    recent_messages: Optional[List[dict]] = None,
    order_status: Optional[str] = None,
    item_count: int = 0,
    items: Optional[List[dict]] = None,
) -> dict:
    """
    Send a conversation report email to the review team.

    Args:
        session_id: UUID of the session being reported
        store_id: Store identifier
        caller_id: Caller ID / phone number used to start the session
        customer_name: Customer's name if available
        customer_phone: Customer's phone number if available
        recent_messages: Last N messages from conversation history
        order_status: Current order status
        item_count: Number of items in cart
        items: Cart items (adapter dict format with display_name, quantity, line_total, modifiers)

    Returns:
        dict with status and details
    """
    to_email = "info@zervio.ai"
    short_id = session_id[:8]
    subject = f"Conversation Report - Session {short_id}"

    # Build session details for plain text
    details_text = f"Session ID: {session_id}\n"
    if store_id:
        details_text += f"Store ID: {store_id}\n"
    if caller_id:
        details_text += f"Caller ID: {caller_id}\n"
    if customer_name:
        details_text += f"Customer Name: {customer_name}\n"
    if customer_phone:
        details_text += f"Customer Phone: {customer_phone}\n"
    if order_status:
        details_text += f"Order Status: {order_status}\n"
    details_text += f"Items in Cart: {item_count}\n"

    # Build cart items section
    cart_text = ""
    cart_html = ""
    if items:
        cart_text = "\nCart Contents:\n"
        cart_html = "<h3 style='margin: 16px 0 8px 0; font-size: 16px;'>Cart Contents</h3>"
        cart_html += (
            "<table style='border-collapse: collapse; width: 100%; max-width: 500px; "
            "border: 1px solid #eee;'>"
            "<tr style='background: #f5f5f5;'>"
            "<th style='padding: 8px; text-align: left; border-bottom: 1px solid #ddd;'>Item</th>"
            "<th style='padding: 8px; text-align: left; border-bottom: 1px solid #ddd;'>Details</th>"
            "<th style='padding: 8px; text-align: right; border-bottom: 1px solid #ddd;'>Price</th>"
            "</tr>"
        )
        for cart_item in items:
            name = cart_item.get("display_name") or cart_item.get("menu_item_name", "Item")
            qty = cart_item.get("quantity", 1)
            line_total = cart_item.get("line_total", 0)
            mods = cart_item.get("modifiers") or []
            mod_names = [m.get("name", "") for m in mods if m.get("name")]
            details = ", ".join(mod_names)

            cart_text += f"  {qty}x {name}"
            if details:
                cart_text += f" ({details})"
            cart_text += f" - ${line_total:.2f}\n"

            cart_html += (
                f"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'>"
                f"{qty}x {name}</td>"
                f"<td style='padding: 8px; border-bottom: 1px solid #eee; color: #666; "
                f"font-size: 13px;'>{details}</td>"
                f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right;'>"
                f"${line_total:.2f}</td></tr>"
            )
        cart_html += "</table>"

    # Build messages section
    messages_text = ""
    messages_html = ""
    if recent_messages:
        messages_text = "\nRecent Messages:\n"
        messages_html = "<h3 style='margin: 16px 0 8px 0; font-size: 16px;'>Recent Messages</h3>"
        for msg in recent_messages:
            role = msg.get("role", "unknown").title()
            content = msg.get("content", "")
            messages_text += f"  [{role}]: {content}\n"
            bg = "#f0f4ff" if role == "Assistant" else "#f9f9f9"
            messages_html += (
                f"<div style='padding: 8px 12px; margin: 4px 0; "
                f"background: {bg}; border-radius: 6px; font-size: 13px;'>"
                f"<strong>{role}:</strong> {content}</div>"
            )

    body_text = f"""Conversation Report

A user has flagged this conversation for review.

Session Details:
{details_text}
{cart_text}
{messages_text}
---
This is an automated report from the ordering chatbot.
"""

    # Build session details HTML table
    details_html = "<table style='border-collapse: collapse; width: 100%; max-width: 500px;'>"
    detail_rows = [("Session ID", session_id)]
    if store_id:
        detail_rows.append(("Store ID", store_id))
    if caller_id:
        detail_rows.append(("Caller ID", caller_id))
    if customer_name:
        detail_rows.append(("Customer Name", customer_name))
    if customer_phone:
        detail_rows.append(("Customer Phone", customer_phone))
    if order_status:
        detail_rows.append(("Order Status", order_status))
    detail_rows.append(("Items in Cart", str(item_count)))

    for label, value in detail_rows:
        details_html += (
            f"<tr><td style='padding: 4px 8px; color: #666; white-space: nowrap;'>"
            f"{label}:</td><td style='padding: 4px 8px;'>{value}</td></tr>"
        )
    details_html += "</table>"

    body_html = f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
<h2 style="margin: 0 0 16px 0; font-size: 20px;">Conversation Report</h2>
<p>A user has flagged this conversation for review.</p>
<h3 style="margin: 16px 0 8px 0; font-size: 16px;">Session Details</h3>
{details_html}
{cart_html}
{messages_html}
<hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
<p style="color: #999; font-size: 12px;">This is an automated report from the ordering chatbot.</p>
</body>
</html>
"""

    if not is_email_configured():
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
            "mock": True,
            "message": "Report email logged (AWS SES not configured)",
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = AWS_SES_FROM_EMAIL
        msg["To"] = to_email

        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        client = _get_ses_client()
        if client is None:
            return {
                "status": "error",
                "to_email": to_email,
                "error": "boto3 not installed",
                "mock": False,
                "message": "Failed to send report email: boto3 not installed",
            }

        client.send_raw_email(
            Source=AWS_SES_FROM_EMAIL,
            Destinations=[to_email],
            RawMessage={"Data": msg.as_string()},
        )

        logger.info("Report email sent successfully for session %s", short_id)

        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "mock": False,
            "message": "Report email sent successfully",
        }

    except Exception as e:
        logger.error("Failed to send report email for session %s: %s", short_id, str(e))
        return {
            "status": "error",
            "to_email": to_email,
            "error": str(e),
            "mock": False,
            "message": f"Failed to send report email: {str(e)}",
        }
