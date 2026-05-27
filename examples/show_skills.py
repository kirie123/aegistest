"""
演示自进化生成的 Skill 和 Memory 目录结构
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegistest import SessionLake
from aegistest.session.session_storage import SessionEntry

SKILL_DIR = os.path.expanduser("~/.aegistest_demo/skills")
MEMORY_FILE = os.path.expanduser("~/.aegistest_demo/memory.json")
SESSION_DIR = "./sessions_showcase"


def show_tree(path, prefix=""):
    """简单的目录树打印"""
    import os
    items = sorted(os.listdir(path))
    for i, item in enumerate(items):
        item_path = os.path.join(path, item)
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{item}")
        if os.path.isdir(item_path):
            extension = "    " if is_last else "│   "
            show_tree(item_path, prefix + extension)


def main():
    print("=" * 60)
    print("自进化 Skill / Memory 目录演示")
    print("=" * 60)

    # 创建 SessionLake（启用进化）
    lake = SessionLake(
        session_dir=SESSION_DIR,
        skill_dir=SKILL_DIR,
        memory_file=MEMORY_FILE,
        enable_evolution=True,
    )

    # 场景 1：用户纠正 → 触发 skill 创建
    print("\n[1] 模拟对话：用户纠正 Agent...")
    sid1 = "sess-correction"
    lake.storage.start_session(sid1, "run-001")
    lake.storage.append_entries("default", sid1, [
        SessionEntry(uuid="u1", type="user", content="Write a Python function", session_id=sid1),
        SessionEntry(uuid="a1", type="assistant", content="def foo(): pass", parent_uuid="u1", session_id=sid1),
        SessionEntry(uuid="u2", type="user", content="不对，你应该加类型注解", parent_uuid="a1", session_id=sid1),
        SessionEntry(uuid="a2", type="assistant", content="def foo() -> None: pass", parent_uuid="u2", session_id=sid1),
        SessionEntry(uuid="f1", type="session_footer", content={"success": True}, parent_uuid="a2", session_id=sid1),
    ])

    sf1 = str(lake.storage.get_session_file("default", sid1))
    result1 = lake.review_session(sf1, review_type="skill")
    print(f"   Review actions: {len(result1['actions'])}, executed: {len(result1['executed'])}")

    # 场景 2：长对话 → 手动写入 memory（演示 memory 存储）
    print("\n[2] 写入 Memory...")
    lake.memory_manager.add("preferred_language", "zh-CN", category="preferences")
    lake.memory_manager.add("coding_style", "type_hints_and_snake_case", category="preferences")
    lake.memory_manager.add("user_name", "Alice", category="persona")
    print(f"   Memory categories: {lake.memory_manager.list_categories()}")

    # 场景 3：创建一个旧 skill，然后运行 curator 归档它
    print("\n[3] 创建旧 Skill 并触发 Curator 归档...")
    lake.skill_manager.upsert("legacy_v1_style", "Use camelCase everywhere",
        metadata={"updated_at": "2020-01-01T00:00:00"})
    lake.skill_manager.upsert("modern_python", "Use type hints and snake_case",
        metadata={"updated_at": "2025-05-27T00:00:00"})

    maint = lake.run_evolution_maintenance()
    print(f"   Curator archived: {maint['curator']['archived']}")

    # 展示目录结构
    print("\n" + "=" * 60)
    print(f"Skill 目录结构: {SKILL_DIR}")
    print("=" * 60)
    if os.path.exists(SKILL_DIR):
        show_tree(SKILL_DIR)
    else:
        print("  (empty)")

    print("\n" + "=" * 60)
    print(f"Memory 文件: {MEMORY_FILE}")
    print("=" * 60)
    if os.path.exists(MEMORY_FILE):
        import json
        with open(MEMORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("  (not found)")

    # 展示 Skill 内容
    print("\n" + "=" * 60)
    print("Skill 内容预览")
    print("=" * 60)
    for skill in lake.skill_manager.list_skills(include_archived=True):
        name = skill["name"]
        status = skill.get("status", "unknown")
        content = lake.skill_manager.get(name)
        print(f"\n  [{status}] {name}:")
        print(f"    {content[:120]}..." if content and len(content) > 120 else f"    {content}")

    print("\n" + "=" * 60)
    print("演示完成！")
    print(f"Skill 目录: {SKILL_DIR}")
    print(f"Memory 文件: {MEMORY_FILE}")
    print(f"Session 目录: {SESSION_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
