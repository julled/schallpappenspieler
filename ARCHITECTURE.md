# Schallpappenspieler Architecture

**Schallpappenspieler** ("record player" in German) is a QR code-based DJ deck controller for Mixxx. It uses a webcam to detect QR codes on physical records/cards and automatically loads tracks into the DJ software.

---

## System Overview

```
┌─────────────┐
│   Webcam    │ 30 FPS @ 1080p (MJPG compressed)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│          CAPTURE THREAD (camera.py)             │
│  • cv2.VideoCapture.read()                      │
│  • Optional horizontal flip (mirror mode)       │
│  • Updates _LatestFrame with version tracking   │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│        DETECTION THREAD (qr_detector.py)        │
│  • Polls for new frame versions                 │
│  • Applies optional ROI cropping                │
│  • Runs QR detection (opencv/pyzbar/zxingcpp)   │
│  • Updates _LatestDetections with coordinates   │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│      MAIN THREAD (main.py + state_tracker.py)   │
│  • Reads latest detections                      │
│  • Splits by screen center (left/right decks)   │
│  • Tracks stability (prevents spurious triggers)│
│  • Fires events when stable                     │
│  • Calls Mixxx automation (mixxx_ui.py)         │
│  • Renders debug GUI (gui_debug.py)             │
└─────────────────────────────────────────────────┘
```

---

## Threading Model

### Why Threaded?

The application uses **3 threads** to maximize throughput and minimize latency:

1. **Capture Thread** - Continuously reads frames from the camera at max speed (30 FPS)
2. **Detection Thread** - Processes frames for QR codes asynchronously
3. **Main Thread** - Handles state tracking, Mixxx control, and GUI rendering

Without threading, QR detection (20-50ms) would block camera capture, causing frame drops and jitter.

### Thread Safety

All shared state uses **locking** to prevent race conditions:

- `_LatestFrame` - Latest camera frame + version number
- `_LatestDetections` - Latest QR detections + version number
- `_LatestROI` - User-selected region of interest (optional crop)
- `_PerfStats` - FPS counters and latency metrics

**Version tracking** prevents the detection thread from processing the same frame twice.

---

## Performance Optimization

### Camera Capture (camera.py)

**Problem:** USB 2.0 webcams at 1080p only achieve ~1-2 FPS with uncompressed YUYV format.

**Solution:**
- Set `CAP_PROP_FOURCC` to **MJPG** (hardware-compressed on camera)
- Set `CAP_PROP_BUFFERSIZE` to **1** (minimize buffering latency)
- Result: **30 FPS** at 1080p

### Async Visualization (main.py)

**Problem:** Rendering GUI at 30 FPS wastes CPU when detection/state haven't changed.

**Solution:**
- Track frame versions in main loop
- Skip redundant rendering when no new frame
- Use `gui.process_events()` to keep window responsive without full redraw
- Only render when frame version increments

### ROI (Region of Interest)

Users can draw a rectangle in the GUI to **limit detection area**. This:
- Reduces detection latency (fewer pixels to process)
- Eliminates false positives from background QR codes
- Coordinates are automatically transformed back to full-frame space

---

## Pipeline Stages

### 1. Camera Capture (camera.py)

Opens webcam with optimized settings:
```python
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
```

Optional **mirror mode** (default ON) flips frames horizontally so left in image = left in reality.

### 2. QR Detection (qr_detector.py)

Multi-backend support for flexibility:

| Backend | Library | Speed | Robustness |
|---------|---------|-------|------------|
| **opencv** (default) | cv2.QRCodeDetector | Medium | Good |
| **pyzbar** | pyzbar (libzbar) | Fast | Excellent |
| **zxingcpp** | zxing-cpp | Fast | Good |
| **opencv_aruco** | cv2.aruco | Slow | Experimental |

Returns `QRCodeDetection` objects with:
- `text` - Decoded content
- `points` - 4 corner coordinates
- `center` - Centroid (x, y)
- `area` - Polygon area (for picking largest code)

### 3. State Tracking (state_tracker.py)

Implements **stability-based triggering** to prevent false positives:

```
Detection Lifecycle:
┌─────────────┐
│ QR appears  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│ Stability Timer             │ ← Must persist for stable_seconds
│ (e.g., 1.0s)                │
└──────┬──────────────────────┘
       │
       ▼ (after stable_seconds)
┌─────────────────────────────┐
│ TriggerEvent fired (once)   │ → Load track in Mixxx
└─────────────────────────────┘
       │
       ▼ (if QR disappears)
┌─────────────────────────────┐
│ Dropout Timer               │ ← Reset if dropout_seconds exceeded
└──────┬──────────────────────┘
       │
       ▼ (if still missing after forget_seconds)
┌─────────────────────────────┐
│ State cleared entirely      │
└─────────────────────────────┘
```

**Timing Parameters:**
- `stable_seconds` (default 1.0) - How long QR must persist before trigger
- `dropout_seconds` (default 1.0) - Max gap before resetting stability timer
- `forget_seconds` (default 5.0) - Max gap before clearing state

### 4. Deck Splitting (main.py)

The screen is split vertically (default 50/50):
- Detections with `center[0] < split_x` → **Left deck**
- Detections with `center[0] >= split_x` → **Right deck**

Each deck has independent state tracking. If multiple QR codes are detected on one side, the **largest by area** wins.

### 5. Mixxx Automation (mixxx_ui.py)

Uses **xdotool** and **wmctrl** to automate Mixxx DJ software:

1. Find Mixxx window by class hint (`wmctrl -lx`)
2. Focus window (`wmctrl -ia`)
3. Open search dialog (`xdotool key ctrl+f`)
4. Paste/type search text (`xclip` + `xdotool`)
5. Tab to results (`xdotool key Tab` × N)
6. Load to deck (`xdotool key Shift+Left` or `Shift+Right`)

**Limitations:**
- Linux-only (requires X11 window manager)
- Requires Mixxx window to be visible (can be on another workspace)
- Timing-dependent (uses `step_delay_seconds` between commands)

### 6. Debug GUI (gui_debug.py)

OpenCV-based visualization showing:
- Live camera feed with overlays
- Detected QR codes (green polylines)
- Split line (green vertical divider)
- Status per deck (current QR, stability/dropout timers)
- Performance stats (CAP/DET/GUI FPS, detection latency)
- ROI controls (red rectangle)

**Keyboard Controls:**
- `r` - Enter ROI selection mode (click-drag to draw rectangle)
- `c` - Clear ROI
- `q` - Quit
- Right-click - Clear ROI

**ROI Button:**
- Click "ROI" button to enter selection mode
- Shows "ROI..." while dragging
- Shows "ROI SET" when active

---

## Configuration (config.toml)

```toml
[camera]
index = 0                    # Camera device index
preferred_width = 0          # 0 = auto-select max resolution
preferred_height = 0
mirror = true                # Flip horizontally (left=left)

[split]
ratio = 0.5                  # Split position (0.0=left, 1.0=right)

[qr]
backend = "opencv"           # opencv|pyzbar|zxingcpp|opencv_aruco

[timing]
stable_seconds = 1.0         # Required stability before trigger
dropout_seconds = 1.0        # Max gap before reset
forget_seconds = 5.0         # Max gap before clear

[mixxx]
window_class_hint = "mixxx"  # Window class for wmctrl
step_delay_seconds = 0.5     # Delay between automation steps
search_hotkey = "ctrl+f"     # Search dialog hotkey
result_tab_count = 3         # Tabs to reach first result
left_deck_key = "Shift+Left" # Load to left deck
right_deck_key = "Shift+Right"

[ui]
show_debug = true            # Enable debug GUI
```

---

## Key Design Decisions

### 1. Why MJPG instead of YUYV?

USB 2.0 bandwidth: **480 Mbps**
1080p YUYV frame: **1920×1080×2 bytes = 4 MB = 32 Mb**
Max FPS: **480 / 32 ≈ 15 FPS** (but overhead limits it to ~1-2 FPS)

MJPG compresses frames **on the camera** before USB transfer, achieving **30 FPS**.

### 2. Why version tracking instead of timestamps?

Version numbers are **monotonic** and **unambiguous** - a frame is either new or not. Timestamps can have precision issues and don't clearly indicate "has this been processed?"

### 3. Why stability tracking instead of immediate triggers?

QR codes can be **momentarily detected** due to:
- Camera motion blur recovery
- Partial occlusion clearing
- Lighting changes

Requiring 1 second of stability prevents accidental track loads from brief appearances.

### 4. Why largest-by-area for duplicate codes?

If two QR codes overlap in screen space (e.g., stacked records), the **topmost** (largest visible area) should win. This matches user intent.

### 5. Why separate capture and detection threads?

Detection takes **20-50ms**. If done inline with capture, it would:
- Block the next frame read (causing frame drops)
- Introduce jitter in capture timing
- Limit effective FPS to ~20-40

With threading, capture runs at full 30 FPS while detection catches up asynchronously.

---

## Future Enhancements

- **Auto-focus control** - Lock focus at expected QR distance
- **Multi-camera support** - Track multiple deck pairs
- **Barcode support** - Use standard 1D barcodes instead of QR
- **Direct MIDI control** - Bypass xdotool for lower latency
- **macOS/Windows support** - Alternative automation methods
- **Calibration mode** - Auto-detect split line from physical setup

---

## Dependencies

**Core:**
- Python 3.8+
- OpenCV (`cv2`) - Camera, GUI, QR detection
- NumPy - Array operations

**Optional QR Backends:**
- `pyzbar` - Fast barcode detection
- `zxing-cpp` - Alternative QR library

**Linux Automation:**
- `wmctrl` - Window management
- `xdotool` - Keyboard automation
- `xclip` or `xsel` - Clipboard access

**Configuration:**
- `tomli` (Python <3.11) or `tomllib` (3.11+) - TOML parsing

---

## File Structure

```
schallpappenspieler/
├── src/schallpappenspieler/
│   ├── main.py           # Main app + threading orchestration
│   ├── camera.py         # Camera initialization
│   ├── qr_detector.py    # Multi-backend QR detection
│   ├── state_tracker.py  # Stability-based triggering
│   ├── gui_debug.py      # OpenCV visualization
│   ├── mixxx_ui.py       # Mixxx automation via xdotool
│   ├── config.py         # TOML configuration loader
│   ├── patches.py        # PDF/QR generator for M3U playlists
│   ├── pdf_layout.py     # ReportLab PDF utilities
│   └── discogs.py        # Discogs API client
├── config.toml           # User configuration
└── ARCHITECTURE.md       # This file
```

---

## Performance Characteristics

**Typical metrics** (Intel i5, 1080p webcam, opencv backend):

- **Capture FPS:** 30 (camera-limited)
- **Detection FPS:** 25-30 (depends on QR complexity)
- **Detection Latency:** 20-40ms per frame
- **GUI FPS:** 28-30 (skips redundant renders)
- **End-to-end Latency:** ~50-100ms (camera → detection → trigger)

**Bottlenecks:**
- Detection speed (use `pyzbar` for faster processing)
- GUI rendering (can disable with `--no-gui`)
- Mixxx automation (xdotool has ~200ms overhead per command)

---

## Debugging

**Low capture FPS (<10):**
- Check camera format: `v4l2-ctl --device=/dev/video0 --all`
- Verify MJPG support: Look for `MJPEG` in pixel formats
- Try lower resolution: Set `preferred_width/height` in config

**Detection not triggering:**
- Check stability timers in GUI overlay
- Verify QR code is in correct half of screen
- Try different backend: `backend = "pyzbar"`
- Use ROI to limit detection area

**Mixxx not responding:**
- Verify window class: `wmctrl -lx | grep -i mixxx`
- Test search hotkey manually (default Ctrl+F)
- Increase `step_delay_seconds` for slower systems
- Check xdotool is installed: `which xdotool`

**GUI lag:**
- Lower camera resolution
- Disable GUI: `--no-gui` flag
- Use ROI to reduce detection area
