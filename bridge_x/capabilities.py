"""Declared adapter capabilities, never inferred from a model or provider name."""
from dataclasses import asdict, dataclass
from typing import AsyncIterator, Protocol
from .schemas import ChatRequest


@dataclass(frozen=True)
class ProviderCapabilities:
    native_tools: bool
    structured_intent: bool
    response_format: bool = False
    max_tokens_parameter: bool = False
    live_verified: bool = False
    interface_status: str = "offline_test_only"

    def public(self):
        return asdict(self)


class Provider(Protocol):
    def generate(self, req: ChatRequest, messages: list[dict]) -> AsyncIterator[object]: ...


def capabilities_for(provider: str) -> ProviderCapabilities:
    if provider == "molab":
        # Native frontend calls are enabled by the manual-mode marimo API.
        # The gateway promotes native_tools only after observing a completed
        # native client call in this process, not merely from a provider name.
        return ProviderCapabilities(False, True, interface_status="marimo_frontend_tools_adapter")
    if provider == "openai-compatible":
        return ProviderCapabilities(True, True, interface_status="operator_supplied_api_unverified")
    return ProviderCapabilities(False, True)
