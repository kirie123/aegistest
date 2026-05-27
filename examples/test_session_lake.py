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
    print("\n[Test 4] SessionLake 在线进化 review")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            memory_file=os.path.join(tmpdir, "memory.json"),
            enable_evolution=True,
        )

        sid = "sess-review"
        lake.storage.start_session(sid, "r1")
        lake.storage.append_entries("default", sid, [
            SessionEntry(uuid="u1", type="user", content="Do this", session_id=sid),
            SessionEntry(uuid="a1", type="assistant", content="不对，你应该那样做", parent_uuid="u1", session_id=sid),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, parent_uuid="a1", session_id=sid),
        ])

        sf = str(lake.storage.get_session_file("default", sid))
        result = lake.review_session(sf, review_type="combined")

        assert "actions" in result
        assert "executed" in result
        print(f"  [OK] Review: {len(result['actions'])} actions, {len(result['executed'])} executed")

        # 验证 memory 是否写入
        mem = lake.memory_manager.get("conversation_patience", category="behavior")
        print(f"  [OK] Memory check: {mem is not None}")


def test_session_lake_maintenance():
    print("\n[Test 5] SessionLake 进化维护（Curator + Offline Miner）")
    with tempfile.TemporaryDirectory() as tmpdir:
        lake = SessionLake(
            session_dir=tmpdir,
            skill_dir=os.path.join(tmpdir, "skills"),
            enable_evolution=True,
        )

        # 创建旧 skill
        lake.skill_manager.upsert("old_python_style", "content", metadata={"updated_at": "2020-01-01T00:00:00"})

        # 创建多个 session
        for i in range(4):
            sid = f"sess-m{i}"
            lake.storage.start_session(sid, "r1", test_id=f"test_{i%2}")
            lake.storage.append_entries("default", sid, [
                SessionEntry(uuid=f"u{i}", type="user", content=f"Q{i}", session_id=sid),
                SessionEntry(uuid=f"a{i}", type="assistant", content=f"A{i}", parent_uuid=f"u{i}", session_id=sid),
                SessionEntry(uuid=f"f{i}", type="session_footer", content={"success": i < 2}, parent_uuid=f"a{i}", session_id=sid),
            ])

        result = lake.run_evolution_maintenance()

        assert "curator" in result
        assert "failure_patterns" in result
        assert "user_preferences" in result

        print(f"  [OK] Curator: checked={result['curator']['checked']}")
        print(f"  [OK] Patterns: {len(result['failure_patterns'])}")
        print(f"  [OK] Preferences: {result['user_preferences']['total_sessions']} sessions")


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
