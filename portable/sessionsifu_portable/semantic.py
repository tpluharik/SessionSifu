"""Optional, strictly offline semantic retrieval for Privacy Recall.

The model is never downloaded by SessionSifu.  Users explicitly select an
already installed SentenceTransformers directory; loading is forced into
offline mode and bounded input/output sizes keep search predictable.
"""

from __future__ import annotations

import math
import os
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import Iterable, Mapping

MAX_DOCUMENTS = 2048
MAX_DOCUMENT_CHARS = 4096
MAX_VECTOR_DIMENSIONS = 4096
MAX_CACHED_VECTORS = 4096


class OfflineSemanticSearch:
    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(
            model_path or os.environ.get("SESSIONSIFU_SEMANTIC_MODEL", "")
        ).expanduser()
        self._model = None
        self._error = ""
        self._document_vectors: OrderedDict[object, tuple[bytes, list[float]]] = OrderedDict()

    def _validated_model_path(self) -> Path:
        path = self.model_path
        if not str(path) or str(path) == ".":
            raise RuntimeError("no local semantic model is configured")
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError("the configured semantic model is not a regular local directory")
        resolved = path.resolve(strict=True)
        if not any((resolved / name).is_file() for name in ("config.json", "modules.json")):
            raise RuntimeError("the local semantic model has no recognized configuration")
        return resolved

    def _load(self):
        if self._model is not None:
            return self._model
        path = self._validated_model_path()
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers is not installed; install the optional semantic component"
            ) from error
        try:
            self._model = SentenceTransformer(
                str(path), local_files_only=True, trust_remote_code=False
            )
        except TypeError:
            # Older compatible releases do not expose trust_remote_code.  The
            # local_files_only boundary remains mandatory.
            self._model = SentenceTransformer(str(path), local_files_only=True)
        return self._model

    @staticmethod
    def _vector(value: object) -> list[float]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, (list, tuple)):
            raise RuntimeError("semantic model returned an invalid vector")
        vector = [float(item) for item in value[:MAX_VECTOR_DIMENSIONS]]
        if not vector or any(not math.isfinite(item) for item in vector):
            raise RuntimeError("semantic model returned an invalid vector")
        return vector

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dimensions = min(len(left), len(right), MAX_VECTOR_DIMENSIONS)
        dot = sum(left[index] * right[index] for index in range(dimensions))
        left_norm = math.sqrt(sum(left[index] ** 2 for index in range(dimensions)))
        right_norm = math.sqrt(sum(right[index] ** 2 for index in range(dimensions)))
        if not left_norm or not right_norm:
            return 0.0
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))

    def rank(self, query: str, documents: Iterable[str] | Mapping[object, str]) -> dict[object, float]:
        query = str(query).strip()[:512]
        if isinstance(documents, Mapping):
            items = list(documents.items())[:MAX_DOCUMENTS]
        else:
            items = list(enumerate(documents))[:MAX_DOCUMENTS]
        keys = [key for key, _value in items]
        values = [str(value)[:MAX_DOCUMENT_CHARS] for _key, value in items]
        if not query or not values:
            return {}
        try:
            model = self._load()
            missing: list[tuple[object, bytes, str]] = []
            for key, value in zip(keys, values):
                digest = hashlib.blake2b(value.encode("utf-8"), digest_size=16).digest()
                cached = self._document_vectors.get(key)
                if cached and cached[0] == digest:
                    self._document_vectors.move_to_end(key)
                else:
                    missing.append((key, digest, value))
            if missing:
                encoded_documents = model.encode(
                    [value for _key, _digest, value in missing],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=32,
                )
                for (key, digest, _value), vector in zip(missing, encoded_documents):
                    self._document_vectors[key] = (digest, self._vector(vector))
                    self._document_vectors.move_to_end(key)
                while len(self._document_vectors) > MAX_CACHED_VECTORS:
                    self._document_vectors.popitem(last=False)
            encoded_query = model.encode(
                [query],
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=1,
            )
            query_vector = self._vector(encoded_query[0])
            self._error = ""
            return {
                key: score
                for key in keys
                for cached in [self._document_vectors.get(key)]
                if cached is not None
                for score in [self._cosine(query_vector, cached[1])]
                if score >= 0.22
            }
        except (OSError, RuntimeError, ValueError) as error:
            self._error = str(error)[:512]
            return {}

    def diagnostics(self) -> dict[str, object]:
        configured = bool(str(self.model_path)) and str(self.model_path) != "."
        return {
            "enabled": configured,
            "available": self._model is not None and not self._error,
            "model": str(self.model_path) if configured else "not configured",
            "offline_only": True,
            "cached_documents": len(self._document_vectors),
            "last_error": self._error,
        }

    def clear_cache(self) -> None:
        """Drop document embeddings without unloading the user-selected model."""
        self._document_vectors.clear()
