"""Explicit configuration. No credentials are copied into distributions or logs."""
from dataclasses import dataclass
import os
import math
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    provider: str = "fake"
    generic_url: str = ""
    generic_model: str = ""
    generic_api_key: str = ""
    local_api_key: str = "molab-local"
    molab_config_path: str = str(Path(__file__).resolve().parent.parent / ".molab_local.json")
    max_molab_response_bytes: int = 4_000_000
    journal_path: str = "bridge_x_state.sqlite3"
    # Ingress history may be much larger than the compacted provider payload.
    max_request_bytes: int = 16_000_000
    max_upstream_request_bytes: int = 1_500_000
    max_output_chars: int = 1_000_000
    # Advisory size target for a single ZCode tool action, NOT a Molab API token limit.
    max_action_chars: int = 2_200
    max_tool_args_bytes: int = 256_000
    max_message_chars: int = 65_536
    max_context_chars: int = 220_000
    heartbeat_s: float = 5.0
    timeout_s: float = 600.0
    # Library compatibility default; the Windows/CLI entry point uses native.
    molab_tool_mode: str = "structured"
    verify_molab_native_mode: bool = False
    molab_rate_control: bool = False
    molab_request_interval_s: float = 15.0
    molab_background_interval_s: float = 30.0
    molab_background_idle_s: float = 10.0
    molab_cooldown_s: float = 60.0
    molab_max_queue_wait_s: float = 120.0
    molab_rate_retries: int = 0
    molab_rate_recovery_s: float = 900.0

    def __post_init__(self):
        if self.molab_tool_mode not in ("auto", "native", "structured"):
            raise ValueError("BRIDGEX_MOLAB_TOOL_MODE must be native, auto or structured")
        for name in ("timeout_s", "heartbeat_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be a positive finite number")
        for name in ("molab_request_interval_s", "molab_background_interval_s", "molab_background_idle_s",
                     "molab_cooldown_s", "molab_max_queue_wait_s", "molab_rate_recovery_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be a positive finite number")
        for name in ("max_molab_response_bytes", "max_request_bytes", "max_upstream_request_bytes", "max_output_chars",
                     "max_tool_args_bytes", "max_message_chars", "max_context_chars"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(name + " must be a positive integer")
        if type(self.molab_rate_retries) is not int or not 0 <= self.molab_rate_retries <= 2:
            raise ValueError("molab_rate_retries must be an integer between 0 and 2")
        if self.molab_rate_retries and not self.molab_rate_control:
            raise ValueError("Safe rate retries require enabled request pacing")
        if not self.local_api_key or not self.local_api_key.strip():
            raise ValueError("BRIDGEX_LOCAL_KEY must not be empty")

    @classmethod
    def from_env(cls) -> "Settings":
        from .paths import config_path, journal_path
        vals = {
            "provider": os.getenv("BRIDGEX_PROVIDER", "molab").strip().lower(),
            "molab_config_path": os.getenv("BRIDGEX_MOLAB_CONFIG", str(config_path())),
            "generic_url": os.getenv("BRIDGEX_GENERIC_URL", ""),
            "generic_model": os.getenv("BRIDGEX_GENERIC_MODEL", ""),
            "generic_api_key": os.getenv("BRIDGEX_GENERIC_API_KEY", ""),
            "local_api_key": os.getenv("BRIDGEX_LOCAL_KEY", "molab-local"),
            "journal_path": os.getenv("BRIDGEX_JOURNAL_PATH", str(journal_path())),
            "timeout_s": float(os.getenv("BRIDGEX_TIMEOUT_SECONDS", "600")),
            "max_action_chars": int(os.getenv("BRIDGEX_ACTION_CHARS", "2200")),
            "molab_tool_mode": os.getenv("BRIDGEX_MOLAB_TOOL_MODE", "native").strip().lower(),
            "verify_molab_native_mode": True,
            "molab_rate_control": True,
            "molab_request_interval_s": float(os.getenv("BRIDGEX_MOLAB_REQUEST_INTERVAL", "15")),
            "molab_background_interval_s": float(os.getenv("BRIDGEX_MOLAB_BACKGROUND_INTERVAL", "30")),
            "molab_background_idle_s": float(os.getenv("BRIDGEX_MOLAB_BACKGROUND_IDLE", "10")),
            "molab_cooldown_s": float(os.getenv("BRIDGEX_MOLAB_COOLDOWN", "60")),
            "molab_max_queue_wait_s": float(os.getenv("BRIDGEX_MOLAB_MAX_QUEUE_WAIT", "120")),
            "molab_rate_retries": int(os.getenv("BRIDGEX_MOLAB_RATE_RETRIES", "2")),
            "molab_rate_recovery_s": float(os.getenv("BRIDGEX_MOLAB_RATE_RECOVERY", "900")),
        }
        if not 1000 <= vals["max_action_chars"] <= 12000:
            raise ValueError("BRIDGEX_ACTION_CHARS must be between 1000 and 12000")
        if vals["provider"] not in ("fake", "openai-compatible", "molab"):
            raise ValueError("BRIDGEX_PROVIDER must be molab, fake or openai-compatible")
        if vals["provider"] == "openai-compatible":
            from urllib.parse import urlsplit
            url = urlsplit(vals["generic_url"])
            if url.scheme not in ("https",) or not url.netloc or url.username or url.password or url.fragment:
                raise ValueError("Supported upstream must be a documented HTTPS API endpoint")
        return cls(**vals)

    def description(self):
        return {"provider": self.provider, "live_provider_configured": self.provider in ("openai-compatible", "molab"),
                "molab_config_present": bool(self.provider == "molab" and Path(self.molab_config_path).is_file()),
                "journal_enabled": self.journal_path != ":memory:",
                "molab_tool_mode": self.molab_tool_mode,
                "action_char_budget": self.max_action_chars}
