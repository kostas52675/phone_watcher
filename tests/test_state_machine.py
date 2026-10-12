import unittest

from state_machine import DoomscrollStateMachine

PHONE_SUSTAIN_SECONDS = 1.5
GAZE_IDLE_INPUT_SECONDS = 4.0
GAZE_SUSTAIN_SECONDS = 5.0
COOLDOWN_SECONDS = 10.0


def make_state_machine() -> DoomscrollStateMachine:
    return DoomscrollStateMachine(
        phone_sustain_seconds=PHONE_SUSTAIN_SECONDS,
        gaze_idle_input_seconds=GAZE_IDLE_INPUT_SECONDS,
        gaze_sustain_seconds=GAZE_SUSTAIN_SECONDS,
        cooldown_seconds=COOLDOWN_SECONDS,
    )


class TypingWhileLookingDownTests(unittest.TestCase):
    def test_no_beep_while_actively_typing(self):
        # Looking down at the keyboard while typing: input_idle_seconds stays tiny.
        sm = make_state_machine()
        for now in [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]:
            decision = sm.update(
                now=now,
                phone_visible=False,
                face_detected=True,
                looking_down=True,
                input_idle_seconds=0.3,
            )
            self.assertFalse(decision.should_beep, f"unexpected beep at now={now}")


class DoomscrollWithoutInputTests(unittest.TestCase):
    def test_looking_down_with_no_input_for_6s_beeps(self):
        sm = make_state_machine()
        # Idle input immediately exceeds the 4s threshold and looking-down holds throughout.
        decision = sm.update(now=0.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=4.5)
        self.assertFalse(decision.should_beep)

        decision = sm.update(now=3.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=7.5)
        self.assertFalse(decision.should_beep)

        decision = sm.update(now=6.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=10.5)
        self.assertTrue(decision.should_beep)
        self.assertEqual(decision.reason, "doomscroll")
        self.assertEqual(decision.status, "looking_down")

    def test_recent_keystroke_resets_the_gaze_timer(self):
        sm = make_state_machine()
        sm.update(now=0.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=5.0)
        sm.update(now=4.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=9.0)
        # A keystroke lands right before the 5s sustain would fire.
        decision = sm.update(now=4.5, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=0.1)
        self.assertFalse(decision.should_beep)
        # Even though looking-down + idle resumes, the timer restarts from here (at now=9.0).
        decision = sm.update(now=9.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=4.5)
        self.assertFalse(decision.should_beep)
        decision = sm.update(now=14.0, phone_visible=False, face_detected=True, looking_down=True, input_idle_seconds=9.5)
        self.assertTrue(decision.should_beep)


class PhoneVisibleTests(unittest.TestCase):
    def test_phone_visible_for_2s_beeps(self):
        sm = make_state_machine()
        decision = sm.update(now=0.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertFalse(decision.should_beep)
        decision = sm.update(now=2.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertTrue(decision.should_beep)
        self.assertEqual(decision.reason, "phone")
        self.assertEqual(decision.status, "phone_detected")

    def test_phone_disappearing_resets_the_timer(self):
        sm = make_state_machine()
        sm.update(now=0.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        sm.update(now=1.0, phone_visible=False, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        decision = sm.update(now=2.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertFalse(decision.should_beep)  # only 0s since it reappeared


class NoFaceTests(unittest.TestCase):
    def test_no_face_never_beeps_even_if_looking_down_flag_is_set(self):
        sm = make_state_machine()
        for now in [0.0, 5.0, 10.0, 20.0]:
            decision = sm.update(
                now=now,
                phone_visible=False,
                face_detected=False,
                looking_down=True,
                input_idle_seconds=100.0,
            )
            self.assertFalse(decision.should_beep, f"unexpected beep at now={now}")
            self.assertEqual(decision.status, "monitoring")


class RepeatAlertTests(unittest.TestCase):
    def test_repeats_every_cooldown_while_sustained_then_stops_on_recovery(self):
        sm = make_state_machine()
        sm.update(now=0.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        first = sm.update(now=2.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertTrue(first.should_beep)

        # Still sustained but cooldown hasn't elapsed yet.
        again_too_soon = sm.update(now=5.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertFalse(again_too_soon.should_beep)

        # Cooldown elapsed: re-beep so the user can't just ignore it.
        repeat = sm.update(now=12.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertTrue(repeat.should_beep)

        # Phone put away: no more alerts.
        recovered = sm.update(now=13.0, phone_visible=False, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertFalse(recovered.should_beep)
        self.assertEqual(recovered.status, "monitoring")


class PauseTests(unittest.TestCase):
    def test_paused_never_beeps_and_resets_state(self):
        sm = make_state_machine()
        sm.update(now=0.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        decision = sm.update(
            now=1.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0, paused=True
        )
        self.assertFalse(decision.should_beep)
        self.assertEqual(decision.status, "paused")

        # Resuming starts the phone timer over, since pausing reset it.
        decision = sm.update(now=2.0, phone_visible=True, face_detected=False, looking_down=False, input_idle_seconds=0.0)
        self.assertFalse(decision.should_beep)


if __name__ == "__main__":
    unittest.main()
