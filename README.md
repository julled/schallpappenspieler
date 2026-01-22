# Schallpappenspieler

![](schallpappen.jpg)

A new audio media based on cardboard to play music from.

## Technology

QR-code controlled Mixxx loader (live camera) and a CLI generator for printable song patches.

## Requirements
- Xorg session (Wayland not supported for UI automation).
- `xdotool` and `wmctrl` installed.
- Python 3.11+.

## Install (uv)
```bash
uv sync
```

## Live mode
```bash
# start scanner
uv run schallpappenspieler --config config.toml
# start mixxx
mixxx
```

## Song patch generator (M3U -> PDF)
```bash
uv run schallpappenspieler-patches --config config.toml --m3u path/to/list.m3u --cover-source discogs
```

## Notes
- Mixxx must run under X11/XWayland.
- Discogs token is required if you set `--cover-source discogs` (read from `.env`).
- Key bindings in `config.toml` must match Mixxx shortcuts.
- QR scan backend defaults to OpenCV; set `qr.backend = "pyzbar"` if you install `pyzbar`.
- Fix possible xdotool remote control problems: `xhost +SI:localuser:$USER`
- Maybe remote control needs to be activated in your OS!
- Mixxx sometimes needs to be start with explicit remote controllable platform: `QT_QPA_PLATFORM=xcb mixxx`
