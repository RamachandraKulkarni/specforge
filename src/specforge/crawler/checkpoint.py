"""Crawl state persistence for pause/resume."""

import json
import time
from pathlib import Path


class Checkpoint:
    """Save and restore crawl state to enable pause/resume."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self._file = output_dir / "checkpoint.json"

    def save(self, state: dict):
        """Persist current crawl state to disk."""
        state["_saved_at"] = time.time()
        self._file.write_text(json.dumps(state, indent=2, default=str))

    def load(self) -> dict | None:
        """Load a previously saved crawl state."""
        if not self._file.exists():
            return None
        try:
            return json.loads(self._file.read_text())
        except Exception:
            return None

    def exists(self) -> bool:
        return self._file.exists()

    def delete(self):
        if self._file.exists():
            self._file.unlink()

    def save_screens(self, screens: dict):
        """Partial save of just the screens dict (lightweight)."""
        screens_file = self.output_dir / "checkpoint_screens.json"
        screens_file.write_text(
            json.dumps(screens, indent=2, default=str)
        )

    def load_screens(self) -> dict:
        screens_file = self.output_dir / "checkpoint_screens.json"
        if not screens_file.exists():
            return {}
        try:
            return json.loads(screens_file.read_text())
        except Exception:
            return {}
