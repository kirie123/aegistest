"""
AegisTest — Agent Evaluation & Guarded Inspection System

融合评估、可观测性、安全性和回归测试的完整 Agent 测试框架。

快速开始:
    from aegistest import AegisTest, TestCase, TestSuite, AgentInterface
"""

__version__ = "0.1.0"

from .core.test_case import TestCase, TestSuite, TestCategory, TestPriority, SafetyCheck
from .core.agent_interface import AgentInterface, AgentRunResult, AgentStep
from .core.executor import AgentExecutor, ExecutionResult
from .core.aegis import AegisTest
from .reports.report_generator import ReportGenerator

__all__ = [
    "AegisTest",
    "TestCase",
    "TestSuite",
    "TestCategory",
    "TestPriority",
    "SafetyCheck",
    "AgentInterface",
    "AgentRunResult",
    "AgentStep",
    "AgentExecutor",
    "ExecutionResult",
    "ReportGenerator",
]
