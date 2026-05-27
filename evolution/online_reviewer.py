"""在线审查器 —— 基于持久化 session 的单会话 review"""

import json
import re
from typing import Dict, Any, List, Optional


class OnlineReviewer:
    """
    单会话在线审查器

    与 hermes Background Review 的区别：
    - hermes 读取内存中的 messages snapshot
    - 我们读取刚落盘的 JSONL session 文件

    优势：进程重启后仍可审查；支持测试流水线集成
    """

    def __init__(
        self,
        llm_client=None,
        skill_manager=None,
        memory_manager=None,
    ):
        self.llm_client = llm_client
        self.skill_manager = skill_manager
        self.memory_manager = memory_manager

    def review_session(
        self,
        session_file: str,
        review_type: str = "combined",
    ) -> Dict[str, Any]:
        """
        审查单个 session 文件

        Args:
            session_file: JSONL 会话文件路径
            review_type: "memory" | "skill" | "combined"
        """
        from ..session.session_loader import SessionLoader

        # 1. 加载会话链
        loader = SessionLoader()
        chain = loader.load_session(session_file)

        if not chain:
            return {"review_type": review_type, "actions": [], "executed": [], "error": "empty session"}

        # 2. 提取质量信号
        quality_signals = self._extract_quality_signals(session_file)

        # 3. 构建 review prompt
        prompt = self._build_review_prompt(chain, quality_signals, review_type)

        # 4. 调用 LLM 或规则审查
        if self.llm_client:
            review_result = self._call_llm(prompt)
        else:
            review_result = self._rule_based_review(chain, review_type)

        # 5. 解析并执行 action
        actions = self._parse_actions(review_result)
        executed = self._execute_actions(actions)

        return {
            "review_type": review_type,
            "actions": actions,
            "executed": executed,
            "session_file": session_file,
            "raw_review": review_result if not self.llm_client else None,
        }

    def _build_review_prompt(
        self,
        chain: List[Dict[str, Any]],
        quality_signals: Dict[str, Any],
        review_type: str,
    ) -> str:
        """构建 review prompt"""
        conversation_text = "\n".join([
            f"[{entry.get('type', '?').upper()}] {str(entry.get('content', ''))[:300]}"
            for entry in chain
        ])

        base = f"""You are an expert AI agent reviewer. Analyze the following conversation and suggest improvements.

Conversation:
{conversation_text}

Quality signals: {json.dumps(quality_signals, ensure_ascii=False)}
"""

        if review_type == "memory":
            return base + """
Extract durable user knowledge:
1. User persona and preferences
2. Workflow habits
3. Implicit expectations
4. Facts that should be remembered long-term

Output JSON array of actions:
[{"action": "memory_add", "key": "...", "value": "...", "category": "general"}]
"""
        elif review_type == "skill":
            return base + """
Identify skill improvements:
1. User corrections (style, tone, format, workflow)
2. New techniques or workarounds discovered
3. Existing skills that were wrong or outdated
4. Opportunities for new umbrella skills

Output JSON array of actions:
[{"action": "skill_update", "skill_name": "...", "content": "..."}]
"""
        else:
            return base + """
Perform both memory and skill review.

Output JSON array of actions with "action" in ["memory_add", "skill_update", "skill_create"]:
[{"action": "memory_add", "key": "...", "value": "..."}]
"""

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM，简化接口"""
        if hasattr(self.llm_client, "complete"):
            return self.llm_client.complete(prompt)
        elif hasattr(self.llm_client, "chat"):
            return self.llm_client.chat([{"role": "user", "content": prompt}])
        return ""

    def _rule_based_review(
        self,
        chain: List[Dict[str, Any]],
        review_type: str,
    ) -> str:
        """无 LLM 时的规则-based review"""
        actions = []

        # 规则 1：检测到用户纠正 → 创建 skill
        correction_keywords = ["不对", "错了", "should be", "不对", "错了", "不是这样", "修正"]
        for i, entry in enumerate(chain):
            content = str(entry.get("content", "")).lower()
            if any(kw in content for kw in correction_keywords):
                actions.append({
                    "action": "skill_create",
                    "skill_name": "user_correction_handler",
                    "content": f"Detected user correction at turn {i}. Content: {content[:100]}",
                })
                break  # 只记录一次

        # 规则 2：长对话 → 记录用户耐心度
        if len(chain) > 10 and review_type in ("memory", "combined"):
            actions.append({
                "action": "memory_add",
                "key": "conversation_patience",
                "value": "user engaged in long multi-turn conversation",
                "category": "behavior",
            })

        return json.dumps(actions)

    def _extract_quality_signals(self, session_file: str) -> Dict[str, Any]:
        """从 session 文件提取质量信号"""
        signals = {
            "success": True,
            "judge_score": 1.0,
            "has_feedback": False,
            "turn_count": 0,
        }

        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                etype = entry.get("type", "")

                if etype == "session_header":
                    meta = entry.get("content", {})
                    signals["success"] = meta.get("success", True)
                elif etype == "session_footer":
                    meta = entry.get("content", {})
                    signals["success"] = meta.get("success", signals["success"])
                elif etype == "quality_annotation":
                    content = entry.get("content", {})
                    signals["judge_score"] = content.get("judge_score", 1.0)
                    if content.get("feedback_type"):
                        signals["has_feedback"] = True
                elif etype in ("user", "assistant", "tool_call", "tool_result"):
                    signals["turn_count"] += 1

        return signals

    def _parse_actions(self, review_result: str) -> List[Dict[str, Any]]:
        """从 LLM/规则输出解析 action 列表"""
        if not review_result:
            return []

        # 尝试提取 JSON 数组
        try:
            match = re.search(r'\[.*\]', review_result, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # 尝试整个字符串作为 JSON
        try:
            data = json.loads(review_result)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "actions" in data:
                return data["actions"]
        except json.JSONDecodeError:
            pass

        return []

    def _execute_actions(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """执行 action"""
        executed = []
        for action in actions:
            act_type = action.get("action")
            try:
                if act_type == "memory_add" and self.memory_manager:
                    self.memory_manager.add(
                        key=action.get("key", "unknown"),
                        value=action.get("value", ""),
                        category=action.get("category", "general"),
                    )
                    executed.append(action)

                elif act_type in ("skill_update", "skill_create") and self.skill_manager:
                    self.skill_manager.upsert(
                        skill_name=action.get("skill_name", "unknown"),
                        content=action.get("content", ""),
                    )
                    executed.append(action)

            except Exception as e:
                action["_error"] = str(e)
                executed.append(action)

        return executed
