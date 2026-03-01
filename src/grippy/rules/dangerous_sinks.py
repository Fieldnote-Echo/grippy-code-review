# SPDX-License-Identifier: MIT
"""Rule 3: dangerous-execution-sinks — eval/exec/subprocess/pickle detection."""

from __future__ import annotations

import re

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.context import RuleContext

# Python dangerous sinks
_PYTHON_SINKS: list[tuple[str, re.Pattern[str]]] = [
    ("eval()", re.compile(r"\beval\s*\(")),
    ("exec()", re.compile(r"\bexec\s*\(")),
    ("os.system()", re.compile(r"\bos\.system\s*\(")),
    ("os.popen()", re.compile(r"\bos\.popen\s*\(")),
    ("subprocess with shell=True", re.compile(r"\bsubprocess\.\w+\(.*shell\s*=\s*True")),
    ("pickle.loads()", re.compile(r"\bpickle\.loads?\s*\(")),
    ("marshal.loads()", re.compile(r"\bmarshal\.loads?\s*\(")),
]

# yaml.load without SafeLoader — special handling
_YAML_LOAD_RE = re.compile(r"\byaml\.load\s*\(")
_YAML_SAFE_RE = re.compile(r"\b(?:yaml\.safe_load|SafeLoader|CSafeLoader)\b")

# JS/TS dangerous sinks
_JS_SINKS: list[tuple[str, re.Pattern[str]]] = [
    ("eval()", re.compile(r"\beval\s*\(")),
    ("new Function()", re.compile(r"\bnew\s+Function\s*\(")),
    ("require('child_process')", re.compile(r"""require\s*\(\s*['"]child_process['"]\s*\)""")),
    ("execSync()", re.compile(r"\bexecSync\s*\(")),
    ("spawnSync()", re.compile(r"\bspawnSync\s*\(")),
]

_PYTHON_EXTENSIONS = frozenset({".py"})
_JS_EXTENSIONS = frozenset({".js", ".ts", ".jsx", ".tsx"})


def _file_ext(path: str) -> str:
    """Get file extension including the dot."""
    dot = path.rfind(".")
    return path[dot:] if dot >= 0 else ""


class DangerousSinksRule:
    """Detect dangerous execution sinks in Python and JavaScript/TypeScript."""

    id = "dangerous-execution-sinks"
    description = "Flag eval, exec, subprocess shell=True, pickle, and JS equivalents"
    default_severity = RuleSeverity.ERROR

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for f in ctx.files:
            ext = _file_ext(f.path)
            if ext in _PYTHON_EXTENSIONS:
                results.extend(self._scan_python(f.path, ctx))
            elif ext in _JS_EXTENSIONS:
                results.extend(self._scan_js(f.path, ctx))
        return results

    def _scan_python(self, path: str, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        added = [(ln, content) for _, ln, content in ctx.added_lines_for(path)]
        for lineno, content in added:
            # Standard sinks
            for name, pattern in _PYTHON_SINKS:
                if pattern.search(content):
                    results.append(
                        RuleResult(
                            rule_id=self.id,
                            severity=self.default_severity,
                            message=f"Dangerous execution sink: {name}",
                            file=path,
                            line=lineno,
                            evidence=content.strip(),
                        )
                    )
                    break  # one finding per line

            # yaml.load without safe loader
            if _YAML_LOAD_RE.search(content) and not _YAML_SAFE_RE.search(content):
                results.append(
                    RuleResult(
                        rule_id=self.id,
                        severity=self.default_severity,
                        message="Dangerous execution sink: yaml.load() without SafeLoader",
                        file=path,
                        line=lineno,
                        evidence=content.strip(),
                    )
                )

        return results

    def _scan_js(self, path: str, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        added = [(ln, content) for _, ln, content in ctx.added_lines_for(path)]
        for lineno, content in added:
            for name, pattern in _JS_SINKS:
                if pattern.search(content):
                    results.append(
                        RuleResult(
                            rule_id=self.id,
                            severity=self.default_severity,
                            message=f"Dangerous execution sink: {name}",
                            file=path,
                            line=lineno,
                            evidence=content.strip(),
                        )
                    )
                    break
        return results
