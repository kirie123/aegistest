"""Memory Manager — Hermes-compatible persistent memory.

Two stores:
  - MEMORY.md: agent's personal notes and observations
  - USER.md: what the agent knows about the user

Entry delimiter: § (section sign). Entries can be multiline.
Character limits (not tokens) because char counts are model-independent.

Back-compat: the old JSON file path still works; on first load we migrate
JSON entries into markdown format.
"""

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENTRY_DELIMITER = "\n§\n"
DEFAULT_MEMORY_CHAR_LIMIT = 2200
DEFAULT_USER_CHAR_LIMIT = 1375


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    """
    Bounded curated memory with file persistence.

    Maintains two parallel states:
      - _system_prompt_snapshot: frozen at load time
      - memory_entries / user_entries: live state, mutated by tool calls
    """

    def __init__(
        self,
        memory_dir: str = "~/.aegistest/memories",
        memory_char_limit: int = DEFAULT_MEMORY_CHAR_LIMIT,
        user_char_limit: int = DEFAULT_USER_CHAR_LIMIT,
        legacy_json_file: Optional[str] = None,
        memory_file: Optional[str] = None,
    ):
        # Back-compat: memory_file is alias for legacy_json_file
        if memory_file and not legacy_json_file:
            legacy_json_file = memory_file

        self.memory_dir = Path(memory_dir).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit

        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}

        self._load_from_disk()

        # Migrate legacy JSON if present
        if legacy_json_file:
            self._maybe_migrate_legacy(Path(legacy_json_file).expanduser())

    def _memory_file(self) -> Path:
        return self.memory_dir / "MEMORY.md"

    def _user_file(self) -> Path:
        return self.memory_dir / "USER.md"

    def _read_file(self, path: Path) -> List[str]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            return []
        if not text.strip():
            return []
        # Split on delimiter, strip each entry
        entries = [entry.strip() for entry in text.split(ENTRY_DELIMITER) if entry.strip()]
        # Deduplicate preserving order
        seen: set = set()
        result: List[str] = []
        for e in entries:
            if e not in seen:
                seen.add(e)
                result.append(e)
        return result

    def _write_file(self, path: Path, entries: List[str]) -> None:
        text = ENTRY_DELIMITER.join(entries)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _maybe_migrate_legacy(self, legacy_path: Path) -> None:
        if not legacy_path.exists():
            return
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return
        migrated = False
        for category, items in data.items():
            if not isinstance(items, dict):
                continue
            for key, entry in items.items():
                if isinstance(entry, dict) and "value" in entry:
                    text = f"[{category}] {key}: {entry['value']}"
                else:
                    text = f"[{category}] {key}: {entry}"
                if category == "user" or category == "preferences":
                    if text not in self.user_entries:
                        self.user_entries.append(text)
                        migrated = True
                else:
                    if text not in self.memory_entries:
                        self.memory_entries.append(text)
                        migrated = True
        if migrated:
            self._flush()
            # Rename legacy file so we don't migrate again
            try:
                legacy_path.rename(legacy_path.with_suffix(".json.migrated"))
            except OSError:
                pass

    def _load_from_disk(self) -> None:
        self.memory_entries = self._read_file(self._memory_file())
        self.user_entries = self._read_file(self._user_file())
        self._capture_snapshot()

    def _capture_snapshot(self) -> None:
        self._system_prompt_snapshot = {
            "memory": self._render_block("memory", self.memory_entries),
            "user": self._render_block("user", self.user_entries),
        }

    def _render_block(self, label: str, entries: List[str]) -> str:
        if not entries:
            return ""
        return f"[{label.upper()}]\n" + "\n".join(f"  • {e}" for e in entries)

    def _flush(self) -> None:
        self._write_file(self._memory_file(), self.memory_entries)
        self._write_file(self._user_file(), self.user_entries)

    def _enforce_bounds(self) -> None:
        # Trim from oldest if over limit
        while self.memory_entries and sum(len(e) for e in self.memory_entries) > self.memory_char_limit:
            self.memory_entries.pop(0)
        while self.user_entries and sum(len(e) for e in self.user_entries) > self.user_char_limit:
            self.user_entries.pop(0)

    # ------------------------------------------------------------------
    # Public API (back-compat + Hermes-style)
    # ------------------------------------------------------------------
    def add(self, key: str, value: Any, category: str = "general") -> None:
        """Back-compat: add an entry keyed by category."""
        text = f"{key}: {value}"
        if category in ("user", "preferences", "profile"):
            if text not in self.user_entries:
                self.user_entries.append(text)
        else:
            if text not in self.memory_entries:
                self.memory_entries.append(text)
        self._enforce_bounds()
        self._flush()

    def set(self, key: str, value: Any, category: str = "general") -> None:
        """Alias for add."""
        self.add(key, value, category)

    def get(self, key: str, category: str = "general") -> Any:
        """Back-compat: search for key prefix in entries."""
        entries = self.user_entries if category in ("user", "preferences", "profile") else self.memory_entries
        prefix = f"{key}:"
        for e in entries:
            if e.startswith(prefix):
                return e[len(prefix):].strip()
        return None

    def get_entry(self, key: str, category: str = "general") -> Optional[Dict[str, Any]]:
        val = self.get(key, category)
        if val is None:
            return None
        return {"value": val, "updated_at": _now_iso()}

    def get_by_category(self, category: str) -> Dict[str, Any]:
        entries = self.user_entries if category in ("user", "preferences", "profile") else self.memory_entries
        result: Dict[str, Any] = {}
        for e in entries:
            if ":" in e:
                k, v = e.split(":", 1)
                result[k.strip()] = v.strip()
        return result

    def delete(self, key: str, category: str = "general") -> bool:
        entries = self.user_entries if category in ("user", "preferences", "profile") else self.memory_entries
        prefix = f"{key}:"
        for i, e in enumerate(entries):
            if e.startswith(prefix):
                entries.pop(i)
                self._flush()
                return True
        return False

    def search(self, keyword: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        kw = keyword.lower()
        for entries, label in ((self.memory_entries, "memory"), (self.user_entries, "user")):
            for e in entries:
                if kw in e.lower():
                    results.append({"category": label, "entry": e})
        return results

    def list_categories(self) -> List[str]:
        cats = ["memory"]
        if self.user_entries:
            cats.append("user")
        return cats

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory": self.memory_entries.copy(),
            "user": self.user_entries.copy(),
        }

    # ------------------------------------------------------------------
    # Hermes-style raw entry API
    # ------------------------------------------------------------------
    def add_entry(self, text: str, store: str = "memory") -> None:
        """Add a raw text entry to MEMORY.md or USER.md."""
        text = text.strip()
        if not text:
            return
        if store == "user":
            if text not in self.user_entries:
                self.user_entries.append(text)
        else:
            if text not in self.memory_entries:
                self.memory_entries.append(text)
        self._enforce_bounds()
        self._flush()

    def remove_entry(self, substring: str, store: str = "memory") -> bool:
        """Remove the first entry containing the substring."""
        entries = self.user_entries if store == "user" else self.memory_entries
        for i, e in enumerate(entries):
            if substring in e:
                entries.pop(i)
                self._flush()
                return True
        return False

    def read_store(self, store: str = "memory") -> str:
        """Return full store content as a single string."""
        entries = self.user_entries if store == "user" else self.memory_entries
        return ENTRY_DELIMITER.join(entries)

    def build_system_prompt_block(self) -> str:
        """Build the memory block for system prompt injection."""
        parts: List[str] = []
        mem = self._system_prompt_snapshot.get("memory", "")
        user = self._system_prompt_snapshot.get("user", "")
        if mem:
            parts.append(mem)
        if user:
            parts.append(user)
        return "\n\n".join(parts)

    def refresh_snapshot(self) -> None:
        """Re-capture snapshot after external edits."""
        self._load_from_disk()
