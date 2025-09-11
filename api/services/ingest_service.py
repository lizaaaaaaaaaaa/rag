from __future__ import annotations
import importlib
from typing import Callable

_CANDIDATES = [
    "rag.ingested_text",   # ← あなたの構成に追加
    "ingested_text",
    "api.ingested_text",
    "app.ingested_text",
    "backend.ingested_text",
]

def _resolve_ingest_func() -> Callable[[str], object]:
    last_error = None
    for mod_name in _CANDIDATES:
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, "ingest_pdf_to_vectorstore", None)
            if callable(fn):
                return fn
        except Exception as e:
            last_error = e
    raise ModuleNotFoundError(
        "ingest_pdf_to_vectorstore が見つかりません。候補: "
        + ", ".join(_CANDIDATES)
        + (f" / last_error={last_error}" if last_error else "")
    )

def ingest_pdf_to_vectorstore_entry(pdf_path: str):
    return _resolve_ingest_func()(pdf_path)
