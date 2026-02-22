"""Configuration for the Chaos Monkey test generator."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChaosMonkeyConfig:
    """Configuration settings for the Chaos Monkey test runner."""

    # Runtime settings
    duration_seconds: int = 14400  # 4 hours default
    batch_size: int = 10  # Scenarios per batch
    batch_delay_seconds: float = 2.0  # Delay between batches

    # Rate limiting - be conservative to avoid 429 errors
    rate_limit: int = 20  # Max requests per minute
    request_delay_seconds: float = 1.5  # Delay between each API request

    # LLM settings
    use_llm: bool = False  # Enable LLM-generated phrasings
    llm_phrasing_ratio: float = 0.1  # 10% of tests use LLM phrasings

    # Input mode: "text" (default) or "voice" (STT simulation)
    input_mode: str = "text"

    # Mutation settings
    mutation_probability: float = 0.2  # 20% of inputs get mutated
    gentle_mutations: bool = True  # Use gentle mutations (no typos, no word doubling)

    # Scenario weights (must sum to 1.0)
    scenario_weights: dict[str, float] = field(default_factory=lambda: {
        "corpus_order": 0.35,
        "regression": 0.15,
        "realistic_order": 0.15,
        "modifier_flow": 0.10,
        "menu_inquiry": 0.10,
        "tricky": 0.05,
        "single_item": 0.03,
        "multi_item": 0.03,
        "cart_ops": 0.04,
    })

    # Paths
    generated_tests_dir: Path = field(
        default_factory=lambda: Path("tests/chaos_monkey/generated")
    )
    report_path: Path = field(
        default_factory=lambda: Path("tests/chaos_monkey_failures.md")
    )

    # API settings
    api_base_url: str = "http://localhost:8000"

    # Cleanup settings
    cleanup_interval_seconds: int = 300  # Run cleanup every 5 minutes

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not abs(sum(self.scenario_weights.values()) - 1.0) < 0.001:
            raise ValueError(
                f"Scenario weights must sum to 1.0, got {sum(self.scenario_weights.values())}"
            )
        if self.mutation_probability < 0 or self.mutation_probability > 1:
            raise ValueError("mutation_probability must be between 0 and 1")
        if self.llm_phrasing_ratio < 0 or self.llm_phrasing_ratio > 1:
            raise ValueError("llm_phrasing_ratio must be between 0 and 1")
        if self.input_mode not in ("text", "voice"):
            raise ValueError(f"input_mode must be 'text' or 'voice', got '{self.input_mode}'")
