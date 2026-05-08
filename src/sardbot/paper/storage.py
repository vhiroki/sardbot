"""Pluggable storage backends for paper trading state.

Two implementations:
- LocalStorage: writes to disk under a base directory. For development.
- GCSStorage:   writes to Google Cloud Storage. For production (Cloud Run Job).

The Storage interface is intentionally narrow: read/write a few JSON blobs and
parquet files. We don't need transactions because Cloud Run Job execution is
serialized via Cloud Scheduler (one invocation per cron tick).
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd


class Storage(ABC):
    @abstractmethod
    def read_text(self, path: str) -> str | None: ...

    @abstractmethod
    def write_text(self, path: str, content: str) -> None: ...

    @abstractmethod
    def read_parquet(self, path: str) -> pd.DataFrame | None: ...

    @abstractmethod
    def write_parquet(self, path: str, df: pd.DataFrame) -> None: ...

    def append_parquet(self, path: str, new_rows: pd.DataFrame) -> None:
        existing = self.read_parquet(path)
        combined = pd.concat([existing, new_rows], ignore_index=True) if existing is not None else new_rows
        self.write_parquet(path, combined)


class LocalStorage(Storage):
    def __init__(self, base_dir: Path | str = "data/paper"):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def _full(self, path: str) -> Path:
        return self.base / path

    def read_text(self, path: str) -> str | None:
        p = self._full(path)
        return p.read_text() if p.exists() else None

    def write_text(self, path: str, content: str) -> None:
        p = self._full(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def read_parquet(self, path: str) -> pd.DataFrame | None:
        p = self._full(path)
        return pd.read_parquet(p) if p.exists() else None

    def write_parquet(self, path: str, df: pd.DataFrame) -> None:
        p = self._full(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)


class GCSStorage(Storage):
    """Google Cloud Storage backend. Lazy-imports google-cloud-storage so it's
    only required when actually used (not in tests / local dev).
    """

    def __init__(self, bucket_name: str, prefix: str = ""):
        from google.cloud import storage as gcs  # noqa: F401 - lazy import
        self._gcs_module = gcs
        self.client = gcs.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""

    def _key(self, path: str) -> str:
        return self.prefix + path.lstrip("/")

    def read_text(self, path: str) -> str | None:
        blob = self.bucket.blob(self._key(path))
        if not blob.exists():
            return None
        return blob.download_as_text()

    def write_text(self, path: str, content: str) -> None:
        blob = self.bucket.blob(self._key(path))
        blob.upload_from_string(content, content_type="application/json")

    def read_parquet(self, path: str) -> pd.DataFrame | None:
        blob = self.bucket.blob(self._key(path))
        if not blob.exists():
            return None
        buf = io.BytesIO(blob.download_as_bytes())
        return pd.read_parquet(buf)

    def write_parquet(self, path: str, df: pd.DataFrame) -> None:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        blob = self.bucket.blob(self._key(path))
        blob.upload_from_string(buf.getvalue(), content_type="application/octet-stream")


def make_storage_from_env() -> Storage:
    """Pick backend based on env. SARDBOT_STORAGE=gcs:bucket-name or local:path."""
    import os
    spec = os.environ.get("SARDBOT_STORAGE", "local:data/paper")
    kind, _, target = spec.partition(":")
    if kind == "gcs":
        bucket, _, prefix = target.partition("/")
        return GCSStorage(bucket_name=bucket, prefix=prefix)
    if kind == "local":
        return LocalStorage(base_dir=target or "data/paper")
    raise ValueError(f"unknown storage spec: {spec!r}")
