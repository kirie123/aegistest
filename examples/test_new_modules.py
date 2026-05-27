"""
新模块单元测试 —— 验证 Session / DataPipeline / Evolution 各组件
"""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegistest.session import SessionStorage, SessionLoader, SessionEntry, QualityAnnotator
from aegistest.datapipeline import TraceConverter, QualityFilter, DatasetExporter
from aegistest.evolution import SkillManager, MemoryManager, OnlineReviewer, OfflineMiner, Curator


def test_session_storage():
    print("\n[Test] SessionStorage")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SessionStorage(base_dir=tmpdir)
        session_id = "test-session-001"
        run_id = "run-001"

        # start session
        path = storage.start_session(session_id, run_id, test_id="t1", project="proj1")
        assert path.exists(), "Session file should be created"

        # append entries
        entries = [
            SessionEntry(uuid="u1", type="user", content="hello", session_id=session_id),
            SessionEntry(uuid="a1", type="assistant", content="hi", parent_uuid="u1", session_id=session_id),
        ]
        storage.append_entries("proj1", session_id, entries)

        # list sessions
        sessions = storage.list_sessions("proj1")
        assert len(sessions) == 1, f"Expected 1 session, got {len(sessions)}"

        print("  OK SessionStorage works")


def test_session_loader():
    print("\n[Test] SessionLoader")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SessionStorage(base_dir=tmpdir)
        session_id = "test-session-002"
        storage.start_session(session_id, "run-002", test_id="t2")

        entries = [
            SessionEntry(uuid="u1", type="user", content="What is AI?", session_id=session_id),
            SessionEntry(uuid="a1", type="assistant", content="AI is...", parent_uuid="u1", session_id=session_id),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, parent_uuid="a1", session_id=session_id),
        ]
        storage.append_entries("default", session_id, entries)

        loader = SessionLoader()
        path = storage.get_session_file("default", session_id)
        chain = loader.load_session(str(path))

        assert len(chain) == 2, f"Expected 2 messages, got {len(chain)}"
        assert chain[0]["type"] == "user"
        assert chain[1]["type"] == "assistant"

        # extract metadata
        meta = loader.extract_metadata(str(path))
        assert meta.get("success") is True

        print("  OK SessionLoader works")


def test_trace_converter():
    print("\n[Test] TraceConverter")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SessionStorage(base_dir=tmpdir)
        session_id = "test-session-003"
        storage.start_session(session_id, "run-003")

        entries = [
            SessionEntry(uuid="s1", type="system", content="You are helpful.", session_id=session_id),
            SessionEntry(uuid="u1", type="user", content="Hello", session_id=session_id),
            SessionEntry(uuid="a1", type="assistant", content="Hi there", parent_uuid="u1", session_id=session_id),
        ]
        storage.append_entries("default", session_id, entries)

        converter = TraceConverter()
        path = storage.get_session_file("default", session_id)

        chatml = converter.convert(str(path), "chatml")
        assert "messages" in chatml
        # system 消息不在 parent chain 中，user + assistant 构成链
        assert len(chatml["messages"]) == 2
        assert chatml["messages"][0]["role"] == "user"
        assert chatml["messages"][1]["role"] == "assistant"

        traces = converter.convert(str(path), "traces")
        assert "messages" in traces

        print("  OK TraceConverter works")


def test_quality_filter():
    print("\n[Test] QualityFilter")
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建两个 session：一个成功，一个失败
        storage = SessionStorage(base_dir=tmpdir)

        # 成功 session
        sid1 = "sess-success"
        storage.start_session(sid1, "r1")
        storage.append_entries("default", sid1, [
            SessionEntry(uuid="u1", type="user", content="Q1", session_id=sid1),
            SessionEntry(uuid="a1", type="assistant", content="A1", session_id=sid1),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, session_id=sid1),
        ])

        # 失败 session
        sid2 = "sess-fail"
        storage.start_session(sid2, "r1")
        storage.append_entries("default", sid2, [
            SessionEntry(uuid="u2", type="user", content="Q2", session_id=sid2),
            SessionEntry(uuid="a2", type="assistant", content="A2", session_id=sid2),
            SessionEntry(uuid="f2", type="session_footer", content={"success": False}, session_id=sid2),
        ])

        files = [str(f) for f in storage.list_sessions("default")]

        # 不过滤
        f1 = QualityFilter(require_success=False)
        assert len(f1.filter_sessions(files)) == 2

        # 只过滤成功
        f2 = QualityFilter(require_success=True)
        passed = f2.filter_sessions(files)
        assert len(passed) == 1

        print("  OK QualityFilter works")


def test_skill_manager():
    print("\n[Test] SkillManager")
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = SkillManager(skills_dir=os.path.join(tmpdir, "skills"))

        # create
        path = mgr.upsert("python_style", "Use type hints.")
        assert os.path.exists(path)

        # get
        content = mgr.get("python_style")
        assert content == "Use type hints."

        # list
        skills = mgr.list_skills()
        assert len(skills) == 1

        # archive
        assert mgr.archive("python_style") is True
        assert mgr.get("python_style") is not None  # 仍可从归档读取

        print("  OK SkillManager works")


def test_memory_manager():
    print("\n[Test] MemoryManager")
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = MemoryManager(memory_file=os.path.join(tmpdir, "memory.json"))

        mem.add("name", "Alice")
        assert mem.get("name") == "Alice"

        mem.add("lang", "zh", category="prefs")
        assert mem.get("lang", "prefs") == "zh"

        results = mem.search("Alice")
        assert len(results) == 1

        print("  OK MemoryManager works")


def test_online_reviewer():
    print("\n[Test] OnlineReviewer")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SessionStorage(base_dir=tmpdir)
        session_id = "sess-review"
        storage.start_session(session_id, "r1")
        storage.append_entries("default", session_id, [
            SessionEntry(uuid="u1", type="user", content="Do this", session_id=session_id),
            SessionEntry(uuid="a1", type="assistant", content="不对，你应该那样做", session_id=session_id),
            SessionEntry(uuid="f1", type="session_footer", content={"success": True}, session_id=session_id),
        ])

        skill_mgr = SkillManager(skills_dir=os.path.join(tmpdir, "skills"))
        mem_mgr = MemoryManager(memory_file=os.path.join(tmpdir, "memory.json"))
        reviewer = OnlineReviewer(skill_manager=skill_mgr, memory_manager=mem_mgr)

        path = storage.get_session_file("default", session_id)
        result = reviewer.review_session(str(path), review_type="combined")

        assert "actions" in result
        assert "executed" in result
        print(f"  Actions: {len(result['actions'])}, Executed: {len(result['executed'])}")
        print("  OK OnlineReviewer works")


def test_offline_miner():
    print("\n[Test] OfflineMiner")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SessionStorage(base_dir=tmpdir)

        for i in range(3):
            sid = f"sess-{i}"
            storage.start_session(sid, "r1")
            storage.append_entries("default", sid, [
                SessionEntry(uuid=f"u{i}", type="user", content=f"Q{i}", session_id=sid),
                SessionEntry(uuid=f"a{i}", type="assistant", content=f"A{i}", session_id=sid),
                SessionEntry(uuid=f"f{i}", type="session_footer", content={"success": i < 2}, session_id=sid),
            ])

        files = [str(f) for f in storage.list_sessions("default")]
        miner = OfflineMiner()

        prefs = miner.mine_user_preferences(files)
        assert prefs["total_sessions"] == 3

        high_value = miner.mine_high_value_sessions(files)
        assert len(high_value) <= 3

        print("  OK OfflineMiner works")


def test_curator():
    print("\n[Test] Curator")
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_mgr = SkillManager(skills_dir=os.path.join(tmpdir, "skills"))
        # 创建一个旧 skill
        skill_mgr.upsert("old_skill", "content", metadata={"updated_at": "2020-01-01T00:00:00"})

        curator = Curator(skill_mgr, stale_threshold_days=1, archive_threshold_days=30)
        result = curator.run_maintenance(synchronous=True)

        assert result["checked"] >= 1
        print(f"  Checked: {result['checked']}, Archived: {result['archived']}")
        print("  OK Curator works")


def main():
    print("=" * 60)
    print("Running AegisTest Evolution Module Tests")
    print("=" * 60)

    tests = [
        test_session_storage,
        test_session_loader,
        test_trace_converter,
        test_quality_filter,
        test_skill_manager,
        test_memory_manager,
        test_online_reviewer,
        test_offline_miner,
        test_curator,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
