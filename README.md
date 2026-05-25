# AegisTest

> **Agent Evaluation & Guarded Inspection System**
>
> 零外部依赖的 LLM Agent 端到端测试框架。

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AegisTest 是一个专为 LLM Agent 设计的测试框架，覆盖**用例定义 → 执行（超时控制）→ 双重评估（字符串匹配 + LLM Judge）→ 安全检测 → 失败分析 → Trace 持久化 → 回归对比 → 多格式报告**的完整评测闭环。

## 特性

- **零第三方依赖** — 纯 Python 标准库实现，开箱即用
- **双重评估模式** — 传统字符串匹配 + LLM-as-a-Judge 语义评判
- **安全检测** — 危险工具、Prompt Injection、数据泄露、敏感信息泄露
- **失败自动分析** — 基于规则自动分类失败根因（prompt / tool / retrieval / model / state）
- **回归测试** — 保存基线、对比版本迭代后的能力退化
- **多格式报告** — HTML（可视化）、JSON（CI 解析）、Markdown（轻量文本）
- **跨平台超时控制** — Windows / Linux / macOS 原生支持

## 快速开始

### 安装

```bash
pip install aegistest
```

或者从源码安装：

```bash
git clone https://github.com/your-org/aegistest.git
cd aegistest
pip install -e .
```

### 3 分钟写一个测试

```python
from aegistest import AegisTest, TestCase, TestSuite, TestCategory, TestPriority
from aegistest.core.agent_interface import AgentInterface, AgentRunResult, AgentStep


# 1. 实现你的 Agent（必须实现 AgentInterface）
class MyAgent(AgentInterface):
    @property
    def name(self) -> str:
        return "my-agent"

    @property
    def version(self) -> str:
        return "0.1.0"

    def run(self, user_input: str, **kwargs) -> AgentRunResult:
        # 这里调用你的真实 Agent
        steps = [
            AgentStep(step_number=1, step_type="thought", content="Thinking..."),
            AgentStep(step_number=2, step_type="response", content=f"Answer: {user_input}"),
        ]
        return AgentRunResult(
            final_output=f"Answer: {user_input}",
            steps=steps,
            total_steps=len(steps),
            total_latency_ms=120.0,
        )

    def run_stream(self, user_input: str, **kwargs):
        result = self.run(user_input, **kwargs)
        for step in result.steps:
            yield step


# 2. 定义测试用例
suite = TestSuite(name="Demo Suite", description="快速开始示例")
suite.add(TestCase(
    id="func_001_hello",
    input="你好",
    expected_output_contains=["Answer"],
    expected_behavior=["友好回应"],
    category=TestCategory.FUNCTIONAL,
    priority=TestPriority.HIGH,
    timeout=60,
))

# 3. 运行测试
agent = MyAgent()
aegis = AegisTest(agent=agent, trace_dir="./traces", report_dir="./reports")
summary = aegis.run_suite(suite)

# 4. 生成 HTML 报告
aegis.generate_report(fmt="html")
```

运行后会在当前目录生成：

```
traces/     # 每条测试的详细 JSON trace
reports/    # HTML / JSON / Markdown 报告
baselines/  # 基线数据（用于回归测试）
```

## 目录结构

```
aegistest/
├── core/
│   ├── aegis.py           # AegisTest 主入口
│   ├── agent_interface.py # Agent 抽象接口（必须实现）
│   ├── executor.py        # 执行器（超时控制、结果封装）
│   └── test_case.py       # TestCase / TestSuite 定义
├── analyzers/
│   └── failure_analyzer.py    # 失败原因自动分类
├── checkers/
│   └── safety_checker.py      # 安全检测（危险工具、Prompt Injection、数据泄露）
├── collectors/
│   └── trace_collector.py     # Trace JSON 记录
├── regression/
│   └── regression_tester.py   # 基线与回归对比
├── reports/
│   └── report_generator.py    # 多格式报告生成（HTML / JSON / Markdown）
└── examples/
    ├── basic_example.py         # 极简入门示例
    ├── advanced_example.py      # 进阶完整示例
    └── suite.yaml               # YAML 配置文件示例
```

## 核心概念

### AgentInterface

你的 Agent 必须实现这个接口，AegisTest 才能驱动它：

```python
class AgentInterface(ABC):
    @abstractmethod
    def run(self, user_input: str, **kwargs) -> AgentRunResult: ...

    @abstractmethod
    def run_stream(self, user_input: str, **kwargs) -> Generator[AgentStep, None, None]: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...
```

### TestCase

```python
TestCase(
    id="func_001_hello",
    input="你好",                          # 给 Agent 的用户输入
    expected_output_contains=["Answer"],   # 输出必须包含的字符串
    expected_not_contains=["error"],       # 输出不能包含的字符串
    expected_behavior=["友好回应"],         # 预期行为（供 LLM Judge 使用）
    expected_tool_calls=[{"tool": "Read"}], # 期望调用的工具
    category=TestCategory.FUNCTIONAL,
    priority=TestPriority.HIGH,
    tags=["basic"],
    timeout=60,
    max_steps=30,
)
```

### 通过配置文件运行

不用写 Python 代码，直接用 YAML/JSON 定义测试套件：

```bash
# 1. 生成示例配置
aegistest init

# 2. 运行（通过 --agent 指定 Agent 类）
aegistest run suite.yaml --agent examples.advanced_example:MockCodingAgent

# 3. 生成报告并保存基线
aegistest run suite.yaml --agent examples.advanced_example:MockCodingAgent \
  --report html json --save-baseline
```

配置文件中也可以定义 Agent：

```yaml
name: "My Suite"
agent:
  module: "my_agent"
  class: "MyAgent"
  kwargs:
    model: "gpt-4"

cases:
  - id: func_001_hello
    input: "你好"
    expected_output_contains: ["你好"]
    category: functional
    priority: high
```

> **注意**：YAML 支持需要安装 `pip install pyyaml`。JSON 配置纯标准库即可。

### LLM-as-a-Judge

接入外部 Judge，让大模型评判语义级别的任务完成度：

```python
from aegistest import AegisTest

aegis = AegisTest(
    agent=agent,
    judge=your_llm_judge_instance,  # 任何实现了 evaluate() 接口的对象
)
```

当 `TestCase` 设置了 `expected_behavior` 且提供了 `judge` 时，AegisTest 会自动调用 LLM Judge；否则回退到字符串匹配。

### 报告格式切换

```python
# HTML 可视化报告（默认）
aegis.generate_report(fmt="html")

# JSON 结构化报告（方便 CI/CD 解析）
aegis.generate_report(fmt="json")

# Markdown 轻量报告
aegis.generate_report(fmt="markdown")
```

### 回归测试

```python
# 保存当前结果为基线
aegis.save_baseline(prompt_version="1.0", model_version="gpt-4")

# 新版本运行后，对比基线检测退化
regression = aegis.check_regression(baseline_run_id="abc123")
print(regression["regressions"])  # 退化的用例
print(regression["improvements"]) # 进步的用例
```

## 完整示例

参见 [`examples/basic_example.py`](examples/basic_example.py)、[`examples/advanced_example.py`](examples/advanced_example.py) 和 [`examples/suite.yaml`](examples/suite.yaml)。

运行完整示例：

```bash
python examples/basic_example.py
python examples/advanced_example.py
```

## 设计哲学

1. **零依赖** — 不绑定任何 LLM SDK、Web 框架或数据库，降低接入成本
2. **接口优先** — 通过 `AgentInterface` 解耦框架与具体 Agent 实现
3. **可扩展** — Judge、报告格式、安全检查规则均可插拔替换
4. **生产就绪** — 超时控制、Trace 持久化、回归对比，覆盖从开发到 CI 的全链路

## License

MIT
