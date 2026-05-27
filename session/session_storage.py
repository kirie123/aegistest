"""Session 存储核心 —— 追加式 JSONL 持久化"""

import json
import uuid
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class SessionEntry:
    """单条会话记录（对应 JSONL 的一行）"""
    uuid: str
    type: str
    content: Any
    parent_uuid: Optional[str] = None
    session_id: str = ""
    run_id: str = ""
    test_id: str = ""
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class SessionStorage:
    """
    追加式 JSONL 会话存储器

    存储路径: <base_dir>/<project>/<session_id>.jsonl
    每条 entry 包含 uuid + 可选 parent_uuid，支持链式结构
    """

    def __init__(self, base_dir: str = "./sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def start_session(
        self,
        session_id: str,
        run_id: str,
        test_id: str = "",
        project: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """启动新会话，写入 header entry"""
        self._ensure_project_dir(project)
        file_path = self._get_file_path(project, session_id)

        header = SessionEntry(
            uuid=str(uuid.uuid4()),
            type="session_header",
            content={"run_id": run_id, "test_id": test_id, **(metadata or {})},
            session_id=session_id,
            run_id=run_id,
            test_id=test_id,
            timestamp=self._now(),
        )
        self._append_to_file(file_path, [header])
        return file_path

    def append_entries(
        self,
        project: str,
        session_id: str,
        entries: List[SessionEntry],
    ) -> None:
        """批量追加 entry 到指定 session"""
        file_path = self._get_file_path(project, session_id)
        self._append_to_file(file_path, entries)

    def get_session_file(self, project: str, session_id: str) -> Optional[Path]:
        """获取 session 文件路径（如果不存在返回 None）"""
        file_path = self._get_file_path(project, session_id)
        return file_path if file_path.exists() else None

    def list_sessions(self, project: str = "default") -> List[Path]:
        """列出指定 project 下的所有 session 文件"""
        project_dir = self.base_dir / project
        if not project_dir.exists():
            return []
        return sorted(project_dir.glob("*.jsonl"))

    def _append_to_file(self, file_path: Path, entries: List[SessionEntry]) -> None:
        """原子追加到 JSONL 文件"""
        lines = [e.to_jsonl() + "\n" for e in entries]
        with open(file_path, "a", encoding="utf-8") as f:
            f.writelines(lines)

    def _get_file_path(self, project: str, session_id: str) -> Path:
        return self.base_dir / project / f"{session_id}.jsonl"

    def _ensure_project_dir(self, project: str) -> None:
        (self.base_dir / project).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S")
