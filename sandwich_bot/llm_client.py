import json
from typing import List, Dict, Any
from openai import OpenAI

from dotenv import load_dotenv
import os

# Load variables from .env into environment
load_dotenv()


SYSTEM_PROMPT = """You are 'Sammy', a concise polite sandwich-order bot."""


USER_PROMPT_TEMPLATE = """CONVERSATION HISTORY:
{conversation_history}

ORDER STATE:
{order_state}

MENU:
{menu_json}

USER MESSAGE:
{user_message}

JSON SCHEMA:
{schema}
"""


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "intent": {
            "type": "string",
            "enum": [
                "add_sandwich", "update_sandwich", "add_side", "add_drink",
                "collect_customer_info", "review_order", "confirm_order",
                "cancel_order", "small_talk", "unknown"
            ],
        },
        "slots": {
            "type": "object",
            "properties": {
                "item_type": {"type": ["string", "null"]},
                "menu_item_name": {"type": ["string", "null"]},
                "size": {"type": ["string", "null"]},
                "bread": {"type": ["string", "null"]},
                "protein": {"type": ["string", "null"]},
                "cheese": {"type": ["string", "null"]},
                "toppings": {"type": "array", "items": {"type": "string"}},
                "sauces": {"type": "array", "items": {"type": "string"}},
                "toasted": {"type": ["boolean", "null"]},
                "quantity": {"type": ["integer", "null"]},
                "item_index": {"type": ["integer", "null"]},
                "customer_name": {"type": ["string", "null"]},
                "phone": {"type": ["string", "null"]},
                "pickup_time": {"type": ["string", "null"]},
                "confirm": {"type": ["boolean", "null"]},
                "cancel_reason": {"type": ["string", "null"]},
            },
            "required": [
                "item_type", "menu_item_name", "size", "bread", "protein",
                "cheese", "toppings", "sauces", "toasted", "quantity",
                "item_index", "customer_name", "phone", "pickup_time",
                "confirm", "cancel_reason"
            ]
        }
    },
    "required": ["reply", "intent", "slots"]
}

# -------- OpenAI client handling --------

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """
    Lazily create and return a singleton OpenAI client.

    This:
    - Reads OPENAI_API_KEY from environment (loaded via .env)
    - Avoids failing at import time if the key is missing
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Set it in your environment or .env file."
            )
        _client = OpenAI(api_key=api_key)
    return _client


# -------- Prompt helpers + main call --------

def render_history(history: List[Dict[str, str]]) -> str:
    if not history:
        return "(no history)"
    return "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])


def call_sandwich_bot(
    history: List[Dict[str, str]],
    order_state: Dict[str, Any],
    menu_json: Dict[str, Any],
    user_message: str,
    model: str = "gpt-4.1",
) -> Dict[str, Any]:
    """
    Call the OpenAI chat model and return the parsed JSON response
    matching RESPONSE_SCHEMA.
    """
    client = get_client()

    prompt = USER_PROMPT_TEMPLATE.format(
        conversation_history=render_history(history),
        order_state=json.dumps(order_state, indent=2),
        menu_json=json.dumps(menu_json, indent=2),
        user_message=user_message,
        schema=json.dumps(RESPONSE_SCHEMA, indent=2),
    )

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    content = completion.choices[0].message.content
    return json.loads(content)
