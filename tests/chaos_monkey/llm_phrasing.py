"""Optional LLM-based phrasing generation for Chaos Monkey tests."""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LLMPhrasingGenerator:
    """Generates realistic customer phrasings using an LLM."""

    DEFAULT_CACHE_DIR = Path("tests/chaos_monkey/.phrasing_cache")

    def __init__(
        self,
        cache_dir: Path | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        """Initialize the LLM phrasing generator.

        Args:
            cache_dir: Directory for caching LLM responses.
            model: The LLM model to use.
        """
        self.cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
        self.model = model
        self._client = None
        self._cache: dict[str, list[str]] = {}

        # Load cache from disk
        self._load_cache()

    def _get_client(self) -> Any:
        """Get or create the OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI

                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY environment variable not set")

                self._client = OpenAI(api_key=api_key)
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")

        return self._client

    def _load_cache(self) -> None:
        """Load cached phrasings from disk."""
        cache_file = self.cache_dir / "phrasings.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                logger.info("Loaded %d cached phrasings", len(self._cache))
            except Exception as e:
                logger.warning("Failed to load phrasing cache: %s", e)
                self._cache = {}

    def _save_cache(self) -> None:
        """Save cached phrasings to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / "phrasings.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save phrasing cache: %s", e)

    def _get_cache_key(self, item_name: str, modifiers: list[str] | None) -> str:
        """Generate a cache key for an item+modifiers combination."""
        data = f"{item_name.lower()}:{','.join(sorted(modifiers or []))}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def generate_phrasings(
        self,
        item_name: str,
        modifiers: list[str] | None = None,
        count: int = 5,
    ) -> list[str]:
        """Generate realistic customer phrasings for ordering an item.

        Args:
            item_name: The menu item name.
            modifiers: Optional list of modifiers.
            count: Number of phrasings to generate.

        Returns:
            List of phrasing strings.
        """
        cache_key = self._get_cache_key(item_name, modifiers)

        # Check cache first
        if cache_key in self._cache:
            logger.debug("Using cached phrasings for %s", item_name)
            return self._cache[cache_key]

        # Generate new phrasings
        try:
            phrasings = self._call_llm(item_name, modifiers, count)
            self._cache[cache_key] = phrasings
            self._save_cache()
            return phrasings
        except Exception as e:
            logger.error("Failed to generate phrasings: %s", e)
            # Return default phrasing on failure
            return [f"I'll have a {item_name}"]

    def _call_llm(
        self,
        item_name: str,
        modifiers: list[str] | None,
        count: int,
    ) -> list[str]:
        """Call the LLM to generate phrasings."""
        client = self._get_client()

        modifier_str = ""
        if modifiers:
            modifier_str = f" with {', '.join(modifiers)}"

        prompt = f"""Generate {count} different ways a customer might verbally order "{item_name}"{modifier_str} at a restaurant or cafe.

Requirements:
- Use natural, conversational language
- Include variations in politeness, formality, and phrasing
- Some should be short and direct, others more polite
- Include common speech patterns like fillers (um, uh), corrections, and natural pauses
- Do not include any special characters or formatting

Return ONLY the phrasings, one per line, with no numbering or other text."""

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that generates realistic customer speech patterns.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=500,
        )

        content = response.choices[0].message.content or ""
        phrasings = [line.strip() for line in content.split("\n") if line.strip()]

        logger.info("Generated %d phrasings for %s", len(phrasings), item_name)
        return phrasings

    def get_cached_count(self) -> int:
        """Get the number of cached phrasing sets."""
        return len(self._cache)

    def clear_cache(self) -> None:
        """Clear the phrasing cache."""
        self._cache = {}
        cache_file = self.cache_dir / "phrasings.json"
        if cache_file.exists():
            cache_file.unlink()
        logger.info("Phrasing cache cleared")
