"""Load and template prompt files from the prompts/ directory."""

import json
from pathlib import Path


class PromptManager:
    def __init__(self, prompts_dir: str = "./prompts"):
        self.prompts_dir = Path(prompts_dir)
        self.cache: dict[str, str] = {}

    def load(self, prompt_path: str, variables: dict | None = None) -> str:
        """
        Load a prompt template and interpolate variables.
        prompt_path: dot-separated path, e.g. 'decisions.click_decision'
        """
        if prompt_path not in self.cache:
            file_path = self.prompts_dir / prompt_path.replace(".", "/")
            file_path = file_path.with_suffix(".md")
            self.cache[prompt_path] = file_path.read_text(encoding="utf-8")

        prompt = self.cache[prompt_path]
        if variables:
            for key, value in variables.items():
                serialized = (
                    json.dumps(value, indent=2)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                prompt = prompt.replace(f"{{{{{key}}}}}", serialized)
        return prompt

    def clear_cache(self):
        self.cache.clear()
