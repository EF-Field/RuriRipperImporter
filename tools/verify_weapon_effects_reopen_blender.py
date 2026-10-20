"""Clean, no-autoexec reopen of an externally supplied actual-resource fixture."""
import argparse
import json
from pathlib import Path
import sys


def main():
    import bpy
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    roots = [obj for obj in bpy.data.objects if 'ruri_effect_owner' in obj]
    assert len(roots) == 2
    actor = roots[0]['ruri_effect_owner']
    assert all(root['ruri_effect_owner'] == actor for root in roots)
    sockets = [obj for obj in bpy.data.objects if obj.get('ruri_weapon_owner') == actor]
    assert len(sockets) == 1
    weapon = next(obj for obj in sockets[0].children_recursive if obj.type == 'ARMATURE')
    assert actor.animation_data.action and weapon.animation_data.action
    assert actor.animation_data.action != weapon.animation_data.action
    report = dict(build_hash=bpy.app.build_hash.decode(), actual_resource_fixture=True,
                  no_autoexec=True, addon_registered=False, effects=[],
                  particle_playback='pending', event_timing='UNKNOWN', shader_appearance='not_tested')
    for root in roots:
        members = list(root['ruri_effect_members'])
        assert members and set(root.children_recursive) == set(members)
        text = root['ruri_effect_manifest']
        assert not text.use_module
        manifest = json.loads(text.as_string())
        assert manifest['source']['identity'] == root['ruri_effect_identity']
        assert manifest['particle_playback'] == 'pending'
        templates = [obj for obj in members if obj.get('ruri_effect_source_template')]
        assert len(templates) == int(root['ruri_effect_templates']) == 2
        assert all(obj.type == 'MESH' and len(obj.data.vertices) for obj in templates)
        report['effects'].append(dict(name=manifest['source']['name'], templates=len(templates),
                                      particles=int(root['ruri_effect_particles']),
                                      manifest_characters=len(text.as_string())))
    report['character_weapon_actions_independent'] = True
    report['metadata_meshes_id_pointers_survive'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('WEAPON_EFFECTS_REAL_REOPEN_PASS', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
