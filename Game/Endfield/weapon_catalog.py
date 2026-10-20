"""Standalone weapon resources in the Character list's shared browsing shape.

The private reader owns exact prefab enumeration, including misc resources.
This module only projects display names and hands row payloads to the ordinary
Load/Reveal commands. Materials and textures use the same build as Character.
"""
from ...Kernel import host as host_port
from ...Kernel.app import browser, cast_panel, command, filtering, schemas
from ...Kernel.app import state as app_state, view as app_view
from ...Kernel.bridge import cabmap_state
from . import datasets

HOLDS_PROCESS_STATE = True
STATE = 'ruri_endfield_weapon_catalog'
SPEC_KEY = 'Endfield:weapon'
BOUND = app_view.Bound(SPEC_KEY)
_TABLE = None
_SOURCE = None

FAMILIES = {
    'sword': '单手剑', 'claym': '双手剑', 'funnel': '施术单元',
    'lance': '长柄武器', 'pistol': '手铳', 'misc': '配饰／技能道具',
}


def state_of(context):
    return host_port.current().panel_state(context, STATE)


def source_of(context):
    bridge = cabmap_state.BRIDGE
    return (bridge, getattr(bridge, '_map', None), browser.state_of(context).current_tab)


def current(context):
    return _TABLE is not None and _SOURCE == source_of(context) and browser.state_of(context).loaded


def rebuild(state):
    with filtering.rebuilding():
        BOUND.open(_TABLE, state)


SCHEMA = app_state.Schema('EndfieldWeaponCatalog', 'Standalone weapon browser.', (),
    include=(schemas.FILTER_STATE, schemas.LOADING_STATE, cast_panel.CAST_STATE))
HANDLERS = cast_panel.handlers(BOUND, __name__, rebuild)
FILTER_SPEC = filtering.register_spec(filtering.FilterSpec(
    key=SPEC_KEY, fields=BOUND.fields, state_for=state_of,
    apply=lambda context: rebuild(state_of(context))))


def project(rows):
    """Display projection only. Ambiguous rows retain provenance, but no load seed."""
    return [[row['seed'], row.get('label', row['asset']), row['asset'],
             FAMILIES.get(row['family'], row['family']), row['family'], row['status'],
             row['seed'] if row['status'] == 'ready' else '',
             '可导入' if row['status'] == 'ready' else '预制体路径存在歧义',
             int(row['routes']), row['basis']]
            for row in rows]


def _loaded(context):
    return browser.state_of(context).loaded and cabmap_state.BRIDGE is not None


def _refresh(context, arguments):
    global _TABLE, _SOURCE
    state = state_of(context)
    # Invalidate before reading: failure must never leave the old install loadable.
    BOUND.open(None, state)
    _TABLE, _SOURCE = None, None
    state.rows.clear()
    state.active_index = -1
    try:
        browser._sync_bridge_to_tab(browser.active_config(browser.state_of(context)))
        rows = datasets._rows(datasets.WEAPON_RESOURCES)
        _TABLE = cabmap_state.BRIDGE.open_host_table(SPEC_KEY,
            ['key|资源路径', 'label|名称', 'asset|资源名', 'kind|类别', 'family|资源分类',
             'status|状态', 'seed|导入来源', 'detail|状态说明', 'routes#|来源数', 'basis|依据'],
            project(rows), [app_view.KEY, app_view.LABEL, 0, app_view.FACET,
                            0, 0, app_view.PAYLOAD, app_view.DETAIL, 0, 0])
        _SOURCE = source_of(context)
        rebuild(state)
        state.status = '扫描到 %d 个武器／道具资源；材质与贴图随模型导入' % len(rows)
    except Exception as exc:
        BOUND.open(None, state)
        _TABLE, _SOURCE = None, None
        state.status = '武器扫描失败，请检查匹配后端：%s' % (str(exc).splitlines() or [type(exc).__name__])[0]
        return {'CANCELLED'}


REFRESH = command.COMMANDS.define('ruri.weapon_resources_refresh', '扫描武器资源', _refresh,
    description='扫描当前索引的武器预制体；独立导入，无需角色或挂点', poll=_loaded)

_COLUMNS = (
    BOUND.column('', label='名称', width=0.72, icon='MESH_DATA'),
    BOUND.column('detail', label='状态', enabled=False),
)


def draw(layout, context, verbs=True, import_options=True):
    state = state_of(context)
    command.draw_progress(layout, state)
    if not current(context):
        layout.operator(REFRESH.id, icon='FILE_REFRESH')
        layout.label(text=state.status if _SOURCE is None and state.status else
                     '打开资源索引后扫描武器；独立导入无需角色', icon='INFO')
        return
    # Same head/search/filter/list/options/verbs as Character, with no face or
    # character-only controls and no second list/filter implementation.
    app_view.draw_head(BOUND, layout, state, REFRESH.id)
    app_view.draw_list(BOUND, layout, state, _COLUMNS, 'weapon_resources', rows=10)
    if state.status:
        layout.label(text=state.status, icon='INFO')
    if import_options or verbs:
        picked = BOUND.picked(state)
        options = layout.column(align=True)
        options.enabled = picked is not None and bool(picked.payload)
        if import_options:
            browser.draw_import_options(options, context)
        if verbs:
            cast_panel.draw_row_verbs(options, [picked.payload] if picked and picked.payload else [], STATE)
    if import_options:
        layout.label(text='材质与贴图自动加载；配饰／技能道具不代表可装备武器', icon='INFO')


def register():
    host_port.current().register_state(STATE, SCHEMA, HANDLERS, extra={'FILTER_SPEC_KEY': SPEC_KEY})


def unregister():
    global _TABLE, _SOURCE
    BOUND.close()
    BOUND.table = None
    _TABLE, _SOURCE = None, None
    host_port.current().unregister_state(STATE)
