"""质量筛选器 —— 基于质量标注筛选训练数据"""

import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable


class QualityFilter:
    """
    基于质量标注和元数据筛选高质量训练数据

    支持：
    - 按 judge score 过滤
    - 按 overall success 过滤
    - 按输入去重
    - 自定义过滤函数
    """

    def __init__(
        self,
        min_judge_score: float = 0.8,
        require_success: bool = True,
        dedup_by_input: bool = True,
        custom_filter: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    ):
        self.min_judge_score = min_judge_score
        self.require_success = require_success
        self.dedup_by_input = dedup_by_input
        self.custom_filter = custom_filter
        self._seen_hashes: set = set()

    def filter_sessions(self, session_files: List[str]) -> List[str]:
        """筛选通过质量门槛的 session 文件列表"""
        passed = []
        for sf in session_files:
            if self._check_session(sf):
                passed.append(sf)
        return passed

    def filter_directory(
        self,
        session_dir: str,
        pattern: str = "*.jsonl",
    ) -> List[str]:
        """筛选目录下所有 session 文件"""
        path = Path(session_dir)
        files = [str(f) for f in path.rglob(pattern) if f.is_file()]
        return self.filter_sessions(files)

    def _check_session(self, session_file: str) -> bool:
        """检查单个 session 是否通过质量门槛"""
        # 1. 自定义过滤
        meta = self._load_metadata(session_file)
        if self.custom_filter:
            if not self.custom_filter(session_file, meta):
                return False

        # 2. 检查 overall success
        if self.require_success:
            if not meta.get("success", True):
                return False

        # 3. 检查 judge score
        annotations = self._load_annotations(session_file)
        if annotations:
            avg_score = sum(a.get("judge_score", 0) for a in annotations) / len(annotations)
            if avg_score < self.min_judge_score:
                return False

        # 4. 去重
        if self.dedup_by_input:
            query_hash = self._hash_first_user_query(session_file)
            if not query_hash:
                return False
            if query_hash in self._seen_hashes:
                return False
            self._seen_hashes.add(query_hash)

        return True

    def _load_annotations(self, session_file: str) -> List[Dict[str, Any]]:
        """加载质量标注"""
        annotations = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get("type") == "quality_annotation":
                    annotations.append(entry.get("content", {}))
        return annotations

    def _load_metadata(self, session_file: str) -> Dict[str, Any]:
        """加载 session 元数据（合并 header 和 footer）"""
        meta = {}
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                etype = entry.get("type", "")
                if etype in ("session_header", "session_footer"):
                    meta.update(entry.get("content", {}))
        return meta

    def _hash_first_user_query(self, session_file: str) -> str:
        """计算第一个 user query 的 hash 用于去重"""
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get("type") == "user":
                    text = str(entry.get("content", ""))
                    return hashlib.md5(text.encode()).hexdigest()[:16]
        return ""
