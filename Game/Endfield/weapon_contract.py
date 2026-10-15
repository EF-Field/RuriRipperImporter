"""Host-free rules for explicit equipment choices and attachment dependencies.

No game resource parsing, model-name guesses, default loadout or implicit anchor.
"""
import json
import math


def selections(value=''):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('装备选择包含重复槽位')
            result[key] = item
        return result
    if not value:
        return {}
    if not isinstance(value, str) or len(value) > 32768:
        raise ValueError('装备选择记录无效')
    data = json.loads(value, object_pairs_hook=pairs)
    if not isinstance(data, dict):
        raise ValueError('装备选择应为槽位到资源的映射')
    for key, seed in data.items():
        if (not key.isascii() or not key.isdecimal() or str(int(key)) != key
                or int(key) > 2147483647 or not isinstance(seed, str) or not seed.strip()):
            raise ValueError('装备选择的槽位或资源无效')
    return data


def selection_json(choices):
    encoded = json.dumps(choices, ensure_ascii=False, sort_keys=True)
    selections(encoded)
    return encoded


def slot_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or value < 0:
        raise ValueError('槽位编号无效')
    return int(value)


def attachment_order(rows, selected):
    """Parents before children, retaining hidden rows. No scene mutation happens here."""
    mode = selected['mode']
    indexed = {}
    for row in rows:
        if row['mode'] != mode:
            continue
        slot = slot_number(row['slot'])
        if slot in indexed:
            raise ValueError('角色配置包含重复槽位')
        indexed[slot] = row
    target = slot_number(selected['slot'])
    if target not in indexed:
        raise ValueError('所选槽位已不在当前角色配置中')
    result, visiting, visited = [], set(), set()

    def visit(slot):
        if slot in visiting:
            raise ValueError('武器挂接依赖存在循环')
        if slot in visited:
            return
        if len(visiting) >= 128:
            raise ValueError('武器挂接依赖过深')
        row = indexed.get(slot)
        if row is None:
            raise ValueError('缺少父武器槽：%d' % slot)
        if row['status'] not in ('ready', 'cross_weapon_mount') or not row['seed']:
            raise ValueError('槽 %d 尚未解析：%s' % (slot, row['status']))
        scale = float(row['scale'])
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('武器缩放无效')
        visiting.add(slot)
        if row.get('mount_kind') == 'weapon' or row['status'] == 'cross_weapon_mount':
            if 'target_slot' not in row or 'weapon_mount' not in row:
                raise ValueError('后端未提供完整跨武器关系，请使用匹配版本后端')
            visit(slot_number(row['target_slot']))
        elif row.get('mount_kind', 'character') != 'character' or not row['bone']:
            raise ValueError('角色挂点未解析')
        visiting.remove(slot)
        visited.add(slot)
        result.append(row)
    visit(target)
    return result


def mount_ancestry(rows, key):
    """A mount key must identify one authored component entry, including hidden nodes."""
    key = slot_number(key)
    matches = [r for r in rows if slot_number(r['key']) == key]
    if len(matches) != 1:
        raise ValueError('武器挂点 %d 缺失或存在多个配置组件，请检查来源' % key)
    row = matches[0]
    if row['status'] != 'ready' or row['basis'] != 'blender':
        raise ValueError('武器挂点未解析或坐标基不匹配')
    chain = json.loads(row['ancestry'])
    if not isinstance(chain, list) or not chain or len(chain) > 128:
        raise ValueError('武器挂点缺少完整变换链')
    seen = set()
    for node in chain:
        path, matrix = node.get('path'), node.get('local')
        if not isinstance(path, str) or path in seen:
            raise ValueError('武器挂点路径重复或无效')
        if seen and path.rpartition('/')[0] != chain[len(seen) - 1]['path']:
            raise ValueError('武器挂点父链不连续')
        if not isinstance(matrix, list) or len(matrix) != 16 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in matrix):
            raise ValueError('武器挂点矩阵无效')
        if any(abs(matrix[12 + i] - (1 if i == 3 else 0)) > 1e-8 for i in range(4)):
            raise ValueError('武器挂点矩阵不是仿射变换')
        seen.add(path)
    if chain[0]['path'] != '' or chain[-1]['path'] != row['path']:
        raise ValueError('武器挂点根路径或目标路径不一致')
    return chain
