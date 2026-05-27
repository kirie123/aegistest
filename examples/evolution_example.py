"""
AegisTest Evolution Framework 完整示例（解耦架构）

展示以下能力：
1. 原有测试功能（完全不变）
2. SessionLake 独立数据平台（持久化 + 训练数据 + 自进化）
3. AegisTest 与 SessionLake 通过组合关联

新架构：
    AegisTest（纯测试） ◄──► SessionLake（数据平台）
                              └── 可被生产 Agent 直接复用
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Dict, Any
from aegistest import (
    AegisTest,
    TestCase,
    TestSuite,
    TestCategory,
    TestPriority,
    AgentInterface,
    AgentRunResult,
    AgentStep,
    SessionLake,   # 新增：独立数据平台
)


class DemoAgent(AgentInterface):
    """演示 Agent"""

    def __init__(self):
        self._messages: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "demo-agent"

    @property
    def version(self) -> str:
        return "0.2.0"

    def run(self, user_input: str, **kwargs) -> AgentRunResult:
        self._messages.append({"role": "user", "content": user_input})

        steps = []
        steps.append(AgentStep(step_number=1, step_type="thought", content=f"Analyzing: {user_input}"))

        if "search" in user_input.lower() or "查询" in user_input:
            steps.append(AgentStep(
                step_number=2, step_type="tool_call", content="Calling search...",
                tool_name="web_search", tool_args={"query": user_input},
            ))
            answer = f"Search results for '{user_input}': [result1, result2, result3]"
            tool_calls = [{"tool_name": "web_search", "tool_args": {"query": user_input}}]
        else:
            answer = f"Hello! I received: {user_input}"
            tool_calls = []

        steps.append(AgentStep(step_number=len(steps)+1, step_type="response", content=answer))
        self._messages.append({"role": "assistant", "content": answer})

        return AgentRunResult(
            final_output=answer, steps=steps, total_steps=len(steps),
            total_latency_ms=150.0, tool_calls=tool_calls,
        )

    def run_stream(self, user_input: str, **kwargs):
        result = self.run(user_input, **kwargs)
        for step in result.steps:
            yield step

    def get_message_history(self) -> List[Dict[str, Any]]:
        return self._messages.copy()


def main():
    print("=" * 70)
    print("AegisTest + SessionLake 解耦架构 Demo")
    print("=" * 70)

    # ==================== 1. 定义测试用例 ====================
    suite = TestSuite(name="Evolution Demo Suite", description="测试 + 数据生产 + 进化")
    suite.add(TestCase(
        id="func_001_greeting", input="你好，请介绍一下自己",
        expected_output_contains=["Hello", "received"],
        category=TestCategory.FUNCTIONAL, priority=TestPriority.HIGH, timeout=10,
    ))
    suite.add(TestCase(
        id="func_002_search", input="请搜索 Python 教程",
        expected_output_contains=["Search results"],
        category=TestCategory.TOOL_CALLING, priority=TestPriority.HIGH, timeout=10,
    ))
    suite.add(TestCase(
        id="func_003_search_fail", input="search machine learning papers",
        expected_output_contains=["Search results"],
        category=TestCategory.TOOL_CALLING, priority=TestPriority.MEDIUM, timeout=10,
    ))

    # ==================== 2. 创建 SessionLake（独立数据平台）====================
    lake = SessionLake(
        session_dir="./sessions_demo",
        skill_dir="~/.aegistest_demo/skills",
        enable_evolution=True,
    )

    # ==================== 3. AegisTest 只负责测试 ====================
    agent = DemoAgent()
    aegis = AegisTest(
        agent=agent,
        trace_dir="./traces_demo",
        report_dir="./reports_demo",
        session_lake=lake,          # 通过组合关联（可选）
    )

    print("\n[Phase 1] Running test suite...")
    summary = aegis.run_suite(suite)
    print(f"\nSuite Summary: {summary['passed']}/{summary['total']} passed")

    # ==================== 4. SessionLake 负责数据导出 ====================
    print("\n[Phase 2] Exporting training data via SessionLake...")

    lake.export_training_data(
        output_path="./train_data_demo.json",
        output_format="chatml",
        require_success=False,
    )

    lake.export_training_data(
        output_path="./train_data_demo_filtered.json",
        output_format="traces",
        require_success=True,
    )

    # ==================== 5. SessionLake 负责进化维护 ====================
    print("\n[Phase 3] Running evolution maintenance via SessionLake...")
    maintenance = lake.run_evolution_maintenance()

    if "curator" in maintenance:
        print(f"Curator checked: {maintenance['curator']['checked']} skills")
    if "failure_patterns" in maintenance:
        print(f"Failure patterns: {len(maintenance['failure_patterns'])}")
    if "user_preferences" in maintenance:
        prefs = maintenance["user_preferences"]
        print(f"User prefs: avg_turns={prefs['avg_turns']}, success_rate={prefs['success_rate']}")

    # ==================== 6. AegisTest 只负责报告 ====================
    print("\n[Phase 4] Generating report via AegisTest...")
    aegis.generate_report(fmt="html")
    aegis.generate_report(fmt="json")

    print("\n" + "=" * 70)
    print("Demo completed!")
    print("Architecture: AegisTest(test) + SessionLake(data + evolution)")
    print("=" * 70)


if __name__ == "__main__":
    main()
