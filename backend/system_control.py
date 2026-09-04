from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4


SystemAction = Literal["restart", "shutdown"]
ReservationResult = Literal["accepted", "unavailable", "pending"]


class ServerHandle(Protocol):
    should_exit: bool


@dataclass(frozen=True)
class SystemControlStatus:
    control_available: bool
    instance_id: str
    pending_action: SystemAction | None


class SystemController:
    """Coordinates graceful process control for the dedicated dashboard runner."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._server: ServerHandle | None = None
        self._pending_action: SystemAction | None = None
        self._instance_id = uuid4().hex

    def bind(self, server: ServerHandle) -> None:
        with self._lock:
            self._server = server
            self._pending_action = None

    def status(self) -> SystemControlStatus:
        with self._lock:
            return SystemControlStatus(
                control_available=self._server is not None,
                instance_id=self._instance_id,
                pending_action=self._pending_action,
            )

    def reserve(self, action: SystemAction) -> ReservationResult:
        with self._lock:
            if self._server is None:
                return "unavailable"
            if self._pending_action is not None:
                return "pending"
            self._pending_action = action
            return "accepted"

    def request_exit(self) -> None:
        """Run after the HTTP response has been sent to begin graceful shutdown."""
        with self._lock:
            if self._server is not None and self._pending_action is not None:
                self._server.should_exit = True

    def release(self, server: ServerHandle) -> SystemAction | None:
        with self._lock:
            if self._server is not server:
                return None
            action = self._pending_action
            self._server = None
            self._pending_action = None
            return action

    def reset_for_tests(self) -> None:
        with self._lock:
            self._server = None
            self._pending_action = None


system_controller = SystemController()
