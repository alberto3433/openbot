"""CLI interface for Chaos Monkey testing."""

import argparse
import logging
import sys
from pathlib import Path

from tests.chaos_monkey.config import ChaosMonkeyConfig
from tests.chaos_monkey.runner import ChaosMonkeyRunner


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Reduce noise from other loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Chaos Monkey Test Generator - Find bugs through varied inputs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run for 1 hour with default settings
  python -m tests.chaos_monkey.cli --duration 3600

  # Run with LLM-generated phrasings
  python -m tests.chaos_monkey.cli --use-llm

  # Quick test run (1 minute)
  python -m tests.chaos_monkey.cli -d 60

  # High rate limit and larger batches
  python -m tests.chaos_monkey.cli -d 7200 -b 20 -r 60
        """,
    )

    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=14400,
        help="Duration in seconds (default: 14400 = 4 hours)",
    )

    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=10,
        help="Number of scenarios per batch (default: 10)",
    )

    parser.add_argument(
        "-r", "--rate-limit",
        type=int,
        default=20,
        help="Max API requests per minute (default: 20)",
    )

    parser.add_argument(
        "--request-delay",
        type=float,
        default=1.5,
        help="Delay in seconds between API requests (default: 1.5)",
    )

    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable LLM-generated phrasings (requires API key)",
    )

    parser.add_argument(
        "--llm-ratio",
        type=float,
        default=0.1,
        help="Ratio of tests using LLM phrasings (default: 0.1)",
    )

    parser.add_argument(
        "--mutation-prob",
        type=float,
        default=0.2,
        help="Probability of applying mutations (default: 0.2)",
    )

    parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Use aggressive mutations (typos, word doubling). Default is gentle mode.",
    )

    parser.add_argument(
        "--scenario-type",
        type=str,
        default=None,
        choices=["single_item", "multi_item", "modifier", "cart_ops", "modifier_flow", "menu_inquiry"],
        help="Focus on a specific scenario type (default: mixed)",
    )

    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL for the API (default: http://localhost:8000)",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for generated test files",
    )

    parser.add_argument(
        "--report-path",
        type=str,
        default=None,
        help="Path for the failure report",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Build configuration
    config = ChaosMonkeyConfig(
        duration_seconds=args.duration,
        batch_size=args.batch_size,
        rate_limit=args.rate_limit,
        request_delay_seconds=args.request_delay,
        use_llm=args.use_llm,
        llm_phrasing_ratio=args.llm_ratio,
        mutation_probability=args.mutation_prob,
        gentle_mutations=not args.aggressive,
        api_base_url=args.api_url,
    )

    if args.output_dir:
        config.generated_tests_dir = Path(args.output_dir)

    if args.report_path:
        config.report_path = Path(args.report_path)

    # Override scenario weights if focusing on a specific type
    if args.scenario_type:
        config.scenario_weights = {args.scenario_type: 1.0}

    # Log configuration
    logger.info("=" * 60)
    logger.info("Chaos Monkey Test Generator")
    logger.info("=" * 60)
    logger.info("Configuration:")
    logger.info("  Duration: %d seconds (%.1f hours)", args.duration, args.duration / 3600)
    logger.info("  Batch size: %d", args.batch_size)
    logger.info("  Rate limit: %d req/min", args.rate_limit)
    logger.info("  Request delay: %.1f seconds", args.request_delay)
    logger.info("  Use LLM: %s", args.use_llm)
    logger.info("  Mutation probability: %.1f%%", args.mutation_prob * 100)
    logger.info("  Gentle mutations: %s", config.gentle_mutations)
    logger.info("  Scenario type: %s", args.scenario_type or "mixed")
    logger.info("  API URL: %s", args.api_url)
    logger.info("  Output dir: %s", config.generated_tests_dir)
    logger.info("  Report path: %s", config.report_path)
    logger.info("=" * 60)
    logger.info("Press Ctrl+C to stop gracefully")
    logger.info("=" * 60)

    # Create and run
    runner = ChaosMonkeyRunner(config=config)

    try:
        summary = runner.run()

        # Print final summary
        logger.info("=" * 60)
        logger.info("FINAL SUMMARY")
        logger.info("=" * 60)
        logger.info("Total scenarios: %d", summary.get("total", 0))
        logger.info("Passed: %d", summary.get("passed", 0))
        logger.info("Failed: %d", summary.get("failed", 0))
        logger.info("Batches: %d", summary.get("batches", 0))
        logger.info("Duration: %.1f seconds", summary.get("duration_seconds", 0))

        if summary.get("by_category"):
            logger.info("Failures by category:")
            for category, count in sorted(
                summary["by_category"].items(), key=lambda x: -x[1]
            ):
                logger.info("  %s: %d", category, count)

        logger.info("Report: %s", config.report_path)
        logger.info("=" * 60)

        # Return exit code based on failures
        if summary.get("failed", 0) > 0:
            return 1
        return 0

    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
