"""Skill 管理器 —— Skill 的创建、读取、更新、归档"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class SkillManager:
    """
    Skill 文件系统管理器

    存储结构：
    <skills_dir>/
    ├── <skill_name>/
    │   ├── skill.json      # 元数据
    │   └── prompt.md       # 提示内容
    ├── <another_skill>/
    └── .archive/           # 归档目录
    """

    def __init__(self, skills_dir: str = "~/.aegistest/skills"):
        self.skills_dir = Path(skills_dir).expanduser()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.skills_dir / ".archive"
        self.archive_dir.mkdir(exist_ok=True)

    def upsert(
        self,
        skill_name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """创建或更新 skill"""
        skill_path = self.skills_dir / skill_name
        skill_path.mkdir(exist_ok=True)

        # 写入 prompt
        prompt_file = skill_path / "prompt.md"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(content)

        # 读取已有元数据（如果存在）
        meta_file = skill_path / "skill.json"
        existing_meta = {}
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing_meta = json.load(f)
            except json.JSONDecodeError:
                pass

        # 更新元数据
        from datetime import datetime
        now = datetime.now().isoformat()
        meta = {
            **existing_meta,
            "name": skill_name,
            "updated_at": now,
            "version": existing_meta.get("version", "1.0"),
            **(metadata or {}),
        }
        if "created_at" not in meta:
            meta["created_at"] = now

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        return str(skill_path)

    def get(self, skill_name: str) -> Optional[str]:
        """读取 skill 的 prompt 内容"""
        prompt_file = self.skills_dir / skill_name / "prompt.md"
        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read()
        # 尝试从归档读取
        archived = self.archive_dir / skill_name / "prompt.md"
        if archived.exists():
            with open(archived, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_meta(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """读取 skill 元数据"""
        meta_file = self.skills_dir / skill_name / "skill.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def list_skills(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """列出所有 skill 的元数据"""
        skills = []
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            meta = self.get_meta(skill_dir.name)
            if meta:
                meta["status"] = "active"
                skills.append(meta)

        if include_archived:
            for skill_dir in self.archive_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                meta_file = skill_dir / "skill.json"
                if meta_file.exists():
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        meta["status"] = "archived"
                        skills.append(meta)

        return skills

    def archive(self, skill_name: str) -> bool:
        """归档 skill（移动到 .archive，不删除）"""
        src = self.skills_dir / skill_name
        if not src.exists():
            return False

        dst = self.archive_dir / skill_name
        # 如果目标已存在，先删除
        if dst.exists():
            import shutil
            shutil.rmtree(dst)

        src.rename(dst)
        return True

    def restore(self, skill_name: str) -> bool:
        """从归档恢复 skill"""
        src = self.archive_dir / skill_name
        if not src.exists():
            return False

        dst = self.skills_dir / skill_name
        if dst.exists():
            import shutil
            shutil.rmtree(dst)

        src.rename(dst)
        return True

    def delete(self, skill_name: str) -> bool:
        """彻底删除 skill（包括归档）"""
        import shutil
        deleted = False
        for loc in [self.skills_dir / skill_name, self.archive_dir / skill_name]:
            if loc.exists():
                shutil.rmtree(loc)
                deleted = True
        return deleted
