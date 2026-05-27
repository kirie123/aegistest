"""语义索引模块 —— 轻量级纯 Python 实现"""

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import Counter


class SemanticIndex:
    """
    轻量级语义索引（纯 Python，零外部依赖）

    MVP 版本使用字符 n-gram + TF-IDF + cosine similarity。
    生产环境可替换为 faiss / chromadb。
    """

    def __init__(self, storage_dir: str = "./index"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "index.json"
        self.documents: Dict[str, Dict[str, Any]] = {}
        self._load()

    def add(self, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加文档到索引"""
        vector = self._vectorize(text)
        self.documents[doc_id] = {
            "text": text,
            "vector": vector,
            "metadata": metadata or {},
        }
        self._save()

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """语义搜索 + 结构化过滤"""
        query_vec = self._vectorize(query)

        scored = []
        for doc_id, doc in self.documents.items():
            if filters and not self._match_filters(doc.get("metadata", {}), filters):
                continue
            score = self._cosine_similarity(query_vec, doc["vector"])
            scored.append((score, doc_id, doc))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, doc_id, doc in scored[:top_k]:
            results.append({
                "id": doc_id,
                "score": score,
                "text": doc["text"],
                "metadata": doc["metadata"],
            })
        return results

    def delete(self, doc_id: str) -> bool:
        """从索引中删除文档"""
        if doc_id in self.documents:
            del self.documents[doc_id]
            self._save()
            return True
        return False

    def clear(self) -> None:
        """清空索引"""
        self.documents.clear()
        self._save()

    def _vectorize(self, text: str) -> List[float]:
        """极简向量化：字符 3-gram 频率直方图"""
        n = 3
        text = str(text).lower()
        grams = [text[i : i + n] for i in range(len(text) - n + 1)]
        counts = Counter(grams)

        # 取最常见的 200 个 n-gram 作为维度
        top = counts.most_common(200)
        vec = [0.0] * 200
        for i, (_, count) in enumerate(top):
            vec[i] = float(count)

        # L2 归一化
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        # 两个向量已经 L2 归一化，点积即 cosine similarity
        return sum(x * y for x, y in zip(a, b))

    def _match_filters(self, metadata: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """检查 metadata 是否匹配 filters"""
        for key, expected in filters.items():
            actual = metadata.get(key)
            if callable(expected):
                if not expected(actual):
                    return False
            elif actual != expected:
                return False
        return True

    def _load(self) -> None:
        """从磁盘加载索引"""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.documents = data.get("documents", {})
            except (json.JSONDecodeError, IOError):
                self.documents = {}

    def _save(self) -> None:
        """保存索引到磁盘"""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump({"documents": self.documents}, f, ensure_ascii=False)
