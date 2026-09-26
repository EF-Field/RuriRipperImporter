"""An Unreal package into Blender, with no other engine in between.

The other road turns an Unreal package into Unity assets, runs the AssetRipper pipeline over
them, serialises a project and hands the text back to be parsed; every step of it exists to
reach facts the engine already stated. This asks the decoder for those facts directly -- what a
level places, the buffers of every mesh, the reference skeleton a skinned one indexes, the
parameters of every material, the pixels of every texture -- and builds from them.

What it does NOT do is build differently. The mesh goes through ``mesh_builder``, the material
through ``material_builder``, the armature through ``armature_builder``: the same three the
Unity path uses, reached through the same normalised forms (``DecodedMesh``,
``MaterialProperties``, reference-skeleton nodes). This module is the assembly -- what is asked
for, in what order, and which object hangs under which -- and nothing else.
"""

from __future__ import annotations

import bpy
from mathutils import Quaternion, Vector

try:
    from . import (animation_builder, armature_builder, coordinate, derived_state,
                   material_builder, mesh_builder, prefab_importer)
    from .RuriRipperPyBridge.unreal import direct
except ImportError:  # standalone (non-package) testing
    import animation_builder
    import armature_builder
    import coordinate
    import derived_state
    import prefab_importer
    import material_builder
    import mesh_builder
    from RuriRipperPyBridge.unreal import direct

# Blender's own name for each light kind the decoder states.
LIGHT_KINDS = {"spot": "SPOT", "directional": "SUN", "point": "POINT", "area": "AREA"}

_DEGREES = 0.017453292519943295


def import_package(context, bridge, package, options):
    """Build everything one package places. Returns the objects created, parents first.

    One dataset call for the placements, one per mesh, then one for every material those slots
    name and one for the pixels of every texture those materials name. A level that stamps one
    mesh into hundreds of rows reads that mesh once. A package that places nothing is asked for
    its animation instead.
    """
    table = bridge.game_data(direct.PLACEMENTS, package=package)
    rows = _rows(table)
    if not rows:
        # A package that places nothing may still carry animation; asking what a package HOLDS
        # beats making the caller declare which kind it handed over.
        return _import_animations(context, bridge, package, options)
    meshes = _mesh_library(bridge, rows, options)
    materials = _materials(bridge, rows, meshes, options)
    built = []
    shared = {}
    for row in rows:
        built.append(_place(context, row, built, meshes, materials, shared, options))
    return [obj for obj in built if obj is not None]


def _import_animations(context, bridge, package, options):
    """Every sequence in the package as an action on the armature the user is working on.

    The clips reach the same builder a Unity clip reaches, through the same clip form, and bind
    through the rig identity the armature carries -- so a rig this add-on built in any session,
    under any names its bones have since been given, is a valid target.
    """
    if not options.get("import_animations", True):
        return []
    clips = direct.animations(bridge, package)
    if not clips:
        return []
    armature = prefab_importer.find_target_armature(context)
    if armature is None:
        raise RuntimeError(
            "{0} sequence(s) read, but no armature is selected to play them on: import the "
            "character first, then select its armature.".format(len(clips)))
    maps = prefab_importer.maps_from_stamped_armature(armature)
    if maps is None:
        raise RuntimeError(
            "'{0}' carries no rig identity, so a clip cannot be bound to its bones.".format(armature.name))
    first = None
    for name in sorted(clips):
        action, slot, _frames = animation_builder.build_action(
            clips[name], armature, maps, options=options, display_name=name)
        if first is None:
            first = (action, slot)
    if first is not None:
        animation_builder.adopt_action(armature, first[0], first[1], scene=context.scene)
    return [armature]


def _rows(table):
    """The placement table as plain rows, each column read once."""
    columns = {name: table.values(name) for name in table.names}
    return [{name: values[index] for name, values in columns.items()}
            for index in range(len(table))]


def _mesh_library(bridge, rows, options):
    """``{mesh object path: (DecodedMesh, own slot materials, bone names, skeleton nodes)}``.

    One dataset call per mesh, not per placement. The detail level asked for picks among the
    LODs the mesh carries -- the nearest one it has, so a mesh with fewer levels than asked for
    still builds rather than vanishing.
    """
    detail = max(0, int(options.get("detail_level", 0) or 0))
    library = {}
    for path in sorted({row["mesh"] for row in rows if row["mesh"]}):
        table = direct.mesh_rows(bridge, path)
        export = path.rsplit(".", 1)[-1]
        chosen = None
        for index in range(len(table)):
            if table.cell(index, "name") != export:
                continue
            level = int(table.cell(index, "lod"))
            if chosen is None or abs(level - detail) < abs(chosen[1] - detail):
                chosen = (index, level)
        if chosen is None:
            continue
        index = chosen[0]
        bones = direct.mesh_bones(table, index)
        nodes = _skeleton_nodes(bridge, path, export) if bones else []
        library[path] = (direct.decoded_mesh(table, index),
                         direct.mesh_material_paths(table, index), bones, nodes)
    return library


def _skeleton_nodes(bridge, path, export):
    """One skinned mesh's reference skeleton in the shape the armature builder takes."""
    skeletons = direct.skeleton(bridge, path)
    return [(bone["name"], bone["parent"], Vector(bone["position"]),
             Quaternion((bone["rotation"][3], bone["rotation"][0],
                         bone["rotation"][1], bone["rotation"][2])), bone["path"])
            for bone in skeletons.get(export, [])]


def _materials(bridge, rows, meshes, options):
    """Every material any placement draws with, built once each."""
    if not options.get("import_materials", True):
        return {}
    wanted = []
    for row in rows:
        wanted.extend(_slot_paths(row, meshes))
    properties = direct.material_properties(bridge, wanted)
    source = direct.UnrealTextureSource(bridge)
    if options.get("import_textures", True):
        source.request([path for props in properties.values() for path in props.textures.values()])
    builder = material_builder.MaterialBuilder(source, options)
    return {path: builder.build_from_props(props, path) for path, props in properties.items()}


def _slot_paths(row, meshes):
    """The material each of a row's slots draws with.

    The decoder already applied the rule -- the component's override where it states one, else
    the mesh's own -- so a row that states any list at all states the whole answer; the mesh's
    own list is only for a row that renders through no component of its own.
    """
    stated = row["materials"].split(direct.SLOT_SEPARATOR) if row["materials"] else []
    if stated:
        return stated
    entry = meshes.get(row["mesh"])
    return list(entry[1]) if entry else []


def _place(context, row, built, meshes, materials, shared, options):
    """One row as a Blender object: a mesh where it renders one, a light where it lights, an
    empty otherwise -- so a transform other rows hang under never disappears.

    The object returned is the one that CARRIES the placement: a skinned mesh hangs under the
    armature its weights index, so the armature is the placement and the mesh rides it.
    """
    entry = meshes.get(row["mesh"])
    if entry is not None:
        obj = _mesh_object(context, row, entry, materials, meshes, shared, options)
    elif row["light"]:
        obj = _light_object(row)
        context.collection.objects.link(obj)
    else:
        obj = bpy.data.objects.new(row["name"], None)
        context.collection.objects.link(obj)
    parent = int(row["parent"])
    top = not (0 <= parent < len(built) and built[parent] is not None)
    if not top:
        obj.parent = built[parent]
    convert = coordinate.convert_root_matrix if top else coordinate.convert_matrix
    obj.matrix_basis = convert(coordinate.unity_trs(
        {"x": row["px"], "y": row["py"], "z": row["pz"]},
        {"x": row["qx"], "y": row["qy"], "z": row["qz"], "w": row["qw"]},
        {"x": row["sx"], "y": row["sy"], "z": row["sz"]}))
    if row["active"] != "1":
        obj.hide_viewport = obj.hide_render = True
    return obj


def _mesh_object(context, row, entry, materials, meshes, shared, options):
    """A placement that renders a mesh: the mesh with its slots, and -- when it is skinned --
    the armature its weights index, with the mesh parented to it.

    A level stamps the same mesh into hundreds of placements: this one measures 1533 of them
    over 56 distinct meshes, so building a fresh mesh per placement writes the same 215k
    vertices 5.47 MILLION times over. A placement that renders the same mesh with the same
    materials as one already built gets an object over the SAME mesh datablock -- Blender's own
    linked duplicate, which is what the engine does with them too. Skinned placements are not
    shared: their weights live in vertex groups on the object, and their armature is their own.

    Returns whichever of the two the placement's own transform belongs on.
    """
    decoded, _own, bones, nodes = entry
    paths = _slot_paths(row, meshes)
    slots = [materials.get(path) for path in paths]
    skinned = bool(nodes) and options.get("import_skeleton", True)
    if not skinned:
        key = (row["mesh"], tuple(paths))
        existing = shared.get(key)
        if existing is not None:
            obj = bpy.data.objects.new(row["name"], existing)
            context.collection.objects.link(obj)
            derived_state.announce(obj)
            return obj
    armature = None
    if skinned:
        armature, names = armature_builder.build_armature_from_nodes(
            context, nodes, row["name"] + "_Armature")
        bones = [names.get(index, bone) for index, bone in enumerate(bones)]
    mesh = mesh_builder.build_mesh_object(
        context, decoded, row["name"], armature,
        [{"fileID": bone} for bone in bones],
        {bone: bone for bone in bones},
        slots, options)
    if not skinned:
        shared[(row["mesh"], tuple(paths))] = mesh.data
    return armature if armature is not None else mesh


def _light_object(row):
    """A light component as a Blender light: its kind, colour, energy and shape as stated."""
    data = bpy.data.lights.new(row["name"], LIGHT_KINDS.get(row["light"], "POINT"))
    data.color = (row["lr"], row["lg"], row["lb"])
    data.energy = row["intensity"]
    if data.type in ("POINT", "SPOT", "AREA") and row["range"]:
        data.use_custom_distance = True
        data.cutoff_distance = row["range"]
    if data.type == "SPOT":
        data.spot_size = row["outer"] * _DEGREES
        data.spot_blend = max(0.0, 1.0 - (row["inner"] / row["outer"])) if row["outer"] else 0.0
    if data.type == "AREA":
        data.shape = "RECTANGLE"
        data.size = row["width"]
        data.size_y = row["height"]
    return bpy.data.objects.new(row["name"], data)
