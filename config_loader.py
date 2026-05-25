"""配置加载器 —— 从 YAML/JSON 文件加载测试套件"""

import json
from pathlib import Path
from typing import Dict, Any, List, Union

from .core.test_case import TestCase, TestSuite, TestCategory, TestPriority, SafetyCheck, TaskInput


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required to load YAML config files. "
            "Install it with: pip install pyyaml"
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config(path: str) -> dict:
    """加载配置文件（自动识别 YAML/JSON）"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _load_yaml(p)
    elif suffix == ".json":
        return _load_json(p)
    else:
        raise ValueError(f"Unsupported config format: {suffix}. Use .yaml, .yml, or .json")


def _parse_task_input(data: Union[str, dict]) -> Union[str, TaskInput]:
    """解析输入（支持纯字符串或 TaskInput 对象）"""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        files = [Path(f) for f in data.get("files", [])]
        return TaskInput(
            prompt=data.get("prompt", ""),
            files=files,
            context=data.get("context", {}),
        )
    return str(data)


def _parse_safety_check(data: dict) -> SafetyCheck:
    return SafetyCheck(
        name=data.get("name", ""),
        description=data.get("description", ""),
        forbidden_tools=data.get("forbidden_tools", []),
        required_confirmations=data.get("required_confirmations", []),
        forbidden_patterns=data.get("forbidden_patterns", []),
        data_exfiltration_check=data.get("data_exfiltration_check", False),
        max_token_cost=data.get("max_token_cost"),
    )


def _parse_test_case(data: dict) -> TestCase:
    # 解析 input
    raw_input = data.get("input", "")
    parsed_input = _parse_task_input(raw_input) if raw_input else ""

    # 解析 turns
    raw_turns = data.get("turns", [])
    parsed_turns = [_parse_task_input(t) for t in raw_turns] if raw_turns else []

    # 解析路径字段
    working_dir = data.get("working_dir")
    workspace_template = data.get("workspace_template")

    return TestCase(
        id=data["id"],
        input=parsed_input,
        turns=parsed_turns,
        working_dir=Path(working_dir) if working_dir else None,
        workspace_template=Path(workspace_template) if workspace_template else None,
        workspace_cleanup=data.get("workspace_cleanup", "auto"),
        expected_output_contains=data.get("expected_output_contains", []),
        expected_not_contains=data.get("expected_not_contains", []),
        expected_behavior=data.get("expected_behavior", []),
        expected_tool_calls=data.get("expected_tool_calls", []),
        expected_final_state=data.get("expected_final_state", {}),
        code_assertions=data.get("code_assertions", {}),
        safety_checks=[_parse_safety_check(sc) for sc in data.get("safety_checks", [])],
        max_steps=data.get("max_steps", 30),
        timeout=data.get("timeout", 120),
        category=TestCategory(data.get("category", "functional")),
        priority=TestPriority(data.get("priority", "high")),
        tags=data.get("tags", []),
        metadata=data.get("metadata", {}),
    )


def load_suite(path: str) -> TestSuite:
    """从配置文件加载 TestSuite"""
    config = load_config(path)
    suite = TestSuite(
        name=config.get("name", "Untitled Suite"),
        description=config.get("description", ""),
        version=config.get("version", "1.0"),
    )
    for case_data in config.get("cases", []):
        suite.add(_parse_test_case(case_data))
    return suite


def load_agent_spec(config: dict) -> Dict[str, Any]:
    """从配置中读取 Agent 定义

    Returns:
        dict with keys: module, class, kwargs (optional)
    """
    agent_cfg = config.get("agent", {})
    if not agent_cfg:
        return {}
    return {
        "module": agent_cfg.get("module", ""),
        "class": agent_cfg.get("class", ""),
        "kwargs": agent_cfg.get("kwargs", {}),
    }
