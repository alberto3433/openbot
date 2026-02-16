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
        self.false_positives: int = 0
        self.start_time: datetime | None = None

    def start_session(self) -> None:
        """Mark the start of a test session."""
        self.start_time = datetime.now()
        self.failures = []
        self.passes = 0
        self.false_positives = 0

    def record_false_positive(self) -> None:
        """Record a false positive (failure that didn't reproduce on retry)."""
        self.false_positives += 1

    def record_result(self, result: ScenarioResult) -> None:
        """Record a scenario result.

        Args:
            result: The scenario result to record.
        """
        if result.passed:
            self.passes += 1
        else:
            self.failures.append(result)

    def _get_dedup_key(self, result: ScenarioResult) -> str:
        """Generate a dedup key for grouping similar failures.

        Key format: scenario_type | trick_type (if tricky) | failure_pattern

        Args:
            result: The failed scenario result.

        Returns:
            A string key for dedup grouping.
        """
        # Extract trick type from name like "Tricky (change_config): X"
        trick_match = re.search(r"Tricky \((\w+)\)", result.scenario_name)
        trick_type = trick_match.group(1) if trick_match else ""

        # Normalize failure summary to a pattern
        failure_pattern = self._normalize_failure_pattern(
            result.failure_summary or ""
        )

        parts = [result.scenario_type]
        if trick_type:
            parts.append(trick_type)
        parts.append(failure_pattern)
        return " | ".join(parts)

    def _normalize_failure_pattern(self, summary: str) -> str:
        """Normalize a failure summary into a short pattern string.

        Args:
            summary: The raw failure summary text.

        Returns:
            A normalized pattern string.
        """
        s = summary.lower()
        if "don't have" in s or "not on our menu" in s or "don't carry" in s:
            return "item_not_recognized"
        if "couldn't find" in s or "not in" in s:
            return "modifier_not_in_order"
        if "not added" in s or "not in cart" in s:
            return "item_not_added"
        if "wrong price" in s or "price" in s:
            return "pricing_error"
        if "wrong question" in s or "expected question" in s:
            return "wrong_question"
        if "disambiguation" in s:
            return "disambiguation"
        if "500" in s or "error" in s or "timeout" in s:
            return "system_error"
        # Fallback: use first 60 chars of the summary as the pattern
        return re.sub(r"[^a-z0-9_]+", "_", s[:60]).strip("_")

    def _group_failures(
        self, failures: list[ScenarioResult]
    ) -> list[tuple[str, list[ScenarioResult]]]:
        """Group failures by dedup key, sorted by count descending.

        Args:
            failures: List of failed scenario results.

        Returns:
            List of (dedup_key, group) tuples sorted by group size.
        """
        groups: dict[str, list[ScenarioResult]] = defaultdict(list)
        for failure in failures:
            key = self._get_dedup_key(failure)
            groups[key].append(failure)
        return sorted(groups.items(), key=lambda x: -len(x[1]))

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
        ]
        if self.false_positives > 0:
            lines.append(f"**False Positives (not reproduced):** {self.false_positives}")
        lines.extend(["", "---", ""])

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

            # Detailed failures by category, deduplicated
            for category, failures in sorted(
                by_category.items(), key=lambda x: -len(x[1])
            ):
                grouped = self._group_failures(failures)
                distinct = len(grouped)
                lines.append(
                    f"## {category.value} ({len(failures)} failures, "
                    f"{distinct} distinct patterns)"
                )
                lines.append("")

                for dedup_key, group in grouped:
                    representative = group[0]
                    others = group[1:]
                    similar_suffix = (
                        f" (+{len(others)} similar)" if others else ""
                    )

                    lines.append(
                        f"### {representative.scenario_name}{similar_suffix}"
                    )
                    lines.append("")
                    lines.append(f"**Count:** {len(group)}")
                    lines.append(f"**Pattern:** `{dedup_key}`")
                    lines.append(f"**Type:** {representative.scenario_type}")
                    lines.append(
                        f"**Session:** `{representative.session_id or 'N/A'}`"
                    )
                    lines.append("")

                    if representative.failure_summary:
                        lines.append(
                            f"**Failure:** {representative.failure_summary}"
                        )
                        lines.append("")

                    # Show conversation for representative
                    lines.append("**Conversation:**")
                    lines.append("```")
                    for turn in representative.turns:
                        lines.append(f"User: {turn.user_input}")
                        if turn.actual_response:
                            resp = turn.actual_response[:200]
                            if len(turn.actual_response) > 200:
                                resp += "..."
                            lines.append(f"Bot: {resp}")
                        if turn.passed is False:
                            lines.append(f"[FAILED: {turn.failure_reason}]")
                    lines.append("```")
                    lines.append("")

                    # Compact list of other instances
                    if others:
                        lines.append("**Other instances:**")
                        for other in others:
                            lines.append(f"- {other.scenario_name}")
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
            "false_positives": self.false_positives,
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
            lines.append(f"        result_{i} = sm.process(user_input_{i}, order)")
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
