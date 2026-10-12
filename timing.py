"""Small time-based debouncing helper shared by the detector and the state machine."""

from dataclasses import dataclass


@dataclass
class SustainTimer:
    """Tracks whether a boolean condition has held continuously for a minimum duration.

    Used both to filter short blips (e.g. an eye blink misread as "looking down")
    and to require phone/gaze conditions to persist before triggering an alert.
    """

    min_duration_seconds: float
    started_at: float | None = None

    def update(self, condition: bool, now: float) -> bool:
        """Feed the current condition value and return True once it has held long enough."""
        if not condition:
            self.started_at = None
            return False
        if self.started_at is None:
            self.started_at = now
        return (now - self.started_at) >= self.min_duration_seconds

    def elapsed(self, now: float) -> float:
        """Seconds the condition has been continuously true, or 0.0 if not currently true."""
        if self.started_at is None:
            return 0.0
        return now - self.started_at

    def reset(self) -> None:
        self.started_at = None
