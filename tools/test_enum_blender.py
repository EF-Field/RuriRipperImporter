"""Native Blender dynamic-enum stress test; factory-startup/background only."""
import ast
import gc
from pathlib import Path
from types import SimpleNamespace

import bpy

assert bpy.app.background
source = Path(__file__).resolve().parents[1] / 'Host/Blender/rna.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
names = {'_enum_items', '_enum_history', '_cache_enum_items', '_enum_callback'}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
         or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
namespace = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)


def generated(_state, _context):
    return [('dialogue', ''.join(('Dia', 'logue')), ''.join(('The cabmap\'s ', 'dialogue assets'))),
            ('emotion', ''.join(('Emo', 'tions')), ''.join(('The cabmap\'s ', 'emotion assets')))]


callback = namespace['_enum_callback'](SimpleNamespace(name='EnumLifetimeFixture'), SimpleNamespace(key='section'), generated)


class EnumLifetimeFixture(bpy.types.PropertyGroup):
    section: bpy.props.EnumProperty(items=callback)


bpy.utils.register_class(EnumLifetimeFixture)
bpy.types.Scene.enum_lifetime_fixture = bpy.props.PointerProperty(type=EnumLifetimeFixture)
state = bpy.context.scene.enum_lifetime_fixture
state.section = 'emotion'
first = callback(state, bpy.context)
for i in range(2000):
    current = callback(state, bpy.context)
    assert current is first
    assert current[0][1] is first[0][1]
    assert state.section == 'emotion'
    if i % 200 == 0:
        gc.collect()
assert first[0][1] == 'Dialogue' and first[0][2] == "The cabmap's dialogue assets"
del bpy.types.Scene.enum_lifetime_fixture
bpy.utils.unregister_class(EnumLifetimeFixture)
print('BLENDER_ENUM_LIFETIME_STRESS_PASS iterations=2000')
