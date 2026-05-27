"""策展人 —— Skill 的慢速维护与归档"""

from datetime import datetime, timedelta
from typing import Dict, Any, List


class Curator:
    """
    Skill 策展人

    防止 skill 无限膨胀：
    1. 自动状态迁移（active → stale → archived）
    2. 建议合并重叠 skill
    """

    def __init__(
        self,
        skill_manager,
        check_interval_days: int = 7,
        stale_threshold_days: int = 30,
        archive_threshold_days: int = 90,
    ):
        self.skill_manager = skill_manager
        self.check_interval_days = check_interval_days
        self.stale_threshold_days = stale_threshold_days
        self.archive_threshold_days = archive_threshold_days

    def run_maintenance(self) -> Dict[str, Any]:
        """执行维护任务"""
        skills = self.skill_manager.list_skills(include_archived=False)

        archived = []
        marked_stale = []
        active_count = 0

        for skill in skills:
            status = self._determine_status(skill)

            if status == "archive":
                if self.skill_manager.archive(skill["name"]):
                    archived.append(skill["name"])
            elif status == "stale":
                marked_stale.append(skill["name"])
            else:
                active_count += 1

        # 生成合并建议
        consolidation = self.suggest_consolidation(skills)

        return {
            "checked": len(skills),
            "active": active_count,
            "marked_stale": marked_stale,
            "archived": archived,
            "consolidation_suggestions": consolidation,
        }

    def _determine_status(self, skill: Dict[str, Any]) -> str:
        """确定 skill 状态"""
        updated_str = skill.get("updated_at", "")
        if not updated_str:
            return "active"

        try:
            updated = datetime.fromisoformat(updated_str)
        except ValueError:
            return "active"

        days_since = (datetime.now() - updated).days

        if days_since >= self.archive_threshold_days:
            return "archive"
        elif days_since >= self.stale_threshold_days:
            return "stale"
        return "active"

    def suggest_consolidation(
        self,
        skills: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        建议合并重叠的 skill

        MVP 版本基于名称前缀相似度判断。
        生产版本可接入 LLM 分析 skill 内容相似度。
        """
        suggestions = []
        names = [s["name"] for s in skills]

        # 规则 1：共享前缀
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

        # 规则 2：相似子串
        from difflib import SequenceMatcher
        for i, name_a in enumerate(names):
            similar = [name_a]
            for name_b in names[i + 1 :]:
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

        # 去重
        seen = set()
        unique = []
        for s in suggestions:
            key = tuple(sorted(s["target_skills"]))
            if key not in seen:
                seen.add(key)
                unique.append(s)

        return unique
