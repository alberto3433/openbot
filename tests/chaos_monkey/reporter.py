"""Failure reporting and pytest file generation for Chaos Monkey tests."""

import hashlib
import logging
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.chaos_monkey.config import ChaosMonkeyConfig
from tests.chaos_monkey.scenarios.base import (
    ConversationTurn,
    FailureCategory,
    ScenarioResult,
)

logger = logging.getLogger(__name__)


class FailureReporter:
    """Reports test failures to a markdown file."""

    def __init__(self, config: ChaosMonkeyConfig) -> None:
        """Initialize the reporter.

        Args:
            config: Chaos Monkey configuration.
        """
        self.config = config
        self.failures: list[ScenarioResult] = []
        self.passes: int = 0
        self.start_time: datetime | None = None

    def start_session(self) -> None:
        """Mark the start of a test session."""
        self.start_time = datetime.now()
        self.failures = []
        self.passes = 0

    def record_result(self, result: ScenarioResult) -> None:
        """Record a scenario result.

        Args:
            result: The scenario result to record.
        """
        if result.passed:
            self.passes += 1
        else:
            self.failures.append(result)

    def write_report(self) -> Path:
        """Write the failure report to the configured path.

        Returns:
            Path to the written report file.
        """
        report_path = self.config.report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)

        # Group failures by category
        by_category: dict[FailureCategory, list[ScenarioResult]] = defaultdict(list)
        for failure in self.failures:
            category = failure.failure_category or FailureCategory.OTHER
            by_category[category].append(failure)

        # Build report content
        lines = [
            "# Chaos Monkey Test Failures",
            "",
            f"**Generated:** {datetime.now().isoformat()}",
            f"**Session Start:** {self.start_time.isoformat() if self.start_time else 'N/A'}",
            f"**Total Tests:** {self.passes + len(self.failures)}",
            f"**Passed:** {self.passes}",
            f"**Failed:** {len(self.failures)}",
            "",
            "---",
            "",
        ]

        if not self.failures:
            lines.append("No failures recorded.")
        else:
            # Summary by category
            lines.append("## Summary by Category")
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|----------|-------|")
            for category, failures in sorted(
                by_category.items(), key=lambda x: -len(x[1])
            ):
                lines.append(f"| {category.value} | {len(failures)} |")
            lines.append("")

            # Detailed failures by category
            for category, failures in sorted(
                by_category.items(), key=lambda x: -len(x[1])
            ):
                lines.append(f"## {category.value}")
                lines.append("")

                for failure in failures[:10]:  # Limit to 10 per category
                    lines.append(f"### {failure.scenario_name}")
                    lines.append("")
                    lines.append(f"**Type:** {failure.scenario_type}")
                    lines.append(f"**Session:** `{failure.session_id or 'N/A'}`")
                    lines.append("")

                    if failure.failure_summary:
                        lines.append(f"**Failure:** {failure.failure_summary}")
                        lines.append("")

                    # Show conversation
                    lines.append("**Conversation:**")
                    lines.append("```")
                    for i, turn in enumerate(failure.turns):
                        lines.append(f"User: {turn.user_input}")
                        if turn.actual_response:
                            # Truncate long responses
                            resp = turn.actual_response[:200]
                            if len(turn.actual_response) > 200:
                                resp += "..."
                            lines.append(f"Bot: {resp}")
                        if turn.passed is False:
                            lines.append(f"[FAILED: {turn.failure_reason}]")
                    lines.append("```")
                    lines.append("")

                if len(failures) > 10:
                    lines.append(
                        f"*... and {len(failures) - 10} more failures in this category*"
                    )
                    lines.append("")

        # Write the report
        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Failure report written to %s", report_path)

        return report_path

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the test results.

        Returns:
            Summary dict with counts and categories.
        """
        by_category = defaultdict(int)
        for failure in self.failures:
            category = failure.failure_category or FailureCategory.OTHER
            by_category[category.value] += 1

        return {
            "total": self.passes + len(self.failures),
            "passed": self.passes,
            "failed": len(self.failures),
            "by_category": dict(by_category),
        }


class PytestFileGenerator:
    """Generates pytest test files from failed scenarios."""

    def __init__(self, config: ChaosMonkeyConfig) -> None:
        """Initialize the generator.

        Args:
            config: Chaos Monkey configuration.
        """
        self.config = config
        self.output_dir = config.generated_tests_dir

    def generate_test_file(self, result: ScenarioResult) -> Path | None:
        """Generate a pytest file for a failed scenario.

        Args:
            result: The failed scenario result.

        Returns:
            Path to the generated test file, or None if generation failed.
        """
        if result.passed:
            return None

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique test ID
        test_id = self._generate_test_id(result)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_failure_{result.scenario_type}_{timestamp}_{test_id}.py"
        filepath = self.output_dir / filename

        # Generate test content
        content = self._generate_test_content(result, test_id)

        filepath.write_text(content, encoding="utf-8")
        logger.info("Generated test file: %s", filepath)

        return filepath

    def _generate_test_id(self, result: ScenarioResult) -> str:
        """Generate a unique 8-char test ID."""
        data = f"{result.scenario_name}:{result.session_id}:{datetime.now().isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:8]

    def _generate_test_content(self, result: ScenarioResult, test_id: str) -> str:
        """Generate the pytest file content."""
        lines = [
            '"""',
            f"Auto-generated test from Chaos Monkey failure.",
            f"",
            f"Scenario: {result.scenario_name}",
            f"Type: {result.scenario_type}",
            f"Category: {result.failure_category.value if result.failure_category else 'Unknown'}",
            f"Generated: {datetime.now().isoformat()}",
            '"""',
            "",
            "import pytest",
            "",
            "from orderbot.tasks.models import OrderTask",
            "from orderbot.tasks.state_machine import OrderStateMachine",
            "",
            "",
            f"class TestChaosMonkeyFailure_{test_id}:",
            f'    """Regression test for: {self._escape_docstring(result.scenario_name)}"""',
            "",
            "    def test_scenario(self) -> None:",
            f'        """Test the failing scenario."""',
            "        # Initialize order",
            "        order = OrderTask()",
            '        order.phase = "taking_items"',
            "        sm = OrderStateMachine()",
            "",
        ]

        # Add conversation turns
        first_failure: ConversationTurn | None = None
        for i, turn in enumerate(result.turns):
            user_input = self._escape_string(turn.user_input)
            lines.append(f"        # Turn {i + 1}")
            lines.append(f'        user_input_{i} = "{user_input}"')
            lines.append(f"        result_{i} = sm.process_message(order, user_input_{i})")
            lines.append("")

            if turn.passed is False and first_failure is None:
                first_failure = turn

        # Add assertion for the failure
        if first_failure:
            failure_reason = self._escape_string(first_failure.failure_reason or "Unknown failure")
            lines.append("        # Verify the expected behavior")
            lines.append(f"        # Original failure: {failure_reason}")

            # Add appropriate assertion based on expected actions
            if first_failure.expected_actions:
                expected = first_failure.expected_actions[0]
                lines.append(
                    f'        # Expected action: {expected.action_type.value}'
                )
                if expected.item_name:
                    item_name = self._escape_string(expected.item_name)
                    lines.append(
                        f'        assert any("{item_name.lower()}" in item.get("name", "").lower() '
                        f'for item in order.items.to_dict().get("items", [])), \\'
                    )
                    lines.append(
                        f'            f"Expected item \'{item_name}\' in cart"'
                    )
                else:
                    lines.append("        # TODO: Add specific assertions")
                    lines.append("        assert False, \"Test needs manual review\"")
            else:
                lines.append("        # TODO: Add specific assertions")
                lines.append("        assert False, \"Test needs manual review\"")

        lines.append("")

        return "\n".join(lines)

    def _escape_string(self, s: str) -> str:
        """Escape a string for use in Python code."""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def _escape_docstring(self, s: str) -> str:
        """Escape a string for use in a docstring."""
        return s.replace('"""', "'''").replace("\n", " ")

    def cleanup_passing_tests(self) -> int:
        """Run pytest on generated tests and delete those that pass.

        Returns:
            Number of test files deleted.
        """
        if not self.output_dir.exists():
            return 0

        test_files = list(self.output_dir.glob("test_*.py"))
        if not test_files:
            return 0

        deleted = 0
        for test_file in test_files:
            try:
                # Run pytest on this specific file
                result = subprocess.run(
                    ["python", "-m", "pytest", str(test_file), "-v", "--tb=no"],
                    capture_output=True,
                    timeout=60,
                )

                # If test passes (exit code 0), delete the file
                if result.returncode == 0:
                    test_file.unlink()
                    deleted += 1
                    logger.info("Deleted passing test: %s", test_file.name)

            except subprocess.TimeoutExpired:
                logger.warning("Test timed out: %s", test_file.name)
            except Exception as e:
                logger.error("Error running test %s: %s", test_file.name, e)

        if deleted > 0:
            logger.info("Cleaned up %d passing test files", deleted)

        return deleted
