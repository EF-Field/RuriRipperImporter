"""Host-side numeric and mount-matrix guards. Equipment planning is private."""
import json
import math


def slot_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or value < 0:
        raise ValueError('槽位编号无效')
    return int(value)


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
