"""Browse the install's levels the way the engine ships them, and import one.

One tab with two halves, because World Partition splits a build's levels in two -- and the
decoder says which by the world's own partitioned flag, never by the shape of a name:

``Scene``  the self-contained levels: a room, a test map, a level small enough to hold
           whole. Nothing to window, so nothing to choose -- pick it, import it.
``World``  the partitioned worlds. Far too big to hold at once, and the running game never
           holds one either: it streams a window of cells around the player. So one is
           imported a window at a time, stated as a share of the ground the decoder
           measured the world to cover, and shown at the size that share really is.

Both lists filter through the same C# engine every other list here uses, and both hand what
they picked to the host's own Import Selected, where the packages load like any other
browser rows. Nothing is cut or matched on this side: the window and the hierarchical level
go to the decoder as dataset arguments, so the cells are cut where they are read, and the
metres a size is shown in come from the unit scale the decoder states for the engine.
"""

from __future__ import annotations

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)

from ... import cabmap_panel, filter_ui, unreal_importer
from ...RuriRipperPyBridge.session import cabmap_state
from . import datasets

LEVEL = "LEVEL"
WORLD = "WORLD"
ALL_LEVELS = -1

_WORLDS = {"rows": [], "unit_scale": 0.0}
_CELLS = {"world": "", "rows": [], "error": ""}
_published = {}

_world_items_cache = [("", "(refresh first)", "")]

_LEVEL_FILTER_FIELDS = (("name", "Name"), ("world", "Package"))
_CELL_FILTER_FIELDS = (("name", "Cell"), ("level", "Package"), ("grid", "Grid"))


def _report_exception(op, prefix, exc):
    import traceback
    traceback.print_exc()
    op.report({"ERROR"}, f"{prefix}: {type(exc).__name__}: {exc} (full traceback in console)")


def _levels_state(context):
    return context.scene.ruri_unreal_levels


def _world_state(context):
    return context.scene.ruri_unreal_scene_world


LEVEL_FILTER_SPEC = filter_ui.register_spec(filter_ui.FilterSpec(
    key="UnrealEngine:level", fields=_LEVEL_FILTER_FIELDS,
    state_for=_levels_state,
    apply=lambda context: _rebuild_levels(_levels_state(context))))

CELL_FILTER_SPEC = filter_ui.register_spec(filter_ui.FilterSpec(
    key="UnrealEngine:cell", fields=_CELL_FILTER_FIELDS,
    state_for=_world_state,
    apply=lambda context: _rebuild_cells(_world_state(context))))


def _on_level_search(self, context):
    _rebuild_levels(self)


def _on_cell_search(self, context):
    _rebuild_cells(self)


def _on_world_pick(self, context):
    """Picking a world drops the cells read for the previous one: they are that world's."""
    _CELLS["world"] = ""
    _CELLS["rows"] = []
    _CELLS["error"] = ""
    _rebuild_cells(self)


def _cell_count(row):
    return int(float(row.get("cells", 0) or 0))


def _world_items(self, context):
    global _world_items_cache
    items = [(row.get("world", ""), row.get("name", "") or row.get("world", ""),
              "{0} streaming cell(s)".format(_cell_count(row)))
             for row in _WORLDS["rows"] if str(row.get("partitioned", "0")) == "1"]
    _world_items_cache = items or [("", "(no partitioned world)", "")]
    return _world_items_cache


class RURI_PG_unreal_level(bpy.types.PropertyGroup):
    key: StringProperty()
    name: StringProperty()


class RURI_PG_unreal_cell(bpy.types.PropertyGroup):
    key: StringProperty()
    name: StringProperty()
    hlevel: IntProperty()
    always_loaded: BoolProperty()
    present: BoolProperty()


class RURI_PG_unreal_levels(filter_ui.FilterStateMixin, bpy.types.PropertyGroup):
    """The self-contained levels: every world the decoder did not call partitioned."""

    FILTER_SPEC_KEY = LEVEL_FILTER_SPEC.key
    search: StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}, update=_on_level_search)
    entries: CollectionProperty(type=RURI_PG_unreal_level)
    active_index: IntProperty()


class RURI_PG_unreal_scene_world(filter_ui.FilterStateMixin, bpy.types.PropertyGroup):
    """One partitioned world and the window of it to read."""

    FILTER_SPEC_KEY = CELL_FILTER_SPEC.key
    search: StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}, update=_on_cell_search)
    entries: CollectionProperty(type=RURI_PG_unreal_cell)
    active_index: IntProperty()
    world: EnumProperty(name="World", items=_world_items, update=_on_world_pick,
                        description="The partitioned world to stream a window of")
    size: FloatProperty(name="Size", default=0.25, min=0.01, max=1.0, subtype="FACTOR",
                        description="How much of the world to read, as a share of the ground its "
                                    "cells cover, taken about the world's centre")
    level: IntProperty(name="Level", default=0, min=ALL_LEVELS,
                       description="The hierarchical level to read (0 is the leaf cells, -1 every level)")
    use_always_loaded: BoolProperty(
        name="Always loaded", default=True,
        description="Take the always-loaded cells too, whose actors the cook folded into the "
                    "world's own package -- the persistent level every window of this world "
                    "sits on. A small partitioned world is often nothing but one of these")


def _world_row(state):
    for row in _WORLDS["rows"]:
        if row.get("world", "") == state.world:
            return row
    return None


def _world_rect(state):
    """The ground the picked world's cells cover, in the decoder's own units, or None when it states none."""
    row = _world_row(state)
    if row is None:
        return None
    min_x, min_y = float(row.get("minX", 0) or 0), float(row.get("minY", 0) or 0)
    max_x, max_y = float(row.get("maxX", 0) or 0), float(row.get("maxY", 0) or 0)
    return (min_x, min_y, max_x, max_y) if max_x > min_x and max_y > min_y else None


def _window(state):
    """The rect to cut the cells to: the world's own ground shrunk to ``size`` about its centre."""
    rect = _world_rect(state)
    if rect is None or state.size >= 1.0:
        return None
    min_x, min_y, max_x, max_y = rect
    center_x, center_y = (min_x + max_x) * 0.5, (min_y + max_y) * 0.5
    half_x, half_y = (max_x - min_x) * 0.5 * state.size, (max_y - min_y) * 0.5 * state.size
    return (center_x - half_x, center_y - half_y, center_x + half_x, center_y + half_y)


def _metres(units):
    """``units`` of the engine's own length in metres, by the scale the decoder states."""
    scale = _WORLDS["unit_scale"]
    return units * scale if scale else 0.0


def _matching(handle, rows, columns, values_of, state):
    """The rows passing the search box and every enabled rule, matched by the same C# engine
    every other list here uses. Falls back to the unfiltered rows only when there is no bridge
    to ask, which is also the only state in which there is nothing to show."""
    if cabmap_state.BRIDGE is None or not rows:
        return list(rows)
    if _published.get(handle) is not rows:
        cabmap_state.BRIDGE.open_host_table(handle, columns, [values_of(row) for row in rows])
        _published[handle] = rows
    ids = cabmap_state.BRIDGE.search_data_table(handle, state.search.strip(), state.filter_rules)
    return [rows[index] for index in ids if 0 <= index < len(rows)]


def _level_rows():
    return [row for row in _WORLDS["rows"] if str(row.get("partitioned", "0")) != "1"]


def _rebuild_levels(state):
    with filter_ui.rebuilding():
        chosen = filter_ui.selected_key(state)
        state.entries.clear()
        rows = _matching("ruri.unreal.level", _level_rows(),
                         tuple(key for key, _label in _LEVEL_FILTER_FIELDS),
                         lambda row: (row.get("name", ""), row.get("world", "")), state)
        for row in rows:
            entry = state.entries.add()
            entry.key = row.get("world", "")
            entry.name = row.get("name", "") or row.get("world", "")
        filter_ui.restore_selection(state, chosen)


def _cell_rows(state):
    kept = []
    for row in _CELLS["rows"]:
        if not state.use_always_loaded and str(row.get("alwaysLoaded", "0")) == "1":
            continue
        kept.append(row)
    return kept


def _rebuild_cells(state):
    with filter_ui.rebuilding():
        chosen = filter_ui.selected_key(state)
        state.entries.clear()
        rows = _matching("ruri.unreal.cell\x1f" + _CELLS["world"], _cell_rows(state),
                         tuple(key for key, _label in _CELL_FILTER_FIELDS),
                         lambda row: (row.get("cell", ""), row.get("level", ""), row.get("grid", "")),
                         state)
        for row in rows:
            entry = state.entries.add()
            entry.key = row.get("level", "")
            entry.name = row.get("cell", "")
            entry.hlevel = int(float(row.get("hlevel", 0) or 0))
            entry.always_loaded = str(row.get("alwaysLoaded", "0")) == "1"
            entry.present = str(row.get("present", "0")) == "1"
        filter_ui.restore_selection(state, chosen)


class RURI_UL_unreal_levels(bpy.types.UIList):
    bl_idname = "RURI_UL_unreal_levels"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon="FILE_3D")


class RURI_UL_unreal_cells(bpy.types.UIList):
    bl_idname = "RURI_UL_unreal_cells"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        row = layout.row(align=True)
        row.label(text=item.name,
                  icon="PINNED" if item.always_loaded else ("MESH_GRID" if item.present else "GHOST_DISABLED"))
        tail = row.row(align=True)
        tail.alignment = "RIGHT"
        tail.label(text="L{0}".format(item.hlevel))


class RURI_OT_unreal_scene_refresh(bpy.types.Operator):
    """Re-read the worlds the install ships off the decoder"""

    bl_idname = "ruri.unreal_scene_refresh"
    bl_label = "Refresh"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            _WORLDS["rows"] = datasets.worlds()
            session = datasets.session() or {}
            _WORLDS["unit_scale"] = float(session.get("unitScale", 0) or 0)
        except Exception as exc:
            _report_exception(self, "Unreal worlds", exc)
            return {"CANCELLED"}
        _published.clear()
        _rebuild_levels(_levels_state(context))
        _rebuild_cells(_world_state(context))
        return {"FINISHED"}


class RURI_OT_unreal_cells_refresh(bpy.types.Operator):
    """Read the picked world's streaming cells, cut to the size and level stated"""

    bl_idname = "ruri.unreal_cells_refresh"
    bl_label = "Read Cells"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(_world_state(context).world)

    def execute(self, context):
        state = _world_state(context)
        args = {}
        window = _window(state)
        if window is not None:
            args.update(minX=window[0], minY=window[1], maxX=window[2], maxY=window[3])
        if state.level != ALL_LEVELS:
            args["level"] = state.level
        try:
            _CELLS["rows"] = datasets.world_cells(state.world, **args)
            _CELLS["world"] = state.world
            _CELLS["error"] = ""
        except Exception as exc:
            _CELLS["rows"] = []
            _CELLS["error"] = f"{type(exc).__name__}: {exc}"
            _report_exception(self, "Unreal cells", exc)
            return {"CANCELLED"}
        _published.clear()
        _rebuild_cells(state)
        return {"FINISHED"}


def _import_packages(operator, context, packages, what):
    """Build every package through the decoder's own placements -- the direct road.

    Nothing here is a cabmap closure: the decoder addresses a package by its path in the mount,
    reads what it places and hands over the geometry, materials and pixels. A package the mount
    does not carry simply yields nothing, and is reported as such.
    """
    blocked = cabmap_panel._blocking_required_options(
        cabmap_panel._ensure_active_config(context.scene.ruri_cabmap))
    if blocked:
        operator.report({"ERROR"}, blocked)
        return {"CANCELLED"}
    options = context.scene.ruri_cabmap.as_options(scene=True)
    built = 0
    empty = 0
    for package in dict.fromkeys(packages):
        try:
            objects = unreal_importer.import_package(context, cabmap_state.BRIDGE, package, options)
        except Exception as exc:
            _report_exception(operator, "Unreal {0} import".format(what), exc)
            return {"CANCELLED"}
        built += len(objects)
        empty += 0 if objects else 1
    if not built:
        operator.report({"ERROR"}, "The {0} {1} package(s) place nothing this install carries.".format(
            len(packages), what))
        return {"CANCELLED"}
    if empty:
        operator.report({"WARNING"}, "{0} {1} package(s) placed nothing.".format(empty, what))
    operator.report({"INFO"}, "{0} object(s) from {1} {2} package(s).".format(
        built, len(packages) - empty, what))
    return {"FINISHED"}


class RURI_OT_unreal_level_import(bpy.types.Operator):
    """Import this level whole: its actors at their places, as the browser would"""

    bl_idname = "ruri.unreal_level_import"
    bl_label = "Import Level"
    bl_options = {"REGISTER", "UNDO"}
    world: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.scene.ruri_cabmap.loaded and cabmap_state.BRIDGE is not None

    def execute(self, context):
        state = _levels_state(context)
        package = self.world
        if not package and 0 <= state.active_index < len(state.entries):
            package = state.entries[state.active_index].key
        if not package:
            self.report({"WARNING"}, "Pick a level first.")
            return {"CANCELLED"}
        return _import_packages(self, context, [package], "level")


class RURI_OT_unreal_window_import(bpy.types.Operator):
    """Import every cell listed below: one scene per cell, actors at their world places"""

    bl_idname = "ruri.unreal_window_import"
    bl_label = "Import Window"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.scene.ruri_cabmap.loaded and cabmap_state.BRIDGE is not None
                and bool(_world_state(context).entries))

    def execute(self, context):
        state = _world_state(context)
        packages = list(dict.fromkeys(entry.key for entry in state.entries if entry.key))
        return _import_packages(self, context, packages, "cell")


class RURI_OT_unreal_world_import(bpy.types.Operator):
    """Import the world's own package: the persistent level the cook folded its always-loaded actors into"""

    bl_idname = "ruri.unreal_world_import"
    bl_label = "Import World Package"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.scene.ruri_cabmap.loaded and cabmap_state.BRIDGE is not None
                and bool(_world_state(context).world))

    def execute(self, context):
        return _import_packages(self, context, [_world_state(context).world], "world")


def _draw_self_contained(layout, context):
    """The levels that hold whole: nothing to window, so nothing to choose."""
    state = _levels_state(context)
    filter_ui.draw_search_row(layout, state,
                              extra_operator=(RURI_OT_unreal_scene_refresh.bl_idname, "FILE_REFRESH"))
    if not _WORLDS["rows"]:
        layout.label(text="Refresh to read the levels this install ships.", icon="INFO")
        return
    layout.template_list(RURI_UL_unreal_levels.bl_idname, "", state, "entries",
                         state, "active_index", rows=10)
    layout.label(text="{0} self-contained level(s)".format(len(state.entries)), icon="INFO")
    tail = layout.column(align=True)
    tail.enabled = 0 <= state.active_index < len(state.entries)
    tail.operator(RURI_OT_unreal_level_import.bl_idname, icon="IMPORT")


def _draw_streaming(layout, context):
    """The partitioned worlds: pick one, take a share of it, read its cells, import them."""
    state = _world_state(context)
    if not _WORLDS["rows"]:
        layout.label(text="Refresh to read the worlds this install ships.", icon="INFO")
        layout.operator(RURI_OT_unreal_scene_refresh.bl_idname, icon="FILE_REFRESH")
        return
    head = layout.row(align=True)
    head.prop(state, "world", text="")
    head.operator(RURI_OT_unreal_scene_refresh.bl_idname, text="", icon="FILE_REFRESH")
    if not state.world:
        layout.label(text="This install ships no partitioned world.", icon="INFO")
        return

    row = _world_row(state)
    rect = _world_rect(state)
    box = layout.box()
    box.label(text="{0} cell(s) in this world".format(_cell_count(row) if row else 0),
              icon="WORLD")
    if rect is None:
        box.label(text="It states no ground of its own -- import its package whole.", icon="INFO")
        box.operator(RURI_OT_unreal_world_import.bl_idname, icon="IMPORT")
        return
    box.label(text="{0:.0f} x {1:.0f} m whole".format(
        _metres(rect[2] - rect[0]), _metres(rect[3] - rect[1])))

    size = layout.column(align=True)
    size.prop(state, "size", slider=True)
    window = _window(state)
    if window is not None:
        size.label(text="{0:.0f} x {1:.0f} m of it".format(
            _metres(window[2] - window[0]), _metres(window[3] - window[1])))
    knobs = size.row(align=True)
    knobs.prop(state, "level")
    knobs.prop(state, "use_always_loaded")
    size.operator(RURI_OT_unreal_cells_refresh.bl_idname, icon="VIEWZOOM")

    if _CELLS["error"]:
        layout.label(text=_CELLS["error"], icon="ERROR")
    if _CELLS["world"] != state.world:
        layout.label(text="Read the cells of this world to pick a window.", icon="INFO")
        return
    filter_ui.draw_search_row(layout, state)
    layout.template_list(RURI_UL_unreal_cells.bl_idname, "", state, "entries",
                         state, "active_index", rows=10)
    layout.label(text="{0} cell(s) in the window".format(len(state.entries)), icon="INFO")
    if not state.entries:
        layout.label(text="Nothing in this window: widen Size, or turn Always loaded on.", icon="INFO")
    tail = layout.column(align=True)
    tail.enabled = bool(state.entries)
    tail.operator(RURI_OT_unreal_window_import.bl_idname, icon="IMPORT")
    layout.operator(RURI_OT_unreal_world_import.bl_idname, icon="IMPORT")


_KINDS = (
    (LEVEL, "Scene",
     "The self-contained levels -- small enough to import whole",
     _draw_self_contained),
    (WORLD, "World",
     "The partitioned worlds -- import a window of one at a time, the way the game streams it",
     _draw_streaming),
)
_KIND_ITEMS = tuple(row[:3] for row in _KINDS)
_KIND_DRAW = {row[0]: row[3] for row in _KINDS}


def draw_scene_tab(layout, context):
    """Pick which of the engine's two kinds of level to browse, then browse it."""
    layout.row(align=True).prop(context.scene, "ruri_unreal_scene_kind", expand=True)
    _KIND_DRAW[context.scene.ruri_unreal_scene_kind](layout, context)


_CLASSES = (RURI_PG_unreal_level, RURI_PG_unreal_cell, RURI_PG_unreal_levels,
            RURI_PG_unreal_scene_world, RURI_UL_unreal_levels, RURI_UL_unreal_cells,
            RURI_OT_unreal_scene_refresh, RURI_OT_unreal_cells_refresh,
            RURI_OT_unreal_level_import, RURI_OT_unreal_window_import,
            RURI_OT_unreal_world_import)


def register():
    filter_ui.register_spec(LEVEL_FILTER_SPEC)
    filter_ui.register_spec(CELL_FILTER_SPEC)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ruri_unreal_levels = PointerProperty(type=RURI_PG_unreal_levels)
    bpy.types.Scene.ruri_unreal_scene_world = PointerProperty(type=RURI_PG_unreal_scene_world)
    bpy.types.Scene.ruri_unreal_scene_kind = EnumProperty(
        name="Kind", items=_KIND_ITEMS, default=LEVEL,
        description="Which of the engine's two kinds of level to browse")


def unregister():
    del bpy.types.Scene.ruri_unreal_scene_kind
    del bpy.types.Scene.ruri_unreal_scene_world
    del bpy.types.Scene.ruri_unreal_levels
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _published.clear()
    _WORLDS["rows"] = []
    _CELLS["rows"] = []
    _CELLS["world"] = ""
