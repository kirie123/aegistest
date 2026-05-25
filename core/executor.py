"""Agent 执行器 — 隔离执行 + 超时控制 + Trace 收集"""

import time
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from .test_case import TestCase
from .agent_interface import AgentInterface, AgentRunResult


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
    failure_category: Optional[str] = None     # "prompt"|"tool"|"retrieval"|"model"|"state"|"timeout"|"safety"
    failure_reason: Optional[str] = None
    token_usage: Dict[str, int] = field(default_factory=dict)
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

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
        }


class TimeoutError(Exception):
    pass


@contextmanager
def time_limit(seconds: int):
    """上下文管理器：超时控制（跨平台）"""
    # Windows 不支持 signal.SIGALRM，使用 threading 实现
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

    def execute(self, test_case: TestCase) -> ExecutionResult:
        """执行单个测试用例"""
        start_time = time.time()

        try:
            with time_limit(test_case.timeout):
                result = self.agent.run(test_case.input, max_steps=test_case.max_steps)
        except TimeoutError:
            return ExecutionResult(
                test_id=test_case.id,
                test_input=test_case.input,
                success=False,
                failure_category="timeout",
                failure_reason=f"Exceeded timeout of {test_case.timeout}s",
                latency_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return ExecutionResult(
                test_id=test_case.id,
                test_input=test_case.input,
                success=False,
                failure_category="model",
                failure_reason=f"Agent execution failed: {str(e)}",
                latency_ms=(time.time() - start_time) * 1000,
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

        return ExecutionResult(
            test_id=test_case.id,
            test_input=test_case.input,
            success=True,
            agent_output=result.final_output,
            agent_result=result,
            trace=trace,
            latency_ms=elapsed_ms,
            steps_used=result.total_steps,
            token_usage=result.total_tokens,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

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
