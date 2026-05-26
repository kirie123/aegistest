"""执行分析器 —— 将 Agent 执行过程转化为结构化指标和洞察"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from ..core.executor import ExecutionResult


@dataclass
class SessionMetrics:
    """会话级指标"""
    total_steps: int = 0
    thinking_steps: int = 0
    tool_call_steps: int = 0
    tool_result_steps: int = 0
    error_steps: int = 0
    response_steps: int = 0
    total_latency_ms: float = 0.0
    total_tokens: Dict[str, int] = field(default_factory=dict)
    turn_count: int = 1


@dataclass
class ToolMetrics:
    """工具调用指标"""
    total_calls: int = 0
    distribution: Dict[str, int] = field(default_factory=dict)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    unique_tools: List[str] = field(default_factory=list)


@dataclass
class FileMetrics:
    """文件操作指标"""
    files_read: List[str] = field(default_factory=list)
    files_written: List[str] = field(default_factory=list)
    files_edited: List[str] = field(default_factory=list)
    directories_created: List[str] = field(default_factory=list)
    file_access_count: Dict[str, int] = field(default_factory=dict)


@dataclass
class FailureMetrics:
    """失败与恢复指标"""
    error_count: int = 0
    failure_chain: List[Dict[str, Any]] = field(default_factory=list)
    recovery_detected: bool = False
    first_error_step: Optional[int] = None


@dataclass
class ExecutionInsights:
    """完整的过程洞察"""
    session: SessionMetrics = field(default_factory=SessionMetrics)
    tools: ToolMetrics = field(default_factory=ToolMetrics)
    files: FileMetrics = field(default_factory=FileMetrics)
    failures: FailureMetrics = field(default_factory=FailureMetrics)

    def to_dict(self) -> dict:
        return {
            "session": {
                "total_steps": self.session.total_steps,
                "thinking_steps": self.session.thinking_steps,
                "tool_call_steps": self.session.tool_call_steps,
                "tool_result_steps": self.session.tool_result_steps,
                "error_steps": self.session.error_steps,
                "response_steps": self.session.response_steps,
                "total_latency_ms": self.session.total_latency_ms,
                "total_tokens": self.session.total_tokens,
                "turn_count": self.session.turn_count,
            },
            "tools": {
                "total_calls": self.tools.total_calls,
                "distribution": self.tools.distribution,
                "unique_tools": self.tools.unique_tools,
                "timeline": self.tools.timeline,
            },
            "files": {
                "read": self.files.files_read,
                "written": self.files.files_written,
                "edited": self.files.files_edited,
                "directories_created": self.files.directories_created,
                "access_count": self.files.file_access_count,
            },
            "failures": {
                "error_count": self.failures.error_count,
                "failure_chain": self.failures.failure_chain,
                "recovery_detected": self.failures.recovery_detected,
                "first_error_step": self.failures.first_error_step,
            },
        }


class ExecutionAnalyzer:
    """执行分析器

    从 AgentRunResult 的原始 steps 中挖掘过程指标，包括：
    - 会话级统计（步数、轮次、耗时、token）
    - 工具调用画像（分布、时间线、成功率）
    - 文件操作画像（读写编辑、目录创建）
    - 失败与恢复分析（错误链、自我修复检测）
    """

    # 工具名到操作类型的映射（支持大小写变体）
    READ_TOOLS = {"read", "read_file", "file_read", "ls", "glob", "grep"}
    WRITE_TOOLS = {"write", "write_file", "file_write", "create_file"}
    EDIT_TOOLS = {"edit", "edit_file", "file_edit", "replace", "patch"}
    BASH_TOOLS = {"bash", "shell", "cmd", "exec"}

    def analyze(self, result: ExecutionResult) -> ExecutionInsights:
        """分析单次执行结果"""
        steps = result.agent_result.steps if result.agent_result else []

        insights = ExecutionInsights()
        insights.session = self._analyze_session(result, steps)
        insights.tools = self._analyze_tools(steps)
        insights.files = self._analyze_files(steps)
        insights.failures = self._analyze_failures(steps)

        return insights

    def analyze_batch(self, results: List[ExecutionResult]) -> Dict[str, Any]:
        """批量分析整个测试集"""
        all_insights = [self.analyze(r) for r in results]

        total_tools = sum(i.tools.total_calls for i in all_insights)
        total_errors = sum(i.failures.error_count for i in all_insights)
        total_steps = sum(i.session.total_steps for i in all_insights)

        # 聚合工具分布
        tool_dist: Dict[str, int] = {}
        for i in all_insights:
            for tool, count in i.tools.distribution.items():
                tool_dist[tool] = tool_dist.get(tool, 0) + count

        # 最常访问的文件
        file_access: Dict[str, int] = {}
        for i in all_insights:
            for f, count in i.files.file_access_count.items():
                file_access[f] = file_access.get(f, 0) + count
        top_files = sorted(file_access.items(), key=lambda x: -x[1])[:10]

        # 恢复能力统计
        recovery_count = sum(1 for i in all_insights if i.failures.recovery_detected)

        return {
            "total_tests": len(results),
            "total_steps": total_steps,
            "total_tool_calls": total_tools,
            "total_errors": total_errors,
            "avg_steps_per_test": total_steps / len(results) if results else 0,
            "avg_tools_per_test": total_tools / len(results) if results else 0,
            "tool_distribution": tool_dist,
            "top_accessed_files": top_files,
            "recovery_count": recovery_count,
            "recovery_rate": recovery_count / len(results) if results else 0,
        }

    def _analyze_session(self, result: ExecutionResult, steps: List[Any]) -> SessionMetrics:
        """分析会话级指标"""
        m = SessionMetrics()
        m.total_steps = len(steps)
        m.thinking_steps = sum(1 for s in steps if s.step_type == "thought")
        m.tool_call_steps = sum(1 for s in steps if s.step_type == "tool_call")
        m.tool_result_steps = sum(1 for s in steps if s.step_type == "tool_result")
        m.error_steps = sum(1 for s in steps if s.step_type == "error")
        m.response_steps = sum(1 for s in steps if s.step_type == "response")
        m.total_latency_ms = result.latency_ms
        m.total_tokens = result.token_usage

        # 从 metadata 中提取轮次信息
        if result.agent_result and result.agent_result.metadata:
            m.turn_count = result.agent_result.metadata.get("turn_count", 1)

        return m

    def _analyze_tools(self, steps: List[Any]) -> ToolMetrics:
        """分析工具调用指标"""
        tool_calls = [s for s in steps if s.step_type == "tool_call"]
        m = ToolMetrics()
        m.total_calls = len(tool_calls)
        m.distribution = dict(Counter(s.tool_name for s in tool_calls if s.tool_name))
        m.unique_tools = list(m.distribution.keys())

        # 构建时间线
        for s in tool_calls:
            # 推断状态：如果下一步是 tool_result，视为成功；如果是 error，视为失败
            status = "unknown"
            for next_s in steps:
                if next_s.step_number > s.step_number:
                    if next_s.step_type == "tool_result":
                        status = "success"
                        break
                    elif next_s.step_type == "error":
                        status = "failed"
                        break

            m.timeline.append({
                "step": s.step_number,
                "tool": s.tool_name,
                "latency_ms": s.latency_ms,
                "status": status,
                "args_preview": self._preview_args(s.tool_args),
            })

        return m

    def _analyze_files(self, steps: List[Any]) -> FileMetrics:
        """分析文件操作指标"""
        m = FileMetrics()
        access_count: Dict[str, int] = {}

        for s in steps:
            if s.step_type != "tool_call" or not s.tool_args:
                continue

            args = s.tool_args
            tool_lower = (s.tool_name or "").lower()
            path = self._extract_path(args)

            if not path:
                continue

            if tool_lower in self.READ_TOOLS:
                m.files_read.append(path)
                access_count[path] = access_count.get(path, 0) + 1
            elif tool_lower in self.WRITE_TOOLS:
                m.files_written.append(path)
                access_count[path] = access_count.get(path, 0) + 1
            elif tool_lower in self.EDIT_TOOLS:
                m.files_edited.append(path)
                access_count[path] = access_count.get(path, 0) + 1
            elif tool_lower in self.BASH_TOOLS:
                # 从 bash 命令中提取 mkdir
                command = args.get("command", "")
                dirs = self._extract_mkdirs(command)
                m.directories_created.extend(dirs)
                # 也检测 bash 中的文件操作
                files_from_bash = self._extract_file_ops_from_bash(command)
                for op, fpath in files_from_bash:
                    if op == "read":
                        m.files_read.append(fpath)
                    elif op == "write":
                        m.files_written.append(fpath)
                    access_count[fpath] = access_count.get(fpath, 0) + 1

        # 去重保持顺序
        m.files_read = list(dict.fromkeys(m.files_read))
        m.files_written = list(dict.fromkeys(m.files_written))
        m.files_edited = list(dict.fromkeys(m.files_edited))
        m.directories_created = list(dict.fromkeys(m.directories_created))
        m.file_access_count = access_count

        return m

    def _analyze_failures(self, steps: List[Any]) -> FailureMetrics:
        """分析失败与恢复"""
        m = FailureMetrics()
        error_steps = [s for s in steps if s.step_type == "error"]
        m.error_count = len(error_steps)

        if error_steps:
            m.first_error_step = error_steps[0].step_number

        for i, step in enumerate(steps):
            if step.step_type == "error":
                m.failure_chain.append({
                    "step": step.step_number,
                    "type": "error",
                    "tool": step.tool_name,
                    "reason": step.content[:200],
                })

                # 检测恢复：错误后 5 步内出现成功的 tool_call 或 response
                for j in range(i + 1, min(i + 6, len(steps))):
                    if steps[j].step_type in ("tool_result", "response", "tool_call"):
                        m.recovery_detected = True
                        break

        return m

    @staticmethod
    def _extract_path(args: Dict[str, Any]) -> Optional[str]:
        """从 tool_args 中提取文件路径"""
        candidates = [
            args.get("path"),
            args.get("file"),
            args.get("file_path"),
            args.get("target"),
        ]
        for c in candidates:
            if c and isinstance(c, str):
                return c
        return None

    @staticmethod
    def _extract_mkdirs(command: str) -> List[str]:
        """从 bash 命令中提取 mkdir 创建的目录"""
        dirs = []
        # 匹配 mkdir -p /path 或 mkdir /path
        patterns = [
            r"mkdir\s+-p\s+['\"]?([^;'\"\s]+)['\"]?",
            r"mkdir\s+['\"]?([^;'\"\s-]+)['\"]?",
        ]
        for pat in patterns:
            for match in re.finditer(pat, command):
                path = match.group(1)
                if path:
                    dirs.append(path)
        return dirs

    @staticmethod
    def _extract_file_ops_from_bash(command: str) -> List[tuple]:
        """从 bash 命令中提取文件操作（简化版）"""
        ops = []
        # cat -> read
        for match in re.finditer(r"cat\s+['\"]?([^;'\"\s|>]+)['\"]?", command):
            ops.append(("read", match.group(1)))
        # echo ... > file -> write
        for match in re.finditer(r"echo\s+.*?>\s*['\"]?([^;'\"\s]+)['\"]?", command):
            ops.append(("write", match.group(1)))
        return ops

    @staticmethod
    def _preview_args(args: Optional[Dict[str, Any]], max_len: int = 80) -> str:
        """生成 tool_args 的简短预览"""
        if not args:
            return ""
        try:
            import json
            text = json.dumps(args, ensure_ascii=False)
            return text[:max_len] + ("..." if len(text) > max_len else "")
        except Exception:
            return str(args)[:max_len]
