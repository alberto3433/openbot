"""
Email templates for Orderbot.

Contains HTML/text template builders for all email types:
- Payment link emails
- Receipt emails
- Payment expired emails
- Conversation report emails

All template functions return (subject, body_text, body_html) tuples.
"""


# =============================================================================
# Shared HTML Styles
# =============================================================================

BODY_STYLE = (
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
    "max-width: 600px; margin: 0 auto; padding: 20px;"
)

CTA_BUTTON_STYLE = (
    "background-color: #1976d2; color: white; padding: 14px 28px; "
    "text-decoration: none; display: inline-block; border-radius: 4px; font-weight: 500;"
)

SECTION_HEADING_STYLE = "margin: 16px 0 8px 0; font-size: 16px;"


# =============================================================================
# Shared HTML Helpers
# =============================================================================

def wrap_html_body(content: str) -> str:
    """Wrap HTML content in a standard email body."""
    return f"""
<html>
<body style="{BODY_STYLE}">
{content}
</body>
</html>
"""


def build_cta_button(url: str, label: str) -> str:
    """Build a styled CTA button element."""
    return f'<a href="{url}" style="{CTA_BUTTON_STYLE}">{label}</a>'


# =============================================================================
# Shared Section Builders
# =============================================================================

def _build_order_details_section(
    customer_name: str | None,
    customer_phone: str | None,
    order_type: str | None,
) -> tuple[str, str]:
    """Build order details text and HTML sections. Returns (text, html)."""
    if not customer_name and not customer_phone and not order_type:
        return "", ""

    text = "\nOrder Details:\n"
    html = f"<h3 style='{SECTION_HEADING_STYLE}'>Order Details</h3>"
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
    subtotal: float | None,
    city_tax: float | None,
    state_tax: float | None,
    delivery_fee: float | None,
    amount: float,
) -> tuple[str, str]:
    """Build items list with totals as text and HTML. Returns (text, html)."""
    if not items:
        return "", ""

    text = "\nItems:\n"
    html = f"<h3 style='{SECTION_HEADING_STYLE}'>Items</h3>"
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


# =============================================================================
# Template Builders — each returns (subject, body_text, body_html)
# =============================================================================

def build_payment_link_email(
    order_id: int,
    amount: float,
    store_name: str,
    payment_url: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    order_type: str | None = None,
    items: list | None = None,
    subtotal: float | None = None,
    city_tax: float | None = None,
    state_tax: float | None = None,
    delivery_fee: float | None = None,
) -> tuple[str, str, str]:
    """Build payment link email. Returns (subject, text, html)."""
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

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

    cta = build_cta_button(payment_url, f"Complete Payment - ${amount:.2f}")
    body_html = wrap_html_body(f"""<p>{greeting}</p>
<p>Thank you for your order at <strong>{store_name}</strong>!</p>
{order_details_html}
{items_html}
<p style="margin-top: 24px;">{cta}</p>
<p style="color: #666; font-size: 13px;">Or copy this link: {payment_url}</p>
<p>If you have any questions, please call us.</p>
<p>Thanks,<br><strong>{store_name}</strong></p>""")

    return subject, body_text, body_html


def build_receipt_email(
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    order_type: str | None = None,
    items: list | None = None,
    subtotal: float | None = None,
    city_tax: float | None = None,
    state_tax: float | None = None,
    delivery_fee: float | None = None,
) -> tuple[str, str, str]:
    """Build receipt email. Returns (subject, text, html)."""
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

    order_details_text, order_details_html = _build_order_details_section(
        customer_name, customer_phone, order_type,
    )
    items_text, items_html = _build_items_section(
        items, subtotal, city_tax, state_tax, delivery_fee, amount,
    )

    subject = f"Receipt for Your {store_name} Order #{order_id}"

    body_text = f"""{greeting}

Thank you for your payment! Your order at {store_name} has been received.
{order_details_text}{items_text}
Payment received: ${amount:.2f}

If you have any questions, please call us.

Thanks,
{store_name}
"""

    body_html = wrap_html_body(f"""<p>{greeting}</p>
<p>Thank you for your payment! Your order at <strong>{store_name}</strong> has been received.</p>
{order_details_html}
{items_html}
<div style="margin-top: 24px; padding: 16px 24px; background-color: #ECFDF5; border-radius: 8px; border: 1px solid #A7F3D0; text-align: center;">
  <span style="color: #059669; font-weight: 600; font-size: 16px;">&#10003; Payment Received &mdash; ${amount:.2f}</span>
</div>
<p>If you have any questions, please call us.</p>
<p>Thanks,<br><strong>{store_name}</strong></p>""")

    return subject, body_text, body_html


def build_payment_expired_email(
    order_id: int,
    amount: float,
    store_name: str,
    payment_url: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    order_type: str | None = None,
    items: list | None = None,
    subtotal: float | None = None,
    city_tax: float | None = None,
    state_tax: float | None = None,
    delivery_fee: float | None = None,
) -> tuple[str, str, str]:
    """Build payment expired email. Returns (subject, text, html)."""
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

    order_details_text, order_details_html = _build_order_details_section(
        customer_name, customer_phone, order_type,
    )
    items_text, items_html = _build_items_section(
        items, subtotal, city_tax, state_tax, delivery_fee, amount,
    )

    subject = f"New Payment Link for Your {store_name} Order #{order_id}"

    body_text = f"""{greeting}

Your previous payment link for your {store_name} order has expired. No worries — here's a new one!
{order_details_text}{items_text}
Click here to complete your payment:
{payment_url}

If you have any questions, please call us.

Thanks,
{store_name}
"""

    cta = build_cta_button(payment_url, f"Complete Payment - ${amount:.2f}")
    body_html = wrap_html_body(f"""<p>{greeting}</p>
<p>Your previous payment link for your <strong>{store_name}</strong> order has expired. No worries — here's a new one!</p>
{order_details_html}
{items_html}
<p style="margin-top: 24px;">{cta}</p>
<p style="color: #666; font-size: 13px;">Or copy this link: {payment_url}</p>
<p>If you have any questions, please call us.</p>
<p>Thanks,<br><strong>{store_name}</strong></p>""")

    return subject, body_text, body_html


def build_report_email(
    session_id: str,
    store_id: str | None = None,
    caller_id: str | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    recent_messages: list[dict] | None = None,
    order_status: str | None = None,
    item_count: int = 0,
    items: list[dict] | None = None,
) -> tuple[str, str, str]:
    """Build conversation report email. Returns (subject, text, html)."""
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
        cart_html = f"<h3 style='{SECTION_HEADING_STYLE}'>Cart Contents</h3>"
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
        messages_html = f"<h3 style='{SECTION_HEADING_STYLE}'>Recent Messages</h3>"
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

    body_html = wrap_html_body(f"""<h2 style="margin: 0 0 16px 0; font-size: 20px;">Conversation Report</h2>
<p>A user has flagged this conversation for review.</p>
<h3 style="{SECTION_HEADING_STYLE}">Session Details</h3>
{details_html}
{cart_html}
{messages_html}
<hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
<p style="color: #999; font-size: 12px;">This is an automated report from the ordering chatbot.</p>""")

    return subject, body_text, body_html
