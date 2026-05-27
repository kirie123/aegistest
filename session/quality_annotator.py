"""质量标注模块 —— 为 Session entry 附加质量信号"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class JudgeResult(str, Enum):
    """判定结果枚举"""
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    NOT_ATTEMPTED = "not_attempted"


class FeedbackType(str, Enum):
    """反馈类型枚举"""
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    CORRECTION = "correction"
    EDIT = "edit"


@dataclass
class QualityAnnotation:
    """质量标注数据，将被序列化为 JSONL 的 quality_annotation entry"""
    entry_uuid: str = ""           # 指向被标注的消息 uuid
    judge_result: Optional[str] = None
    judge_score: float = 0.0       # 0.0 - 1.0
    feedback_type: Optional[str] = None
    correction: str = ""           # 用户修正内容
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_uuid": self.entry_uuid,
            "judge_result": self.judge_result,
            "judge_score": self.judge_score,
            "feedback_type": self.feedback_type,
            "correction": self.correction,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QualityAnnotation":
        return cls(
            entry_uuid=data.get("entry_uuid", ""),
            judge_result=data.get("judge_result"),
            judge_score=data.get("judge_score", 0.0),
            feedback_type=data.get("feedback_type"),
            correction=data.get("correction", ""),
            metadata=data.get("metadata", {}),
        )


class QualityAnnotator:
    """
    质量标注器 —— 辅助生成 QualityAnnotation 并写入 SessionStorage
    """

    @staticmethod
    def from_test_result(
        entry_uuid: str,
        success: bool,
        judge_score: float = 1.0,
        failure_category: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> QualityAnnotation:
        """从 AegisTest 执行结果生成质量标注"""
        return QualityAnnotation(
            entry_uuid=entry_uuid,
            judge_result=JudgeResult.CORRECT if success else JudgeResult.INCORRECT,
            judge_score=judge_score if success else 0.0,
            feedback_type=FeedbackType.THUMBS_UP if success else FeedbackType.THUMBS_DOWN,
            metadata={
                "failure_category": failure_category,
                "failure_reason": failure_reason,
            },
        )

    @staticmethod
    def from_user_feedback(
        entry_uuid: str,
        feedback_type: FeedbackType,
        correction: str = "",
    ) -> QualityAnnotation:
        """从用户显式反馈生成质量标注"""
        return QualityAnnotation(
            entry_uuid=entry_uuid,
            feedback_type=feedback_type.value,
            correction=correction,
        )
