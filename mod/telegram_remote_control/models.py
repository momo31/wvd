"""Data contracts for Telegram remote control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum


class RemoteCommand(str, Enum):
    START = "start"
    STOP = "stop"
    STATUS = "status"


class StartReason(str, Enum):
    LOCAL = "local"
    TELEGRAM = "telegram"


class ControlState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    RETURNING_TO_TOWN = "returning_to_town"
    RETURNING_TO_TITLE = "returning_to_title"
    AT_TITLE = "at_title"
    GAME_STOPPED_FALLBACK = "game_stopped_fallback"
    ERROR = "error"


class TaskExitReason(str, Enum):
    COMPLETED = "completed"
    LOCAL_STOP = "local_stop"
    REMOTE_STOP = "remote_stop"
    REMOTE_STOP_FALLBACK = "remote_stop_fallback"
    ERROR = "error"


class CheckpointKind(str, Enum):
    DUNGEON_STABLE = "dungeon_stable"
    BETWEEN_OPERATIONS = "between_operations"
    TOWN_STABLE = "town_stable"


class NotificationPriority(IntEnum):
    TERMINAL = 0
    ACKNOWLEDGEMENT = 10
    PROGRESS = 20


class ServiceStatus(str, Enum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RETRYING = "retrying"
    ERROR = "error"
    STOPPED = "stopped"


class TransitionStatus(str, Enum):
    TOWN_READY = "town_ready"
    AT_TITLE = "at_title"
    GAME_READY = "game_ready"
    FALLBACK_COMPLETE = "fallback_complete"
    LOCAL_ABORT = "local_abort"
    ERROR = "error"


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool
    bot_token: str
    allowed_chat_id: str


@dataclass(frozen=True)
class TelegramCommandPayload:
    command: RemoteCommand
    update_id: int
    chat_id: str
    received_at: datetime
    service_generation: int


@dataclass(frozen=True)
class RemoteProgressPayload:
    run_id: str
    state: ControlState
    detail: str = ""


@dataclass(frozen=True)
class TaskFinishedPayload:
    run_id: str
    reason: TaskExitReason
    detail: str
    farm_target_text: str
    started_at: datetime
    stop_requested_at: datetime | None
    finished_at: datetime
    elapsed_seconds: float
    failure_phase: str | None = None
    notification_chat_id: str | None = None


@dataclass(frozen=True)
class StatusSnapshot:
    state: ControlState
    run_id: str | None
    farm_target_text: str | None
    started_at: datetime | None
    stop_requested_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class OutboundMessage:
    key: str
    chat_id: str
    text: str
    priority: NotificationPriority


@dataclass(frozen=True)
class TransitionOutcome:
    status: TransitionStatus
    detail: str = ""
    failure_phase: str | None = None


@dataclass(frozen=True)
class ConnectionTestRequest:
    request_id: str
    settings: TelegramSettings


@dataclass(frozen=True)
class ConnectionTestResult:
    request_id: str
    succeeded: bool
    public_message: str


@dataclass(frozen=True)
class ServiceStatusPayload:
    service_generation: int
    status: ServiceStatus
    public_message: str = ""


@dataclass(frozen=True)
class ForceStopResult:
    run_id: str
    game_stopped: bool
    public_message: str


class RemoteStopSignal(Exception):
    """Raised at a safe point when a remote stop can begin."""

    def __init__(self, checkpoint_kind: CheckpointKind):
        self.checkpoint_kind = checkpoint_kind
        super().__init__(checkpoint_kind.value)


class RemoteRecoverySuppressed(Exception):
    """Raised when an existing recovery path would restart the game."""

    def __init__(self, operation: str):
        self.operation = _sanitize_phase(operation)
        super().__init__(self.operation)


class BoundedOperationTimeout(Exception):
    """Raised when a legacy operation outlives its bounded step."""

    def __init__(self, failure_phase: str):
        self.failure_phase = _sanitize_phase(failure_phase)
        super().__init__(self.failure_phase)


def _sanitize_phase(value: str) -> str:
    value = str(value or "unknown")
    sanitized = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value)
    return sanitized[:80] or "unknown"

