"""Agent 接口定义 — 你的 Agent 需要实现这个接口"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Generator, Union
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentStep:
    """Agent 执行的单个步骤"""
    step_number: int
    step_type: str           # "thought", "tool_call", "tool_result", "response", "error"
    content: str             # 内容
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[str] = None
    latency_ms: float = 0.0
    token_usage: Dict[str, int] = field(default_factory=dict)
    timestamp: Optional[str] = None


@dataclass
class AgentRunResult:
    """Agent 运行结果"""
    final_output: str
    steps: List[AgentStep]
    total_steps: int
    total_latency_ms: float
    total_tokens: Dict[str, int] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentInterface(ABC):
    """Agent 接口 — 你的 Agent 必须实现这个接口才能被 AegisTest 测试"""

    @abstractmethod
    def run(self, user_input: Union[str, "TaskInput"], **kwargs) -> AgentRunResult:
        """运行 Agent，返回完整结果（包含所有步骤）"""
        pass

    @abstractmethod
    def run_stream(self, user_input: Union[str, "TaskInput"], **kwargs) -> Generator[AgentStep, None, None]:
        """流式运行 Agent，每完成一步 yield 一个 AgentStep"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 名称（用于报告）"""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Agent 版本（用于回归测试对比）"""
        pass

    # ---- 会话管理（可选实现，用于多轮/长程任务） ----

    def start_session(self, working_dir: Optional[Path] = None) -> None:
        """启动会话，可选指定工作目录

        对于需要保持跨轮次上下文的多轮任务，Agent 应在此初始化会话状态。
        """
        pass

    def send_turn(self, user_input: Union[str, "TaskInput"], **kwargs) -> AgentRunResult:
        """发送一轮输入，返回该轮结果

        默认实现直接调用 run()。需要保持上下文的 Agent 应重写此方法。
        """
        return self.run(user_input, **kwargs)

    def end_session(self) -> None:
        """结束会话，释放资源"""
        pass
