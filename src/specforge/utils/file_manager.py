"""Output file management — listing runs, reading specs."""

import json
from pathlib import Path


class FileManager:
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = Path(output_dir)

    def list_runs(self) -> list[dict]:
        """List all completed pipeline runs."""
        runs = []
        if not self.output_dir.exists():
            return runs
        for run_dir in sorted(self.output_dir.iterdir(), reverse=True):
            if run_dir.is_dir():
                spec_file = run_dir / "final_spec.json"
                cost_file = run_dir / "cost_report.json"
                runs.append({
                    "run_id": run_dir.name,
                    "has_spec": spec_file.exists(),
                    "has_cost": cost_file.exists(),
                    "created": run_dir.stat().st_mtime,
                })
        return runs

    def read_spec(self, run_id: str) -> dict | None:
        spec_file = self.output_dir / run_id / "final_spec.json"
        if not spec_file.exists():
            return None
        return json.loads(spec_file.read_text())

    def read_cost_report(self, run_id: str) -> dict | None:
        cost_file = self.output_dir / run_id / "cost_report.json"
        if not cost_file.exists():
            return None
        return json.loads(cost_file.read_text())

    def read_intermediate(self, run_id: str, filename: str) -> dict | None:
        path = self.output_dir / run_id / filename
        if not path.exists():
            return None
        return json.loads(path.read_text())
