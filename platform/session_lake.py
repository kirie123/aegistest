"""SessionLake — Agent session data platform.

Responsibilities:
1. Unified session persistence (JSONL append-only)
2. Training data production (filter → convert → export)
3. Self-evolution engine (Online Review + Offline Mining + Curator)

Design principles:
- Decoupled from AegisTest, usable by both testing framework and production agents
- All components lazy-initialized
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class SessionLake:
    """
    Agent session data platform.

    Usage (testing):
        lake = SessionLake(session_dir="./sessions", enable_evolution=True)
        aegis = AegisTest(agent=MyAgent(), session_lake=lake)
        aegis.run_suite(suite)
        lake.export_training_data("train.json", format="chatml")
        lake.run_evolution_maintenance()

    Usage (production):
        lake = SessionLake(session_dir="./prod_sessions", enable_evolution=True)
        lake.storage.start_session(session_id, run_id)
        lake.storage.append_entries(project, session_id, entries)
        lake.review_session(session_file)
    """

    def __init__(
        self,
        session_dir: str = "./sessions",
        skill_dir: str = "~/.aegistest/skills",
        memory_file: Optional[str] = None,
        memory_dir: str = "~/.aegistest/memories",
        enable_evolution: bool = False,
        evolution_review_type: str = "combined",
        llm_client=None,
    ):
        from ..session.session_storage import SessionStorage
        from ..session.session_loader import SessionLoader

        self.storage = SessionStorage(session_dir)
        self.loader = SessionLoader()

        # Evolution components (lazy)
        self._enable_evolution = enable_evolution
        self._evolution_review_type = evolution_review_type
        self._llm_client = llm_client
        self._skill_dir = skill_dir
        # Back-compat: if memory_file is provided, pass it for migration
        self._memory_file = memory_file
        self._memory_dir = memory_dir

        self._skill_manager = None
        self._memory_manager = None
        self._online_reviewer = None
        self._offline_miner = None
        self._curator = None

    # ==================== Training Data Export ====================

    def export_training_data(
        self,
        output_path: str = "train_data.json",
        output_format: str = "chatml",
        project: str = "default",
        min_judge_score: float = 0.0,
        require_success: bool = False,
        dedup_by_input: bool = True,
    ) -> str:
        from ..datapipeline.trace_converter import TraceConverter
        from ..datapipeline.quality_filter import QualityFilter
        from ..datapipeline.dataset_exporter import DatasetExporter

        session_files = [str(f) for f in self.storage.list_sessions(project)]
        if not session_files:
            print(f"[SessionLake] No sessions found in project '{project}'.")
            return ""

        filter = QualityFilter(
            min_judge_score=min_judge_score,
            require_success=require_success,
            dedup_by_input=dedup_by_input,
        )
        passed_files = filter.filter_sessions(session_files)

        converter = TraceConverter()
        conversations = []
        for sf in passed_files:
            try:
                conv = converter.convert(sf, output_format)
                conversations.append(conv)
            except Exception as e:
                print(f"[SessionLake] Skip {sf}: {e}")

        DatasetExporter.export_json(conversations, output_path)
        print(f"[SessionLake] {len(conversations)} conversations exported to {output_path}")
        return output_path

    def export_dpo_pairs(
        self,
        output_path: str = "dpo_data.json",
        output_format: str = "json",
        project: str = "default",
    ) -> str:
        from ..datapipeline.dataset_exporter import DatasetExporter

        sessions_by_test: Dict[str, Dict[str, List[str]]] = {}

        for sf in self.storage.list_sessions(project):
            meta = self.loader.extract_metadata(str(sf))
            test_id = meta.get("test_id", "unknown")
            success = meta.get("success", True)
            sessions_by_test.setdefault(test_id, {"success": [], "failed": []})
            sessions_by_test[test_id]["success" if success else "failed"].append(str(sf))

        pairs = []
        for test_id, groups in sessions_by_test.items():
            for success_sf in groups["success"]:
                for failed_sf in groups["failed"]:
                    success_chain = self.loader.load_session(success_sf)
                    failed_chain = self.loader.load_session(failed_sf)

                    prompt_msgs = []
                    chosen_msgs = []
                    rejected_msgs = []

                    for entry in success_chain:
                        role = entry.get("type")
                        if role == "user":
                            prompt_msgs.append({"role": "user", "content": str(entry.get("content", ""))})
                        elif role == "assistant":
                            chosen_msgs.append({"role": "assistant", "content": str(entry.get("content", ""))})

                    for entry in failed_chain:
                        role = entry.get("type")
                        if role == "assistant":
                            rejected_msgs.append({"role": "assistant", "content": str(entry.get("content", ""))})

                    if prompt_msgs and chosen_msgs and rejected_msgs:
                        pairs.append({
                            "prompt": prompt_msgs,
                            "chosen": chosen_msgs,
                            "rejected": rejected_msgs,
                            "test_id": test_id,
                        })

        DatasetExporter.export_dpo_pairs(pairs, output_path, format=output_format)
        print(f"[SessionLake] {len(pairs)} DPO pairs exported to {output_path}")
        return output_path

    # ==================== Self-Evolution API ====================

    def review_session(
        self,
        session_file: str,
        review_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run online review on a single session file."""
        if not self._enable_evolution:
            return {"error": "evolution not enabled"}
        reviewer = self._get_online_reviewer()
        return reviewer.review_session(
            session_file,
            review_type=review_type or self._evolution_review_type,
        )

    def run_evolution_maintenance(self, project: str = "default") -> Dict[str, Any]:
        """Run evolution maintenance (Curator + Offline Miner)."""
        if not self._enable_evolution:
            print("[SessionLake] Evolution not enabled.")
            return {}

        results = {}

        # 1. Curator maintenance
        curator = self._get_curator()
        results["curator"] = curator.run_maintenance()
        print(f"[SessionLake] Curator: {results['curator']}")

        # 2. Offline mining
        session_files = [str(f) for f in self.storage.list_sessions(project)]
        if session_files:
            miner = self._get_offline_miner()
            results["failure_patterns"] = miner.mine_failure_patterns(session_files)
            results["user_preferences"] = miner.mine_user_preferences(session_files)
            results["high_value_sessions"] = miner.mine_high_value_sessions(session_files, top_k=10)
            print(f"[SessionLake] Mined {len(results['failure_patterns'])} failure patterns")

        return results

    # ==================== Query API ====================

    def list_sessions(self, project: str = "default") -> List[Path]:
        return self.storage.list_sessions(project)

    def get_session_metadata(self, session_file: str) -> Dict[str, Any]:
        return self.loader.extract_metadata(session_file)

    # ==================== Lazy init ====================

    def _get_online_reviewer(self):
        if self._online_reviewer is None:
            from ..evolution.online_reviewer import OnlineReviewer
            self._online_reviewer = OnlineReviewer(
                llm_client=self._llm_client,
                skill_manager=self._get_skill_manager(),
                memory_manager=self._get_memory_manager(),
            )
        return self._online_reviewer

    def _get_offline_miner(self):
        if self._offline_miner is None:
            from ..evolution.offline_miner import OfflineMiner
            self._offline_miner = OfflineMiner()
        return self._offline_miner

    def _get_skill_manager(self):
        if self._skill_manager is None:
            from ..evolution.skill_manager import SkillManager
            self._skill_manager = SkillManager(self._skill_dir)
        return self._skill_manager

    def _get_memory_manager(self):
        if self._memory_manager is None:
            from ..evolution.memory_manager import MemoryManager
            self._memory_manager = MemoryManager(
                memory_dir=self._memory_dir,
                legacy_json_file=self._memory_file,
            )
        return self._memory_manager

    def _get_curator(self):
        if self._curator is None:
            from ..evolution.curator import Curator
            self._curator = Curator(
                skill_manager=self._get_skill_manager(),
                llm_client=self._llm_client,
                state_file=str(Path(self._skill_dir).expanduser() / ".curator_state"),
            )
        return self._curator

    @property
    def skill_manager(self):
        return self._get_skill_manager()

    @property
    def memory_manager(self):
        return self._get_memory_manager()

    @property
    def online_reviewer(self):
        return self._get_online_reviewer()

    @property
    def offline_miner(self):
        return self._get_offline_miner()

    @property
    def curator(self):
        return self._get_curator()
