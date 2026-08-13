"""Telegram remote-control feature public API."""

from .adapters import ControllerPorts, GameAutomationAdapter
from .config import extend_config_var_list
from .feature import TelegramRemoteFeature
from .models import (
    CheckpointKind,
    ControlState,
    RemoteStopSignal,
    StartReason,
    TaskExitReason,
    TelegramSettings,
)
from .runtime_bridge import RemoteRuntime

__all__ = [
    "ControllerPorts",
    "GameAutomationAdapter",
    "CheckpointKind",
    "ControlState",
    "RemoteStopSignal",
    "RemoteRuntime",
    "StartReason",
    "TaskExitReason",
    "TelegramRemoteFeature",
    "TelegramSettings",
    "extend_config_var_list",
]
