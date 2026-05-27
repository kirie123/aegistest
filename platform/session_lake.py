"""SessionLake —— Agent 会话数据平台

职责：
1. 统一 Session 持久化（JSONL 追加式存储）
2. 训练数据生产（筛选 → 格式转换 → 导出）
3. 自进化引擎（Online Review + Offline Mining + Curator）

设计原则：
- 与 AegisTest 解耦，可被测试框架和生产 Agent 共用
- 所有组件惰性初始化，未使用时不创建
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class SessionLake:
    """
    Agent 会话数据平台

    使用示例（测试场景）：
        lake = SessionLake(session_dir="./sessions", enable_evolution=True)
        aegis = AegisTest(agent=MyAgent(), session_lake=lake)
        aegis.run_suite(suite)
        lake.export_training_data("train.json", format="chatml")
        lake.run_evolution_maintenance()

    使用示例（生产场景）：
        lake = SessionLake(session_dir="./prod_sessions", enable_evolution=True)
        # Agent 运行后
        lake.storage.start_session(session_id, run_id)
        lake.storage.append_entries(project, session_id, entries)
        lake.online_reviewer.review_session(session_file)
    """

    def __init__(
        self,
        session_dir: str = "./sessions",
        skill_dir: str = "~/.aegistest/skills",
        memory_file: str = "~/.aegistest/memory.json",
        enable_evolution: bool = False,
        evolution_review_type: str = "combined",
        llm_client=None,
    ):
        from ..session.session_storage import SessionStorage
        from ..session.session_loader import SessionLoader

        self.storage = SessionStorage(session_dir)
        self.loader = SessionLoader()

        # Evolution 组件（惰性创建）
        self._enable_evolution = enable_evolution
        self._evolution_review_type = evolution_review_type
        self._llm_client = llm_client
        self._skill_dir = skill_dir
        self._memory_file = memory_file

        self._skill_manager = None
        self._memory_manager = None
        self._online_reviewer = None
        self._offline_miner = None
        self._curator = None

    # ==================== 训练数据生产 API ====================

    def export_training_data(
        self,
        output_path: str = "train_data.json",
        output_format: str = "chatml",
        project: str = "default",
        min_judge_score: float = 0.0,
        require_success: bool = False,
        dedup_by_input: bool = True,
    ) -> str:
        """
        导出持久化的 session 为训练数据

        Args:
            output_path: 输出文件路径
            output_format: chatml | sharegpt | traces | raw_messages
            project: 要导出的 project 名称
            min_judge_score: 最低 judge 分数门槛（0 表示不过滤）
            require_success: 是否只导出成功会话
            dedup_by_input: 是否按输入去重
        """
        from ..datapipeline.trace_converter import TraceConverter
        from ..datapipeline.quality_filter import QualityFilter
        from ..datapipeline.dataset_exporter import DatasetExporter

        session_files = [str(f) for f in self.storage.list_sessions(project)]
        if not session_files:
            print(f"[SessionLake] No sessions found in project '{project}'.")
            return ""

        # 质量筛选
        filter = QualityFilter(
            min_judge_score=min_judge_score,
            require_success=require_success,
            dedup_by_input=dedup_by_input,
        )
        passed_files = filter.filter_sessions(session_files)

        # 格式转换
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
        """
        导出 DPO preference pairs

        基于同一测试用例的成功 vs 失败 session 构造 chosen/rejected
        """
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

    # ==================== 自进化 API ====================

    def review_session(
        self,
        session_file: str,
        review_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """对单个 session 文件运行在线 review"""
        if not self._enable_evolution:
            return {"error": "evolution not enabled"}
        reviewer = self._get_online_reviewer()
        return reviewer.review_session(
            session_file,
            review_type=review_type or self._evolution_review_type,
        )

    def run_evolution_maintenance(self, project: str = "default") -> Dict[str, Any]:
        """
        运行进化维护任务（Curator + Offline Miner）

        建议作为定时任务（如每天凌晨）调用。
        """
        if not self._enable_evolution:
            print("[SessionLake] Evolution not enabled.")
            return {}

        results = {}

        # 1. Curator 维护
        if self._skill_manager:
            from ..evolution.curator import Curator
            curator = Curator(self._skill_manager)
            results["curator"] = curator.run_maintenance()
            print(f"[SessionLake] Curator: {results['curator']}")

        # 2. Offline 挖掘
        session_files = [str(f) for f in self.storage.list_sessions(project)]
        if session_files:
            miner = self._get_offline_miner()
            results["failure_patterns"] = miner.mine_failure_patterns(session_files)
            results["user_preferences"] = miner.mine_user_preferences(session_files)
            results["high_value_sessions"] = miner.mine_high_value_sessions(session_files, top_k=10)
            print(f"[SessionLake] Mined {len(results['failure_patterns'])} failure patterns")

        return results

    # ==================== 查询 API ====================

    def list_sessions(self, project: str = "default") -> List[Path]:
        """列出所有 session 文件"""
        return self.storage.list_sessions(project)

    def get_session_metadata(self, session_file: str) -> Dict[str, Any]:
        """获取 session 元数据"""
        return self.loader.extract_metadata(session_file)

    # ==================== 内部：惰性初始化 ====================

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
            self._memory_manager = MemoryManager(self._memory_file)
        return self._memory_manager

    @property
    def skill_manager(self):
        """暴露 skill_manager（惰性初始化）"""
        return self._get_skill_manager()

    @property
    def memory_manager(self):
        """暴露 memory_manager（惰性初始化）"""
        return self._get_memory_manager()

    @property
    def online_reviewer(self):
        """暴露 online_reviewer（惰性初始化）"""
        return self._get_online_reviewer()

    @property
    def offline_miner(self):
        """暴露 offline_miner（惰性初始化）"""
        return self._get_offline_miner()
