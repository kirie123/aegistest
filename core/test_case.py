"""测试用例和测试集定义"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Union
from enum import Enum
import json
from pathlib import Path
import hashlib


class TestPriority(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestCategory(Enum):
    FUNCTIONAL = "functional"
    TOOL_CALLING = "tool_calling"
    MULTITURN = "multiturn"
    SAFETY = "safety"
    REGRESSION = "regression"
    LONG_HORIZON = "long_horizon"
    ERROR_RECOVERY = "error_recovery"
    CODE_GENERATION = "code_generation"
    CODE_REFACTOR = "code_refactor"


@dataclass
class SafetyCheck:
    """安全检查规则"""
    name: str
    description: str
    forbidden_tools: List[str] = field(default_factory=list)
    required_confirmations: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    data_exfiltration_check: bool = False
    max_token_cost: Optional[int] = None


@dataclass
class TaskInput:
    """任务输入 —— 支持文字 + 文件 + 上下文"""
    prompt: str = ""
    files: List[Path] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [self.prompt] if self.prompt else []
        if self.files:
            parts.append(f"[Attached files: {', '.join(str(f) for f in self.files)}]")
        return "\n".join(parts)


@dataclass
class TestCase:
    """单个测试用例"""
    id: str
    input: Union[str, TaskInput] = ""

    # 多轮会话模式（与 input 互斥，优先 turns）
    turns: List[Union[str, TaskInput]] = field(default_factory=list)

    # 工作目录与沙箱
    working_dir: Optional[Path] = None
    workspace_template: Optional[Path] = None
    workspace_cleanup: str = "auto"  # auto / keep / always_reset

    # 输出断言
    expected_output_contains: List[str] = field(default_factory=list)
    expected_not_contains: List[str] = field(default_factory=list)
    expected_behavior: List[str] = field(default_factory=list)
    expected_tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # 最终状态断言（长程任务 / 代码仓库）
    expected_final_state: Dict[str, Any] = field(default_factory=dict)
    # 示例：
    # {
    #   "files": {"created": ["src/auth.py"], "modified": ["src/app.py"]},
    #   "git": {"clean": false, "commit_count_delta": 1},
    #   "tests_passed": true
    # }

    # 代码级断言
    code_assertions: Dict[str, Any] = field(default_factory=dict)
    # 示例：
    # {
    #   "syntax_valid": true,
    #   "test_command": "pytest tests/",
    #   "test_should_pass": true,
    #   "linter": "ruff"
    # }

    safety_checks: List[SafetyCheck] = field(default_factory=list)
    max_steps: int = 30
    timeout: int = 120
    category: TestCategory = TestCategory.FUNCTIONAL
    priority: TestPriority = TestPriority.HIGH
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"
    created_at: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            from datetime import datetime
            self.created_at = datetime.now().isoformat()

    @property
    def is_multiturn(self) -> bool:
        return len(self.turns) > 0

    @property
    def first_input(self) -> Union[str, TaskInput]:
        """获取第一个输入（兼容单轮和多轮）"""
        if self.turns:
            return self.turns[0]
        return self.input

    @property
    def all_inputs(self) -> List[Union[str, TaskInput]]:
        """获取所有输入轮次"""
        if self.turns:
            return self.turns
        return [self.input] if self.input else []

    @property
    def fingerprint(self) -> str:
        content = f"{self.id}:{self.input}:{self.version}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "input": str(self.input),
            "turns": [str(t) for t in self.turns],
            "working_dir": str(self.working_dir) if self.working_dir else None,
            "expected_output_contains": self.expected_output_contains,
            "expected_behavior": self.expected_behavior,
            "expected_tool_calls": self.expected_tool_calls,
            "expected_not_contains": self.expected_not_contains,
            "expected_final_state": self.expected_final_state,
            "code_assertions": self.code_assertions,
            "max_steps": self.max_steps,
            "timeout": self.timeout,
            "category": self.category.value,
            "priority": self.priority.value,
            "tags": self.tags,
            "version": self.version,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestCase":
        data = data.copy()
        data["category"] = TestCategory(data.get("category", "functional"))
        data["priority"] = TestPriority(data.get("priority", "high"))
        # 简单处理：如果 input 不是 str，保持原样（外部 loader 处理 TaskInput）
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TestSuite:
    """测试集"""
    name: str
    description: str
    cases: List[TestCase] = field(default_factory=list)
    version: str = "1.0"

    def add(self, case: TestCase):
        self.cases.append(case)

    def save(self, path: str):
        data = {"name": self.name, "description": self.description,
                "version": self.version, "cases": [c.to_dict() for c in self.cases]}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "TestSuite":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(name=data["name"], description=data["description"],
                   cases=[TestCase.from_dict(c) for c in data.get("cases", [])],
                   version=data.get("version", "1.0"))

    @property
    def stats(self) -> dict:
        from collections import Counter
        return {"total": len(self.cases),
                "by_category": dict(Counter(c.category.value for c in self.cases)),
                "by_priority": dict(Counter(c.priority.value for c in self.cases))}
