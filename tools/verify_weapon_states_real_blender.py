"""Opt-in source resource regression. All private fixtures are command arguments."""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

p=argparse.ArgumentParser()
for name in ('backend','deps','game','cabmap','output'):
    p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--weapon',required=True)
p.add_argument('--addon-root',type=Path,default=Path(__file__).resolve().parents[1])
args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.mkdir(parents=True,exist_ok=True)
sys.dont_write_bytecode=True
sys.path.insert(0,str(args.deps))
os.environ['RURI_RIPPERHOOK_BIN']=str(args.backend)
os.environ['RURI_RIPPER_WORKSPACE']=str(args.output/'workspace')
source=args.addon_root
spec=importlib.util.spec_from_file_location('RuriRipperImporter',source/'__init__.py',submodule_search_locations=[str(source)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
addon._DRIVER.reload_modules()
from RuriRipperImporter.Kernel import bootstrap
with patch.object(bootstrap,'configure'):addon._DRIVER.register()
import bpy
from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn,cabmap_state
from RuriRipperImporter.Game.Endfield import datasets
from RuriRipperImporter.Game.Endfield.Blender import weapon_states as states
pn.set_bin_dir(str(args.backend))
bridge=pn.RipperBridge('Endfield_1.6.0',str(args.game))
bridge.load_cab_map(str(args.cabmap),key='manual-state-test')
cabmap_state.BRIDGE=bridge
cabmap_state.activate('manual-state-test','Endfield')
catalog=datasets._rows(datasets.WEAPON_RESOURCES)
row,=[r for r in catalog if r['asset']==args.weapon and r['status']=='ready']
report={'status':'running','samples':[],'visual_acceptance':False,'addon_root':str(source),
        'backend':str(args.backend),'kernel_sha256':hashlib.sha256((args.backend/'Ruri.RipperHook.dll').read_bytes()).hexdigest(),
        'blender_version':bpy.app.version_string,'blender_hash':bpy.app.build_hash.decode()}
# An existing user's same-named material must retain name, graph and values.
sentinel=bpy.data.materials.new('M_wpn_sword_0022_01')
sentinel.use_nodes=True
sentinel['user_value']=17
sentinel_name=sentinel.name
sentinel_nodes=[(n.name,n.bl_idname) for n in sentinel.node_tree.nodes]
def assert_clock(material):
    tree=material.node_tree
    for node in tree.nodes:
        socket=node.inputs.get('_Time') if node.type=='GROUP' else None
        if socket is None:continue
        assert tree.animation_data and len(tree.animation_data.drivers)>=3
        scene=bpy.context.scene
        old=(scene.render.fps,scene.render.fps_base,scene.frame_current,scene.frame_subframe)
        for fps,base,frame,sub in ((24,1.,24,0.),(60,1.001,120,.5)):
            scene.render.fps=fps;scene.render.fps_base=base
            scene.frame_set(frame,subframe=sub);bpy.context.view_layer.update()
            expected=[(frame+sub)*base/fps*k for k in (.05,1.,2.)]
            assert all(abs(a-b)<1e-4 for a,b in zip(socket.default_value,expected)),(list(socket.default_value),expected)
        scene.render.fps,scene.render.fps_base=old[:2]
        scene.frame_set(old[2],subframe=old[3])
for appearance in ('base','refined'):
    for deco in ('none','gemDeco','gemMaxDeco'):
        root=states.import_state(bpy.context,row['seed'],appearance,deco)
        assert sentinel.name==sentinel_name and sentinel['user_value']==17
        assert sentinel_nodes==[(n.name,n.bl_idname) for n in sentinel.node_tree.nodes]
        manifest=json.loads(root[states.MANIFEST].as_string())
        plan=manifest['plan']
        targets=[o for o in root.children_recursive if o.type=='MESH' and '_vfx_' in o.get(states.SOURCE_NAME,'')]
        for o in targets:
            assert o.hide_render == (deco=='none' or not plan['materials'])
            assert len(o.material_slots)==len(plan['materials'])
            for slot,m in zip(o.material_slots,plan['materials']):
                assert slot.material['ruri_source_key']==m['source_key']
                assert slot.material.use_nodes and len(slot.material.node_tree.nodes)>1
        time_inputs=[]
        for m in {s.material for o in root.children_recursive for s in o.material_slots if s.material}:
            assert_clock(m)
            for n in m.node_tree.nodes:
                for socket in n.inputs:
                    if 'time' in socket.name.lower():
                        time_inputs.append(dict(material=m.name,node=n.name,input=socket.name,linked=socket.is_linked,
                            value=list(socket.default_value) if hasattr(socket,'default_value') and hasattr(socket.default_value,'__len__') else str(getattr(socket,'default_value',None))))
        report['samples'].append(dict(appearance=appearance,deco=deco,root=root.name,targets=[o.name for o in targets],
             effect_count=len(manifest['effects']),warnings=manifest['warnings'],time_inputs=time_inputs,
             native_shaders=[s.material.get('ruri_uber_shader','') for o in targets for s in o.material_slots if s.material]))
        (args.output/'real-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('STATE_IMPORTED',appearance,deco,flush=True)
path=args.output/'six-states-real.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(path),check_existing=False)
bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False)
roots=[o for o in bpy.data.objects if states.MANIFEST in o]
assert len(roots)==6
for root in roots:
    assert set(root.children_recursive)==set(root['ruri_weapon_state_members'])
    assert json.loads(root[states.MANIFEST].as_string())['plan']['deco'] in ('none','gemDeco','gemMaxDeco')
    for mat in {s.material for o in root.children_recursive for s in o.material_slots if s.material}:
        assert_clock(mat)
report['status']='WEAPON_STATES_REAL_PASS';report['reopen']=True
report['time_driver_numeric']=True;report['existing_material_preserved']=True
(args.output/'real-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('WEAPON_STATES_REAL_PASS',flush=True)
