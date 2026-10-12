import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import punishment


class ScanVideosTests(unittest.TestCase):
    def test_scans_dotted_folder_name_and_mixed_case_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos_dir = Path(tmp) / "punishment.videos"
            videos_dir.mkdir()
            (videos_dir / "clip_a.MP4").write_bytes(b"x")
            (videos_dir / "clip_b.mov").write_bytes(b"x")
            (videos_dir / "clip_c.Mkv").write_bytes(b"x")
            (videos_dir / "notes.txt").write_bytes(b"x")

            found = punishment.scan_videos(videos_dir)

            self.assertEqual({p.name for p in found}, {"clip_a.MP4", "clip_b.mov", "clip_c.Mkv"})

    def test_missing_directory_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does.not.exist"
            self.assertEqual(punishment.scan_videos(missing), [])


class PickRandomVideoTests(unittest.TestCase):
    def test_never_repeats_the_previous_pick_when_more_than_one_video(self):
        videos = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
        previous = videos[0]
        for _ in range(50):
            picked = punishment.pick_random_video(videos, exclude=previous)
            self.assertNotEqual(picked, previous)
            previous = picked

    def test_single_video_is_allowed_to_repeat(self):
        videos = [Path("only.mp4")]
        self.assertEqual(punishment.pick_random_video(videos, exclude=videos[0]), videos[0])

    def test_empty_list_returns_none(self):
        self.assertIsNone(punishment.pick_random_video([], exclude=None))


class _FakeVlcModule:
    """Stands in for the real `vlc` module in tests that never touch actual VLC/Tk."""


class FallbackBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.videos_dir = Path(self.tmp.name) / "punishment.videos"
        self.videos_dir.mkdir()
        self.beeps: list = []

        def fake_beep(sound_file, *a, **kw):
            self.beeps.append(sound_file)

        original = punishment.play_notification
        punishment.play_notification = fake_beep
        self.addCleanup(setattr, punishment, "play_notification", original)

    def _patch_vlc(self, replacement):
        original = punishment._vlc_module
        punishment._vlc_module = replacement
        self.addCleanup(setattr, punishment, "_vlc_module", original)

    def test_falls_back_to_beep_when_vlc_is_unavailable(self):
        (self.videos_dir / "a.mp4").write_bytes(b"x")
        self._patch_vlc(lambda: None)

        player = punishment.PunishmentPlayer(videos_dir=self.videos_dir, sound_file=None)
        player.trigger_blocking()

        self.assertEqual(len(self.beeps), 1)

    def test_falls_back_to_beep_when_folder_is_empty(self):
        self._patch_vlc(lambda: _FakeVlcModule())

        player = punishment.PunishmentPlayer(videos_dir=self.videos_dir, sound_file=None)
        player.trigger_blocking()

        self.assertEqual(len(self.beeps), 1)

    def test_skips_a_corrupted_file_and_plays_the_next_one(self):
        good = self.videos_dir / "good.mp4"
        bad = self.videos_dir / "bad.mp4"
        good.write_bytes(b"x")
        bad.write_bytes(b"x")
        self._patch_vlc(lambda: _FakeVlcModule())

        # Pin the "random" pick to the corrupted file so the retry path is exercised
        # deterministically, regardless of which file pick_random_video would otherwise choose.
        original_pick = punishment.pick_random_video
        punishment.pick_random_video = lambda videos, exclude, rng=None: bad
        self.addCleanup(setattr, punishment, "pick_random_video", original_pick)

        attempted = []

        def fake_play(vlc_module, path):
            attempted.append(path)
            return path == good

        player = punishment.PunishmentPlayer(videos_dir=self.videos_dir, sound_file=None, play_video_fn=fake_play)
        player.trigger_blocking()

        self.assertEqual(attempted, [bad, good])
        self.assertEqual(self.beeps, [])

    def test_falls_back_to_beep_when_every_file_is_corrupted(self):
        (self.videos_dir / "bad1.mp4").write_bytes(b"x")
        (self.videos_dir / "bad2.mp4").write_bytes(b"x")
        self._patch_vlc(lambda: _FakeVlcModule())

        player = punishment.PunishmentPlayer(
            videos_dir=self.videos_dir, sound_file=None, play_video_fn=lambda vlc_module, path: False
        )
        player.trigger_blocking()

        self.assertEqual(len(self.beeps), 1)


class _FakeProcess:
    def __init__(self, returncode=0, timeout=False):
        self._returncode = returncode
        self._timeout = timeout
        self.killed = False

    def wait(self, timeout=None):
        if self._timeout:
            raise subprocess.TimeoutExpired(cmd="video_player.py", timeout=timeout)
        return self._returncode

    def kill(self):
        self.killed = True


class SubprocessPlaybackTests(unittest.TestCase):
    """Playback must run in a separate process: Tkinter/Tcl can only be driven from a
    process's main thread, and doing it from a worker thread killed the whole app with a
    fatal Tcl_AsyncDelete panic after a few clips."""

    def _patch_popen(self, process):
        captured = {}

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return process

        original = punishment.subprocess.Popen
        punishment.subprocess.Popen = fake_popen
        self.addCleanup(setattr, punishment.subprocess, "Popen", original)
        return captured

    def test_runs_video_player_in_its_own_process(self):
        captured = self._patch_popen(_FakeProcess(returncode=0))

        played = punishment._play_video_subprocess(
            Path("clip.mp4"),
            volume=80,
            portrait_height_ratio=0.8,
            landscape_width_ratio=0.6,
            max_duration_seconds=30.0,
        )

        self.assertTrue(played)
        command = captured["command"]
        self.assertEqual(command[0], sys.executable)
        self.assertIn(str(punishment.VIDEO_PLAYER_SCRIPT), command)
        self.assertIn("clip.mp4", command)
        self.assertIn("80", command)

    def test_non_zero_exit_code_counts_as_failure(self):
        self._patch_popen(_FakeProcess(returncode=1))

        played = punishment._play_video_subprocess(
            Path("broken.mp4"),
            volume=100,
            portrait_height_ratio=0.8,
            landscape_width_ratio=0.6,
            max_duration_seconds=30.0,
        )

        self.assertFalse(played)

    def test_hung_player_is_killed_and_counts_as_failure(self):
        process = _FakeProcess(timeout=True)
        self._patch_popen(process)

        played = punishment._play_video_subprocess(
            Path("hangs.mp4"),
            volume=100,
            portrait_height_ratio=0.8,
            landscape_width_ratio=0.6,
            max_duration_seconds=1.0,
        )

        self.assertFalse(played)
        self.assertTrue(process.killed)


class NoConcurrentPlaybackTests(unittest.TestCase):
    def test_second_trigger_is_ignored_while_first_video_is_playing(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos_dir = Path(tmp) / "punishment.videos"
            videos_dir.mkdir()
            (videos_dir / "a.mp4").write_bytes(b"x")

            original = punishment._vlc_module
            punishment._vlc_module = lambda: _FakeVlcModule()
            try:
                release_first = threading.Event()
                call_count = {"n": 0}
                lock = threading.Lock()

                def fake_play(vlc_module, path):
                    with lock:
                        call_count["n"] += 1
                    release_first.wait(timeout=2.0)
                    return True

                player = punishment.PunishmentPlayer(videos_dir=videos_dir, sound_file=None, play_video_fn=fake_play)

                player.trigger()
                for _ in range(100):
                    if player.is_playing:
                        break
                    time.sleep(0.01)
                self.assertTrue(player.is_playing)

                player.trigger()  # should be a no-op: a video is already "playing"
                time.sleep(0.1)
                with lock:
                    self.assertEqual(call_count["n"], 1)

                release_first.set()
                for _ in range(100):
                    if not player.is_playing:
                        break
                    time.sleep(0.01)
                self.assertFalse(player.is_playing)

                player.trigger()
                for _ in range(100):
                    if not player.is_playing:
                        break
                    time.sleep(0.01)
                with lock:
                    self.assertEqual(call_count["n"], 2)
            finally:
                punishment._vlc_module = original


if __name__ == "__main__":
    unittest.main()
