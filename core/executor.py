"""Agent 执行器 — 隔离执行 + 超时控制 + Trace 收集 + 多轮会话 + 工作区管理"""

import time
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

from .test_case import TestCase, TaskInput
from .agent_interface import AgentInterface, AgentRunResult
from ..workspace_manager import WorkspaceManager


@dataclass
class ExecutionResult:
    """单次测试执行结果"""
    test_id: str
    test_input: str
    success: bool
    agent_output: str = ""
    agent_result: Optional[AgentRunResult] = None
    trace: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    steps_used: int = 0
    safety_violations: List[Dict[str, Any]] = field(default_factory=list)
    failure_category: Optional[str] = None
    failure_reason: Optional[str] = None
    token_usage: Dict[str, int] = field(default_factory=dict)
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    workspace_path: Optional[str] = None  # 测试使用的工作区路径
    turn_results: List[AgentRunResult] = field(default_factory=list)  # 多轮每轮结果

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id, "test_input": self.test_input,
            "success": self.success, "agent_output": self.agent_output[:500],
            "latency_ms": self.latency_ms, "steps_used": self.steps_used,
            "safety_violations": self.safety_violations,
            "failure_category": self.failure_category,
            "failure_reason": self.failure_reason,
            "token_usage": self.token_usage,
            "timestamp": self.timestamp,
            "workspace_path": self.workspace_path,
        }


class TimeoutError(Exception):
    pass


@contextmanager
def time_limit(seconds: int):
    """上下文管理器：超时控制（跨平台）"""
    if hasattr(signal, "SIGALRM"):
        def signal_handler(signum, frame):
            raise TimeoutError(f"Execution timed out after {seconds} seconds")

        signal.signal(signal.SIGALRM, signal_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
    else:
        timer_triggered = False
        def timer_handler():
            nonlocal timer_triggered
            timer_triggered = True

        timer = threading.Timer(seconds, timer_handler)
        timer.start()
        try:
            yield
        finally:
            timer.cancel()
            if timer_triggered:
                raise TimeoutError(f"Execution timed out after {seconds} seconds")


class AgentExecutor:
    """Agent 执行器"""

    def __init__(self, agent: AgentInterface, max_steps: int = 30):
        self.agent = agent
        self.max_steps = max_steps
        self.workspace_manager = WorkspaceManager()

    def _prepare_workspace(self, test_case: TestCase) -> Optional[Path]:
        """准备测试工作区"""
        if test_case.working_dir:
            return Path(test_case.working_dir)
        elif test_case.workspace_template:
            return self.workspace_manager.create_sandbox(test_case.workspace_template)
        return None

    def _cleanup_workspace(self, test_case: TestCase, workspace: Optional[Path]) -> None:
        """清理工作区"""
        if test_case.workspace_cleanup == "auto" and test_case.workspace_template and workspace:
            self.workspace_manager.cleanup(workspace)

    def execute(self, test_case: TestCase) -> ExecutionResult:
        """执行单个测试用例（支持单轮和多轮）"""
        start_time = time.time()
        workspace = self._prepare_workspace(test_case)
        turn_results: List[AgentRunResult] = []

        try:
            with time_limit(test_case.timeout):
                if test_case.is_multiturn:
                    result = self._execute_multiturn(test_case, workspace)
                else:
                    result = self._execute_single(test_case, workspace)
                turn_results = result.metadata.get("turn_results", [result])
        except TimeoutError:
            self._cleanup_workspace(test_case, workspace)
            return ExecutionResult(
                test_id=test_case.id,
                test_input=str(test_case.first_input),
                success=False,
                failure_category="timeout",
                failure_reason=f"Exceeded timeout of {test_case.timeout}s",
                latency_ms=(time.time() - start_time) * 1000,
                workspace_path=str(workspace) if workspace else None,
            )
        except Exception as e:
            self._cleanup_workspace(test_case, workspace)
            return ExecutionResult(
                test_id=test_case.id,
                test_input=str(test_case.first_input),
                success=False,
                failure_category="model",
                failure_reason=f"Agent execution failed: {str(e)}",
                latency_ms=(time.time() - start_time) * 1000,
                workspace_path=str(workspace) if workspace else None,
            )

        elapsed_ms = (time.time() - start_time) * 1000

        # 构建 trace
        trace = []
        for step in result.steps:
            trace.append({
                "step": step.step_number,
                "type": step.step_type,
                "content": step.content[:200],
                "tool": step.tool_name,
                "latency_ms": step.latency_ms,
            })

        self._cleanup_workspace(test_case, workspace)

        return ExecutionResult(
            test_id=test_case.id,
            test_input=str(test_case.first_input),
            success=True,
            agent_output=result.final_output,
            agent_result=result,
            trace=trace,
            latency_ms=elapsed_ms,
            steps_used=result.total_steps,
            token_usage=result.total_tokens,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            workspace_path=str(workspace) if workspace else None,
            turn_results=turn_results,
        )

    def _execute_single(self, test_case: TestCase, workspace: Optional[Path]) -> AgentRunResult:
        """执行单轮测试"""
        user_input = test_case.input
        kwargs = {"max_steps": test_case.max_steps}
        if workspace:
            kwargs["working_dir"] = workspace
        return self.agent.run(user_input, **kwargs)

    def _execute_multiturn(self, test_case: TestCase, workspace: Optional[Path]) -> AgentRunResult:
        """执行多轮测试"""
        self.agent.start_session(working_dir=workspace)
        all_steps: List[Any] = []
        all_tool_calls: List[Dict[str, Any]] = []
        all_errors: List[str] = []
        outputs: List[str] = []
        turn_results: List[AgentRunResult] = []

        for i, turn_input in enumerate(test_case.all_inputs):
            result = self.agent.send_turn(turn_input, max_steps=test_case.max_steps)
            turn_results.append(result)
            all_steps.extend(result.steps)
            all_tool_calls.extend(result.tool_calls)
            all_errors.extend(result.errors)
            outputs.append(result.final_output)

        self.agent.end_session()

        # 合并为多轮总结果
        combined = AgentRunResult(
            final_output="\n\n".join(outputs),
            steps=all_steps,
            total_steps=len(all_steps),
            total_latency_ms=sum(r.total_latency_ms for r in turn_results),
            total_tokens=self._merge_tokens([r.total_tokens for r in turn_results]),
            tool_calls=all_tool_calls,
            errors=all_errors,
            metadata={"turn_results": turn_results, "turn_count": len(turn_results)},
        )
        return combined

    @staticmethod
    def _merge_tokens(token_list: List[Dict[str, int]]) -> Dict[str, int]:
        merged: Dict[str, int] = {}
        for tokens in token_list:
            for k, v in tokens.items():
                merged[k] = merged.get(k, 0) + v
        return merged

    def execute_batch(self, test_cases: List[TestCase]) -> List[ExecutionResult]:
        """批量执行"""
        results = []
        for i, tc in enumerate(test_cases):
            print(f"  [{i+1}/{len(test_cases)}] Running {tc.id}...")
            result = self.execute(tc)
            results.append(result)
            status = "PASS" if result.success else f"FAIL({result.failure_category})"
            print(f"       -> {status} ({result.latency_ms:.0f}ms, {result.steps_used} steps)")
        return results
