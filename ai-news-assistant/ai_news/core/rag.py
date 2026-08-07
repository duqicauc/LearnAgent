"""轻量 RAG：TF-IDF 向量化 + 余弦相似度 Top-K 检索（无外部向量库）。

知识点：RAG（检索增强生成）—— 将历史报告要点向量化，
用户追问「上次报告的结论」时检索相关片段注入上下文，使 Agent 具备跨任务记忆能力。
"""
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}|[\u4e00-\u9fff]")


def _tokenize(text: str) -> List[str]:
    """中英文混合分词：英文按词、中文按字/词（简单实现）。"""
    return _TOKEN_RE.findall(text.lower())


class SimpleRAG:
    """TF-IDF 向量检索。"""

    def __init__(self) -> None:
        self.documents: List[Dict[str, Any]] = []
        self._vectors: List[Dict[str, float]] = []
        self._idf: Dict[str, float] = {}

    def index(self, documents: List[Dict[str, str]]) -> None:
        """建立文档索引。documents: [{"id", "text", "meta"}]"""
        self.documents = documents
        if not documents:
            self._idf, self._vectors = {}, []
            return

        # 计算 IDF
        df: Counter = Counter()
        for doc in documents:
            df.update(set(_tokenize(doc["text"])))
        n = len(documents)
        self._idf = {
            token: math.log((n + 1) / (count + 1)) + 1.0
            for token, count in df.items()
        }

        # 计算各文档 TF-IDF 向量
        self._vectors = [self._tfidf(doc["text"]) for doc in documents]

    def _tfidf(self, text: str) -> Dict[str, float]:
        tf = Counter(_tokenize(text))
        return {token: count * self._idf.get(token, 0.0) for token, count in tf.items()}

    @staticmethod
    def _cosine(v1: Dict[str, float], v2: Dict[str, float]) -> float:
        if not v1 or not v2:
            return 0.0
        common = set(v1) & set(v2)
        dot = sum(v1[t] * v2[t] for t in common)
        norm1 = math.sqrt(sum(x * x for x in v1.values()))
        norm2 = math.sqrt(sum(x * x for x in v2.values()))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """检索与 query 最相关的 Top-K 文档。"""
        if not self.documents:
            return []
        qv = self._tfidf(query)
        scored = [
            (self._cosine(qv, vec), doc)
            for vec, doc in zip(self._vectors, self.documents)
        ]
        scored.sort(key=lambda x: -x[0])
        results = [
            {**doc, "score": round(score, 4)}
            for score, doc in scored[:top_k]
            if score > 0
        ]
        return results

    def build_context(self, query: str, top_k: int = 3, max_chars: int = 1500) -> str:
        """把检索结果拼成可注入的上下文文本。"""
        results = self.retrieve(query, top_k)
        if not results:
            return ""
        parts = []
        used = 0
        for r in results:
            summary = (r.get("meta") or {}).get("summary", "")
            title = (r.get("meta") or {}).get("title", "")
            chunk = f"【历史要点】{title or '未命名'}: {summary}"
            if used + len(chunk) > max_chars:
                break
            parts.append(chunk)
            used += len(chunk)
        return "\n".join(parts)
