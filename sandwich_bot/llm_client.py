import json
import os
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

# --------------------------------------------------------------------------------------
# Load .env explicitly from the project root (one level above sandwich_bot/)
# --------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # project root (where .env lives)
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("OPENAI_API_KEY")

print("Using OPENAI_API_KEY prefix:", (api_key or "")[:12])

if not api_key:
    # Fail fast with a clear error if the key is missing
    raise RuntimeError(
        f"OPENAI_API_KEY not found in {env_path}. "
        "Create a .env file with OPENAI_API_KEY=sk-proj-... at the project root."
    )

# Explicitly pass the key so we don't depend on any global environment
client = OpenAI(api_key=api_key)

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
                "add_sandwich",
                "update_sandwich",
                "add_side",
                "add_drink",
                "collect_customer_info",
                "review_order",
                "confirm_order",
                "cancel_order",
                "small_talk",
                "unknown",
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
                "item_type",
                "menu_item_name",
                "size",
                "bread",
                "protein",
                "cheese",
                "toppings",
                "sauces",
                "toasted",
                "quantity",
                "item_index",
                "customer_name",
                "phone",
                "pickup_time",
                "confirm",
                "cancel_reason",
            ],
        },
    },
    "required": ["reply", "intent", "slots"],
}


def render_history(history: List[Dict[str, str]]) -> str:
    if not history:
        return "(no history)"
    return "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])


def call_sandwich_bot(
    conversation_history,
    current_order_state,
    menu_json,
    user_message,
    model: str = "gpt-4.1",
) -> Dict[str, Any]:
    """
    Call the OpenAI chat completion to get the bot's reply + structured intent/slots.
    """

    prompt = USER_PROMPT_TEMPLATE.format(
        conversation_history=render_history(conversation_history),
        order_state=json.dumps(current_order_state, indent=2),
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
