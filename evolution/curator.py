"""Curator — background skill maintenance orchestrator.

The curator is an auxiliary task that periodically reviews agent-created
skills and maintains the collection.

Responsibilities:
  - Auto-transition lifecycle states based on derived skill activity timestamps
  - Spawn a review agent that can pin / archive / consolidate / patch
    agent-created skills
  - Persist curator state (last_run_at, paused, etc.) in .curator_state

Strict invariants:
  - Only touches agent-created skills
  - Never auto-deletes — only archives. Archive is recoverable.
  - Pinned skills bypass all auto-transitions
"""

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .skill_manager import STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_HOURS = 24 * 7
DEFAULT_MIN_IDLE_HOURS = 2
DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 90


_CURATOR_REVIEW_PROMPT = (
    "You are running as the background skill CURATOR. This is an "
    "UMBRELLA-BUILDING consolidation pass, not a passive audit.\n\n"
    "The goal: a LIBRARY OF CLASS-LEVEL INSTRUCTIONS. A collection of hundreds "
    "of narrow skills where each one captures one session's specific bug is a "
    "FAILURE. One broad umbrella skill with labeled subsections beats five "
    "narrow siblings for discoverability.\n\n"
    "Hard rules:\n"
    "1. DO NOT touch bundled or hub-installed skills. Candidate list below is "
    "already filtered to agent-created skills only.\n"
    "2. DO NOT delete any skill. Archiving is the maximum destructive action.\n"
    "3. DO NOT touch skills shown as pinned=yes. Skip them entirely.\n"
    "4. DO NOT reject consolidation on 'each skill has a distinct trigger'. "
    "Pairwise distinctness is the wrong bar. Ask: 'would a maintainer write "
    "this as N separate skills, or as one skill with N labeled subsections?'\n\n"
    "How to work:\n"
    "1. Scan the full candidate list. Identify PREFIX CLUSTERS.\n"
    "2. For each cluster with 2+ members, ask 'what is the UMBRELLA CLASS?'\n"
    "3. Three ways to consolidate:\n"
    "   a. MERGE INTO EXISTING UMBRELLA — patch it, archive siblings.\n"
    "   b. CREATE A NEW UMBRELLA SKILL.md — create class-level skill, archive siblings.\n"
    "   c. DEMOTE TO REFERENCES/TEMPLATES/SCRIPTS — move narrow content under umbrella.\n"
    "4. Flag skills whose NAME is too narrow (PR number, error string, codename).\n"
    "5. Iterate. Don't stop after 3 merges.\n\n"
    "Your tools:\n"
    "  - skill_manage action=patch      — add sections to umbrella\n"
    "  - skill_manage action=create     — create new umbrella SKILL.md\n"
    "  - skill_manage action=write_file — add references/ templates/ scripts/\n"
    "  - skill_manage action=delete     — archive a skill (pass absorbed_into=<umbrella>)\n\n"
    "Expected output: real umbrella-ification. Process every obvious cluster.\n\n"
    "When done, write a human summary AND a structured block:\n\n"
    "## Structured summary (required)\n"
    "```yaml\n"
    "consolidations:\n"
    "  - from: <old-skill-name>\n"
    "    into: <umbrella-skill-name>\n"
    "    reason: <one short sentence>\n"
    "prunings:\n"
    "  - name: <skill-name>\n"
    "    reason: <one short sentence>\n"
    "```\n"
)


class Curator:
    """Skill curator with automatic transitions + optional LLM consolidation."""

    def __init__(
        self,
        skill_manager,
        llm_client=None,
        check_interval_days: int = 7,
        stale_threshold_days: int = 30,
        archive_threshold_days: int = 90,
        state_file: Optional[str] = None,
    ):
        self.skill_manager = skill_manager
        self.llm_client = llm_client
        self.check_interval_days = check_interval_days
        self.stale_threshold_days = stale_threshold_days
        self.archive_threshold_days = archive_threshold_days

        if state_file is None:
            state_file = str(Path(skill_manager.skills_dir) / ".curator_state")
        self.state_file = Path(state_file)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _default_state(self) -> Dict[str, Any]:
        return {
            "last_run_at": None,
            "last_run_duration_seconds": None,
            "last_run_summary": None,
            "paused": False,
            "run_count": 0,
        }

    def load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return self._default_state()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = self._default_state()
                base.update({k: v for k, v in data.items() if k in base or k.startswith("_")})
                return base
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Failed to read curator state: %s", e)
        return self._default_state()

    def save_state(self, data: Dict[str, Any]) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.state_file.parent), prefix=".curator_state_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(self.state_file))
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.debug("Failed to save curator state: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Automatic transitions (pure, no LLM)
    # ------------------------------------------------------------------
    def apply_automatic_transitions(self, now: Optional[datetime] = None) -> Dict[str, int]:
        if now is None:
            now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=self.stale_threshold_days)
        archive_cutoff = now - timedelta(days=self.archive_threshold_days)

        counts = {"marked_stale": 0, "archived": 0, "reactivated": 0, "checked": 0}

        for rec in self.skill_manager.list_skills(include_archived=False):
            counts["checked"] += 1
            name = rec["name"]
            if rec.get("pinned"):
                continue

            last_activity = self.skill_manager.latest_activity_at(name)
            anchor = (
                self._parse_iso(last_activity)
                or self._parse_iso(rec.get("updated_at"))
                or self._parse_iso(rec.get("created_at"))
                or now
            )

            current = self.skill_manager.get_state(name)

            if anchor <= archive_cutoff and current != STATE_ARCHIVED:
                if self.skill_manager.archive(name):
                    counts["archived"] += 1
            elif anchor <= stale_cutoff and current == STATE_ACTIVE:
                self.skill_manager.set_state(name, STATE_STALE)
                counts["marked_stale"] += 1
            elif anchor > stale_cutoff and current == STATE_STALE:
                self.skill_manager.set_state(name, STATE_ACTIVE)
                counts["reactivated"] += 1

        return counts

    @staticmethod
    def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Consolidation suggestions (rule-based MVP)
    # ------------------------------------------------------------------
    def suggest_consolidation(self, skills: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        if skills is None:
            skills = self.skill_manager.list_skills(include_archived=False, agent_created_only=True)
        suggestions = []
        names = [s["name"] for s in skills]

        # Rule 1: shared prefix clusters
        prefixes: Dict[str, List[str]] = {}
        for name in names:
            parts = name.split("_")
            if len(parts) >= 2:
                prefix = parts[0]
                prefixes.setdefault(prefix, []).append(name)

        for prefix, group in prefixes.items():
            if len(group) >= 3:
                suggestions.append({
                    "type": "consolidate_by_prefix",
                    "target_skills": group,
                    "proposed_umbrella": f"{prefix}_best_practices",
                    "reason": f"{len(group)} skills share prefix '{prefix}'",
                })

        # Rule 2: high name similarity
        from difflib import SequenceMatcher
        for i, name_a in enumerate(names):
            similar = [name_a]
            for name_b in names[i + 1:]:
                ratio = SequenceMatcher(None, name_a, name_b).ratio()
                if ratio > 0.7:
                    similar.append(name_b)
            if len(similar) >= 2:
                suggestions.append({
                    "type": "consolidate_by_similarity",
                    "target_skills": similar,
                    "proposed_umbrella": f"merged_{similar[0]}",
                    "reason": f"High name similarity among {len(similar)} skills",
                })

        # Deduplicate
        seen: Set[tuple] = set()
        unique: List[Dict[str, Any]] = []
        for s in suggestions:
            key = tuple(sorted(s["target_skills"]))
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return unique

    # ------------------------------------------------------------------
    # LLM-driven consolidation pass
    # ------------------------------------------------------------------
    def _run_llm_consolidation(self) -> Dict[str, Any]:
        """Run the LLM-driven consolidation review."""
        llm_meta: Dict[str, Any] = {"final": "", "summary": "", "tool_calls": [], "error": None}
        if self.llm_client is None:
            llm_meta["summary"] = "skipped (no LLM client)"
            return llm_meta

        candidates = self.skill_manager.agent_created_report()
        if not candidates:
            llm_meta["summary"] = "skipped (no agent-created skills)"
            return llm_meta

        candidate_list = self._render_candidate_list(candidates)
        prompt = f"{_CURATOR_REVIEW_PROMPT}\n\n{candidate_list}"

        # Simplified: single-turn LLM call (no tool loop for curator to keep it simple)
        try:
            result = self.llm_client.complete(prompt)
            llm_meta["final"] = result
            llm_meta["summary"] = (result[:240] + "…") if len(result) > 240 else (result or "no change")
        except Exception as e:
            llm_meta["error"] = str(e)
            llm_meta["summary"] = f"error: {e}"

        return llm_meta

    @staticmethod
    def _render_candidate_list(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "No agent-created skills to review."
        lines = [f"Agent-created skills ({len(rows)}):\n"]
        for r in rows:
            lines.append(
                f"- {r['name']}  "
                f"state={r.get('status', 'active')}  "
                f"pinned={'yes' if r.get('pinned') else 'no'}  "
                f"activity={r.get('use_count', 0) + r.get('view_count', 0) + r.get('patch_count', 0)}  "
                f"last_activity={r.get('last_activity_at') or 'never'}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------
    def run_maintenance(
        self,
        synchronous: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute a single curator review pass."""
        start = datetime.now(timezone.utc)

        # 1. Auto transitions
        if dry_run:
            counts = {
                "checked": len(self.skill_manager.agent_created_report()),
                "marked_stale": 0, "archived": 0, "reactivated": 0,
            }
        else:
            counts = self.apply_automatic_transitions(now=start)

        auto_parts = []
        if counts["marked_stale"]:
            auto_parts.append(f"{counts['marked_stale']} marked stale")
        if counts["archived"]:
            auto_parts.append(f"{counts['archived']} archived")
        if counts["reactivated"]:
            auto_parts.append(f"{counts['reactivated']} reactivated")
        auto_summary = ", ".join(auto_parts) if auto_parts else "no changes"

        # Persist state
        state = self.load_state()
        if not dry_run:
            state["last_run_at"] = start.isoformat()
            state["run_count"] = int(state.get("run_count", 0)) + 1
        prefix = "dry-run auto: " if dry_run else "auto: "
        state["last_run_summary"] = f"{prefix}{auto_summary}"
        self.save_state(state)

        # 2. LLM consolidation pass
        def _llm_pass():
            llm_meta = self._run_llm_consolidation()
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            state2 = self.load_state()
            state2["last_run_duration_seconds"] = elapsed
            final = f"{prefix}{auto_summary}; llm: {llm_meta.get('summary', 'no change')}"
            state2["last_run_summary"] = final
            self.save_state(state2)

        if synchronous:
            _llm_pass()
        else:
            t = threading.Thread(target=_llm_pass, daemon=True, name="curator-review")
            t.start()

        return {
            "started_at": start.isoformat(),
            "auto_transitions": counts,
            "auto_summary": auto_summary,
            "summary_so_far": auto_summary,
            "checked": counts["checked"],
            "marked_stale": counts["marked_stale"],
            "archived": counts["archived"],
            "reactivated": counts["reactivated"],
            "consolidation_suggestions": self.suggest_consolidation(),
        }

    def should_run_now(self) -> bool:
        """Gate: check if enough time has passed since last run."""
        state = self.load_state()
        if state.get("paused"):
            return False
        last = self._parse_iso(state.get("last_run_at"))
        if last is None:
            # First run: seed state and defer
            state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            state["last_run_summary"] = "deferred first run"
            self.save_state(state)
            return False
        interval = timedelta(days=self.check_interval_days)
        return (datetime.now(timezone.utc) - last) >= interval
