"""Loaded/empty weapon-state browser through the real Blender layout renderer.

Opt-in resource index supplied by args. No imports, saves, preferences or live UI.
The native target deliberately has no neutral-layout ``list`` method.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

parser=argparse.ArgumentParser()
for name in ('backend','deps','game','cabmap','output'):
    parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--addon-root',type=Path,default=Path(__file__).resolve().parents[1])
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.mkdir(parents=True,exist_ok=True)
sys.dont_write_bytecode=True
sys.path.insert(0,str(args.deps))
sys.path.insert(0,str(Path(__file__).parent))
os.environ['RURI_RIPPERHOOK_BIN']=str(args.backend)
os.environ['RURI_RIPPER_WORKSPACE']=str(args.output/'workspace')
from verify_weapon_catalog_blender import RecordingLayout
spec=importlib.util.spec_from_file_location('RuriRipperImporter',args.addon_root/'__init__.py',submodule_search_locations=[str(args.addon_root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
addon._DRIVER.reload_modules()
from RuriRipperImporter.Kernel import bootstrap
with patch.object(bootstrap,'configure'):addon._DRIVER.register()
import bpy
from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn,cabmap_state
from RuriRipperImporter.Kernel.app import browser,layout
from RuriRipperImporter.Host.Blender import render
from RuriRipperImporter.Game.Endfield import weapon,weapon_catalog as catalog
from RuriRipperImporter.Game.Endfield.Blender import weapon_states
pn.set_bin_dir(str(args.backend))
bridge=pn.RipperBridge('Endfield_1.6.0',str(args.game))
bridge.load_cab_map(str(args.cabmap),key='state-browser-test')
cabmap_state.BRIDGE=bridge
cabmap_state.activate('state-browser-test','Endfield')
cabmap_state.load_rows()
state=browser.state_of(bpy.context)
config=state.games.add();config.key='state-browser-test';config.game_name='Endfield'
config.game_root=str(args.game);config.decoder_id='Endfield_1.6.0'
state.current_tab=config.key;state.active_tab='Endfield:weapon'
getattr(bpy.context.scene,weapon.STATE).pane='states'
assert state.loaded
before=set(bpy.data.objects)
snapshots=[]
def draw_case(name,expected_list):
    target=RecordingLayout()
    assert not hasattr(target,'list')
    render.draw(layout.describe(weapon.draw_tab,bpy.context),target,bpy.context)
    assert all(('prop',key) in target.calls for key in ('appearance','deco','advanced','instance')),target.calls
    hidden=('import_inactive','game_shaders','import_empties','import_animations','retarget_face','import_secondary_motion')
    assert not any(('prop',key) in target.calls for key in hidden),target.calls
    advanced=getattr(bpy.context.scene,weapon_states.STATE).advanced
    assert all((('prop',key) in target.calls)==advanced for key in ('detail_level','import_shadow_proxies','deco_key'))
    assert ('operator','ruri.endfield_import_weapon_state',True) in target.calls,target.calls
    assert (('list','weapon_resources') in target.calls)==expected_list,target.calls
    snapshots.append(dict(case=name,resources=catalog.BOUND.count,calls=target.calls))
draw_case('not_scanned',False)
assert catalog._refresh(bpy.context,{}) is None
assert catalog.current(bpy.context) and catalog.BOUND.count>0
total=catalog.BOUND.count
draw_case('populated',True)
panel=catalog.state_of(bpy.context)
panel.search='fixture-no-matching-weapon';catalog.rebuild(panel)
assert catalog.BOUND.count==0
draw_case('empty_filter',True)
panel.search='';catalog.rebuild(panel)
assert catalog.BOUND.count==total
assert catalog._refresh(bpy.context,{}) is None
draw_case('refreshed',True)
getattr(bpy.context.scene,weapon_states.STATE).advanced=True
draw_case('advanced',True)
nav=getattr(bpy.context.scene,weapon.STATE)
assert [p[0] for p in weapon.PANES]==['states','mount','effects','glow']
nav['pane']=3
weapon_states.migrate_navigation()
assert nav.pane=='states'
assert set(bpy.data.objects)==before
report=dict(status='WEAPON_STATE_BROWSER_PASS',resources=total,cases=snapshots,objects_preserved=True,scene_saved=False,visual_acceptance=False)
(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('WEAPON_STATE_BROWSER_PASS',total,flush=True)
