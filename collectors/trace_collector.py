"""Trace 收集器 — 记录每一步的详细 trace"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TraceRecord:
    """单次运行 trace 记录"""
    run_id: str
    test_id: str
    agent_name: str
    agent_version: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    agent_output: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "test_id": self.test_id,
            "agent_name": self.agent_name, "agent_version": self.agent_version,
            "steps": self.steps, "agent_output": self.agent_output,
            "start_time": self.start_time,
            "end_time": self.end_time, "metadata": self.metadata,
        }


class TraceCollector:
    """Trace 收集器"""

    def __init__(self, storage_dir: str = "./traces"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current_run: Optional[TraceRecord] = None

    def start_run(self, run_id: str, test_id: str, agent_name: str, agent_version: str):
        """开始记录一次运行"""
        self._current_run = TraceRecord(
            run_id=run_id, test_id=test_id,
            agent_name=agent_name, agent_version=agent_version,
            start_time=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

    def log_step(self, step_type: str, content: str, **kwargs):
        """记录一个步骤"""
        if self._current_run is None:
            return
        step = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": step_type,
            "content": content[:500],
            **kwargs
        }
        self._current_run.steps.append(step)

    def set_output(self, output: str):
        """记录 Agent 最终输出"""
        if self._current_run is not None:
            self._current_run.agent_output = output[:5000]

    def end_run(self, metadata: Optional[Dict[str, Any]] = None):
        """结束记录"""
        if self._current_run is None:
            return
        self._current_run.end_time = time.strftime("%Y-%m-%dT%H:%M:%S")
        if metadata:
            self._current_run.metadata.update(metadata)
        self._save_trace()
        self._current_run = None

    def _save_trace(self):
        """保存 trace 到文件"""
        if self._current_run is None:
            return
        filename = f"{self._current_run.run_id}_{self._current_run.test_id}.json"
        filepath = self.storage_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._current_run.to_dict(), f, indent=2, ensure_ascii=False)

    def get_trace(self, run_id: str, test_id: str) -> Optional[TraceRecord]:
        """获取指定 trace"""
        filename = f"{run_id}_{test_id}.json"
        filepath = self.storage_dir / filename
        if not filepath.exists():
            return None
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        return TraceRecord(**data)

    def list_traces(self) -> List[str]:
        """列出所有 trace 文件"""
        return [f.name for f in self.storage_dir.glob("*.json")]
