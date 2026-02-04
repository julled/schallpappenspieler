"""
State tracking for QR code detections with stability-based triggering.

Prevents spurious triggers from transient QR detections by requiring
a configurable stability period before firing events.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SideState:
    """Current state for one side (left or right) of the detection area."""

    current_text: Optional[str] = None
    first_seen: Optional[float] = None
    last_seen: Optional[float] = None
    triggered: bool = False


@dataclass
class TriggerEvent:
    """Event fired when a QR code detection becomes stable."""

    side: str  # "left" or "right"
    text: str  # QR code content


class StateTracker:
    """
    Tracks detection stability across left and right sides.

    Timing behavior:
    - stable_seconds: How long a detection must persist before triggering
    - dropout_seconds: Max time without detection before resetting stability
    - forget_seconds: Max time without detection before clearing state entirely

    This prevents accidental triggers from momentary QR code appearances.
    """

    def __init__(
        self, stable_seconds: float, dropout_seconds: float, forget_seconds: float
    ):
        self.stable_seconds = stable_seconds
        self.dropout_seconds = dropout_seconds
        self.forget_seconds = forget_seconds
        self.left = SideState()
        self.right = SideState()

    def update(
        self, side: str, detected_text: Optional[str], now: float
    ) -> Optional[TriggerEvent]:
        state = self.left if side == "left" else self.right

        if detected_text is None:
            if state.last_seen is None:
                return None
            time_since_seen = now - state.last_seen
            if time_since_seen > self.forget_seconds:
                state.current_text = None
                state.first_seen = None
                state.last_seen = None
                state.triggered = False
            elif time_since_seen > self.dropout_seconds:
                state.first_seen = None
            return None

        if state.current_text != detected_text:
            state.current_text = detected_text
            state.first_seen = now
            state.last_seen = now
            state.triggered = False
            return None

        state.last_seen = now
        if state.first_seen is None:
            state.first_seen = now
            return None

        if not state.triggered and (now - state.first_seen) >= self.stable_seconds:
            state.triggered = True
            return TriggerEvent(side=side, text=detected_text)

        return None
