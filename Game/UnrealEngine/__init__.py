"""Unreal Engine -- every install built on that engine, claimed by the ENGINE FAMILY the
kernel's probe reports rather than by a product name: an Unreal build publishes no
Unity productName a folder here could be named after, and one decoder reads every
title of the engine (``Ruri.RipperHook.Unreal.UnrealEngine_Hook``), so one module
draws every title's panels. A title that ships its own decoder and panels claims
its install by product first and this module never sees it.

Two contributions, neither of which any Unity game needs:

``source_options``  the values the install is READ with beyond its folder -- the
                    engine version, AES keys, the .usmap reflection schema, the
                    texture platform, the versioning overrides FModel keeps per
                    game. Drawn ABOVE the cabmap gate from the decoder's own
                    published schema (``unreal.settings.schema``), because an
                    archive key is what makes building the map possible at all.
``Scene`` tab       the levels the install ships: the self-contained ones whole, the
                    partitioned ones a streamed window at a time.
``Unreal`` tab      what the mounted session says about itself and its archives.

Declared as one GAME_MODULE row (see ``Game``).
"""

from __future__ import annotations

from .. import GameModule, GameTab
from . import actors_panel, datasets, scene_panel, unreal_panel


def _import_packages(context, packages, options):
    """Every package built from what the decoder states it holds.

    An Unreal build is read directly: placements, geometry, materials, texture pixels and
    animation curves all cross as data, so nothing here creates a Unity asset or parses text.
    """
    from ...RuriRipperPyBridge.session import cabmap_state
    from ... import unreal_importer
    built = []
    for package in dict.fromkeys(packages):
        built.extend(unreal_importer.import_package(context, cabmap_state.BRIDGE, package, options))
    return built


def _register():
    unreal_panel.register()
    scene_panel.register()
    actors_panel.register()


def _unregister():
    actors_panel.unregister()
    scene_panel.unregister()
    unreal_panel.unregister()


GAME_MODULE = GameModule(
    # The family-wide decoder's GameName -- the GameType member the kernel declares for
    # the engine, and the family string its install probe reports.
    game_name="UnrealEngine",
    label="Unreal Engine",
    engine="UnrealEngine",
    tabs=(
        GameTab("scene", "Scene",
                "The levels the install ships: the self-contained ones imported whole, the "
                "partitioned worlds a streamed window at a time",
                scene_panel.draw_scene_tab),
        GameTab("actors", "Actors",
                "Every Blueprint actor the install ships -- characters, pawns, props -- "
                "found by name and kind and imported whole",
                actors_panel.draw_actors_tab),
        GameTab("unreal", "Unreal",
                "The mounted Unreal session: project, engine, schema and archives",
                unreal_panel.draw_unreal_tab),
    ),
    importer=_import_packages,
    source_options=unreal_panel.draw_source_options,
    settings_schema=datasets.SETTINGS_SCHEMA,
    register=_register,
    unregister=_unregister,
)
