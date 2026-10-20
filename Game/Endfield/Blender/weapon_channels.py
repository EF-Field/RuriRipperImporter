"""Host facts and reader-declared native controls; no game channel profiles.

Declarations persist with matching graph facts for offline edits/reopen. Graph
fields, bound images and gate values are always read from the owning live stack.
"""
import json

from ....Host.Blender import material_panel
from ....Kernel.bridge import cabmap_state

DATASET = 'endfield.material.channels'
RECORD = 'ruri_weapon_channel_declaration'
STATUS = 'ruri_weapon_channel_status'


def interface(material):
    entry = material_panel.stack_of(material)
    if entry is None:
        return None, []
    return entry, entry['stack'].panel_rows(material)


def facts_of(material):
    entry, groups = interface(material)
    names = {r['name'] for g in groups for r in g['rows']}
    images = material.get('ruri_uber_images', {})
    meta = entry['stack'].PART_META.get(material.get('ruri_uber_part', ''), {}) if entry else {}
    return dict(schema=1, shader=meta.get('shader', ''), fields=sorted(names),
                images=sorted(key for key, image in images.items() if image))


def _validate(answer, facts):
    if (answer.get('schema') != 1 or answer.get('state') not in ('ready', 'UNKNOWN')
            or not isinstance(answer.get('channels'), list) or not isinstance(answer.get('manual'), list)):
        raise ValueError('Unsupported material-channel declaration')
    kinds = set()
    for channel in answer['channels']:
        if (not all(isinstance(channel.get(key), str) for key in ('kind', 'label', 'gate', 'image'))
                or not channel['kind'] or channel['kind'] in kinds
                or not isinstance(channel.get('full_panel'), bool)
                or not isinstance(channel.get('controls'), list)
                or any(not isinstance(key, str) or key not in facts['fields'] for key in channel['controls'])
                or (channel['gate'] and (channel['gate'] not in facts['fields'] or channel['image'] not in facts['images']))
                or (not channel['gate'] and not channel['full_panel'])):
            raise ValueError('Material-channel declaration does not match live graph')
        kinds.add(channel['kind'])
    for candidate in answer['manual']:
        if (candidate.get('image') not in facts['images'] or not isinstance(candidate.get('role'), str)
                or not isinstance(candidate.get('selected'), bool)):
            raise ValueError('Manual candidate does not match live image bindings')
    if answer['state'] == 'UNKNOWN' and (answer['channels'] or answer['manual']):
        raise ValueError('Unknown declaration must not enable controls')
    return answer


def describe(material, *, refresh=False):
    facts = facts_of(material)
    cached = None
    try:
        record = json.loads(material.get(RECORD, ''))
        if record['facts'] == facts:
            cached = _validate(record['answer'], facts)
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    if cached is not None and not refresh:
        return cached
    try:
        if cabmap_state.BRIDGE is None:
            raise ValueError('请连接匹配后端以识别新材质')
        answer = _validate(json.loads(cabmap_state.BRIDGE.game_data_blob(
            DATASET, payload=json.dumps(facts, allow_nan=False).encode('utf-8'))), facts)
        status = answer['state']
    except Exception as exc:
        reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        answer = cached if cached is not None else dict(schema=1, state='UNKNOWN', channels=[], manual=[])
        status = ('CACHED: ' if cached and cached['state'] == 'ready' else 'UNKNOWN: ') + reason
    if getattr(material, 'is_editable', True):
        material[RECORD] = json.dumps(dict(facts=facts, answer=answer), separators=(',', ':'), allow_nan=False)
        material[STATUS] = status
    return answer


def discover(material, *, refresh=False):
    declared = describe(material, refresh=refresh)['channels']
    entry, _groups = interface(material)
    values = entry['stack'].panel_read(material)['values'] if entry else {}
    return [dict(channel, enabled=bool(values.get(channel['gate'], False)) if channel['gate'] else False)
            for channel in declared]


def channel_of(material, kind):
    return next((channel for channel in discover(material) if channel['kind'] == kind), None)


def draw(layout, material, kind):
    channel = channel_of(material, kind)
    if channel is None:
        layout.label(text='通道已变化，请重新识别', icon='INFO')
        return
    material_panel.draw_subset(layout, material, None if channel['full_panel'] else channel['controls'])
