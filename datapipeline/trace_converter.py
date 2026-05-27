"""Trace 转换器 —— 将 Session JSONL 转换为标准训练格式"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class TraceConverter:
    """
    将 AegisTest 的 session JSONL 转换为标准对话格式

    支持输出格式：
    - chatml: OpenAI ChatML [{"role": "user", "content": "..."}]
    - sharegpt: ShareGPT 格式 [{"from": "human", "value": "..."}]
    - traces: MiroThinker traces 格式（含 MCP XML tool call）
    - raw_messages: 直接输出 messages 列表
    """

    SUPPORTED_FORMATS = ["chatml", "sharegpt", "traces", "raw_messages"]

    def convert(
        self,
        session_file: str,
        output_format: str = "chatml",
    ) -> Dict[str, Any]:
        """转换单个 session 文件"""
        if output_format not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format: {output_format}. "
                f"Supported: {self.SUPPORTED_FORMATS}"
            )

        from ..session.session_loader import SessionLoader

        loader = SessionLoader()
        chain = loader.load_session(session_file)

        if output_format == "chatml":
            return self._to_chatml(chain)
        elif output_format == "sharegpt":
            return self._to_sharegpt(chain)
        elif output_format == "traces":
            return self._to_traces(chain)
        else:
            return {"messages": chain}

    def convert_batch(
        self,
        session_dir: str,
        output_format: str = "chatml",
        output_file: str = "train_data.json",
        pattern: str = "*.jsonl",
    ) -> str:
        """批量转换目录下所有 session"""
        all_conversations = []
        session_path = Path(session_dir)

        for jsonl_file in sorted(session_path.rglob(pattern)):
            try:
                conv = self.convert(str(jsonl_file), output_format)
                all_conversations.append(conv)
            except Exception as e:
                print(f"Warning: failed to convert {jsonl_file}: {e}")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_conversations, f, ensure_ascii=False, indent=2)

        return output_file

    def _to_chatml(self, chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        """转换为 ChatML 格式"""
        messages = []
        for entry in chain:
            role = self._map_role(entry.get("type"))
            content = self._extract_content(entry)
            if role is not None and content:
                messages.append({"role": role, "content": content})
        return {"messages": messages}

    def _to_sharegpt(self, chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        """转换为 ShareGPT 格式"""
        conversations = []
        for entry in chain:
            role = self._map_role(entry.get("type"))
            content = self._extract_content(entry)
            if role is not None and content:
                from_role = "human" if role == "user" else role
                conversations.append({"from": from_role, "value": content})
        return {"conversations": conversations}

    def _to_traces(self, chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        """转换为 MiroThinker traces 格式"""
        messages = []
        for entry in chain:
            msg_type = entry.get("type")
            if msg_type in ("system", "user"):
                messages.append({
                    "role": msg_type,
                    "content": self._extract_content(entry),
                })
            elif msg_type == "assistant":
                content = self._extract_content(entry)
                meta = entry.get("metadata", {})
                # 如果有 tool_calls，将 tool call 内容追加到 assistant message
                tool_calls = meta.get("tool_calls", [])
                if tool_calls:
                    tool_xml = "\n".join(
                        self._tool_call_to_mcp_xml(tc) for tc in tool_calls
                    )
                    content = f"{content}\n{tool_xml}".strip()
                messages.append({"role": "assistant", "content": content})
            elif msg_type == "tool_call":
                # 作为 assistant message 的一部分处理（已在上面处理）
                continue
            elif msg_type == "tool_result":
                messages.append({
                    "role": "user",
                    "content": f"[Tool Result]\n{self._extract_content(entry)}",
                })
        return {"messages": messages}

    def _map_role(self, entry_type: Optional[str]) -> Optional[str]:
        """将 entry type 映射为 standard role"""
        mapping = {
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "tool_result": "user",
        }
        return mapping.get(entry_type or "")

    def _extract_content(self, entry: Dict[str, Any]) -> str:
        """从 entry 中提取文本内容"""
        content = entry.get("content", "")
        if isinstance(content, str):
            return content
        elif isinstance(content, dict):
            return content.get("text", "")
        return str(content)

    def _tool_call_to_mcp_xml(self, tool_call: Dict[str, Any]) -> str:
        """将 tool_call 转为 MCP XML 格式"""
        tool_name = tool_call.get("tool_name", tool_call.get("name", "unknown"))
        tool_args = tool_call.get("tool_args", tool_call.get("arguments", {}))
        return (
            f"<use_mcp_tool>\n"
            f"<tool_name>{tool_name}</tool_name>\n"
            f"<arguments>{json.dumps(tool_args, ensure_ascii=False)}</arguments>\n"
            f"</use_mcp_tool>"
        )
