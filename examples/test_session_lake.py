"""
SessionLake + Evolution 完整功能测试

覆盖场景：
1. SessionLake 基础读写
2. 训练数据导出（ChatML / ShareGPT / Traces）
3. DPO preference pairs 导出
4. 在线进化 review（memory + skill）
5. 离线模式挖掘 + Curator 维护
6. 生产 Agent 直接使用 SessionLake
"""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegistest import (
    AegisTest,
    TestCase,
    TestSuite,
    TestCategory,
    TestPriority,
    AgentInterface,
    AgentRunResult,
    AgentStep,
    SessionLake,
)
from aegistest.session.session_storage import SessionStorage, SessionEntry
from aegistest.session.session_loader import SessionLoader


class SearchAgent(AgentInterface):
    """模拟一个会搜索的 Agent"""

    def __init__(self):
        self._msgs = []

    @property
    def name(self):
        return "search-agent"

    @property
    def version(self):
        return "1.0"

    def run(self, user_input: str, **kwargs):
        self._msgs.append({"role": "user", "content": user_input})
        steps = [
            AgentStep(step_number=1, step_type="thought", content="Thinking..."),
        ]
        tool_calls = []
        if "search" in user_input.lower():
            steps.append(AgentStep(
                step_number=2, step_type="tool_call",
                content="Searching...", tool_name="web_search",
                tool_args={"query": user_input},
            ))
            answer = f"Search results for '{user_input}'"
            tool_calls = [{"tool_name": "web_search", "tool_args": {"query": user_input}}]
        else:
            answer = f"Echo: {user_input}"
        steps.append(AgentStep(step_number=len(steps)+1, step_type="response", content=answer))
        self._msgs.append({"role": "assistant", "content": answer})
        return AgentRunResult(
            final_output=answer, steps=steps, total_steps=len(steps),
            total_latency_ms=100.0, tool_calls=tool_calls,
        )

    def run_stream(self, user_input: str, **kwargs):
        result = self.run(user_input, **kwargs)
        for step in result.steps:
            yield step

    def get_message_history(self):
        return self._msgs.copy()


def test_session_lake_storage():
    print("\n[Test 1] SessionLake 基础存储")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(session_dir=tmpdir)
        sid = "sess-001"
        lake.storage.start_session(sid, "run-001", test_id="t1")
        lake.storage.append_entries("default", sid, [
            SessionEntry(uuid="u1", type="user", content="What is AI?", session_id=sid),
            SessionEntry(uuid="a1", type="assistant", content="AI is...", parent_uuid="u1", session_id=sid),
        ])
        files = lake.list_sessions("default")
        assert len(files) == 1, f"Expected 1 session, got {len(files)}"
        meta = lake.get_session_metadata(str(files[0]))
        assert meta.get("test_id") == "t1"
        print("  [OK] Storage + metadata works")


def test_session_lake_training_export():
    print("\n[Test 2] SessionLake 训练数据导出")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(session_dir=tmpdir)

        # 创建成功 session
        for i in range(3):
            sid = f"sess-s{i}"
            lake.storage.start_session(sid, "r1", test_id=f"test_{i}")
            lake.storage.append_entries("default", sid, [
                SessionEntry(uuid=f"u{i}", type="user", content=f"Q{i}", session_id=sid),
                SessionEntry(uuid=f"a{i}", type="assistant", content=f"A{i}", parent_uuid=f"u{i}", session_id=sid),
                SessionEntry(uuid=f"f{i}", type="session_footer", content={"success": True}, parent_uuid=f"a{i}", session_id=sid),
            ])

        # 导出 ChatML
        chatml_path = os.path.join(tmpdir, "chatml.json")
        lake.export_training_data(chatml_path, output_format="chatml")
        assert os.path.exists(chatml_path)

        # 导出 ShareGPT
        sg_path = os.path.join(tmpdir, "sharegpt.json")
        lake.export_training_data(sg_path, output_format="sharegpt")
        assert os.path.exists(sg_path)

        # 导出 traces
        tr_path = os.path.join(tmpdir, "traces.json")
        lake.export_training_data(tr_path, output_format="traces")
        assert os.path.exists(tr_path)

        print("  [OK] ChatML / ShareGPT / Traces export works")


def test_session_lake_dpo_export():
    print("\n[Test 3] SessionLake DPO pairs 导出")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(session_dir=tmpdir)

        # 同一 test_id 的成功 + 失败
        for success in [True, False]:
            sid = f"sess-dpo-{1 if success else 0}"
            lake.storage.start_session(sid, "r1", test_id="same_test")
            lake.storage.append_entries("default", sid, [
                SessionEntry(uuid="u1", type="user", content="Solve 2+2", session_id=sid),
                SessionEntry(uuid="a1", type="assistant", content="4" if success else "5", parent_uuid="u1", session_id=sid),
                SessionEntry(uuid="f1", type="session_footer", content={"success": success}, parent_uuid="a1", session_id=sid),
            ])

        dpo_path = os.path.join(tmpdir, "dpo.json")
        lake.export_dpo_pairs(dpo_path)
        assert os.path.exists(dpo_path)
        import json
        with open(dpo_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) >= 1, "Should have at least 1 DPO pair"
        assert "prompt" in data[0]
        assert "chosen" in data[0]
        assert "rejected" in data[0]
        print(f"  [OK] DPO export: {len(data)} pairs generated")


def test_session_lake_evolution_review():
    print("\n[Test 4] SessionLake 在线进化 review（端到端验证）")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            memory_file=os.path.join(tmpdir, "memory.json"),
            enable_evolution=True,
        )

        # --- 场景 A：用户纠正 → 触发 skill 创建 ---
        sid_a = "sess-correction"
        lake.storage.start_session(sid_a, "r1")
        lake.storage.append_entries("default", sid_a, [
            SessionEntry(uuid="u1", type="user", content="Write a function", session_id=sid_a),
            SessionEntry(uuid="a1", type="assistant", content="Here is the code", parent_uuid="u1", session_id=sid_a),
            SessionEntry(uuid="u2", type="user", content="不对，你应该加上类型注解", parent_uuid="a1", session_id=sid_a),
            SessionEntry(uuid="a2", type="assistant", content="OK, updated with type hints", parent_uuid="u2", session_id=sid_a),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, parent_uuid="a2", session_id=sid_a),
        ])

        sf_a = str(lake.storage.get_session_file("default", sid_a))
        result_a = lake.review_session(sf_a, review_type="skill")

        assert result_a["executed"], "Skill review should execute actions"
        skills_after = lake.skill_manager.list_skills()
        assert len(skills_after) >= 1, f"Expected at least 1 skill created, got {len(skills_after)}"
        skill_content = lake.skill_manager.get(skills_after[0]["name"])
        assert skill_content, "Skill file should be written to disk"
        print(f"  [OK] Skill created: '{skills_after[0]['name']}' -> {len(skill_content)} chars")

        # --- 场景 B：长对话 → 触发 memory 创建 ---
        # 直接操作 memory_manager 验证 CRUD（因为 rule-based reviewer 需要 >10 轮才触发 memory）
        lake.memory_manager.add("preferred_language", "zh-CN", category="preferences")
        lake.memory_manager.add("coding_style", "use_type_hints", category="preferences")

        mem_lang = lake.memory_manager.get("preferred_language", "preferences")
        assert mem_lang == "zh-CN", f"Expected 'zh-CN', got {mem_lang}"

        search_results = lake.memory_manager.search("type")
        assert len(search_results) >= 1, "Memory search should find 'use_type_hints'"
        print(f"  [OK] Memory: {len(search_results)} entries found by keyword search")

        # --- 场景 C：已有 skill 被更新 ---
        lake.skill_manager.upsert("python_style", "Always use snake_case")
        lake.skill_manager.upsert("python_style", "Always use snake_case and type hints")
        updated_content = lake.skill_manager.get("python_style")
        assert "type hints" in updated_content, "Skill should be updated"
        print(f"  [OK] Skill updated: 'python_style' -> {updated_content[:50]}")


def test_session_lake_maintenance():
    print("\n[Test 5] SessionLake 进化维护（Curator + Offline Miner 端到端）")
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = os.path.join(tmpdir, "skills")
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=skill_dir,
            enable_evolution=True,
        )

        # 创建活跃 skill
        lake.skill_manager.upsert("active_skill", "This is active")
        # 创建旧 skill（模拟 2 年前更新）
        lake.skill_manager.upsert("old_legacy_skill", "This is outdated",
            metadata={"updated_at": "2022-01-01T00:00:00"})
        # Reset activity timestamps so curator sees it as truly old
        lake.skill_manager._set_record("old_legacy_skill",
            last_patched_at=None, last_used_at=None, last_viewed_at=None)

        # 创建多个 session：2 成功 + 2 失败，带 tool_call
        for i in range(4):
            sid = f"sess-m{i}"
            lake.storage.start_session(sid, "r1", test_id=f"test_{i%2}")
            lake.storage.append_entries("default", sid, [
                SessionEntry(uuid=f"u{i}", type="user", content=f"Query {i}", session_id=sid),
                SessionEntry(uuid=f"t{i}", type="tool_call", content="searching",
                             metadata={"tool_name": "web_search", "tool_args": {"q": f"Q{i}"}},
                             parent_uuid=f"u{i}", session_id=sid),
                SessionEntry(uuid=f"r{i}", type="tool_result", content="Found 3 results",
                             parent_uuid=f"t{i}", session_id=sid),
                SessionEntry(uuid=f"a{i}", type="assistant", content=f"Answer {i}",
                             parent_uuid=f"r{i}", session_id=sid),
                SessionEntry(uuid=f"f{i}", type="session_footer",
                             content={"success": i < 2, "failure_category": None if i < 2 else "timeout"},
                             parent_uuid=f"a{i}", session_id=sid),
            ])

        result = lake.run_evolution_maintenance()
        # Wait for any async curator threads to finish before temp dir cleanup
        import time
        time.sleep(0.5)

        # --- 验证 Curator 归档 ---
        curator_result = result["curator"]
        assert curator_result["checked"] >= 2, f"Expected >=2 skills checked, got {curator_result['checked']}"

        # 验证物理文件：旧 skill 应该被移动到 .archive/
        archive_path = os.path.join(skill_dir, ".archive", "old_legacy_skill", "SKILL.md")
        assert os.path.exists(archive_path), f"Archived skill file should exist at {archive_path}"
        print(f"  [OK] Curator archived 'old_legacy_skill' to .archive/")

        # 活跃 skill 应该仍在原处
        active_path = os.path.join(skill_dir, "active_skill", "SKILL.md")
        assert os.path.exists(active_path), "Active skill should NOT be archived"
        print(f"  [OK] Curator kept 'active_skill' in place")

        # --- 验证 Offline Miner ---
        assert "failure_patterns" in result
        assert "user_preferences" in result
        prefs = result["user_preferences"]
        assert prefs["total_sessions"] == 4
        assert prefs["success_rate"] == 0.5  # 2/4
        print(f"  [OK] OfflineMiner: {prefs['total_sessions']} sessions, success_rate={prefs['success_rate']}")

        # --- 验证 Skill 有效性评估 ---
        effectiveness = lake.offline_miner.mine_skill_effectiveness(
            "active_skill",
            [str(f) for f in lake.storage.list_sessions("default")]
        )
        assert "before_success_rate" in effectiveness
        print(f"  [OK] Skill effectiveness: {effectiveness['skill_name']} rate={effectiveness.get('after_success_rate', 'N/A')}")


def test_production_agent_direct_use():
    print("\n[Test 6] 生产 Agent 直接使用 SessionLake（非测试场景）")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            memory_file=os.path.join(tmpdir, "memory.json"),
            enable_evolution=True,
        )

        # 模拟生产 Agent 运行
        agent = SearchAgent()
        result = agent.run("search Python tutorials")

        # 直接写入 SessionLake
        sid = "prod-session-001"
        lake.storage.start_session(sid, "run-prod")
        lake.storage.append_entries("default", sid, [
            SessionEntry(uuid="u1", type="user", content="search Python tutorials", session_id=sid),
            SessionEntry(uuid="a1", type="assistant", content=result.final_output,
                         parent_uuid="u1", session_id=sid,
                         metadata={"tool_calls": result.tool_calls, "has_tool_call": bool(result.tool_calls)}),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, parent_uuid="a1", session_id=sid),
        ])

        # 导出数据
        export_path = os.path.join(tmpdir, "prod_train.json")
        lake.export_training_data(export_path)
        assert os.path.exists(export_path)

        # 触发 review
        sf = str(lake.storage.get_session_file("default", sid))
        review = lake.review_session(sf)
        assert "actions" in review

        print(f"  [OK] Production integration: export + review works")


def test_aegis_with_session_lake():
    print("\n[Test 7] AegisTest + SessionLake 组合使用")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            enable_evolution=True,
        )

        suite = TestSuite(name="Combo Suite", description="Combo test")
        suite.add(TestCase(
            id="combo_001", input="search AI news",
            expected_output_contains=["Search results"],
            category=TestCategory.TOOL_CALLING, priority=TestPriority.HIGH, timeout=10,
        ))

        agent = SearchAgent()
        aegis = AegisTest(agent=agent, session_lake=lake)
        summary = aegis.run_suite(suite)

        # 测试后通过 lake 导出数据
        export_path = os.path.join(tmpdir, "from_test.json")
        lake.export_training_data(export_path, require_success=True)

        assert summary["total"] == 1
        assert os.path.exists(export_path)
        print(f"  [OK] AegisTest + SessionLake combo: {summary['passed']}/{summary['total']} passed")


def main():
    print("=" * 70)
    print("SessionLake + Evolution Full Test Suite")
    print("=" * 70)

    tests = [
        test_session_lake_storage,
        test_session_lake_training_export,
        test_session_lake_dpo_export,
        test_session_lake_evolution_review,
        test_session_lake_maintenance,
        test_production_agent_direct_use,
        test_aegis_with_session_lake,
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
