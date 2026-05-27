"""Memory 管理器 —— 用户偏好和事实的持久化存储"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class MemoryManager:
    """
    Memory 管理器

    以 JSON 文件形式持久化用户相关信息：
    ~/.aegistest/memory.json

    结构：
    {
        "general": {
            "user_name": {"value": "Alice", "updated_at": "..."}
        },
        "preferences": {
            "language": {"value": "zh-CN", "updated_at": "..."}
        }
    }
    """

    def __init__(self, memory_file: str = "~/.aegistest/memory.json"):
        self.memory_file = Path(memory_file).expanduser()
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self._memories: Dict[str, Dict[str, Any]] = {}
        self._load()

    def add(self, key: str, value: Any, category: str = "general") -> None:
        """添加或更新记忆"""
        if category not in self._memories:
            self._memories[category] = {}

        from datetime import datetime
        self._memories[category][key] = {
            "value": value,
            "updated_at": datetime.now().isoformat(),
        }
        self._save()

    def get(self, key: str, category: str = "general") -> Any:
        """读取记忆值"""
        cat = self._memories.get(category, {})
        entry = cat.get(key)
        return entry["value"] if entry else None

    def get_entry(self, key: str, category: str = "general") -> Optional[Dict[str, Any]]:
        """读取完整记忆条目（含 updated_at）"""
        cat = self._memories.get(category, {})
        return cat.get(key)

    def get_by_category(self, category: str) -> Dict[str, Any]:
        """按类别获取所有记忆值"""
        return {
            k: v["value"]
            for k, v in self._memories.get(category, {}).items()
        }

    def delete(self, key: str, category: str = "general") -> bool:
        """删除记忆"""
        cat = self._memories.get(category, {})
        if key in cat:
            del cat[key]
            self._save()
            return True
        return False

    def search(self, keyword: str) -> List[Dict[str, Any]]:
        """关键词搜索记忆"""
        results = []
        keyword_lower = keyword.lower()
        for category, items in self._memories.items():
            for key, entry in items.items():
                value_str = str(entry["value"]).lower()
                if keyword_lower in key.lower() or keyword_lower in value_str:
                    results.append({
                        "category": category,
                        "key": key,
                        "value": entry["value"],
                        "updated_at": entry.get("updated_at", ""),
                    })
        return results

    def list_categories(self) -> List[str]:
        """列出所有类别"""
        return list(self._memories.keys())

    def to_dict(self) -> Dict[str, Any]:
        """导出全部记忆"""
        return self._memories.copy()

    def _load(self) -> None:
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    self._memories = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._memories = {}

    def _save(self) -> None:
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self._memories, f, indent=2, ensure_ascii=False)
