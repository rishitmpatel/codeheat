from __future__ import annotations

import json


def dumps(rep: dict, indent: int | None = 2) -> str:
    return json.dumps(rep, indent=indent, ensure_ascii=False)
