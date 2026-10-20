"""Exercise the real cast command without importing the Blender add-on entrypoint."""
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("cast_test_addon")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
host = importlib.import_module("cast_test_addon.Kernel.host")
with patch.object(host, "current", return_value=SimpleNamespace(capabilities=frozenset())):
    cast = importlib.import_module("cast_test_addon.Kernel.app.cast_panel")
    browser = importlib.import_module("cast_test_addon.Kernel.app.browser")


class FindAnimationsTests(unittest.TestCase):
    def test_query_is_forwarded_without_loading_clips(self):
        context = object()
        state = SimpleNamespace(status="")
        rules = [{"field": "path", "relation": "contains", "value": "actor/animations"}]
        panel = SimpleNamespace(
            animation_rules=lambda c, s: (iter(rules), "Actor animations"),
            state_for=lambda c: state,
            bound=SimpleNamespace(picked=lambda s: SimpleNamespace(label="Actor")))
        with patch.object(cast, "_panel", return_value=panel), patch.object(browser, "show_rules") as show:
            self.assertIsNone(cast._find_animations(context, {}))
            show.assert_called_once_with(context, rules)
            self.assertEqual(state.status, "Actor animations")

    def test_missing_animation_query_cancels_cleanly(self):
        state = SimpleNamespace(status="")
        panel = SimpleNamespace(animation_rules=lambda c, s: None,
            state_for=lambda c: state,
            bound=SimpleNamespace(picked=lambda s: SimpleNamespace(label="Actor")))
        with patch.object(cast, "_panel", return_value=panel), patch.object(browser, "show_rules") as show:
            self.assertEqual(cast._find_animations(object(), {}), {"CANCELLED"})
            show.assert_not_called()
            self.assertIn("No animation folder", state.status)

    def test_real_browser_receives_and_replaces_filters(self):
        class Rules(list):
            def add(self):
                item = SimpleNamespace()
                self.append(item)
                return item
        context = object()
        browser_state = SimpleNamespace(active_tab="character", search="old search",
            filter_rules=Rules([SimpleNamespace(value="old rule")]))
        cast_state = SimpleNamespace(status="")
        rule = {"field": "path", "relation": "contains", "value": "actor/animations"}
        panel = SimpleNamespace(animation_rules=lambda c, s: ([rule], "Animations"),
            state_for=lambda c: cast_state,
            bound=SimpleNamespace(picked=lambda s: SimpleNamespace(label="Actor")))
        with patch.object(cast, "_panel", return_value=panel), \
             patch.object(browser, "state_of", return_value=browser_state), \
             patch.object(browser, "_reapply_and_refresh") as refresh:
            self.assertIsNone(cast._find_animations(context, {}))
            self.assertEqual(browser_state.active_tab, browser.BROWSER_TAB_ID)
            self.assertEqual(browser_state.search, "")
            self.assertEqual(len(browser_state.filter_rules), 1)
            self.assertEqual(browser_state.filter_rules[0].value, rule["value"])
            self.assertTrue(browser_state.filter_rules[0].enabled)
            refresh.assert_called_once_with(context)


if __name__ == "__main__":
    unittest.main()
