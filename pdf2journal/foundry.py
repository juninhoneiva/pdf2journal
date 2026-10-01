"""Montagem do JournalEntry no formato de exportação do Foundry VTT (v11–v13)."""
from __future__ import annotations

import json
import secrets
import string
import time

_ALPHABET = string.ascii_letters + string.digits
CORE_VERSION = "13.351"


def random_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(16))


def journal_entry(name: str, pages: list[tuple], source: str) -> dict:
    """``pages`` é uma lista de (título, html) ou (id, título, html)."""
    pages = [p if len(p) == 3 else (random_id(), *p) for p in pages]
    now = int(time.time() * 1000)
    stats = {"coreVersion": CORE_VERSION, "createdTime": now, "modifiedTime": now}
    return {
        "_id": random_id(),
        "name": name,
        "pages": [
            {
                "_id": pid,
                "name": title,
                "type": "text",
                "title": {"show": True, "level": 1},
                "text": {"content": content, "format": 1},
                "sort": (i + 1) * 100000,
                "ownership": {"default": -1},
                "flags": {},
                "_stats": dict(stats),
            }
            for i, (pid, title, content) in enumerate(pages)
        ],
        "folder": None,
        "sort": 0,
        "ownership": {"default": 0},
        "flags": {"pdf2journal": {"source": source}},
        "_stats": stats,
    }


def macro_script(entry: dict) -> str:
    """Script para colar numa macro do tipo *Script* e criar o Journal direto."""
    data = {k: v for k, v in entry.items() if k not in ("_id", "_stats")}
    payload = json.dumps(data, ensure_ascii=False)
    return (
        "// Gerado pelo pdf2journal. Cole numa macro do tipo Script e execute como GM.\n"
        f"const data = {payload};\n"
        "const entry = await JournalEntry.create(data);\n"
        "entry?.sheet.render(true);\n"
    )
