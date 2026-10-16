"""Clean background reopen: packed pixels and material links survive without addon."""
import argparse
import json
from pathlib import Path
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    import bpy
    assert bpy.app.background and bpy.app.build_hash == b'73cfbda0a06d'
    bpy.context.preferences.filepaths.recent_files = 0
    report = json.loads(args.report.read_text(encoding='utf-8'))
    assert not any('RuriRipperImporter' in name for name in sys.modules)
    bpy.ops.wm.open_mainfile(filepath=report['saved_blend'], load_ui=False, use_scripts=False)
    checked = []
    for expected in report['expected_images']:
        image = bpy.data.images[expected['name']]
        assert image.packed_file
        assert list(image.size) == expected['size']
        assert image.has_data and len(image.pixels) > 0
        checked.append(image.name)
    meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']
    assert len(meshes) == sum(row['meshes'] for row in report['source_imports'])
    mats = {slot.material for obj in meshes for slot in obj.material_slots if slot.material}
    assert mats
    for mat in mats:
        assert mat.node_tree and mat.node_tree.links
        for image in mat.get('ruri_uber_images', {}).values():
            assert image is None or image.name in bpy.data.images
    result = dict(status='WEAPON_CATALOG_REOPEN_PASS',
                  no_addon_loaded=True, no_autoexec=True, packed_source_images=len(checked),
                  meshes=len(meshes), materials=len(mats), visual_acceptance=False)
    (args.report.parent / 'reopen-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('WEAPON_CATALOG_REOPEN_PASS', json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
