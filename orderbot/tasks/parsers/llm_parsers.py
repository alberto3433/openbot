"""
LLM-Powered Parsers.

This module provides the instructor/OpenAI client used by
llm_category_inference.py for semantic item category inference.

Most parsers have been migrated to deterministic implementations in
validators.py (name, phone, email, side choice, confirmation,
delivery choice, payment method).
"""

import os
import logging

from typing import TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

# Generic type for response models
T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

# Module-level cached clients — reuse HTTP connection pool across calls
_openai_client: OpenAI | None = None
_instructor_client = None


def _get_openai_client(timeout: float = 10.0) -> OpenAI:
    """Get or create a cached OpenAI client."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        _openai_client = OpenAI(api_key=api_key, timeout=timeout)
    return _openai_client


def get_instructor_client(timeout: float = 10.0):
    """Get a cached instructor-wrapped OpenAI client."""
    global _instructor_client
    if _instructor_client is None:
        _instructor_client = instructor.from_openai(_get_openai_client(timeout))
    return _instructor_client


def _create_llm_parser(
    prompt_template: str,
    response_model: type[T],
    model: str = "gpt-4o-mini",
) -> T:
    """Generic LLM parser factory.

    Creates a parsed response by sending a prompt to the LLM.

    Args:
        prompt_template: The fully formatted prompt to send
        response_model: The Pydantic model type to parse the response into
        model: The LLM model to use

    Returns:
        Parsed response of type T
    """
    client = get_instructor_client()
    return client.chat.completions.create(
        model=model,
        response_model=response_model,
        messages=[{"role": "user", "content": prompt_template}],
    )


