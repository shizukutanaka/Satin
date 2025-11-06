"""
Code quality metrics and static analysis integration for Satin.

Provides:
- Cyclomatic complexity analysis (McCabe complexity)
- Maintainability index calculation
- Code metrics (LOC, LLOC, CRAP index)
- Code smell detection
- Technical debt tracking
- Quality gates and thresholds

Integrates with:
- Radon (complexity metrics)
- Pylint (code analysis)
- Flake8 (style/error checking)
- Custom analysis rules
"""

import ast
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import inspect
import re

logger = logging.getLogger(__name__)


class ComplexityLevel(str, Enum):
    """Cyclomatic complexity levels."""
    SIMPLE = "simple"  # 1-3
    MODERATE = "moderate"  # 4-7
    HIGH = "high"  # 8-10
    VERY_HIGH = "very_high"  # 11+


class CodeQualityGrade(str, Enum):
    """Code quality grade."""
    A = "A"  # 80-100
    B = "B"  # 70-79
    C = "C"  # 60-69
    D = "D"  # 50-59
    F = "F"  # < 50


@dataclass
class ComplexityMetrics:
    """Complexity metrics for a function/method."""
    name: str
    cyclomatic_complexity: int
    cognitive_complexity: int
    halstead_volume: float
    lines_of_code: int
    lines_logical: int
    crap_index: float
    nested_depth: int

    @property
    def complexity_level(self) -> ComplexityLevel:
        """Get complexity level."""
        if self.cyclomatic_complexity <= 3:
            return ComplexityLevel.SIMPLE
        elif self.cyclomatic_complexity <= 7:
            return ComplexityLevel.MODERATE
        elif self.cyclomatic_complexity <= 10:
            return ComplexityLevel.HIGH
        else:
            return ComplexityLevel.VERY_HIGH

    @property
    def is_high_complexity(self) -> bool:
        """Check if complexity is high."""
        return self.complexity_level in (ComplexityLevel.HIGH, ComplexityLevel.VERY_HIGH)

    @property
    def is_high_crap(self) -> bool:
        """Check if CRAP index is high (>30)."""
        return self.crap_index > 30


@dataclass
class FileMetrics:
    """Metrics for entire file."""
    filepath: Path
    functions: Dict[str, ComplexityMetrics] = field(default_factory=dict)
    classes: Dict[str, Dict[str, ComplexityMetrics]] = field(default_factory=dict)
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    maintainability_index: float = 0.0
    issues: List[str] = field(default_factory=list)

    @property
    def quality_grade(self) -> CodeQualityGrade:
        """Get quality grade based on maintainability index."""
        if self.maintainability_index >= 80:
            return CodeQualityGrade.A
        elif self.maintainability_index >= 70:
            return CodeQualityGrade.B
        elif self.maintainability_index >= 60:
            return CodeQualityGrade.C
        elif self.maintainability_index >= 50:
            return CodeQualityGrade.D
        else:
            return CodeQualityGrade.F

    def get_high_complexity_functions(self) -> List[ComplexityMetrics]:
        """Get all functions with high complexity."""
        high_complexity = []

        for metrics in self.functions.values():
            if metrics.is_high_complexity:
                high_complexity.append(metrics)

        for class_methods in self.classes.values():
            for metrics in class_methods.values():
                if metrics.is_high_complexity:
                    high_complexity.append(metrics)

        return sorted(
            high_complexity,
            key=lambda m: m.cyclomatic_complexity,
            reverse=True
        )

    def get_high_crap_functions(self) -> List[ComplexityMetrics]:
        """Get functions with high CRAP index."""
        high_crap = []

        for metrics in self.functions.values():
            if metrics.is_high_crap:
                high_crap.append(metrics)

        for class_methods in self.classes.values():
            for metrics in class_methods.values():
                if metrics.is_high_crap:
                    high_crap.append(metrics)

        return sorted(
            high_crap,
            key=lambda m: m.crap_index,
            reverse=True
        )


class CyclomaticComplexityVisitor(ast.NodeVisitor):
    """AST visitor for cyclomatic complexity calculation."""

    def __init__(self, name: str):
        """Initialize visitor."""
        self.name = name
        self.complexity = 1
        self.nested_depth = 0
        self.max_nested_depth = 0
        self.lines_of_code = 0
        self.decision_points = []

    def visit_If(self, node: ast.If) -> None:
        """Visit if statements."""
        self.complexity += 1
        self.decision_points.append(('if', node.lineno))
        self.nested_depth += 1
        self.max_nested_depth = max(self.max_nested_depth, self.nested_depth)
        self.generic_visit(node)
        self.nested_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        """Visit while loops."""
        self.complexity += 1
        self.decision_points.append(('while', node.lineno))
        self.nested_depth += 1
        self.max_nested_depth = max(self.max_nested_depth, self.nested_depth)
        self.generic_visit(node)
        self.nested_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        """Visit for loops."""
        self.complexity += 1
        self.decision_points.append(('for', node.lineno))
        self.nested_depth += 1
        self.max_nested_depth = max(self.max_nested_depth, self.nested_depth)
        self.generic_visit(node)
        self.nested_depth -= 1

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Visit exception handlers."""
        self.complexity += 1
        self.decision_points.append(('except', node.lineno))
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        """Visit boolean operations."""
        # Add complexity for each extra condition
        if isinstance(node.op, (ast.And, ast.Or)):
            self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Don't count lambda functions."""
        pass


class CodeComplexityAnalyzer:
    """Analyze code complexity metrics."""

    @staticmethod
    def analyze_function(
        func: callable,
        include_docstring_analysis: bool = True
    ) -> ComplexityMetrics:
        """
        Analyze function complexity.

        Args:
            func: Function to analyze
            include_docstring_analysis: Include docstring quality check

        Returns:
            ComplexityMetrics for function
        """
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):
            # Built-in or compiled function
            return ComplexityMetrics(
                name=func.__name__,
                cyclomatic_complexity=1,
                cognitive_complexity=1,
                halstead_volume=0.0,
                lines_of_code=0,
                lines_logical=0,
                crap_index=1.0,
                nested_depth=0
            )

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ComplexityMetrics(
                name=func.__name__,
                cyclomatic_complexity=999,
                cognitive_complexity=999,
                halstead_volume=0.0,
                lines_of_code=len(source.split('\n')),
                lines_logical=0,
                crap_index=999.0,
                nested_depth=0
            )

        # Find the function definition
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func.__name__:
                    func_node = node
                    break

        if func_node is None:
            return ComplexityMetrics(
                name=func.__name__,
                cyclomatic_complexity=1,
                cognitive_complexity=1,
                halstead_volume=0.0,
                lines_of_code=len(source.split('\n')),
                lines_logical=0,
                crap_index=1.0,
                nested_depth=0
            )

        visitor = CyclomaticComplexityVisitor(func.__name__)
        visitor.visit(func_node)

        loc = len(source.split('\n'))
        cognitive_complexity = CodeComplexityAnalyzer._calculate_cognitive_complexity(func_node)
        crap_index = CodeComplexityAnalyzer._calculate_crap_index(
            visitor.complexity,
            len(source.split('\n'))
        )

        return ComplexityMetrics(
            name=func.__name__,
            cyclomatic_complexity=visitor.complexity,
            cognitive_complexity=cognitive_complexity,
            halstead_volume=CodeComplexityAnalyzer._estimate_halstead_volume(source),
            lines_of_code=loc,
            lines_logical=len([l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]),
            crap_index=crap_index,
            nested_depth=visitor.max_nested_depth
        )

    @staticmethod
    def analyze_file(filepath: Path) -> FileMetrics:
        """
        Analyze entire Python file.

        Args:
            filepath: Path to Python file

        Returns:
            FileMetrics with all metrics
        """
        metrics = FileMetrics(filepath=filepath)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                source = f.read()
        except (IOError, UnicodeDecodeError):
            metrics.issues.append(f"Cannot read file: {filepath}")
            return metrics

        lines = source.split('\n')
        metrics.total_lines = len(lines)

        # Count code, comment, blank lines
        for line in lines:
            stripped = line.strip()
            if not stripped:
                metrics.blank_lines += 1
            elif stripped.startswith('#'):
                metrics.comment_lines += 1
            else:
                metrics.code_lines += 1

        # Parse AST
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            metrics.issues.append(f"Syntax error: {e}")
            return metrics

        # Analyze functions and classes
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, 'parent') and isinstance(node.parent, ast.ClassDef):
                    # Method of a class
                    class_name = node.parent.name
                    if class_name not in metrics.classes:
                        metrics.classes[class_name] = {}
                    # Analyze method
                    func_source = '\n'.join(lines[node.lineno - 1:node.end_lineno])
                    visitor = CyclomaticComplexityVisitor(node.name)
                    visitor.visit(node)
                    metrics.classes[class_name][node.name] = ComplexityMetrics(
                        name=f"{class_name}.{node.name}",
                        cyclomatic_complexity=visitor.complexity,
                        cognitive_complexity=CodeComplexityAnalyzer._calculate_cognitive_complexity(node),
                        halstead_volume=CodeComplexityAnalyzer._estimate_halstead_volume(func_source),
                        lines_of_code=node.end_lineno - node.lineno + 1,
                        lines_logical=len([l for l in func_source.split('\n') if l.strip()]),
                        crap_index=CodeComplexityAnalyzer._calculate_crap_index(
                            visitor.complexity,
                            node.end_lineno - node.lineno + 1
                        ),
                        nested_depth=visitor.max_nested_depth
                    )
                else:
                    # Module-level function
                    func_source = '\n'.join(lines[node.lineno - 1:node.end_lineno] if node.end_lineno else lines[node.lineno - 1:])
                    visitor = CyclomaticComplexityVisitor(node.name)
                    visitor.visit(node)
                    metrics.functions[node.name] = ComplexityMetrics(
                        name=node.name,
                        cyclomatic_complexity=visitor.complexity,
                        cognitive_complexity=CodeComplexityAnalyzer._calculate_cognitive_complexity(node),
                        halstead_volume=CodeComplexityAnalyzer._estimate_halstead_volume(func_source),
                        lines_of_code=node.end_lineno - node.lineno + 1 if node.end_lineno else 1,
                        lines_logical=len([l for l in func_source.split('\n') if l.strip()]),
                        crap_index=CodeComplexityAnalyzer._calculate_crap_index(
                            visitor.complexity,
                            node.end_lineno - node.lineno + 1 if node.end_lineno else 1
                        ),
                        nested_depth=visitor.max_nested_depth
                    )

        # Calculate maintainability index
        metrics.maintainability_index = CodeComplexityAnalyzer._calculate_maintainability_index(
            metrics.code_lines,
            metrics.functions,
            metrics.classes,
            metrics.comment_lines
        )

        return metrics

    @staticmethod
    def _calculate_cognitive_complexity(node: ast.AST) -> int:
        """Calculate cognitive complexity."""
        # Simplified: mostly based on cyclomatic complexity
        # Real calculation would weight nesting levels higher
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
        return complexity

    @staticmethod
    def _calculate_crap_index(cyclomatic_complexity: int, lines: int) -> float:
        """
        Calculate CRAP (Change Risk Analysis and Predictions) index.

        CRAP = C² + C*L
        where C = cyclomatic complexity, L = lines of code
        """
        c = cyclomatic_complexity
        l = lines
        return c * c + c * l

    @staticmethod
    def _estimate_halstead_volume(source: str) -> float:
        """
        Estimate Halstead volume.

        Simplified calculation: volume = N * log2(n)
        where N = total operators + operands, n = unique operators + operands
        """
        # Remove comments and strings
        lines = source.split('\n')
        code_lines = [l for l in lines if l.strip() and not l.strip().startswith('#')]
        code = '\n'.join(code_lines)

        # Count operators and operands (simplified)
        operators = len(re.findall(r'[\+\-\*/=<>!&\|]', code))
        operands = len(re.findall(r'\b\w+\b', code))

        n_total = operators + operands
        if n_total > 0 and n_total > 2:
            n_unique = len(set(re.findall(r'[\+\-\*/=<>!&\|]', code))) + len(set(re.findall(r'\b\w+\b', code)))
            volume = n_total * (2 if n_unique == 0 else (n_total / max(1, n_unique)).__format__('.2f'))
            return float(volume) if isinstance(volume, (int, float)) else 0.0
        return 0.0

    @staticmethod
    def _calculate_maintainability_index(
        loc: int,
        functions: Dict,
        classes: Dict,
        comments: int
    ) -> float:
        """
        Calculate Maintainability Index (0-100).

        Based on: volume, cyclomatic complexity, lines of code, comments
        """
        if loc == 0:
            return 100.0

        # Average cyclomatic complexity
        all_metrics = list(functions.values())
        for class_methods in classes.values():
            all_metrics.extend(class_methods.values())

        if not all_metrics:
            return 100.0

        avg_complexity = sum(m.cyclomatic_complexity for m in all_metrics) / len(all_metrics)

        # Comment ratio
        comment_ratio = (comments / loc * 100) if loc > 0 else 0

        # Maintainability index formula (simplified)
        mi = max(0, 100 - (avg_complexity * 10) - (loc / 100) + (comment_ratio * 0.5))

        return min(100.0, mi)


class CodeSmellDetector:
    """Detect code smells and anti-patterns."""

    @staticmethod
    def detect_long_functions(metrics: FileMetrics, threshold: int = 50) -> List[str]:
        """Detect functions longer than threshold."""
        issues = []

        for name, metric in metrics.functions.items():
            if metric.lines_of_code > threshold:
                issues.append(f"Long function '{name}': {metric.lines_of_code} lines")

        for class_name, methods in metrics.classes.items():
            for method_name, metric in methods.items():
                if metric.lines_of_code > threshold:
                    issues.append(
                        f"Long method '{class_name}.{method_name}': {metric.lines_of_code} lines"
                    )

        return issues

    @staticmethod
    def detect_high_complexity(metrics: FileMetrics, threshold: int = 10) -> List[str]:
        """Detect functions with high cyclomatic complexity."""
        issues = []

        for name, metric in metrics.functions.items():
            if metric.cyclomatic_complexity > threshold:
                issues.append(
                    f"High complexity '{name}': {metric.cyclomatic_complexity}"
                )

        for class_name, methods in metrics.classes.items():
            for method_name, metric in methods.items():
                if metric.cyclomatic_complexity > threshold:
                    issues.append(
                        f"High complexity '{class_name}.{method_name}': {metric.cyclomatic_complexity}"
                    )

        return issues

    @staticmethod
    def detect_insufficient_comments(metrics: FileMetrics, min_ratio: float = 0.1) -> List[str]:
        """Detect files with insufficient comments."""
        issues = []

        if metrics.code_lines > 0:
            comment_ratio = metrics.comment_lines / metrics.code_lines
            if comment_ratio < min_ratio and metrics.code_lines > 50:
                issues.append(
                    f"Insufficient comments: {comment_ratio:.2%} (threshold: {min_ratio:.2%})"
                )

        return issues


class QualityGate:
    """Quality gate enforcement."""

    def __init__(
        self,
        max_complexity: int = 10,
        max_file_loc: int = 500,
        min_comment_ratio: float = 0.05,
        min_maintainability: float = 70.0
    ):
        """
        Initialize quality gate.

        Args:
            max_complexity: Maximum allowed cyclomatic complexity
            max_file_loc: Maximum lines of code per file
            min_comment_ratio: Minimum comment to code ratio
            min_maintainability: Minimum maintainability index
        """
        self.max_complexity = max_complexity
        self.max_file_loc = max_file_loc
        self.min_comment_ratio = min_comment_ratio
        self.min_maintainability = min_maintainability

    def check(self, metrics: FileMetrics) -> Tuple[bool, List[str]]:
        """
        Check if file passes quality gate.

        Returns:
            (passed, violations) tuple
        """
        violations = []

        # Check file complexity
        if metrics.maintainability_index < self.min_maintainability:
            violations.append(
                f"Maintainability index {metrics.maintainability_index:.1f} < {self.min_maintainability}"
            )

        # Check file size
        if metrics.code_lines > self.max_file_loc:
            violations.append(
                f"File too large: {metrics.code_lines} > {self.max_file_loc} lines"
            )

        # Check function complexity
        for name, metric in metrics.functions.items():
            if metric.cyclomatic_complexity > self.max_complexity:
                violations.append(
                    f"Function '{name}' complexity {metric.cyclomatic_complexity} > {self.max_complexity}"
                )

        # Check comment ratio
        if metrics.code_lines > 50:
            ratio = metrics.comment_lines / metrics.code_lines if metrics.code_lines > 0 else 0
            if ratio < self.min_comment_ratio:
                violations.append(
                    f"Comment ratio {ratio:.2%} < {self.min_comment_ratio:.2%}"
                )

        return len(violations) == 0, violations
