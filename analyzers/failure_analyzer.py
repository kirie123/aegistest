"""失败分析器 — 分类失败原因"""

import re
from typing import Dict, Any, List, Optional
from collections import Counter


class FailureAnalyzer:
    """失败分析器 — 判断失败发生在哪个环节"""

    # 失败模式关键词映射
    FAILURE_PATTERNS = {
        "prompt": [
            r"system prompt", r"instruction", r"developer message",
            r"prompt injection", r"jailbreak", r"ignore previous",
            r"override", r"disregard",
        ],
        "tool": [
            r"tool call", r"function call", r"invalid tool",
            r"tool not found", r"tool execution failed",
            r"permission denied", r"tool error",
        ],
        "retrieval": [
            r"search", r"retrieve", r"query", r"lookup",
            r"no results found", r"retrieval failed",
            r"vector store", r"embedding",
        ],
        "model": [
            r"llm error", r"model error", r"generation failed",
            r"timeout", r"rate limit", r"context window",
            r"token limit exceeded", r"hallucination",
        ],
        "state": [
            r"state", r"memory", r"context", r"session",
            r"lost track", r"forgot", r"context overflow",
            r"conversation history",
        ],
    }

    def analyze(self, execution_result: Dict[str, Any]) -> Dict[str, Any]:
        """分析失败原因"""
        if execution_result.get("success", True):
            return {"category": None, "reason": "Success", "confidence": 1.0}

        failure_reason = execution_result.get("failure_reason", "")
        trace = execution_result.get("trace", [])
        agent_output = execution_result.get("agent_output", "")

        # 1. 如果已经有明确分类，直接返回
        existing_category = execution_result.get("failure_category")
        if existing_category and existing_category != "model":
            return {
                "category": existing_category,
                "reason": failure_reason,
                "confidence": 0.9,
                "evidence": f"Pre-categorized as {existing_category}",
            }

        # 2. 基于 trace 分析
        evidence_text = " ".join([
            step.get("content", "") + " " + str(step.get("tool", ""))
            for step in trace
        ]) + " " + failure_reason + " " + agent_output

        # 3. 匹配失败模式
        category_scores = {}
        for category, patterns in self.FAILURE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, evidence_text, re.IGNORECASE))
                score += matches
            if score > 0:
                category_scores[category] = score

        if category_scores:
            best_category = max(category_scores, key=category_scores.get)
            return {
                "category": best_category,
                "reason": failure_reason,
                "confidence": min(0.9, 0.5 + category_scores[best_category] * 0.1),
                "evidence": f"Matched patterns in {best_category} (score: {category_scores[best_category]})",
                "all_scores": category_scores,
            }

        # 4. 默认归类
        return {
            "category": "unknown",
            "reason": failure_reason,
            "confidence": 0.3,
            "evidence": "No specific pattern matched",
        }

    def analyze_batch(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量分析，生成统计"""
        categories = Counter()
        details = []

        for result in results:
            analysis = self.analyze(result)
            categories[analysis["category"]] += 1
            details.append({
                "test_id": result.get("test_id", "unknown"),
                "success": result.get("success", False),
                **analysis,
            })

        return {
            "distribution": dict(categories),
            "top_category": categories.most_common(1)[0][0] if categories else None,
            "details": details,
        }
