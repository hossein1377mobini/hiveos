"""Tool implementations. Importing this package registers every tool.

The import is what performs registration, so the loop must import it before
building a provider payload. Kept explicit rather than a filesystem scan: a
scan would make tool availability depend on deploy contents, and a typo in a
filename would silently remove a tool instead of failing the import.
"""

from backend.agent.tools import chart_tool, report_tool  # noqa: F401  (registration side effect)

__all__ = ["chart_tool", "report_tool"]
