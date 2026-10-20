"""Execute reader-declared coverage operations; no game/shader matching rules.

The reader owns eligibility and property names. Only the small node operation and
the generated host coverage contract live here. Records survive material rebuilds
and file reopen without asking the reader again. Unknown projections stay intact.
"""
from __future__ import annotations

import hashlib
import json

RECORD = 'ruri_material_coverage_record'
STATUS = 'ruri_material_coverage_status'
MARK = 'ruri_material_coverage_node'
_READERS = {}


def projection(material):
    from . import material_panel
    entry = material_panel.stack_of(material)
    if not entry:
        return None
    stack = entry['stack']
    part = material.get('ruri_uber_part')
    spec = stack.m.get('parts', {}).get(part)
    if not spec:
        return None
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=True).encode('utf-8')).hexdigest()
    return dict(part=part, sha256=digest, has_clip='__clip' in spec['finals'])


def register_reader(game, dataset):
    from . import material_builder
    _READERS[game] = dataset
    material_builder.MATERIAL_FINALIZERS.add(finalize)


def unregister_reader(game):
    from . import material_builder
    _READERS.pop(game, None)
    if not _READERS:
        material_builder.MATERIAL_FINALIZERS.remove(finalize)


def capture(material, props, options):
    """Ask once at source import; no duplicate asset loading or name inference."""
    dataset = _READERS.get(options.get('source_game'))
    if not dataset:
        return
    projected = projection(material)
    if projected is None:
        return
    from ...Kernel.bridge import cabmap_state
    source = dict(shader=props.shader_name, keywords=list(props.keywords or ()),
                  floats=dict(props.floats), colors={k:list(v) for k,v in props.colors.items()},
                  textures=list(props.textures), disabled_passes=list(props.disabled_passes or ()),
                  passes=[dict(name=str(n), light_mode=str(mode)) for n,mode in props.shader_passes])
    payload = dict(schema=1, material=source, projection=projected)
    try:
        answer = json.loads(cabmap_state.BRIDGE.game_data_blob(
            dataset, payload=json.dumps(payload, allow_nan=False).encode('utf-8')))
        if answer.get('schema') != 1 or answer.get('state') not in ('none', 'UNKNOWN', 'apply'):
            raise ValueError('Unsupported coverage answer')
        material[RECORD] = json.dumps(dict(answer=answer, keywords=source['keywords']),
                                      separators=(',', ':'), allow_nan=False)
        material[STATUS] = answer['state'] + ': ' + str(answer.get('reason', ''))
        if answer['state'] == 'UNKNOWN':
            print('[material coverage] {0}: {1}'.format(material.name, material[STATUS]))
    except Exception as exc:
        # An older optional reader must not turn an otherwise valid import into a failure.
        material[STATUS] = 'UNKNOWN: reader unavailable: ' + str(exc).splitlines()[0]
        print('[material coverage] {0}: {1}'.format(material.name, material[STATUS]))


def _driver(socket, material, path):
    curve = socket.driver_add('default_value')
    driver = curve.driver
    driver.type = 'SUM'
    variable = driver.variables.new()
    variable.name = 'source_value'
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id_type = 'MATERIAL'
    variable.targets[0].id = material
    variable.targets[0].data_path = path


def finalize(material):
    raw = material.get(RECORD)
    if not raw:
        return
    try:
        answer = json.loads(raw)['answer']
        if answer.get('state') != 'apply':
            return
        projected = projection(material)
        if not projected or projected['has_clip'] or projected['sha256'] != answer['projection_sha256']:
            raise ValueError('UNKNOWN: projection changed; coverage needs review')
        if answer['schema'] != 1 or answer['op'] != 'alpha_test_product' or answer['channel'] != 3 or answer['tint_channel'] != 3:
            raise ValueError('UNKNOWN: unsupported coverage operation')
        tree = material.node_tree
        owned = [n for n in tree.nodes if n.get(MARK)]
        coverage, = [n for n in tree.nodes if n.label == 'RuriSurfaceCoverage']
        if owned:
            # Idempotent after repeated finalization; do not compound the mask.
            combined, = [n for n in owned if n.get(MARK) == 'combined']
            if len(owned) != 5 or coverage.inputs[0].links[0].from_node != combined:
                raise ValueError('UNKNOWN: incomplete coverage companion')
            return
        if coverage.operation != 'ADD' or len(coverage.inputs[0].links) != 1:
            raise ValueError('UNKNOWN: unexpected host coverage contract')
        images = material.get('ruri_uber_images', {})
        image = images.get(answer['texture'])
        sampler, = [n for n in tree.nodes if n.type == 'TEX_IMAGE'
                    and n.label == answer['texture'] and n.image == image and image is not None]
        if image.alpha_mode != 'CHANNEL_PACKED':
            raise ValueError('UNKNOWN: source alpha sampling is not channel-packed')
        tint_key, cutoff_key = answer['tint'], answer['cutoff']
        tint = float(material['ruri_uber_colors'][tint_key][answer['tint_channel']])
        cutoff = float(material['ruri_uber_floats'][cutoff_key])
        previous = coverage.inputs[0].links[0].from_socket
        made = []
        try:
            frame = tree.nodes.new('NodeFrame');made.append(frame)
            frame[MARK] = 'frame';frame.label = 'Reader-declared material coverage'
            def math(role, op, x):
                node = tree.nodes.new('ShaderNodeMath');made.append(node)
                node[MARK] = role;node.operation = op;node.parent = frame
                node.location = (x, 0);node.label = role
                return node
            alpha = math('alpha_product', 'MULTIPLY', 0)
            tree.links.new(sampler.outputs['Alpha'], alpha.inputs[0]);alpha.inputs[1].default_value = tint
            _driver(alpha.inputs[1], material, '["ruri_uber_colors"][{0}][3]'.format(json.dumps(tint_key)))
            below = math('below_cutoff', 'LESS_THAN', 180)
            tree.links.new(alpha.outputs[0], below.inputs[0]);below.inputs[1].default_value = cutoff
            _driver(below.inputs[1], material, '["ruri_uber_floats"][{0}]'.format(json.dumps(cutoff_key)))
            keep = math('keep_equality', 'SUBTRACT', 360)
            keep.inputs[0].default_value = 1.0;tree.links.new(below.outputs[0], keep.inputs[1])
            combined = math('combined', 'MULTIPLY', 540)
            tree.links.new(previous, combined.inputs[0]);tree.links.new(keep.outputs[0], combined.inputs[1])
            tree.links.new(combined.outputs[0], coverage.inputs[0])
            frame.location = (coverage.location.x - 800, coverage.location.y - 350)
        except Exception:
            tree.links.new(previous, coverage.inputs[0])
            for node in reversed(made):
                for socket in node.inputs:
                    if hasattr(socket, 'default_value'):
                        try: socket.driver_remove('default_value')
                        except (TypeError, RuntimeError): pass
                tree.nodes.remove(node)
            raise
        material[STATUS] = 'applied'
        material.update_tag()
    except Exception as exc:
        material[STATUS] = str(exc).splitlines()[0]
        print('[material coverage] {0}: {1}'.format(material.name, material[STATUS]))
