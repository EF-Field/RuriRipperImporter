"""Offline, frontend-only display names. Never rewrite resource identities.

The adjacent snapshot records its provenance. Weapon keys are MODEL prefab
stems, not item IDs: e.g. funnel_0008 and funnel_0010 deliberately cross over.
Unknown resources keep their original label; no substring or numeric guessing.
"""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _names():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def _stem(value):
    leaf = str(value or '').strip().replace('\\', '/').rsplit('/', 1)[-1].lower()
    return leaf.removesuffix('.prefab')


def character_label(key, original=''):
    """A known full character ID or exact bare token, including model families."""
    stem = _stem(key)
    for suffix in ('_postmodel', '_uimodel'):
        stem = stem.removesuffix(suffix)
    names = _names()['characters']
    name = names.get(stem)
    if name is None and not stem.startswith(('chr_', 'npc_')):
        matches = {label for identity, label in names.items()
                   if identity.split('_', 2)[-1] == stem}
        name = next(iter(matches)) if len(matches) == 1 else None
    return name or original or str(key or '')


def weapon_label(asset):
    """Keep the technical stem visible/searchable beside the Chinese name."""
    name = _names()['weapons'].get(_stem(asset))
    return '%s · %s' % (name, _stem(asset)) if name else str(asset or '')
