"""
Test to detect hardcoded domain-specific food data in production code.

This enforces the data-driven architecture principle: all food-domain knowledge
should come from the database, not hardcoded in Python code.
"""

import ast
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
import yaml


@dataclass
class Violation:
    """A detected domain term violation."""

    file: Path
    line: int
    term: str
    context: str  # 'code', 'docstring', or 'comment'
    snippet: str  # The actual line of code


class DomainTermScanner:
    """Scans Python files for hardcoded domain-specific terms."""

    def __init__(self, terms_file: Path, allowlist_file: Path):
        self.terms = self._load_terms(terms_file)
        self.allowlist = self._load_allowlist(allowlist_file)
        # Sort terms by length (longest first) for correct multi-word matching
        self.sorted_terms = sorted(self.terms, key=len, reverse=True)
        # Build regex pattern for whole-word matching
        escaped_terms = [re.escape(t) for t in self.sorted_terms]
        self.pattern = re.compile(
            r"\b(" + "|".join(escaped_terms) + r")\b", re.IGNORECASE
        )

    def _load_terms(self, terms_file: Path) -> set[str]:
        """Load domain terms from YAML file."""
        if not terms_file.exists():
            return set()

        with open(terms_file) as f:
            data = yaml.safe_load(f)

        terms = set()
        for category, term_list in data.items():
            if isinstance(term_list, list):
                for term in term_list:
                    terms.add(term.lower())
        return terms

    def _load_allowlist(self, allowlist_file: Path) -> dict:
        """Load allowlist from YAML file."""
        if not allowlist_file.exists():
            return {}

        with open(allowlist_file) as f:
            data = yaml.safe_load(f)

        return data or {}

    def _is_allowlisted(
        self, rel_path: str, line: int, term: str, context: str
    ) -> bool:
        """Check if a violation is in the allowlist."""
        # Check for file-level wildcard
        if rel_path in self.allowlist:
            entries = self.allowlist[rel_path]
            if entries == "*":
                return True
            for entry in entries:
                if entry.get("term") == "*":
                    return True
                if entry.get("term", "").lower() == term.lower():
                    # Check context if specified
                    entry_context = entry.get("context", "all")
                    if entry_context != "all" and entry_context != context:
                        continue
                    # Check line range if specified
                    line_range = entry.get("line_range")
                    if line_range:
                        if not (line_range[0] <= line <= line_range[1]):
                            continue
                    return True
        return False

    def _extract_strings_from_ast(
        self, source: str
    ) -> Iterator[tuple[int, str, str]]:
        """
        Extract string literals from AST with context.

        Yields: (line_number, string_value, context)
        context is 'docstring' or 'code'
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        # First, collect all docstring positions
        docstring_positions = set()

        for node in ast.walk(tree):
            # Module, class, and function docstrings
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_positions.add(id(node.body[0].value))

        # Now extract all string constants
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                context = "docstring" if id(node) in docstring_positions else "code"
                yield (node.lineno, node.value, context)

    def _extract_comments(self, source: str) -> Iterator[tuple[int, str]]:
        """Extract comments using tokenize."""
        try:
            tokens = tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__)
            for token in tokens:
                if token.type == tokenize.COMMENT:
                    yield (token.start[0], token.string)
        except tokenize.TokenizeError:
            pass

    def scan_file(self, file_path: Path, base_path: Path) -> list[Violation]:
        """Scan a single file for domain term violations."""
        violations = []
        rel_path = str(file_path.relative_to(base_path)).replace("\\", "/")

        try:
            source = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return violations

        lines = source.splitlines()

        # Scan string literals from AST
        for line_no, string_val, context in self._extract_strings_from_ast(source):
            for match in self.pattern.finditer(string_val):
                term = match.group(1).lower()
                if not self._is_allowlisted(rel_path, line_no, term, context):
                    snippet = lines[line_no - 1] if line_no <= len(lines) else ""
                    violations.append(
                        Violation(
                            file=file_path,
                            line=line_no,
                            term=term,
                            context=context,
                            snippet=snippet.strip(),
                        )
                    )

        # Scan comments
        for line_no, comment_text in self._extract_comments(source):
            for match in self.pattern.finditer(comment_text):
                term = match.group(1).lower()
                if not self._is_allowlisted(rel_path, line_no, term, "comment"):
                    snippet = lines[line_no - 1] if line_no <= len(lines) else ""
                    violations.append(
                        Violation(
                            file=file_path,
                            line=line_no,
                            term=term,
                            context="comment",
                            snippet=snippet.strip(),
                        )
                    )

        return violations

    def scan_directory(self, directory: Path, base_path: Path) -> list[Violation]:
        """Scan all Python files in a directory."""
        violations = []
        for py_file in directory.rglob("*.py"):
            violations.extend(self.scan_file(py_file, base_path))
        return violations


def format_violations(violations: list[Violation], base_path: Path) -> str:
    """Format violations for display in test output."""
    if not violations:
        return ""

    # Group by file
    by_file: dict[Path, list[Violation]] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)

    lines = ["", "=== DOMAIN DATA VIOLATIONS DETECTED ===", ""]

    for file_path, file_violations in sorted(by_file.items()):
        rel_path = file_path.relative_to(base_path)
        lines.append(f"  {rel_path}:")
        for v in sorted(file_violations, key=lambda x: x.line):
            lines.append(f"    Line {v.line}: '{v.term}' ({v.context})")
            lines.append(f"      {v.snippet}")
        lines.append("")

    lines.extend(
        [
            "To fix: Remove hardcoded terms and use database-driven approach.",
            "If this is intentional legacy code, add to tests/domain_data/allowlist.yaml",
            "",
        ]
    )

    return "\n".join(lines)


def generate_allowlist_yaml(violations: list[Violation], base_path: Path) -> str:
    """Generate YAML for allowlisting current violations."""
    # Group by file
    by_file: dict[str, list[Violation]] = {}
    for v in violations:
        rel_path = str(v.file.relative_to(base_path)).replace("\\", "/")
        by_file.setdefault(rel_path, []).append(v)

    lines = ["# Auto-generated allowlist for existing violations", ""]

    for file_path, file_violations in sorted(by_file.items()):
        lines.append(f"{file_path}:")
        # Group by term to avoid duplicates
        terms_seen: dict[str, Violation] = {}
        for v in file_violations:
            if v.term not in terms_seen:
                terms_seen[v.term] = v
        for term, v in sorted(terms_seen.items()):
            lines.append(f"  - term: {term}")
            lines.append(f"    context: all")
            lines.append(f'    reason: "Legacy code - TODO: refactor to data-driven"')
        lines.append("")

    return "\n".join(lines)


class TestNoDomainData:
    """Test that production code doesn't contain hardcoded domain data."""

    @pytest.fixture
    def scanner(self) -> DomainTermScanner:
        """Create scanner with project paths."""
        base_path = Path(__file__).parent.parent
        terms_file = Path(__file__).parent / "domain_data" / "domain_terms.yaml"
        allowlist_file = Path(__file__).parent / "domain_data" / "allowlist.yaml"
        return DomainTermScanner(terms_file, allowlist_file)

    @pytest.fixture
    def project_paths(self) -> tuple[Path, Path]:
        """Get project paths."""
        base_path = Path(__file__).parent.parent
        orderbot_path = base_path / "orderbot"
        return base_path, orderbot_path

    def test_no_domain_specific_data_in_production_code(
        self, scanner: DomainTermScanner, project_paths: tuple[Path, Path]
    ):
        """
        Verify that orderbot/ contains no hardcoded domain-specific food data.

        All food-domain knowledge (item names, ingredients, modifiers, etc.)
        should come from the database, not hardcoded in Python code.
        """
        base_path, orderbot_path = project_paths

        if not orderbot_path.exists():
            pytest.skip("orderbot/ directory not found")

        violations = scanner.scan_directory(orderbot_path, base_path)

        if violations:
            # Generate helpful output
            error_msg = format_violations(violations, base_path)
            # Also generate allowlist YAML for convenience
            allowlist_yaml = generate_allowlist_yaml(violations, base_path)
            error_msg += "\n--- Allowlist YAML (copy to allowlist.yaml if grandfathering): ---\n"
            error_msg += allowlist_yaml

            pytest.fail(error_msg)


if __name__ == "__main__":
    # When run directly, print all violations (useful for initial setup)
    import sys

    base_path = Path(__file__).parent.parent
    terms_file = Path(__file__).parent / "domain_data" / "domain_terms.yaml"
    allowlist_file = Path(__file__).parent / "domain_data" / "allowlist.yaml"

    scanner = DomainTermScanner(terms_file, allowlist_file)
    orderbot_path = base_path / "orderbot"

    violations = scanner.scan_directory(orderbot_path, base_path)

    if violations:
        # Write to file to avoid encoding issues
        output_file = Path(__file__).parent / "domain_data" / "violations_output.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(format_violations(violations, base_path))
            f.write("\n--- Allowlist YAML (copy to allowlist.yaml): ---\n")
            f.write(generate_allowlist_yaml(violations, base_path))
        print(f"Found {len(violations)} violations. Output written to: {output_file}")
    else:
        print("No violations found!")
