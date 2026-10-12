"""Pure decision logic for when to alert, decoupled from camera/input I/O for testability."""

from dataclasses import dataclass

from timing import SustainTimer


@dataclass
class AlertDecision:
    """Result of one state-machine update."""

    should_beep: bool
    status: str  # "monitoring" | "looking_down" | "phone_detected" | "paused"
    reason: str | None = None  # "phone" | "doomscroll" | None


class DoomscrollStateMachine:
    """Combines phone-visibility and gaze/keyboard signals into a single alert decision.

    Two independent triggers, each backed by its own sustain timer:
      - "phone": a phone is continuously visible for `phone_sustain_seconds`.
      - "doomscroll": the user is looking down, a face is detected, and no keyboard/mouse
        activity has occurred for `gaze_idle_input_seconds`, and that combined condition
        holds for `gaze_sustain_seconds`.

    While either trigger stays active, alerts repeat every `cooldown_seconds` so the
    user cannot simply ignore a single beep. Switching triggers (e.g. phone -> doomscroll)
    always alerts immediately, since it represents a new situation.
    """

    def __init__(
        self,
        phone_sustain_seconds: float,
        gaze_idle_input_seconds: float,
        gaze_sustain_seconds: float,
        cooldown_seconds: float,
    ) -> None:
        self._gaze_idle_input_seconds = gaze_idle_input_seconds
        self._cooldown_seconds = cooldown_seconds

        self._phone_timer = SustainTimer(min_duration_seconds=phone_sustain_seconds)
        self._gaze_timer = SustainTimer(min_duration_seconds=gaze_sustain_seconds)

        self._active_reason: str | None = None
        self._last_alert_at: float | None = None

    def reset(self) -> None:
        """Clear all timers and alert state, e.g. when pausing or on a fresh start."""
        self._phone_timer.reset()
        self._gaze_timer.reset()
        self._active_reason = None
        self._last_alert_at = None

    def progress_ratio(self, now: float) -> float:
        """How close the currently-active timer is to firing, in [0, 1], for the debug overlay."""
        if self._phone_timer.started_at is not None:
            return min(1.0, self._phone_timer.elapsed(now) / self._phone_timer.min_duration_seconds)
        if self._gaze_timer.started_at is not None:
            return min(1.0, self._gaze_timer.elapsed(now) / self._gaze_timer.min_duration_seconds)
        return 0.0

    def update(
        self,
        now: float,
        phone_visible: bool,
        face_detected: bool,
        looking_down: bool,
        input_idle_seconds: float,
        paused: bool = False,
    ) -> AlertDecision:
        if paused:
            self.reset()
            return AlertDecision(should_beep=False, status="paused")

        phone_sustained = self._phone_timer.update(phone_visible, now)

        doomscroll_condition = (
            face_detected and looking_down and input_idle_seconds >= self._gaze_idle_input_seconds
        )
        gaze_sustained = self._gaze_timer.update(doomscroll_condition, now)

        if phone_sustained:
            reason = "phone"
        elif gaze_sustained:
            reason = "doomscroll"
        else:
            reason = None

        should_beep = False
        if reason is not None:
            new_episode = reason != self._active_reason
            cooldown_elapsed = (
                self._last_alert_at is None or (now - self._last_alert_at) >= self._cooldown_seconds
            )
            if new_episode or cooldown_elapsed:
                should_beep = True
                self._last_alert_at = now
        else:
            self._last_alert_at = None

        self._active_reason = reason

        if phone_sustained:
            status = "phone_detected"
        elif face_detected and looking_down:
            status = "looking_down"
        else:
            status = "monitoring"

        return AlertDecision(should_beep=should_beep, status=status, reason=reason)
