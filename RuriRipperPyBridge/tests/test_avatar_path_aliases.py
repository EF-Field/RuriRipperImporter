import unittest
from RuriRipperPyBridge.unity.clip_paths import avatar_path_aliases, repair_hashed_clip_paths, entry_crc
from RuriRipperPyBridge.unity.clip_curves import ClipCurves, Channel
import numpy as np


class AvatarPathAliasesTests(unittest.TestCase):
    def avatar(self, paths):
        return {"m_TOS": [{"second": p} for p in paths]}

    def test_renamed_joint_anchored_by_parent_and_child(self):
        paths = ["Root", "Root/P", "Root/P/Old", "Root/P/Old/Tip"]
        target = {p: p for p in ["Root", "Root/P", "Root/P/New", "Root/P/New/Tip"]}
        aliases = avatar_path_aliases(self.avatar(paths), target)
        self.assertEqual(aliases, {"Root/P/Old": "Root/P/New", "Root/P/Old/Tip": "Root/P/New/Tip"})
        self.assertEqual(avatar_path_aliases({"m_TOS": dict(enumerate(paths + [None, ""]))}, target), aliases)
        clip = ClipCurves()
        clip.rotations.append(Channel(f'path_0x{entry_crc("Root/P/Old"):08X}_test', np.array([0.]), np.array([[0,0,0,1.]]), np.zeros((1,4)), np.zeros((1,4))))
        self.assertEqual(repair_hashed_clip_paths(clip, target, aliases), (1, 0))
        self.assertEqual(clip.rotations[0].path, "Root/P/New")

    def test_ambiguous_descendants_are_not_guessed(self):
        source = self.avatar(["Root", "Root/P", "Root/P/Old", "Root/P/Old/Tip"])
        target = {p: p for p in ["Root", "Root/P", "Root/P/A", "Root/P/A/Tip", "Root/P/B", "Root/P/B/Tip"]}
        self.assertEqual(avatar_path_aliases(source, target), {})

    def test_no_descendant_evidence_is_not_a_match(self):
        self.assertEqual(avatar_path_aliases(self.avatar(["Root", "Root/Old"]), {"Root": "r", "Root/New": "n"}), {})

    def test_existing_paths_unchanged(self):
        paths = ["Root", "Root/P", "Root/P/Tip"]
        self.assertEqual(avatar_path_aliases(self.avatar(paths), dict.fromkeys(paths)), {})
