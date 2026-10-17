"""Native controls on host materials, not asset parsing or weapon-name rules.

Only the owning generated stack can claim a graph, enumerate live sockets and
write its parameters. This projection never invents a shader or a VFX binding.
"""
from ....Host.Blender import material_panel

# Existing graph interfaces, not inferred texture roles. A bound source image
# AND a live switch are required; mere default parameter declarations prove no
# usable input. The full source shader remains responsible for channel math.
PROFILES = {
    'EMISSION': ('原生自发光', '_UseEmission', '_EmissionMap',
                 ('_UseEmission', '_EmissionColor', '_EmissionBrightness', '_EmissionMapUVSpeed',
                  '_EmissionAlphaBrightBreath', '_EmissionAlphaBrightBreathSpeed',
                  '_EmissionAlphaBrightBreathScaleMin', '_EmissionAlphaBrightBreathScaleMax')),
    'PARALLAX': ('原生视差纹理', '_UseParallax', '_ParallaxTex',
                 ('_UseParallax', '_ParallaxColor', '_ParallaxMarchNum', '_ParallaxScale', '_ParallaxUseNormal')),
    'LIT_EMISSION': ('原生自发光', '_EnableEmissiveMap', '_EmissiveMap',
                     ('_EnableEmissiveMap', '_EmissiveColor', '_EmissiveMaskChannel',
                      '_EmissiveIntensity', '_AlbedoAffectEmissive')),
    'LIT_PARALLAX': ('原生视差', '_EnableParallaxMap', '_ParallaxMap',
                     ('_EnableParallaxMap', '_ParallaxColor', '_ParallaxColorDark',
                      '_ParallaxStrength', '_ParallaxMarchNum', '_ParallaxTilling')),
}


def interface(material):
    entry = material_panel.stack_of(material)
    if entry is None:
        return None, []
    return entry, entry['stack'].panel_rows(material)


def discover(material):
    entry, groups = interface(material)
    if entry is None:
        return []
    names = {r['name'] for g in groups for r in g['rows']}
    images = material.get('ruri_uber_images', {})
    values = entry['stack'].panel_read(material)['values']
    channels = []
    for kind, (label, gate, image, controls) in PROFILES.items():
        if gate in names and images.get(image):
            channels.append(dict(kind=kind, label=label, gate=gate,
                enabled=bool(values.get(gate, False)), image=image))
    # The stack's own variant/shader identity, never a mesh/material name.
    meta = entry['stack'].PART_META.get(material.get('ruri_uber_part', ''), {})
    shader = meta.get('shader', '')
    if shader == 'HGRP/CharacterNPR_VFX' or shader.startswith('HGRP/Effect/'):
        channels.append(dict(kind='VFX', label='原生特效材质 · 不等同自发光',
                             gate='', enabled=False, image=''))
    return channels


def draw(layout, material, kind):
    if kind == 'VFX':
        material_panel.draw_subset(layout, material)
    else:
        material_panel.draw_subset(layout, material, PROFILES[kind][3])
