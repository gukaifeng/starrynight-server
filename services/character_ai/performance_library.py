"""Semantic metadata only; no mesh, bone paths or sampled source curves.

New avatar groups are data, never client/server enum branches. The deployed
catalog is generated from installed capabilities and authored option.ai hints.
"""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def _catalogue():
    path=Path(__file__).with_name('performance_catalog.json')
    return json.loads(path.read_text())['characters'] if path.exists() else {}

def catalogue(character,fallback):
    return _catalogue().get(character,fallback)
