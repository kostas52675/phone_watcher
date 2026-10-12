# Phone Watcher

Local-only Windows MVP that watches your webcam and plays a random "punishment" video
(falling back to a beep) when it thinks you're doomscrolling on your phone. It combines
three signals:

1. **Phone detection (YOLO)** — a visible cell phone in frame, the strongest signal.
2. **Head pose + gaze** — head pitched down and/or eyes looking down (MediaPipe Face
   Landmarker), which catches the common case where the phone itself is held below the
   camera's frame and only your bowed head is visible.
3. **Keyboard/mouse activity** — if you're actively typing, a bowed head means you're
   looking at the keyboard, not a phone, so no alert fires.

It does not record, save, or upload any video, frames, or keystrokes. All processing
happens in memory, locally.

## Setup

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/). During setup, enable **Add Python to PATH**.
2. Open PowerShell in this folder and create the virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python download_model.py
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process Bypass` for that terminal, or run the included `run.bat` after installing dependencies.

Punishment videos need [VLC](https://www.videolan.org/vlc/) installed system-wide (the
`python-vlc` package only binds to it) -- install it once from videolan.org if it isn't
already. If VLC is missing, Phone Watcher automatically falls back to the beep instead of
crashing.

## Calibrate (recommended before first run)

Head pose and "looking down" thresholds vary a lot per person, camera angle and desk
setup, so calibrate once before relying on the gaze signal:

```powershell
python main.py --calibrate
```

A window opens with 3 guided phases, ~5 seconds each:

1. **Look at the screen** normally.
2. **Look at the keyboard** and type.
3. **Look at your phone**, held low, as if scrolling.

Follow the on-screen phase label and countdown (Greek instructions are also printed to
the terminal for each phase). At the end, `calibration.json` is written with your
personal pitch/eye-gaze thresholds. Only aggregate numbers are stored — no images.

## Run

```powershell
python main.py
```

If `calibration.json` exists it's loaded automatically; otherwise the app falls back to
the defaults in `config.py` and prints a reminder to calibrate.

A preview window shows the phone box (when detected) and a status line. Press `q` to
stop, or press `Ctrl+C` in the terminal. For background/headless operation:

```powershell
python main.py --headless
```

Use another camera with `python main.py --camera 1`. To use a local WAV alert as the
fallback sound, run `python main.py --sound C:\path\to\alert.wav`.

## Controls (preview window)

- `q` — quit. Also closing the window with its `X` button fully stops Phone Watcher
  (camera released, no background process left).
- `p` — pause/resume ("study mode": use this when reading a book or notes at your desk,
  where looking down is legitimate). Shows `PAUSED` and suppresses all alerts while active.
- `d` — toggle the debug overlay: head pitch (degrees), eyeLookDown score, seconds since
  the last keyboard/mouse input, and a progress bar showing how close the current timer
  is to triggering.

Status shown: `Monitoring` / `LOOKING DOWN` / `PHONE DETECTED` / `PAUSED`.

## Alert logic

- **Phone visible continuously for `PHONE_SUSTAIN_SECONDS`** (default 1.5s) → trigger.
- **Head/eyes down AND a face is detected AND no keyboard/mouse input for
  `GAZE_IDLE_INPUT_SECONDS`** (default 4s), sustained for `GAZE_SUSTAIN_SECONDS`
  (default 5s) → trigger.
- Looking down while actively typing → no alert (you're looking at the keyboard).
- Looking at the screen → no alert, regardless of keyboard activity.
- No face detected (e.g. you stepped away) → no alert.
- A brief blink is filtered out (`LOOKING_DOWN_MIN_DURATION_SECONDS`) and never counts
  as "looking down".
- If the suspicious state continues after a trigger, it repeats every
  `COOLDOWN_SECONDS` (default 10s) so it can't just be ignored -- unless a punishment
  video is still playing, in which case the repeat is skipped until it finishes.
- Looking back at the screen, or touching the keyboard/mouse, resets the relevant timer
  immediately.

## Punishment videos

Each trigger plays a random video from `punishment.videos/` (image + sound), instead of
the old plain beep:

- Drop `.mp4`, `.mov`, `.webm`, `.mkv`, or `.avi` files (any case) directly into
  `punishment.videos/` at the project root. The folder is re-scanned on every trigger, so
  adding or removing clips takes effect immediately, no restart needed.
- The same video never plays twice in a row (when more than one is available).
- The video window is always-on-top, centered, sized to preserve its aspect ratio
  (portrait clips: `PUNISHMENT_VIDEO_PORTRAIT_HEIGHT_RATIO` of screen height; landscape:
  `PUNISHMENT_VIDEO_LANDSCAPE_WIDTH_RATIO` of screen width), with no controls, and closes
  itself automatically the instant the clip ends.
- Only one video plays at a time; a trigger that fires while one is already playing is
  ignored (the next one counts once the current video finishes and the cooldown elapses).
- The camera preview and detection loop keep running while a video plays. Each video is
  played by `video_player.py` in its own short-lived process, so nothing freezes, and a
  broken clip or VLC problem can never crash the watcher itself.
- **Fallback to the beep** happens automatically, with a clear message printed to the
  console, if: VLC isn't installed, `punishment.videos/` is empty, or a chosen file fails
  to play (a corrupted file is skipped and another is tried). Phone Watcher never crashes
  because of a bad video.

Test it directly, without needing to trigger detection:

```powershell
python main.py --test-video
```

## On/off switch (tray icon + desktop shortcut)

To avoid Phone Watcher running in the background (and using CPU) when you don't want it:

1. Generate the icon and create the "Phone Watcher" desktop shortcut:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1
   ```

   This resolves your real Desktop folder programmatically (works with OneDrive
   redirection and localized folder names), so no path needs to be hardcoded.

2. Double-click **Phone Watcher** on the desktop to start it (camera preview + monitoring
   + a tray icon appears); double-click it again to stop it cleanly. It runs via
   `pythonw.exe`, so no console window ever opens.

While running, right-click the tray icon for:

- **Pause / Resume** — fully releases the camera and stops inference (CPU drops to
  ~idle). Different from the preview window's `p` key, which is a lighter pause that
  keeps the camera open.
- **Show / Hide preview** — hides or shows the camera window; monitoring keeps running
  either way.
- **Stop** — same as closing the preview window: full, clean shutdown.

Stopping (from the tray, the shortcut, or the preview window) asks the running process to
exit cleanly first (camera released, any open punishment video closed) via a stop-flag
file, and only force-kills it if it doesn't exit within a few seconds.

## Tuning

Edit the constants in `config.py`:

- `MIN_DETECTION_CONFIDENCE` / `MIN_TRACKING_CONFIDENCE`: MediaPipe Face Landmarker confidence.
- `GAZE_EMA_ALPHA`: smoothing factor for pitch/eye-gaze signals (lower = smoother, slower to react).
- `LOOKING_DOWN_MIN_DURATION_SECONDS`: how long the down-condition must hold before it counts (blink filter).
- `DEFAULT_PITCH_LOOKING_DOWN_THRESHOLD_DEG` / `DEFAULT_EYE_LOOK_DOWN_THRESHOLD`: fallback thresholds used only when `calibration.json` is missing.
- `CALIBRATION_PHASE_SECONDS`: duration of each calibration phase.
- `GAZE_IDLE_INPUT_SECONDS`: how long without keyboard/mouse input counts as "not typing".
- `GAZE_SUSTAIN_SECONDS`: how long the combined looking-down + idle-input condition must hold before alerting.
- `PHONE_DETECTION_CONFIDENCE` / `PHONE_DETECTION_CONFIDENCE_LOW_ZONE`: YOLO confidence thresholds; the low-zone one is used for detections low in the frame, where the phone is often cropped or half-visible.
- `PHONE_LOW_ZONE_HEIGHT_RATIO`: fraction of the frame height (from the bottom) considered the "low zone".
- `PHONE_DETECTION_FRAME_SKIP`: run YOLO every Nth frame to save CPU; the last box is reused on skipped frames.
- `PHONE_SUSTAIN_SECONDS`: how long a phone must be continuously visible before it counts.
- `COOLDOWN_SECONDS`: minimum gap between repeated alerts while a suspicious state continues.
- `HEADLESS`: permanently disable the preview window (note: `p`/`d` key controls require the preview window).
- `PUNISHMENT_VIDEOS_DIR`: folder scanned for punishment clips (relative to the project root by default).
- `PUNISHMENT_VIDEO_EXTENSIONS`: file extensions treated as playable videos.
- `PUNISHMENT_VIDEO_VOLUME`: playback volume, 0-100.
- `PUNISHMENT_VIDEO_PORTRAIT_HEIGHT_RATIO` / `PUNISHMENT_VIDEO_LANDSCAPE_WIDTH_RATIO`: how large the video window is, as a fraction of the screen, depending on the clip's orientation.
- `PUNISHMENT_VIDEO_MAX_SECONDS`: safety cap that force-closes the video window if the end-of-media signal is never received.
- `LOOP_FPS_LIMIT`: caps the main detection loop's frame rate (10-15 is plenty; no need for 30).

## Tests

```powershell
python -m unittest discover -s tests -v
```

Covers the alert state machine (`state_machine.py`), the blink/debounce timer
(`timing.py`), punishment-video selection/scanning/fallback logic (`punishment.py`), and
the on/off toggle's stale-PID-lock handling (`process_control.py`) -- all with fake
timestamps, temp folders, and fake `psutil`/VLC stand-ins, so no camera, model files, real
VLC install, or real OS processes are required.

## Troubleshooting

- **Camera not found:** close other apps using the webcam, allow camera access in Windows Settings > Privacy & security > Camera, then try `--camera 1` or another index.
- **Missing dependency:** activate `.venv` and run `pip install -r requirements.txt` again.
- **Missing MediaPipe model:** run `python download_model.py` once with an internet connection. The model is then used locally.
- **Missing sound file:** check the path passed to `--sound`; omit it to use the Windows system beep.
- **No detections / gaze feels off:** run `python main.py --calibrate` for your specific desk, camera angle and lighting, then re-run.
- **Doesn't trigger when the phone is out of frame:** that's the gaze-based signal's job — confirm the debug overlay (`d`) shows pitch/eyeLookDown moving when you look down, and that "input idle" climbs when you stop touching the keyboard.
- **Punishment video never plays, only the beep:** check the console for a `[punishment]` message explaining why (VLC missing, empty folder, or every file failed) — run `python main.py --test-video` to see it directly. Make sure VLC itself (not just the `python-vlc` package) is installed.
- **Desktop shortcut does nothing / doesn't toggle:** re-run `create_shortcut.ps1` after creating `.venv`; it needs `.venv\Scripts\pythonw.exe` to exist first.
- **"Phone Watcher is already running" but nothing is visible:** a previous run may have crashed leaving a stale lock; the desktop shortcut / `toggle.py` automatically detect and clean up a stale lock (checked against the live process's command line), so just use the shortcut again.
- **App seems to close on its own after a while:** when started from the desktop shortcut (`pythonw`, no console), everything printed goes to `phonewatcher.log` at the project root -- check its last lines. A line that ends with `=== Phone Watcher stopped ... ===` means a normal stop; if the log just ends without it, the process crashed, and the last line usually says why. (Earlier versions crashed with `Tcl_AsyncDelete: async handler deleted by the wrong thread` after a few videos; video playback now runs in its own process, which fixes that.)

All processing is performed in memory on the local machine. No video, images, or
keystrokes are written to disk by this program — `calibration.json` stores only
aggregate pitch/eye-gaze numbers.
