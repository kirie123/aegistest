"""数据集导出器 —— 输出为训练框架可用的格式"""

import json
from pathlib import Path
from typing import List, Dict, Any


class DatasetExporter:
    """
    将处理后的对话数据导出为各种训练格式
    """

    @staticmethod
    def export_json(conversations: List[Dict[str, Any]], output_path: str) -> str:
        """导出为标准 JSON"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(conversations, f, ensure_ascii=False, indent=2)
        return output_path

    @staticmethod
    def export_jsonl(conversations: List[Dict[str, Any]], output_path: str) -> str:
        """导出为 JSONL（每行一个 conversation）"""
        with open(output_path, "w", encoding="utf-8") as f:
            for conv in conversations:
                f.write(json.dumps(conv, ensure_ascii=False) + "\n")
        return output_path

    @staticmethod
    def export_dpo_pairs(
        pairs: List[Dict[str, Any]],
        output_path: str,
        format: str = "json",
    ) -> str:
        """
        导出 DPO preference pairs

        pairs 格式：
        [
            {
                "prompt": [{"role": "user", "content": "..."}],
                "chosen": [{"role": "assistant", "content": "..."}],
                "rejected": [{"role": "assistant", "content": "..."}],
            }
        ]
        """
        if format == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(pairs, f, ensure_ascii=False, indent=2)
        elif format == "jsonl":
            with open(output_path, "w", encoding="utf-8") as f:
                for pair in pairs:
                    f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        return output_path

    @staticmethod
    def export_parquet(
        data: List[Dict[str, Any]],
        output_path: str,
    ) -> str:
        """
        导出为 Parquet（用于 RL 训练）

        需要 pyarrow，如果未安装会抛出 ImportError
        """
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pylist(data)
            pq.write_table(table, output_path)
            return output_path
        except ImportError:
            raise ImportError(
                "export_parquet requires pyarrow. Install: pip install pyarrow"
            )

    @staticmethod
    def export_messages_for_api(
        session_file: str,
        output_path: str,
    ) -> str:
        """导出为可直接发送给 LLM API 的 messages 格式"""
        from ..session.session_loader import SessionLoader

        loader = SessionLoader()
        chain = loader.load_session(session_file)

        api_messages = []
        for entry in chain:
            role = entry.get("type")
            if role in ("system", "user", "assistant"):
                api_messages.append({
                    "role": role,
                    "content": str(entry.get("content", "")),
                })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(api_messages, f, ensure_ascii=False, indent=2)

        return output_path

    @staticmethod
    def split_train_val(
        conversations: List[Dict[str, Any]],
        train_path: str,
        val_path: str,
        val_ratio: float = 0.1,
        seed: int = 42,
    ) -> tuple[str, str]:
        """随机划分为训练集和验证集"""
        import random

        random.seed(seed)
        shuffled = conversations[:]
        random.shuffle(shuffled)

        val_size = max(1, int(len(shuffled) * val_ratio))
        val_set = shuffled[:val_size]
        train_set = shuffled[val_size:]

        DatasetExporter.export_json(train_set, train_path)
        DatasetExporter.export_json(val_set, val_path)

        return train_path, val_path
