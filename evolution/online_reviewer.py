"""Online Reviewer — Hermes-compatible background review fork.

After every turn, a forked review agent replays the conversation and asks
itself "should any skill/memory be saved or updated?".  Writes go straight to
the memory + skill stores.

The fork runs with a tool whitelist limited to memory and skill management;
everything else is denied.
"""

import json
import re
from typing import Any, Dict, List, Optional


_MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory if appropriate.\n\n"
    "Focus on:\n"
    "1. Has the user revealed things about themselves — their persona, desires, "
    "preferences, or personal details worth remembering?\n"
    "2. Has the user expressed expectations about how you should behave, their work "
    "style, or ways they want you to operate?\n\n"
    "If something stands out, save it using the memory tool. "
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)

_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and update the skill library. Be "
    "ACTIVE — most sessions produce at least one skill update, even if "
    "small. A pass that does nothing is a missed learning opportunity, "
    "not a neutral outcome.\n\n"
    "Target shape of the library: CLASS-LEVEL skills, each with a rich "
    "SKILL.md and a `references/` directory for session-specific detail. "
    "Not a long flat list of narrow one-session-one-skill entries.\n\n"
    "Signals to look for (any one of these warrants action):\n"
    "  • User corrected your style, tone, format, legibility, or "
    "verbosity. Frustration signals like 'stop doing X', 'this is too "
    "verbose', 'don't format like this', 'why are you explaining', "
    "'just give me the answer', 'you always do Y and I hate it', or an "
    "explicit 'remember this' are FIRST-CLASS skill signals.\n"
    "  • User corrected your workflow, approach, or sequence of steps.\n"
    "  • Non-trivial technique, fix, workaround, debugging path, or "
    "tool-usage pattern emerged that a future session would benefit from.\n"
    "  • A skill that got loaded or consulted this session turned out "
    "wrong, missing a step, or outdated. Patch it NOW.\n\n"
    "Preference order — prefer the earliest action that fits:\n"
    "  1. UPDATE A CURRENTLY-LOADED SKILL.\n"
    "  2. UPDATE AN EXISTING UMBRELLA.\n"
    "  3. ADD A SUPPORT FILE under an existing umbrella.\n"
    "  4. CREATE A NEW CLASS-LEVEL UMBRELLA SKILL.\n\n"
    "User-preference embedding: when the user expressed a preference, "
    "update the skill that governs that task — memory alone isn't enough.\n\n"
    "Do NOT capture:\n"
    "  • Environment-dependent failures.\n"
    "  • Negative claims about tools or features.\n"
    "  • Session-specific transient errors that resolved.\n"
    "  • One-off task narratives.\n\n"
    "If genuinely nothing stands out, say 'Nothing to save.' and stop."
)

_COMBINED_REVIEW_PROMPT = (
    "Review the conversation above and update two things:\n\n"
    "**Memory**: who the user is. Did the user reveal persona, "
    "desires, preferences, personal details, or expectations about "
    "how you should behave? Save facts about the user and durable "
    "preferences with the memory tool.\n\n"
    "**Skills**: how to do this class of task. Be ACTIVE — most "
    "sessions produce at least one skill update.\n\n"
    "Target shape: CLASS-LEVEL skills with rich SKILL.md and "
    "`references/` directory. Not one-session-one-skill micro-entries.\n\n"
    "Signals that warrant a skill update (any one is enough):\n"
    "  • User corrected your style, tone, format, legibility, verbosity, or approach.\n"
    "  • Non-trivial technique, fix, workaround, or debugging path emerged.\n"
    "  • A skill that was loaded or consulted turned out wrong, missing, or outdated.\n\n"
    "Preference order:\n"
    "  1. UPDATE A CURRENTLY-LOADED SKILL.\n"
    "  2. UPDATE AN EXISTING UMBRELLA.\n"
    "  3. ADD A SUPPORT FILE under an existing umbrella.\n"
    "  4. CREATE A NEW CLASS-LEVEL UMBRELLA when nothing exists.\n\n"
    "Do NOT capture as skills:\n"
    "  • Environment-dependent failures.\n"
    "  • Negative claims about tools.\n"
    "  • Transient errors that resolved before session end.\n"
    "  • One-off task narratives.\n\n"
    "If genuinely nothing stands out on either dimension, say 'Nothing to save.' "
    "and stop — but don't reach for that conclusion as a default."
)

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Add a durable memory entry to the agent's memory store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "store": {"type": "string", "enum": ["memory", "user"], "description": "Which store to write to."},
                    "entry": {"type": "string", "description": "The memory text to save."},
                },
                "required": ["store", "entry"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_manage",
            "description": "Create, update, or patch a skill in the skill library.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "patch", "write_file"]},
                    "name": {"type": "string", "description": "Skill name."},
                    "content": {"type": "string", "description": "Full SKILL.md content for create, or new_string for patch."},
                    "old_string": {"type": "string", "description": "Text to replace (for patch)."},
                    "file_path": {"type": "string", "description": "Path under skill dir for write_file, e.g. references/notes.md."},
                    "file_content": {"type": "string", "description": "Content for write_file."},
                    "description": {"type": "string", "description": "Short description for new skills."},
                },
                "required": ["action", "name"],
            },
        },
    },
]


class OnlineReviewer:
    """
    Background review fork.

    Simulates a Hermes-style forked agent that:
      1. Loads the conversation from JSONL
      2. Builds the review prompt
      3. Calls LLM with tool schemas
      4. Executes tool calls
      5. Loops until LLM says "Nothing to save." or max iterations reached
    """

    def __init__(
        self,
        llm_client=None,
        skill_manager=None,
        memory_manager=None,
        max_iterations: int = 8,
    ):
        self.llm_client = llm_client
        self.skill_manager = skill_manager
        self.memory_manager = memory_manager
        self.max_iterations = max_iterations

    def review_session(
        self,
        session_file: str,
        review_type: str = "combined",
    ) -> Dict[str, Any]:
        """Review a single session file."""
        from ..session.session_loader import SessionLoader

        loader = SessionLoader()
        chain = loader.load_session(session_file)
        if not chain:
            return {"review_type": review_type, "actions": [], "executed": [], "error": "empty session"}

        quality_signals = self._extract_quality_signals(session_file)

        # If no LLM client, fall back to rule-based
        if self.llm_client is None:
            review_result = self._rule_based_review(chain, review_type)
            actions = self._parse_actions(review_result)
            executed = self._execute_actions(actions)
            return {
                "review_type": review_type,
                "actions": actions,
                "executed": executed,
                "session_file": session_file,
                "raw_review": review_result,
            }

        # --- LLM-driven fork agent simulation ---
        prompt = self._build_review_prompt(chain, quality_signals, review_type)

        all_actions: List[Dict[str, Any]] = []
        all_executed: List[Dict[str, Any]] = []
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are an expert AI agent reviewer. Analyze conversations and improve the agent's skills and memory."},
            {"role": "user", "content": prompt},
        ]

        for _ in range(self.max_iterations):
            result = self.llm_client.chat(messages, tools=_TOOL_SCHEMAS, temperature=0.3)
            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])

            if not tool_calls:
                # LLM gave a text response
                if "Nothing to save" in content:
                    break
                # Try to parse JSON actions from text as fallback
                actions = self._parse_actions(content)
                if actions:
                    executed = self._execute_actions(actions)
                    all_actions.extend(actions)
                    all_executed.extend(executed)
                break

            # Execute tool calls
            tool_results: List[Dict[str, Any]] = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                action = {"tool": fn_name, "args": args}
                all_actions.append(action)

                exec_result = self._execute_tool_call(fn_name, args)
                action["result"] = exec_result
                all_executed.append(action)

                tool_results.append({
                    "tool_call_id": tc.get("id", ""),
                    "role": "tool",
                    "name": fn_name,
                    "content": json.dumps(exec_result),
                })

            # Add assistant response + tool results to conversation
            messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})
            for tr in tool_results:
                messages.append({"role": "tool", "content": tr["content"], "tool_call_id": tr["tool_call_id"]})

        return {
            "review_type": review_type,
            "actions": all_actions,
            "executed": all_executed,
            "session_file": session_file,
        }

    def _build_review_prompt(
        self,
        chain: List[Dict[str, Any]],
        quality_signals: Dict[str, Any],
        review_type: str,
    ) -> str:
        conversation_text = "\n".join([
            f"[{entry.get('type', '?').upper()}] {str(entry.get('content', ''))[:400]}"
            for entry in chain
        ])

        if review_type == "memory":
            prompt = _MEMORY_REVIEW_PROMPT
        elif review_type == "skill":
            prompt = _SKILL_REVIEW_PROMPT
        else:
            prompt = _COMBINED_REVIEW_PROMPT

        return (
            f"Conversation:\n{conversation_text}\n\n"
            f"Quality signals: {json.dumps(quality_signals, ensure_ascii=False)}\n\n"
            f"{prompt}\n\n"
            "You have access to two tools:\n"
            "  - memory_add(store, entry) — save durable facts to memory or user profile.\n"
            "  - skill_manage(action, name, content, ...) — create/patch/write_file for skills.\n"
            "Only use these tools. Do not attempt any other actions.\n"
        )

    def _execute_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "memory_add":
            return self._do_memory_add(args)
        elif tool_name == "skill_manage":
            return self._do_skill_manage(args)
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    def _do_memory_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.memory_manager:
            return {"success": False, "error": "No memory manager configured"}
        store = args.get("store", "memory")
        entry = args.get("entry", "")
        if not entry:
            return {"success": False, "error": "entry is required"}
        try:
            self.memory_manager.add_entry(entry, store=store)
            return {"success": True, "message": f"Added to {store}", "target": "memory"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _do_skill_manage(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.skill_manager:
            return {"success": False, "error": "No skill manager configured"}
        action = args.get("action", "")
        name = args.get("name", "")
        if not name:
            return {"success": False, "error": "name is required"}

        try:
            if action == "create":
                content = args.get("content", "")
                if not content.strip().startswith("---"):
                    desc = args.get("description", f"Skill '{name}'")
                    from .skill_manager import _build_skill_md
                    content = _build_skill_md(name, desc, content)
                path = self.skill_manager.upsert(
                    name, content,
                    origin="background_review"
                )
                return {"success": True, "message": f"Skill '{name}' created.", "target": name}

            elif action == "patch":
                old_string = args.get("old_string", "")
                new_string = args.get("new_string", "")
                ok = self.skill_manager.patch(name, old_string, new_string)
                if ok:
                    return {"success": True, "message": f"Skill '{name}' patched.", "target": name}
                return {"success": False, "error": "Patch failed: old_string not found"}

            elif action == "write_file":
                file_path = args.get("file_path", "")
                file_content = args.get("file_content", "")
                path = self.skill_manager.write_file(name, file_path, file_content)
                return {"success": True, "message": f"Wrote {file_path}.", "target": name}

            else:
                return {"success": False, "error": f"Unknown skill_manage action: {action}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _rule_based_review(
        self,
        chain: List[Dict[str, Any]],
        review_type: str,
    ) -> str:
        actions = []
        correction_keywords = ["不对", "错了", "should be", "不是这样", "修正", "纠正", "stop doing", "don't format", "i hate"]
        for i, entry in enumerate(chain):
            content = str(entry.get("content", "")).lower()
            if any(kw in content for kw in correction_keywords):
                actions.append({
                    "action": "skill_create",
                    "skill_name": "user_correction_handler",
                    "content": f"Detected user correction at turn {i}. Content: {content[:100]}",
                })
                break

        if len(chain) > 10 and review_type in ("memory", "combined"):
            actions.append({
                "action": "memory_add",
                "key": "conversation_patience",
                "value": "user engaged in long multi-turn conversation",
                "category": "behavior",
            })

        return json.dumps(actions)

    def _parse_actions(self, review_result: str) -> List[Dict[str, Any]]:
        if not review_result:
            return []
        try:
            match = re.search(r'\[.*\]', review_result, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
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
                        origin="background_review",
                    )
                    executed.append(action)
            except Exception as e:
                action["_error"] = str(e)
                executed.append(action)
        return executed

    def _extract_quality_signals(self, session_file: str) -> Dict[str, Any]:
        signals = {"success": True, "judge_score": 1.0, "has_feedback": False, "turn_count": 0}
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
