"""AegisTest 主入口 — 一键运行全部评测"""

import time
import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from .test_case import TestCase, TestSuite
from .agent_interface import AgentInterface
from .executor import AgentExecutor, ExecutionResult
from ..collectors.trace_collector import TraceCollector
from ..analyzers.failure_analyzer import FailureAnalyzer
from ..checkers.safety_checker import SafetyChecker
from ..regression.regression_tester import RegressionTester
from ..reports.report_generator import ReportGenerator


class AegisTest:
    """AegisTest — Agent 评测主入口"""

    def __init__(self, agent: AgentInterface,
                 trace_dir: str = "./traces",
                 baseline_dir: str = "./baselines",
                 report_dir: str = "./reports",
                 judge=None):
        self.agent = agent
        self.executor = AgentExecutor(agent)
        self.trace_collector = TraceCollector(trace_dir)
        self.failure_analyzer = FailureAnalyzer()
        self.safety_checker = SafetyChecker()
        self.regression_tester = RegressionTester(baseline_dir)
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = str(uuid.uuid4())[:8]
        self.results: List[ExecutionResult] = []
        self.judge = judge  # LLM Judge（可选）

    def run_test(self, test_case: TestCase) -> ExecutionResult:
        """运行单个测试"""
        print(f"\n{'='*60}")
        print(f"Test: {test_case.id} [{test_case.category.value}]")
        print(f"Input: {test_case.input[:80]}...")
        print(f"{'='*60}")

        # 1. 开始 trace
        self.trace_collector.start_run(
            run_id=self.run_id,
            test_id=test_case.id,
            agent_name=self.agent.name,
            agent_version=self.agent.version,
        )

        # 2. 执行
        start = time.time()
        result = self.executor.execute(test_case)
        elapsed = time.time() - start

        # 3. 评估输出
        if result.success:
            passed, reason = self._evaluate_output(result.agent_output, test_case)
            result.success = passed
            if not result.success:
                result.failure_category = "output_mismatch"
                result.failure_reason = reason

        # 4. 记录 trace steps + agent_output
        if result.agent_result:
            for s in result.agent_result.steps:
                self.trace_collector.log_step(
                    step_type=s.step_type,
                    content=s.content,
                    tool=s.tool_name,
                    tool_args=s.tool_args,
                    tool_result=s.tool_result,
                )
        self.trace_collector.set_output(result.agent_output)

        # 5. 安全检查
        if result.agent_result:
            trace_steps = [
                {"step": s.step_number, "type": s.step_type,
                 "content": s.content, "tool": s.tool_name}
                for s in result.agent_result.steps
            ]
            violations = self.safety_checker.check(trace_steps, result.agent_output)
            result.safety_violations = [{
                "rule": v.rule, "severity": v.severity,
                "description": v.description, "evidence": v.evidence,
            } for v in violations]

        # 6. 失败分析
        if not result.success:
            analysis = self.failure_analyzer.analyze(result.to_dict())
            result.failure_category = analysis.get("category", "unknown")
            result.failure_reason = analysis.get("reason", result.failure_reason)

        # 7. 结束 trace
        self.trace_collector.end_run(metadata={
            "success": result.success,
            "failure_category": result.failure_category,
            "safety_violations": len(result.safety_violations),
        })

        self.results.append(result)

        # 8. 打印结果
        status = "PASS" if result.success else "FAIL"
        safety_info = f" | Safety: {len(result.safety_violations)} violations" if result.safety_violations else ""
        print(f"\nResult: {status} ({result.latency_ms:.0f}ms, {result.steps_used} steps){safety_info}")
        if not result.success:
            print(f"  Category: {result.failure_category}")
            print(f"  Reason: {result.failure_reason[:100]}...")
            print(f"  Output: {result.agent_output[:200]}...")

        return result

    def run_suite(self, suite: TestSuite, 
                  categories: Optional[List[str]] = None,
                  min_priority: Optional[str] = None) -> Dict[str, Any]:
        """运行整个测试集"""
        cases = suite.cases

        if categories:
            cases = [c for c in cases if c.category.value in categories]
        if min_priority:
            from .test_case import TestPriority
            priority_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            min_level = priority_order.get(min_priority, 0)
            cases = [c for c in cases if priority_order.get(c.priority.value, 0) >= min_level]

        print(f"\n{'#'*60}")
        print(f"# AegisTest Run: {self.run_id}")
        print(f"# Agent: {self.agent.name} v{self.agent.version}")
        print(f"# Tests: {len(cases)} cases")
        print(f"# Started: {datetime.now().isoformat()}")
        print(f"{'#'*60}")

        start_time = time.time()
        for i, case in enumerate(cases):
            print(f"\n[{i+1}/{len(cases)}]")
            self.run_test(case)

        total_time = time.time() - start_time

        # 汇总
        passed = sum(1 for r in self.results if r.success)
        failed = len(self.results) - passed

        # 安全检查统计
        safety_issues = sum(len(r.safety_violations) for r in self.results)

        # 失败分布
        failure_dist = {}
        for r in self.results:
            if not r.success and r.failure_category:
                failure_dist[r.failure_category] = failure_dist.get(r.failure_category, 0) + 1

        summary = {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "agent": {"name": self.agent.name, "version": self.agent.version},
            "total": len(self.results),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(self.results) if self.results else 0,
            "total_time_seconds": round(total_time, 2),
            "safety_issues": safety_issues,
            "failure_distribution": failure_dist,
            "avg_latency_ms": sum(r.latency_ms for r in self.results) / len(self.results) if self.results else 0,
            "avg_steps": sum(r.steps_used for r in self.results) / len(self.results) if self.results else 0,
        }

        print(f"\n{'='*60}")
        print(f"SUMMARY: {passed}/{len(self.results)} passed ({summary['pass_rate']*100:.1f}%)")
        print(f"Time: {total_time:.1f}s | Safety issues: {safety_issues}")
        if failure_dist:
            print(f"Failures by category: {failure_dist}")
        print(f"{'='*60}")

        return summary

    def _evaluate_output(self, output: str, test_case: TestCase) -> tuple[bool, str]:
        """评估输出是否符合预期。返回 (是否通过, 理由)"""
        # 优先使用 LLM Judge
        if self.judge is not None and test_case.expected_behavior:
            print("  [LLM Judge] 正在评估...")
            result = self.judge.evaluate(
                user_input=test_case.input,
                expected_behavior=test_case.expected_behavior,
                actual_output=output,
            )
            print(f"  [LLM Judge] {'PASS' if result.passed else 'FAIL'} — {result.reason}")
            return result.passed, f"[LLM Judge] {result.reason}"

        # 回退到字符串匹配
        # 1. 检查必须包含的内容
        for expected in test_case.expected_output_contains:
            if expected.lower() not in output.lower():
                return False, f"Missing expected text: '{expected}'"

        # 2. 检查不应包含的内容
        for forbidden in test_case.expected_not_contains:
            if forbidden.lower() in output.lower():
                return False, f"Found forbidden text: '{forbidden}'"

        # 3. 检查工具调用
        # (需要在 agent_result 中检查，这里简化)

        return True, "Output matched expected criteria"

    def save_baseline(self, prompt_version: str = "1.0", model_version: str = "unknown"):
        """保存当前结果为基线"""
        results_dict = [r.to_dict() for r in self.results]
        summary = {
            "run_id": self.run_id,
            "total": len(self.results),
            "passed": sum(1 for r in self.results if r.success),
        }
        self.regression_tester.save_baseline(
            run_id=self.run_id,
            agent_version=self.agent.version,
            prompt_version=prompt_version,
            model_version=model_version,
            results=results_dict,
            summary=summary,
        )

    def check_regression(self, baseline_run_id: str) -> Dict[str, Any]:
        """检查回归"""
        new_results = [r.to_dict() for r in self.results]
        return self.regression_tester.compare(new_results, baseline_run_id)

    def generate_report(self, output_path: Optional[str] = None, fmt: str = "html") -> str:
        """生成报告

        Args:
            output_path: 输出路径（默认自动生成）
            fmt: 报告格式，支持 html / json / markdown
        """
        generator = ReportGenerator(str(self.report_dir))
        path = generator.generate(
            results=self.results,
            run_id=self.run_id,
            agent_name=self.agent.name,
            agent_version=self.agent.version,
            output_path=output_path,
            fmt=fmt,
        )
        print(f"\nReport saved: {path}")
        return path
