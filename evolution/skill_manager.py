"""Skill Manager — Hermes-compatible skill storage.

Directory layout:
    <skills_dir>/
    ├── <skill-name>/
    │   ├── SKILL.md          # YAML frontmatter + body
    │   ├── references/       # session-specific detail, knowledge banks
    │   ├── templates/        # starter files
    │   └── scripts/          # re-runnable actions
    ├── <another-skill>/
    └── .archive/             # archived skills (recoverable)

Sidecar:
    <skills_dir>/.usage.json  # usage telemetry + provenance + state
"""

import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Skill lifecycle states
STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"
_VALID_STATES = {STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED}

# Provenance origins
ORIGIN_FOREGROUND = "foreground"
ORIGIN_BACKGROUND_REVIEW = "background_review"

MAX_SKILL_CONTENT_CHARS = 100_000
MAX_DESCRIPTION_LENGTH = 1024
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
ALLOWED_SUBDIRS = {"references", "templates", "scripts", "assets"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _validate_name(name: str) -> Optional[str]:
    if not name:
        return "Skill name is required."
    if len(name) > 64:
        return "Skill name exceeds 64 characters."
    if not VALID_NAME_RE.match(name):
        return (
            f"Invalid skill name '{name}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Must start with a letter or digit."
        )
    return None


def _build_skill_md(name: str, description: str, body: str) -> str:
    """Build a SKILL.md with proper YAML frontmatter."""
    # Escape any "---" inside body to avoid breaking frontmatter
    safe_body = body.replace("\n---\n", "\n--- \n")
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"created_at: {_now_iso()}\n"
        f"---\n\n"
        f"{safe_body}\n"
    )


def _parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from SKILL.md. Returns (meta_dict, body)."""
    meta: Dict[str, Any] = {}
    body = content
    if content.startswith("---"):
        end_match = re.search(r'\n---\s*\n', content[3:])
        if end_match:
            yaml_text = content[3:end_match.start() + 3]
            body = content[end_match.end() + 3:]
            # Simple hand parser for flat key: value lines
            for line in yaml_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    return meta, body.strip()


class SkillManager:
    """CRUD for skills stored as directories with SKILL.md + subdirs + sidecar telemetry."""

    def __init__(self, skills_dir: str = "~/.aegistest/skills"):
        self.skills_dir = Path(skills_dir).expanduser()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.skills_dir / ".archive"
        self.archive_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Sidecar (.usage.json)
    # ------------------------------------------------------------------
    def _usage_file(self) -> Path:
        return self.skills_dir / ".usage.json"

    def _load_usage(self) -> Dict[str, Any]:
        path = self._usage_file()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_usage(self, data: Dict[str, Any]) -> None:
        path = self._usage_file()
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp), str(path))
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    def _get_record(self, name: str) -> Dict[str, Any]:
        usage = self._load_usage()
        return usage.get(name, {})

    def _set_record(self, skill_name: str, **kwargs) -> None:
        usage = self._load_usage()
        rec = usage.get(skill_name, {})
        rec.update(kwargs)
        usage[skill_name] = rec
        self._save_usage(usage)

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------
    def mark_agent_created(self, name: str) -> None:
        self._set_record(name, agent_created=True, created_at=_now_iso())

    def is_agent_created(self, name: str) -> bool:
        return bool(self._get_record(name).get("agent_created"))

    def is_bundled(self, name: str) -> bool:
        # Bundled skills live in a separate manifest; simplified: none are bundled here
        return False

    def is_hub_installed(self, name: str) -> bool:
        return False

    def is_protected(self, name: str) -> bool:
        return self.is_bundled(name) or self.is_hub_installed(name)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------
    def get_state(self, name: str) -> str:
        return self._get_record(name).get("state", STATE_ACTIVE)

    def set_state(self, name: str, state: str) -> None:
        if state not in _VALID_STATES:
            raise ValueError(f"Invalid state: {state}")
        self._set_record(name, state=state)

    def is_pinned(self, name: str) -> bool:
        return bool(self._get_record(name).get("pinned"))

    def pin(self, name: str) -> None:
        self._set_record(name, pinned=True)

    def unpin(self, name: str) -> None:
        self._set_record(name, pinned=False)

    # ------------------------------------------------------------------
    # Usage telemetry
    # ------------------------------------------------------------------
    def bump_use(self, name: str) -> None:
        rec = self._get_record(name)
        self._set_record(name, use_count=rec.get("use_count", 0) + 1, last_used_at=_now_iso())

    def bump_view(self, name: str) -> None:
        rec = self._get_record(name)
        self._set_record(name, view_count=rec.get("view_count", 0) + 1, last_viewed_at=_now_iso())

    def bump_patch(self, name: str) -> None:
        rec = self._get_record(name)
        self._set_record(name, patch_count=rec.get("patch_count", 0) + 1, last_patched_at=_now_iso())

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------
    def _resolve_skill_dir(self, name: str) -> Path:
        return self.skills_dir / name

    def _find_skill(self, name: str) -> Optional[Path]:
        """Find active or archived skill directory."""
        for root in (self.skills_dir, self.archive_dir):
            d = root / name
            if d.is_dir() and (d / "SKILL.md").exists():
                return d
        return None

    def upsert(
        self,
        skill_name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        origin: str = ORIGIN_FOREGROUND,
    ) -> str:
        """
        Create or update a skill.

        If content does not start with '---' (no frontmatter), one is built
        automatically for backward compatibility.
        """
        err = _validate_name(skill_name)
        if err:
            raise ValueError(err)

        skill_dir = self._resolve_skill_dir(skill_name)
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Ensure references/ templates/ scripts/ exist
        for sub in ALLOWED_SUBDIRS:
            (skill_dir / sub).mkdir(exist_ok=True)

        skill_md = skill_dir / "SKILL.md"

        if content.strip().startswith("---"):
            # User provided full SKILL.md with frontmatter
            md_content = content
        else:
            # Back-compat: build frontmatter from metadata
            desc = description or metadata.get("description", "") if metadata else ""
            if not desc:
                desc = f"Skill '{skill_name}'"
            md_content = _build_skill_md(skill_name, desc, content)

        # Validate size
        if len(md_content) > MAX_SKILL_CONTENT_CHARS:
            raise ValueError(
                f"SKILL.md content is {len(md_content):,} characters (limit: {MAX_SKILL_CONTENT_CHARS:,})"
            )

        # Atomic write
        fd, tmp = tempfile.mkstemp(dir=str(skill_dir), prefix=".SKILL.md.tmp.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(md_content)
            os.replace(tmp, str(skill_md))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        # Update sidecar
        now = _now_iso()
        rec = self._get_record(skill_name)
        updates: Dict[str, Any] = {
            "name": skill_name,
            "updated_at": now,
        }
        if "created_at" not in rec:
            updates["created_at"] = now
        if origin == ORIGIN_BACKGROUND_REVIEW and not rec.get("agent_created"):
            updates["agent_created"] = True
        if metadata:
            # Merge metadata; allow explicit updated_at override for testing/backfill
            for k, v in metadata.items():
                if k == "name":
                    continue
                updates[k] = v
        self._set_record(skill_name, **updates)
        self.bump_patch(skill_name)

        return str(skill_dir)

    def get(self, skill_name: str) -> Optional[str]:
        """Read SKILL.md body (without frontmatter) or full file."""
        skill_dir = self._find_skill(skill_name)
        if not skill_dir:
            return None
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
        _, body = _parse_frontmatter(content)
        self.bump_view(skill_name)
        return body or content

    def get_full(self, skill_name: str) -> Optional[str]:
        """Read full SKILL.md including frontmatter."""
        skill_dir = self._find_skill(skill_name)
        if not skill_dir:
            return None
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None
        with open(skill_md, "r", encoding="utf-8") as f:
            return f.read()

    def get_meta(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Return merged frontmatter + sidecar record."""
        full = self.get_full(skill_name)
        if full is None:
            return None
        front, _ = _parse_frontmatter(full)
        rec = self._get_record(skill_name)
        merged = {**front, **rec}
        merged["name"] = skill_name
        merged["status"] = self.get_state(skill_name)
        merged["pinned"] = self.is_pinned(skill_name)
        merged["agent_created"] = self.is_agent_created(skill_name)
        return merged

    def list_skills(self, include_archived: bool = False, agent_created_only: bool = False) -> List[Dict[str, Any]]:
        """List all skills with metadata."""
        results: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        def _scan(root: Path, status: str):
            for entry in root.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                name = entry.name
                if name in seen:
                    continue
                seen.add(name)
                meta = self.get_meta(name)
                if meta is None:
                    continue
                meta["status"] = status if status else self.get_state(name)
                if agent_created_only and not meta.get("agent_created"):
                    continue
                results.append(meta)

        _scan(self.skills_dir, STATE_ACTIVE)
        if include_archived:
            _scan(self.archive_dir, STATE_ARCHIVED)
        return results

    def agent_created_report(self) -> List[Dict[str, Any]]:
        """Return only agent-created skills (for Curator)."""
        return self.list_skills(include_archived=True, agent_created_only=True)

    # ------------------------------------------------------------------
    # Support files (references / templates / scripts)
    # ------------------------------------------------------------------
    def write_file(self, skill_name: str, file_path: str, file_content: str) -> str:
        """Write a supporting file under an existing skill."""
        skill_dir = self._find_skill(skill_name)
        if not skill_dir:
            raise FileNotFoundError(f"Skill '{skill_name}' not found")

        # Validate subdir
        parts = Path(file_path).parts
        if not parts or parts[0] not in ALLOWED_SUBDIRS:
            raise ValueError(f"File must be under one of: {ALLOWED_SUBDIRS}")

        target = skill_dir / file_path
        # Prevent escape
        try:
            target.relative_to(skill_dir)
        except ValueError:
            raise ValueError("Path traversal not allowed")

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.tmp.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(file_content)
            os.replace(tmp, str(target))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        self.bump_patch(skill_name)
        return str(target)

    def read_file(self, skill_name: str, file_path: str) -> Optional[str]:
        skill_dir = self._find_skill(skill_name)
        if not skill_dir:
            return None
        target = skill_dir / file_path
        try:
            target.relative_to(skill_dir)
        except ValueError:
            return None
        if not target.exists():
            return None
        with open(target, "r", encoding="utf-8") as f:
            return f.read()

    def remove_file(self, skill_name: str, file_path: str) -> bool:
        skill_dir = self._find_skill(skill_name)
        if not skill_dir:
            return False
        target = skill_dir / file_path
        try:
            target.relative_to(skill_dir)
        except ValueError:
            return False
        if target.exists():
            target.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def archive(self, skill_name: str) -> bool:
        src = self._resolve_skill_dir(skill_name)
        if not src.exists():
            return False
        dst = self.archive_dir / skill_name
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.move(str(src), str(dst))
        self.set_state(skill_name, STATE_ARCHIVED)
        return True

    def restore(self, skill_name: str) -> bool:
        src = self.archive_dir / skill_name
        if not src.exists():
            return False
        dst = self._resolve_skill_dir(skill_name)
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.move(str(src), str(dst))
        self.set_state(skill_name, STATE_ACTIVE)
        return True

    def delete(self, skill_name: str) -> bool:
        deleted = False
        for loc in (self._resolve_skill_dir(skill_name), self.archive_dir / skill_name):
            if loc.exists():
                shutil.rmtree(loc, ignore_errors=True)
                deleted = True
        # Clean sidecar
        usage = self._load_usage()
        if skill_name in usage:
            del usage[skill_name]
            self._save_usage(usage)
        return deleted

    def patch(self, skill_name: str, old_string: str, new_string: str) -> bool:
        """Targeted find-and-replace in SKILL.md body."""
        skill_dir = self._find_skill(skill_name)
        if not skill_dir:
            return False
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return False

        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()

        front, body = _parse_frontmatter(content)
        # Patch in full content (frontmatter + body) so old_string can match anywhere
        if old_string not in content:
            return False
        new_content = content.replace(old_string, new_string, 1)

        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(new_content)

        self.bump_patch(skill_name)
        return True

    def latest_activity_at(self, skill_name: str) -> Optional[str]:
        rec = self._get_record(skill_name)
        latest_dt: Optional[datetime] = None
        latest_raw: Optional[str] = None
        for key in ("last_used_at", "last_viewed_at", "last_patched_at"):
            raw = rec.get(key)
            dt = _parse_iso(raw)
            if dt is None:
                continue
            if latest_dt is None or dt > latest_dt:
                latest_dt = dt
                latest_raw = str(raw)
        return latest_raw
