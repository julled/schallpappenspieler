import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class MixxxConfig:
    window_class_hint: str
    step_delay_seconds: float
    search_hotkey: str
    result_tab_count: int
    left_deck_key: str
    right_deck_key: str


class MixxxController:
    def __init__(self, config: MixxxConfig):
        self.config = config
        self._xclip = shutil.which("xclip")
        self._xsel = shutil.which("xsel")

    def _find_window_id(self) -> Optional[str]:
        try:
            output = subprocess.check_output(["wmctrl", "-lx"], text=True)
        except subprocess.CalledProcessError:
            return None

        for line in output.splitlines():
            parts = line.split()
            if (
                len(parts) >= 3
                and self.config.window_class_hint.lower() in parts[2].lower()
            ):
                return parts[0]
        return None

    def _focus_window(self, win_id: str) -> bool:
        try:
            subprocess.run(["wmctrl", "-ia", win_id], check=True)
            time.sleep(self.config.step_delay_seconds)
            return True
        except subprocess.CalledProcessError:
            return False

    def _exec_key(self, win_id: str, key: str) -> bool:
        try:
            subprocess.run(["xdotool", "key", "--window", win_id, key], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _type_text(self, win_id: str, text: str) -> bool:
        try:
            subprocess.run(["xdotool", "type", "--window", win_id, text], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _paste_text(self, win_id: str, text: str) -> bool:
        if self._xclip:
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text,
                    text=True,
                    check=True,
                )
                return self._exec_key(win_id, "ctrl+v")
            except subprocess.CalledProcessError:
                return False
        if self._xsel:
            try:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text,
                    text=True,
                    check=True,
                )
                return self._exec_key(win_id, "ctrl+v")
            except subprocess.CalledProcessError:
                return False
        return False

    def load_track(self, text: str, deck: str) -> bool:
        win_id = self._find_window_id()
        if not win_id:
            print("Mixxx window not found.")
            return False

        if not self._focus_window(win_id):
            print("Failed to focus Mixxx window.")
            return False

        if not self._exec_key(win_id, self.config.search_hotkey):
            print("Failed to open search.")
            return False
        time.sleep(self.config.step_delay_seconds)

        if not self._paste_text(win_id, text):
            if not self._type_text(win_id, text):
                print("Failed to enter search text.")
                return False
        time.sleep(self.config.step_delay_seconds)

        for _ in range(self.config.result_tab_count):
            if not self._exec_key(win_id, "Tab"):
                print("Failed to tab to results.")
                return False
            time.sleep(self.config.step_delay_seconds)

        deck_key = (
            self.config.right_deck_key if deck == "right" else self.config.left_deck_key
        )
        if not self._exec_key(win_id, deck_key):
            print("Failed to select deck.")
            return False

        return True
