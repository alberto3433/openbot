"""Chaos Monkey Test Generator for Orderbot.

A continuous test generation and execution system that finds bugs by testing
the orderbot API with varied inputs, keeping failing tests as regression tests.

Usage:
    # Run for 1 hour
    python -m tests.chaos_monkey.cli --duration 3600

    # Quick test (1 minute)
    python -m tests.chaos_monkey.cli -d 60

    # With LLM phrasings
    python -m tests.chaos_monkey.cli --use-llm

Programmatic usage:
    from tests.chaos_monkey import ChaosMonkeyRunner, ChaosMonkeyConfig

    config = ChaosMonkeyConfig(duration_seconds=3600)
    runner = ChaosMonkeyRunner(config=config)
    summary = runner.run()
"""

from tests.chaos_monkey.config import ChaosMonkeyConfig
from tests.chaos_monkey.runner import ChaosMonkeyRunner

__all__ = ["ChaosMonkeyRunner", "ChaosMonkeyConfig"]
