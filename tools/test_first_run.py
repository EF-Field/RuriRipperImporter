"""No bpy, pythonnet, configured backend or .NET runtime required."""
import importlib.util
from pathlib import Path
import unittest


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "Kernel/bridge/pythonnet_bridge.py"
        spec = importlib.util.spec_from_file_location("first_run_bridge", path)
        self.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)

    def test_locale_does_not_load_missing_runtime(self):
        def unexpected():
            self.fail("Locale preference attempted to load .NET")
        self.bridge._ensure_runtime = unexpected
        self.bridge.set_locale("zh_CN")
        self.assertEqual(self.bridge._locale, "zh_CN")
        self.assertIsNone(self.bridge._bridge_type)

    def test_loaded_bridge_receives_locale_changes(self):
        class Loaded:
            def SetLocale(self, locale):
                self.locale = locale
        loaded = Loaded()
        self.bridge._bridge_type = loaded
        self.bridge.set_locale("ja_JP")
        self.assertEqual(loaded.locale, "ja_JP")
        self.bridge.set_locale(None)
        self.assertEqual(loaded.locale, "")


if __name__ == "__main__":
    unittest.main()
