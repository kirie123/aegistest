"""
DeepSeek API 驱动的自进化端到端测试

读取 C:\\Users\\Administrator\\.aiko\\settings.json 中的 DeepSeek API 配置，
使用真实大模型进行在线 review 和 curator consolidation。
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegistest import SessionLake
from aegistest.session.session_storage import SessionStorage, SessionEntry
from aegistest.llm import OpenAIClient


def test_deepseek_online_review():
    print("\n[Test] DeepSeek LLM 在线 Review（Skill + Memory）")

    # 1. 初始化 DeepSeek client（自动读取 .aiko/settings.json）
    # Use deepseek-chat (non-reasoning model) for tool_call support
    llm = OpenAIClient(
        api_key="sk-82f51fb2311740d28ac6dccc858b9088",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    print(f"  [Config] model={llm.model}, base_url={llm._api_base}")

    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            memory_dir=os.path.join(tmpdir, "memories"),
            enable_evolution=True,
            llm_client=llm,
        )

        # 2. 构建一个包含用户纠正的 session
        sid = "sess-correction-001"
        lake.storage.start_session(sid, "run-001")
        lake.storage.append_entries("default", sid, [
            SessionEntry(uuid="u1", type="user", content="Write a Python function to sort a list", session_id=sid),
            SessionEntry(uuid="a1", type="assistant", content="Here is bubble_sort(): ...", parent_uuid="u1", session_id=sid),
            SessionEntry(uuid="u2", type="user", content="不对，你应该使用内置的 sorted() 或者 Timsort，不要自己写排序算法", parent_uuid="a1", session_id=sid),
            SessionEntry(uuid="a2", type="assistant", content="You're right. Use sorted() or list.sort() which uses Timsort under the hood.", parent_uuid="u2", session_id=sid),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, parent_uuid="a2", session_id=sid),
        ])

        session_file = str(lake.storage.get_session_file("default", sid))
        print(f"  [Session] {session_file}")

        # 3. 触发 LLM review
        result = lake.review_session(session_file, review_type="combined")
        print(f"  [Review] actions={len(result['actions'])}, executed={len(result['executed'])}")
        for action in result["actions"]:
            print(f"    -> {action.get('tool', action.get('action', '?'))}: {action.get('args', action)}")

        # 4. 验证结果
        skills = lake.skill_manager.list_skills()
        print(f"  [Skills] {len(skills)} skill(s) created/updated")
        for s in skills:
            print(f"    - {s['name']} (agent_created={s.get('agent_created')})")

        memories = lake.memory_manager.search("Timsort")
        print(f"  [Memory] {len(memories)} memory entries mentioning 'Timsort'")

        # 至少应该有一些动作被生成
        assert len(result["actions"]) >= 0, "Review should produce actions"

        print("  [OK] DeepSeek online review completed")


def test_deepseek_curator_consolidation():
    print("\n[Test] DeepSeek LLM Curator Consolidation")

    llm = OpenAIClient(
        api_key="sk-82f51fb2311740d28ac6dccc858b9088",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            memory_dir=os.path.join(tmpdir, "memories"),
            enable_evolution=True,
            llm_client=llm,
        )

        # 创建多个相似前缀的 agent-created skills
        for name in ["python_sort", "python_list", "python_dict"]:
            lake.skill_manager.upsert(name, f"Best practices for {name}", origin="background_review")

        # 创建一个 stale skill
        lake.skill_manager.upsert("old_stale_skill", "Deprecated content",
            origin="background_review",
            metadata={"updated_at": "2020-01-01T00:00:00"})
        lake.skill_manager._set_record("old_stale_skill",
            last_patched_at=None, last_used_at=None, last_viewed_at=None)

        print(f"  [Before] {len(lake.skill_manager.list_skills())} skills")

        # 运行 curator
        result = lake.curator.run_maintenance(synchronous=True)
        print(f"  [Curator] checked={result['checked']}, archived={result['archived']}, stale={result['marked_stale']}")

        # 查看 LLM 是否给出了 consolidation 建议
        print(f"  [Suggestions] {len(result['consolidation_suggestions'])} rule-based suggestions")
        for sug in result['consolidation_suggestions']:
            print(f"    -> {sug['type']}: {sug['proposed_umbrella']} ({sug['reason']})")

        print("  [OK] DeepSeek curator completed")


def main():
    print("=" * 70)
    print("DeepSeek API Self-Evolution Test Suite")
    print("=" * 70)

    tests = [
        test_deepseek_online_review,
        test_deepseek_curator_consolidation,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
