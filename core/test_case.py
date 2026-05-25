"""测试用例和测试集定义"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
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
class TestCase:
    """单个测试用例"""
    id: str
    input: str
    expected_output_contains: List[str] = field(default_factory=list)
    expected_behavior: List[str] = field(default_factory=list)
    expected_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    expected_not_contains: List[str] = field(default_factory=list)
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
    def fingerprint(self) -> str:
        content = f"{self.id}:{self.input}:{self.version}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "input": self.input,
            "expected_output_contains": self.expected_output_contains,
            "expected_behavior": self.expected_behavior,
            "expected_tool_calls": self.expected_tool_calls,
            "expected_not_contains": self.expected_not_contains,
            "max_steps": self.max_steps, "timeout": self.timeout,
            "category": self.category.value, "priority": self.priority.value,
            "tags": self.tags, "version": self.version,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestCase":
        data = data.copy()
        data["category"] = TestCategory(data.get("category", "functional"))
        data["priority"] = TestPriority(data.get("priority", "high"))
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
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "TestSuite":
        with open(path) as f:
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
