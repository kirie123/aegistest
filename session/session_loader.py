"""Session 加载器 —— 从 JSONL 恢复对话链"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import OrderedDict


class SessionLoader:
    """
    加载 JSONL 会话文件，构建完整对话链

    支持功能：
    - 解析 JSONL
    - 沿 parent_uuid 回溯构建主链
    - 恢复孤儿并行 tool_result
    - 质量标注提取
    """

    def load_session(self, file_path: str) -> List[Dict[str, Any]]:
        """加载完整会话（含死分支过滤、tool result 恢复）"""
        entries = self._parse_jsonl(file_path)
        messages = self._extract_messages(entries)

        if not messages:
            return []

        leaf = self._find_latest_leaf(messages)
        chain = self._build_chain(messages, leaf)
        chain = self._recover_orphaned_tools(messages, chain)
        return chain

    def load_raw_entries(self, file_path: str) -> List[Dict[str, Any]]:
        """加载所有 entry（不过滤、不建链，用于分析）"""
        return self._parse_jsonl(file_path)

    def extract_annotations(self, file_path: str) -> List[Dict[str, Any]]:
        """提取会话中的所有质量标注"""
        annotations = []
        for entry in self._parse_jsonl(file_path):
            if entry.get("type") == "quality_annotation":
                annotations.append(entry.get("content", {}))
        return annotations

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """提取 session header/footer 中的元数据"""
        meta = {}
        for entry in self._parse_jsonl(file_path):
            etype = entry.get("type", "")
            if etype == "session_header":
                meta.update(entry.get("content", {}))
            elif etype == "session_footer":
                meta.update(entry.get("content", {}))
        return meta

    def _parse_jsonl(self, file_path: str) -> List[Dict[str, Any]]:
        """解析 JSONL 文件"""
        entries = []
        path = Path(file_path)
        if not path.exists():
            return entries

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def _extract_messages(self, entries: List[Dict[str, Any]]) -> OrderedDict:
        """提取消息类型的 entry，按 uuid 索引"""
        message_types = {"system", "user", "assistant", "tool_call", "tool_result", "attachment"}
        messages = OrderedDict()
        for entry in entries:
            if entry.get("type") in message_types:
                messages[entry["uuid"]] = entry
        return messages

    def _find_latest_leaf(self, messages: OrderedDict) -> Dict[str, Any]:
        """找到最新的叶子消息（无子节点）

        优先从 assistant / user / tool 类型中选择叶子，
        排除 system / header / footer / annotation 等元数据 entry。
        """
        all_uuids = set(messages.keys())
        child_uuids = set()
        for msg in messages.values():
            pu = msg.get("parent_uuid")
            if pu:
                child_uuids.add(pu)

        # 优先选择对话类型的叶子
        dialog_types = {"user", "assistant", "tool_call", "tool_result"}
        leaves = [
            uid for uid in all_uuids
            if uid not in child_uuids and messages[uid].get("type") in dialog_types
        ]

        if leaves:
            return messages[leaves[-1]]

        # 回退：任何叶子
        leaves = [uid for uid in all_uuids if uid not in child_uuids]
        if leaves:
            return messages[leaves[-1]]

        return list(messages.values())[-1] if messages else {}

    def _build_chain(
        self,
        messages: OrderedDict,
        leaf: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """沿 parent_uuid 回溯构建正序对话链"""
        chain = []
        seen = set()
        current: Optional[Dict[str, Any]] = leaf

        while current:
            uid = current.get("uuid")
            if not uid or uid in seen:
                break
            seen.add(uid)
            chain.append(current)
            parent_uuid = current.get("parent_uuid")
            current = messages.get(parent_uuid) if parent_uuid else None

        chain.reverse()
        return chain

    def _recover_orphaned_tools(
        self,
        all_messages: OrderedDict,
        chain: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """恢复链外的孤儿并行 tool_result"""
        chain_uuids = {msg["uuid"] for msg in chain}

        # 找到链内 assistant 中带有 tool_call 的消息
        tool_call_parents = set()
        for msg in chain:
            if msg.get("type") == "assistant":
                meta = msg.get("metadata", {})
                if meta.get("has_tool_call") or meta.get("tool_calls"):
                    tool_call_parents.add(msg["uuid"])

        # 找到链外但 parent 在链内的 tool_result
        orphaned = []
        for msg in all_messages.values():
            if msg["uuid"] in chain_uuids:
                continue
            if msg.get("type") != "tool_result":
                continue
            parent = msg.get("parent_uuid")
            if parent and parent in tool_call_parents:
                orphaned.append(msg)

        if not orphaned:
            return chain

        # 按 parent_uuid 分组
        orphan_map = {}
        for o in orphaned:
            pu = o.get("parent_uuid")
            orphan_map.setdefault(pu, []).append(o)

        # 插入到对应 assistant 消息之后
        new_chain = []
        for msg in chain:
            new_chain.append(msg)
            if msg["uuid"] in orphan_map:
                new_chain.extend(orphan_map[msg["uuid"]])

        return new_chain
