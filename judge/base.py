"""Judge 抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class JudgeResult:
    """评判结果"""
    passed: bool
    reason: str
    matches_input: bool = False
    matches_behavior: bool = False
    raw_response: str = ""


class BaseJudge(ABC):
    """Judge 基类 —— 所有评估器必须实现此接口"""

    @abstractmethod
    def evaluate(
        self,
        user_input: str,
        expected_behavior: List[str],
        actual_output: str,
    ) -> JudgeResult:
        """评估 Agent 输出

        Args:
            user_input: 给 Agent 的原始输入
            expected_behavior: 预期行为列表
            actual_output: Agent 的实际输出

        Returns:
            JudgeResult
        """
        pass
