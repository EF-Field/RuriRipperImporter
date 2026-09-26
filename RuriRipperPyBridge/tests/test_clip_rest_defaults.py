"""Rest defaults fill missing translations without replacing authored motion."""
import json
import unittest
import numpy as np
from ..unity.clip_curves import Channel, ClipCurves, merge_solved


class RestDefaultTests(unittest.TestCase):
    def channel(self, path, xyz):
        return Channel(path, np.array([0.]), np.array([xyz]), np.zeros((1,3)), np.zeros((1,3)))

    def test_authored_position_and_helpers_survive(self):
        clip, solved = ClipCurves(), ClipCurves()
        authored, helper = self.channel('pelvis',[1,2,3]), self.channel('helper',[4,5,6])
        clip.positions = [authored,helper]
        solved.positions = [self.channel('pelvis',[0,0,0]),self.channel('hips',[7,8,9])]
        solved.rest_position_paths = {'pelvis'}
        merge_solved(clip,solved,[])
        self.assertIs(clip.positions[0],authored)
        self.assertIs(clip.positions[1],helper)
        self.assertEqual(len(clip.positions),3)

    def test_missing_position_receives_default(self):
        clip, solved = ClipCurves(), ClipCurves()
        solved.positions = [self.channel('pelvis',[0,0,0])]
        solved.rest_position_paths = {'pelvis'}
        merge_solved(clip,solved,[])
        self.assertEqual([c.path for c in clip.positions],['pelvis'])

    def test_old_blobs_remain_compatible(self):
        clip=ClipCurves.from_blob(json.dumps({'curves':[]}),b'')
        self.assertEqual(clip.rest_position_paths,set())

    def test_new_metadata_roundtrip(self):
        clip=ClipCurves.from_blob(json.dumps({'curves':[],'restPositionPaths':['pelvis']}),b'')
        self.assertEqual(clip.rest_position_paths,{'pelvis'})
