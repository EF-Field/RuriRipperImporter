"""Weapon tab composition, using the same state/description path as Character.

Host projections register their rig/datablock controls; draw never imports or
resolves weapons. Only navigation is new, all feature state remains unchanged.
"""
from ...Kernel import extensions, host as host_port
from ...Kernel.app import state as app_state

HOLDS_PROCESS_STATE = True
STATE = 'ruri_endfield_weapon_tab'
PANES = (
    # Explicit numeric values preserve old .blend pane selections (0/1/2).
    ('catalog', '武器资源', '独立扫描和导入武器，自动加载材质与贴图', 3),
    ('states', '武器状态', '手动导入普通／满潜模型与两种基质装饰，自由组合', 4),
    ('mount', '武器挂载', '角色武器、挂点与武器动作', 0),
    ('effects', '攻击特效 · 首阶段', '攻击特效资源与静态模板预览', 1),
    ('glow', '材质光效', '原生自发光、视差流光与手动叠加；不含满潜逻辑', 2),
)
SCHEMA = app_state.Schema('EndfieldWeaponTab', 'Weapon tab navigation only.', (
    app_state.Field('pane', app_state.ENUM, 'catalog', 'Weapon', items=PANES, remembered=True),
))
SECTIONS = extensions.point('endfield.weapon.sections', 'Host-owned bodies of the Weapon panes.')


def register_section(key, draw):
    if key not in {one[0] for one in PANES}:
        raise ValueError('Unknown weapon pane: ' + key)
    SECTIONS.add(draw, key=key)


def drop_section(key):
    SECTIONS.discard(key)


def draw_tab(layout, context):
    state = host_port.current().panel_state(context, STATE)
    body = layout.box()
    # Like Character: compact dropdown within the tab, not another button row.
    body.prop(state, 'pane', text='')
    if state.pane == 'catalog':
        from . import weapon_catalog
        weapon_catalog.draw(body, context)
        return
    draw = SECTIONS.get(state.pane)
    if draw is None:
        body.label(text='此应用尚未提供该武器面板', icon='INFO')
        return
    body.native(draw)


def register():
    from . import weapon_catalog
    weapon_catalog.register()
    host_port.current().register_state(STATE, SCHEMA, app_state.Handlers(__name__))


def unregister():
    from . import weapon_catalog
    weapon_catalog.unregister()
    host_port.current().unregister_state(STATE)
    SECTIONS.clear()
