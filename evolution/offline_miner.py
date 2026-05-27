"""离线挖掘器 —— 跨会话模式挖掘（持久化数据的独特优势）"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import Counter, defaultdict


class OfflineMiner:
    """
    跨会话模式挖掘器

    利用持久化的多会话数据，发现：
    1. 重复失败模式
    2. Skill 的系统性缺陷
    3. 跨会话的用户偏好
    4. 高频 tool call 模式
    """

    def __init__(self, semantic_index=None):
        self.semantic_index = semantic_index

    def mine_failure_patterns(
        self,
        session_files: List[str],
        min_occurrence: int = 3,
    ) -> List[Dict[str, Any]]:
        """挖掘重复失败模式"""
        failures = defaultdict(list)

        for sf in session_files:
            failure_info = self._extract_failure(sf)
            if failure_info:
                key = failure_info.get("category", "unknown")
                failures[key].append(failure_info)

        patterns = []
        for category, items in failures.items():
            if len(items) >= min_occurrence:
                patterns.append({
                    "type": "failure_pattern",
                    "category": category,
                    "count": len(items),
                    "sample_sessions": [i["session_file"] for i in items[:3]],
                    "suggestion": f"Consider creating a skill to prevent {category} failures",
                })

        return patterns

    def mine_skill_effectiveness(
        self,
        skill_name: str,
        session_files: List[str],
    ) -> Dict[str, Any]:
        """评估某个 skill 的长期有效性"""
        before = []
        after = []

        for sf in session_files:
            info = self._extract_skill_usage(sf, skill_name)
            if info:
                (before if info["created_before"] else after).append(info["success"])

        before_rate = sum(before) / len(before) if before else 0.0
        after_rate = sum(after) / len(after) if after else 0.0

        return {
            "skill_name": skill_name,
            "before_count": len(before),
            "after_count": len(after),
            "before_success_rate": round(before_rate, 3),
            "after_success_rate": round(after_rate, 3),
            "improvement": round(after_rate - before_rate, 3),
            "recommendation": "keep" if after_rate >= before_rate else "review",
        }

    def mine_user_preferences(self, session_files: List[str]) -> Dict[str, Any]:
        """挖掘跨会话的稳定用户偏好"""
        all_tool_calls = Counter()
        turn_counts = []
        languages = Counter()
        success_count = 0

        for sf in session_files:
            meta = self._extract_session_meta(sf)
            all_tool_calls.update(meta.get("tools_used", []))
            turn_counts.append(meta.get("turn_count", 0))
            if meta.get("success"):
                success_count += 1
            # 简单语言检测：基于内容字符
            lang = meta.get("detected_language", "unknown")
            if lang != "unknown":
                languages[lang] += 1

        total = len(session_files)
        return {
            "total_sessions": total,
            "success_rate": round(success_count / total, 3) if total else 0.0,
            "favorite_tools": all_tool_calls.most_common(5),
            "avg_turns": round(sum(turn_counts) / len(turn_counts), 1) if turn_counts else 0.0,
            "preferred_language": languages.most_common(1)[0][0] if languages else "unknown",
        }

    def mine_high_value_sessions(
        self,
        session_files: List[str],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """挖掘高价值会话（适合作为训练数据）"""
        scored = []
        for sf in session_files:
            score = self._compute_value_score(sf)
            scored.append((score, sf))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"session_file": sf, "value_score": round(score, 3)}
            for score, sf in scored[:top_k]
        ]

    def _compute_value_score(self, session_file: str) -> float:
        """计算单个 session 的价值分数"""
        score = 0.0
        meta = self._extract_session_meta(session_file)

        # 成功 +1.0
        if meta.get("success"):
            score += 1.0

        # 有 judge 高分 +0.5
        judge_score = meta.get("judge_score", 0)
        if judge_score >= 0.9:
            score += 0.5

        # 多轮对话 +0.3
        if meta.get("turn_count", 0) > 5:
            score += 0.3

        # 有 tool call +0.2
        if meta.get("tools_used"):
            score += 0.2

        return score

    def _extract_failure(self, session_file: str) -> Optional[Dict[str, Any]]:
        """提取失败信息"""
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get("type") == "session_footer":
                    meta = entry.get("content", {})
                    if not meta.get("success", True):
                        return {
                            "session_file": session_file,
                            "category": meta.get("failure_category", "unknown"),
                            "reason": meta.get("failure_reason", ""),
                        }
        return None

    def _extract_skill_usage(
        self,
        session_file: str,
        skill_name: str,
    ) -> Optional[Dict[str, Any]]:
        """提取 skill 使用情况（简化版，从 metadata 读取）"""
        meta = self._extract_session_meta(session_file)
        skills_used = meta.get("skills_used", [])
        return {
            "success": meta.get("success", True),
            "created_before": skill_name in skills_used,
        }

    def _extract_session_meta(self, session_file: str) -> Dict[str, Any]:
        """提取 session 元数据"""
        meta = {}
        turn_count = 0
        tools_used = set()

        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                etype = entry.get("type", "")

                if etype == "session_header":
                    meta.update(entry.get("content", {}))
                elif etype == "session_footer":
                    meta.update(entry.get("content", {}))
                elif etype in ("user", "assistant", "tool_call", "tool_result"):
                    turn_count += 1
                    if etype == "tool_call":
                        tool_name = entry.get("metadata", {}).get("tool_name")
                        if tool_name:
                            tools_used.add(tool_name)

        meta["turn_count"] = turn_count
        meta["tools_used"] = list(tools_used)
        return meta
