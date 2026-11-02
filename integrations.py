"""Future adapter contracts. No API keys, SDKs, or network calls in phase one."""
from typing import Protocol, Iterable, Mapping, Any

class ResearchProvider(Protocol):
    def research(self, keyword_or_url: str) -> Mapping[str, Any]:
        """Return a tool object matching collector.FIELDS for local validation."""
        ...

class SheetsConnector(Protocol):
    def export_tools(self, tools: Iterable[Mapping[str, Any]]) -> None:
        ...
    def import_tools(self) -> Iterable[Mapping[str, Any]]:
        ...
