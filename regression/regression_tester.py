"""回归测试器 — 检测 prompt/工具改动后的能力退化"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BaselineRecord:
    """基线记录"""
    run_id: str
    timestamp: str
    agent_version: str
    prompt_version: str
    model_version: str
    results: List[Dict[str, Any]]
    summary: Dict[str, Any]


class RegressionTester:
    """回归测试器"""

    def __init__(self, baseline_dir: str = "./baselines"):
        self.baseline_dir = Path(baseline_dir)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.current_baseline: Optional[BaselineRecord] = None

    def save_baseline(self, run_id: str, agent_version: str, 
                      prompt_version: str, model_version: str,
                      results: List[Dict[str, Any]], summary: Dict[str, Any]):
        """保存当前结果作为基线"""
        baseline = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "agent_version": agent_version,
            "prompt_version": prompt_version,
            "model_version": model_version,
            "results": results,
            "summary": summary,
        }
        filename = f"baseline_{run_id}.json"
        filepath = self.baseline_dir / filename
        with open(filepath, "w") as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
        print(f"Baseline saved: {filepath}")

    def load_baseline(self, run_id: str) -> Optional[BaselineRecord]:
        """加载基线"""
        filepath = self.baseline_dir / f"baseline_{run_id}.json"
        if not filepath.exists():
            return None
        with open(filepath) as f:
            data = json.load(f)
        return BaselineRecord(**{k: v for k, v in data.items() 
                                  if k in ["run_id", "timestamp", "agent_version",
                                           "prompt_version", "model_version", 
                                           "results", "summary"]})

    def compare(self, new_results: List[Dict[str, Any]], 
                baseline_run_id: str) -> Dict[str, Any]:
        """对比新结果和基线，检测退化"""
        baseline = self.load_baseline(baseline_run_id)
        if not baseline:
            return {"error": "Baseline not found"}

        # 构建结果映射
        old_map = {r["test_id"]: r for r in baseline.results}
        new_map = {r["test_id"]: r for r in new_results}

        regressions = []       # 退化的
        improvements = []      # 进步的
        unchanged = []         # 不变的
        new_tests = []         # 新增的
        missing_tests = []     # 丢失的

        all_test_ids = set(old_map.keys()) | set(new_map.keys())

        for test_id in all_test_ids:
            old = old_map.get(test_id)
            new = new_map.get(test_id)

            if old and not new:
                missing_tests.append({"test_id": test_id, "old_result": old})
            elif new and not old:
                new_tests.append({"test_id": test_id, "new_result": new})
            elif old and new:
                old_success = old.get("success", False)
                new_success = new.get("success", False)

                if old_success and not new_success:
                    regressions.append({
                        "test_id": test_id,
                        "old": old, "new": new,
                        "severity": "critical" if old.get("category") == "safety" else "high"
                    })
                elif not old_success and new_success:
                    improvements.append({"test_id": test_id, "old": old, "new": new})
                else:
                    unchanged.append({"test_id": test_id, "success": new_success})

        # 计算指标
        old_pass_rate = sum(1 for r in baseline.results if r.get("success")) / len(baseline.results) if baseline.results else 0
        new_pass_rate = sum(1 for r in new_results if r.get("success")) / len(new_results) if new_results else 0

        return {
            "regressions": regressions,
            "improvements": improvements,
            "unchanged": unchanged,
            "new_tests": new_tests,
            "missing_tests": missing_tests,
            "old_pass_rate": old_pass_rate,
            "new_pass_rate": new_pass_rate,
            "pass_rate_delta": new_pass_rate - old_pass_rate,
            "has_regression": len(regressions) > 0,
            "regression_count": len(regressions),
            "baseline_info": {
                "run_id": baseline.run_id,
                "timestamp": baseline.timestamp,
                "agent_version": baseline.agent_version,
                "prompt_version": baseline.prompt_version,
                "model_version": baseline.model_version,
            }
        }
