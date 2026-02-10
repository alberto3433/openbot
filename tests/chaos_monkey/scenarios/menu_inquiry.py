"""Menu inquiry scenarios - questions about what's available."""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class MenuInquiryScenario(BaseScenario):
    """Scenario for menu inquiry questions.

    Tests realistic customer questions like:
    - "What bagels do you have?"
    - "Do you have gluten-free options?"
    - "What's on the menu?"
    - "What kind of coffee do you have?"

    These are single-turn scenarios that test the bot's ability to
    respond helpfully to menu-related questions.
    """

    scenario_type = "menu_inquiry"

    # Templates for general menu questions
    GENERAL_MENU_TEMPLATES = [
        "What do you have?",
        "What's on the menu?",
        "What do you sell?",
        "What can I order?",
        "What's available?",
        "Can you tell me what you have?",
        "What are my options?",
    ]

    # Templates for category-specific questions
    CATEGORY_TEMPLATES = [
        "What {category} do you have?",
        "What kind of {category} do you have?",
        "Do you have any {category}?",
        "What {category} options do you have?",
        "Can I see your {category}?",
        "Tell me about your {category}",
        "What's good in {category}?",
    ]

    # Templates for specific item inquiries
    SPECIFIC_ITEM_TEMPLATES = [
        "Do you have {item}?",
        "Is {item} available?",
        "Can I get {item}?",
        "Do you sell {item}?",
    ]

    # Templates for dietary restriction questions
    DIETARY_TEMPLATES = [
        "Do you have anything gluten-free?",
        "What are your gluten-free options?",
        "Do you have vegan options?",
        "What's vegetarian on the menu?",
        "Do you have anything without dairy?",
        "What's your healthiest option?",
        "Do you have low-calorie options?",
    ]

    # Templates for recommendation questions
    RECOMMENDATION_TEMPLATES = [
        "What do you recommend?",
        "What's popular here?",
        "What's your best seller?",
        "What should I try?",
        "What's good here?",
        "What do people usually order?",
    ]

    # Common categories to ask about
    CATEGORIES = [
        "bagels",
        "sandwiches",
        "coffee",
        "drinks",
        "spreads",
        "cream cheese",
        "breakfast",
        "salads",
        "soups",
        "sides",
    ]

    def __init__(
        self,
        inquiry_type: str = "general",
        category: str | None = None,
        item_name: str | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize menu inquiry scenario.

        Args:
            inquiry_type: Type of inquiry (general, category, specific, dietary, recommendation).
            category: Category to ask about (for category inquiries).
            item_name: Specific item to ask about (for specific inquiries).
            seed: Random seed.
        """
        if inquiry_type == "category" and category:
            name = f"Ask about {category}"
        elif inquiry_type == "specific" and item_name:
            name = f"Ask about {item_name}"
        elif inquiry_type == "dietary":
            name = "Ask about dietary options"
        elif inquiry_type == "recommendation":
            name = "Ask for recommendations"
        else:
            name = "General menu inquiry"

        super().__init__(name)

        self.inquiry_type = inquiry_type
        self.category = category
        self.item_name = item_name
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the menu inquiry turn."""
        if self.inquiry_type == "general":
            user_input = self.rng.choice(self.GENERAL_MENU_TEMPLATES)
        elif self.inquiry_type == "category" and self.category:
            template = self.rng.choice(self.CATEGORY_TEMPLATES)
            user_input = template.format(category=self.category)
        elif self.inquiry_type == "specific" and self.item_name:
            template = self.rng.choice(self.SPECIFIC_ITEM_TEMPLATES)
            user_input = template.format(item=self.item_name)
        elif self.inquiry_type == "dietary":
            user_input = self.rng.choice(self.DIETARY_TEMPLATES)
        elif self.inquiry_type == "recommendation":
            user_input = self.rng.choice(self.RECOMMENDATION_TEMPLATES)
        else:
            user_input = self.rng.choice(self.GENERAL_MENU_TEMPLATES)

        # For menu inquiries, we expect a helpful response (no specific cart changes)
        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[],  # No specific actions expected
                expected_items_in_cart=[],  # Cart should remain unchanged
                allow_disambiguation=True,  # Disambiguation is fine for inquiries
                is_menu_inquiry=True,  # "Not found" responses are acceptable
            )
        )
