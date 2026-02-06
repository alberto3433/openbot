"""Main orchestrator for Chaos Monkey test generation and execution."""

import logging
import signal
import sys
import time
from datetime import datetime
from typing import Any

from tests.chaos_monkey.config import ChaosMonkeyConfig
from tests.chaos_monkey.executor import TestExecutor
from tests.chaos_monkey.generator import ScenarioGenerator
from tests.chaos_monkey.reporter import FailureReporter

logger = logging.getLogger(__name__)


class ChaosMonkeyRunner:
    """Main runner for Chaos Monkey testing."""

    def __init__(
        self,
        config: ChaosMonkeyConfig | None = None,
        menu_cache: Any = None,
    ) -> None:
        """Initialize the runner.

        Args:
            config: Configuration for the run. Uses defaults if None.
            menu_cache: Menu data cache. Will attempt to load if None.
        """
        self.config = config or ChaosMonkeyConfig()
        self.menu_cache = menu_cache
        self._shutdown_requested = False
        self._setup_signal_handlers()

        # Components
        self.generator: ScenarioGenerator | None = None
        self.executor: TestExecutor | None = None
        self.reporter: FailureReporter | None = None

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        if sys.platform != "win32":
            signal.signal(signal.SIGINT, self._handle_shutdown)
            signal.signal(signal.SIGTERM, self._handle_shutdown)
        else:
            signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown requested (signal %d)", signum)
        self._shutdown_requested = True

    def _load_menu_cache(self) -> None:
        """Load menu cache if not provided."""
        if self.menu_cache is not None:
            return

        try:
            from orderbot.cache import menu_cache as global_cache
            from orderbot.db import SessionLocal

            # Check if already loaded
            if not global_cache.is_loaded:
                logger.info("Loading menu cache from database...")
                db = SessionLocal()
                try:
                    global_cache.load_from_db(db)
                finally:
                    db.close()

            self.menu_cache = global_cache
            logger.info("Menu cache loaded successfully")

        except Exception as e:
            logger.error("Failed to load menu cache: %s", e)
            raise

    def run(self) -> dict[str, Any]:
        """Run the Chaos Monkey test session.

        Returns:
            Summary of the test session.
        """
        logger.info("Starting Chaos Monkey test session")
        logger.info("Duration: %d seconds", self.config.duration_seconds)
        logger.info("Batch size: %d", self.config.batch_size)

        # Initialize components
        self._load_menu_cache()
        self.generator = ScenarioGenerator(self.config, self.menu_cache)
        self.executor = TestExecutor(self.config)
        self.reporter = FailureReporter(self.config)

        # Load menu data
        self.generator.load_menu_data()
        menu_stats = self.generator.get_stats()
        logger.info("Menu stats: %s", menu_stats)

        # Start session
        self.reporter.start_session()
        start_time = time.time()
        end_time = start_time + self.config.duration_seconds

        batch_count = 0
        total_scenarios = 0

        try:
            while time.time() < end_time and not self._shutdown_requested:
                batch_count += 1
                logger.info("Starting batch %d", batch_count)

                # Generate scenarios
                scenarios = self.generator.generate_batch()
                logger.info("Generated %d scenarios", len(scenarios))

                # Execute scenarios
                for scenario in scenarios:
                    if self._shutdown_requested:
                        break

                    try:
                        result = self.executor.execute_scenario(scenario)
                        self.reporter.record_result(result)
                        total_scenarios += 1

                        if not result.passed:
                            logger.info(
                                "FAIL: %s - %s",
                                result.scenario_name,
                                result.failure_summary,
                            )
                        else:
                            logger.debug("PASS: %s", result.scenario_name)

                    except Exception as e:
                        logger.error(
                            "Error executing scenario %s: %s",
                            scenario.name,
                            e,
                            exc_info=True,
                        )

                # Log progress
                elapsed = time.time() - start_time
                remaining = max(0, end_time - time.time())
                summary = self.reporter.get_summary()
                logger.info(
                    "Progress: %d scenarios (%d passed, %d failed) - "
                    "%.0f seconds elapsed, %.0f remaining",
                    total_scenarios,
                    summary["passed"],
                    summary["failed"],
                    elapsed,
                    remaining,
                )

                # Batch delay
                if not self._shutdown_requested:
                    time.sleep(self.config.batch_delay_seconds)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")

        finally:
            # Cleanup
            if self.executor:
                self.executor.close()

            # Write final report
            if self.reporter:
                report_path = self.reporter.write_report()
                logger.info("Report written to: %s", report_path)

        # Return summary
        summary = self.reporter.get_summary() if self.reporter else {}
        summary["batches"] = batch_count
        summary["duration_seconds"] = time.time() - start_time
        summary["shutdown_requested"] = self._shutdown_requested

        logger.info("Chaos Monkey session complete: %s", summary)
        return summary

    def run_single_batch(self) -> dict[str, Any]:
        """Run a single batch of tests (for quick testing).

        Returns:
            Summary of the batch.
        """
        original_duration = self.config.duration_seconds
        self.config.duration_seconds = 1  # Just one iteration

        try:
            return self.run()
        finally:
            self.config.duration_seconds = original_duration
