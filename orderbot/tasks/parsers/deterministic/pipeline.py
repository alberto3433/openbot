"""
Parser Pipeline - Ordered chain of parsers with dependency management.

This module provides a pipeline architecture for deterministic parsing,
replacing the if-cascade in core.py with a more maintainable and extensible
structure.

Usage:
    from .pipeline import ParserPipeline, Parser

    pipeline = ParserPipeline()

    @pipeline.register("greeting", priority=10)
    def parse_greeting(text: str, context: dict) -> OpenInputResponse | None:
        if menu_cache.is_greeting(text):
            return OpenInputResponse(is_greeting=True)
        return None

    # Or register directly
    pipeline.register_parser("gratitude", parse_gratitude, priority=10)

    # Run the pipeline
    result = pipeline.parse(user_input)
"""

from __future__ import annotations

import logging
from typing import Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from orderbot.tasks.schemas import OpenInputResponse

logger = logging.getLogger(__name__)

# Type alias for parser functions
ParserFunc = Callable[[str, dict[str, Any]], "OpenInputResponse | None"]


class Parser:
    """A named parser with priority for ordering."""

    def __init__(
        self,
        name: str,
        func: ParserFunc,
        priority: int = 50,
        description: str = "",
    ):
        """
        Initialize a parser.

        Args:
            name: Unique name for the parser (e.g., "greeting", "gratitude")
            func: The parser function. Takes (text, context) and returns
                  OpenInputResponse or None.
            priority: Lower priority runs first (default 50).
            description: Optional human-readable description.
        """
        self.name = name
        self.func = func
        self.priority = priority
        self.description = description

    def __repr__(self) -> str:
        return f"Parser({self.name!r}, priority={self.priority})"


class ParserPipeline:
    """
    Ordered chain of parsers with dependency management.

    Parsers are executed in priority order (lower = runs first).
    The first parser to return a non-None result wins.
    """

    def __init__(self):
        """Initialize an empty pipeline."""
        self._parsers: list[Parser] = []
        self._sorted = True  # Track if we need to re-sort
        self._disabled: set[str] = set()  # Names of disabled parsers

    def register_parser(
        self,
        name: str,
        func: ParserFunc,
        priority: int = 50,
        description: str = "",
    ) -> None:
        """
        Register a parser with the pipeline.

        Args:
            name: Unique name for the parser.
            func: The parser function.
            priority: Lower priority runs first (default 50).
            description: Optional description.

        Raises:
            ValueError: If a parser with the same name already exists.
        """
        # Check for duplicate names
        if any(p.name == name for p in self._parsers):
            raise ValueError(f"Parser '{name}' already registered")

        self._parsers.append(Parser(name, func, priority, description))
        self._sorted = False

    def register(
        self,
        name: str,
        priority: int = 50,
        description: str = "",
    ) -> Callable[[ParserFunc], ParserFunc]:
        """
        Decorator to register a parser function.

        Usage:
            @pipeline.register("greeting", priority=10)
            def parse_greeting(text: str, context: dict) -> OpenInputResponse | None:
                ...

        Args:
            name: Unique name for the parser.
            priority: Lower priority runs first.
            description: Optional description.

        Returns:
            Decorator that registers the function.
        """
        def decorator(func: ParserFunc) -> ParserFunc:
            self.register_parser(name, func, priority, description)
            return func
        return decorator

    def unregister(self, name: str) -> bool:
        """
        Remove a parser by name.

        Args:
            name: The parser name to remove.

        Returns:
            True if found and removed, False otherwise.
        """
        for i, parser in enumerate(self._parsers):
            if parser.name == name:
                self._parsers.pop(i)
                return True
        return False

    def disable(self, name: str) -> None:
        """
        Temporarily disable a parser without removing it.

        Args:
            name: The parser name to disable.
        """
        self._disabled.add(name)

    def enable(self, name: str) -> None:
        """
        Re-enable a previously disabled parser.

        Args:
            name: The parser name to enable.
        """
        self._disabled.discard(name)

    def is_enabled(self, name: str) -> bool:
        """Check if a parser is enabled."""
        return name not in self._disabled

    def get_parser(self, name: str) -> Parser | None:
        """Get a parser by name."""
        for parser in self._parsers:
            if parser.name == name:
                return parser
        return None

    def _ensure_sorted(self) -> None:
        """Ensure parsers are sorted by priority."""
        if not self._sorted:
            self._parsers.sort(key=lambda p: p.priority)
            self._sorted = True

    def parse(
        self,
        user_input: str,
        context: dict[str, Any] | None = None,
    ) -> "OpenInputResponse | None":
        """
        Run parsers in priority order until one matches.

        Args:
            user_input: The user's input string.
            context: Optional context dict passed to all parsers.
                    Useful for passing menu_cache, session state, etc.

        Returns:
            The first non-None response from a parser, or None if no match.
        """
        self._ensure_sorted()
        context = context or {}

        for parser in self._parsers:
            if parser.name in self._disabled:
                continue

            try:
                result = parser.func(user_input, context)
                if result is not None:
                    logger.debug(
                        "Pipeline: parser '%s' matched input '%s...'",
                        parser.name,
                        user_input[:30]
                    )
                    return result
            except Exception as e:
                logger.error(
                    "Pipeline: parser '%s' raised exception: %s",
                    parser.name,
                    e
                )
                # Continue to next parser on error

        return None

    def list_parsers(self) -> list[tuple[str, int, str]]:
        """
        List all registered parsers.

        Returns:
            List of (name, priority, description) tuples, sorted by priority.
        """
        self._ensure_sorted()
        return [
            (p.name, p.priority, p.description)
            for p in self._parsers
        ]

    def __len__(self) -> int:
        return len(self._parsers)

    def __repr__(self) -> str:
        return f"ParserPipeline({len(self._parsers)} parsers)"


# Global pipeline instance for the deterministic parser
_default_pipeline: ParserPipeline | None = None


def get_default_pipeline() -> ParserPipeline:
    """
    Get the default pipeline instance.

    Creates and populates the pipeline on first access.
    """
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = _create_default_pipeline()
    return _default_pipeline


def _create_default_pipeline() -> ParserPipeline:
    """
    Create and populate the default parser pipeline.

    This mirrors the current if-cascade in core.py but in a more
    maintainable format.
    """
    from orderbot.menu_data_cache import menu_cache
    from orderbot.tasks.schemas import OpenInputResponse
    from ..constants import GRATITUDE_PATTERNS, HELP_PATTERNS, REPEAT_ORDER_PATTERNS
    from .patterns import strip_filler_words

    pipeline = ParserPipeline()

    # Priority groups:
    # 10-19: Simple pattern matches (greeting, gratitude, help, done)
    # 20-29: Order lifecycle (repeat, done)
    # 30-39: Modification patterns (add modifier, replace, cancel)
    # 40-49: Inquiries (price, menu, recommendation, store info)
    # 50-59: Item parsing (configurable, menu items)
    # 60-69: Multi-item and fallback parsing

    @pipeline.register("greeting", priority=10)
    def parse_greeting(text: str, context: dict) -> OpenInputResponse | None:
        if menu_cache.is_greeting(text):
            logger.debug("Deterministic parse: greeting detected")
            return OpenInputResponse(is_greeting=True)
        return None

    @pipeline.register("gratitude", priority=10)
    def parse_gratitude(text: str, context: dict) -> OpenInputResponse | None:
        if GRATITUDE_PATTERNS.match(text):
            logger.debug("Deterministic parse: gratitude detected")
            return OpenInputResponse(is_gratitude=True)
        return None

    @pipeline.register("help", priority=10)
    def parse_help(text: str, context: dict) -> OpenInputResponse | None:
        if HELP_PATTERNS.match(text):
            logger.debug("Deterministic parse: help request detected")
            return OpenInputResponse(is_help_request=True)
        return None

    @pipeline.register("done", priority=20)
    def parse_done(text: str, context: dict) -> OpenInputResponse | None:
        if menu_cache.is_done(text):
            logger.debug("Deterministic parse: done ordering detected")
            return OpenInputResponse(done_ordering=True)
        return None

    @pipeline.register("repeat_order", priority=20)
    def parse_repeat_order(text: str, context: dict) -> OpenInputResponse | None:
        if REPEAT_ORDER_PATTERNS.match(text):
            logger.debug("Deterministic parse: repeat order detected")
            return OpenInputResponse(wants_repeat_order=True)
        return None

    return pipeline
