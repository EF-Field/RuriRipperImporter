"""Search follows the active tab's own row table, not the last enumerated map."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

import numpy as np
from test_import_completion import functions

ROOT = Path(__file__).resolve().parents[1]


class MapSearchTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'Kernel/bridge/pythonnet_bridge.py'
        spec = importlib.util.spec_from_file_location('map_search_bridge', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.bridge = object.__new__(module.RipperBridge)

    def test_later_enumeration_does_not_replace_explicit_search_table(self):
        first, second = object(), object()
        self.bridge.game_data = Mock(side_effect=[first, second])
        self.assertIs(self.bridge.enumerate_table(), first)
        self.assertIs(self.bridge.enumerate_table(), second)
        self.bridge.search_data_table = Mock(return_value=np.array([1, 0], dtype='<i4').tobytes())
        self.bridge._ordered = Mock(side_effect=lambda ids, *_: ids)
        result = self.bridge.search_table(first, 'sword', ('include',), 'name', 1)
        self.bridge.search_data_table.assert_called_once_with(first, 'sword', ('include',))
        np.testing.assert_array_equal(result, [1, 0])
        self.assertEqual(self.bridge._ordered.call_args.args[1:], ('name', 1))
        self.assertEqual(self.bridge.game_data.call_count, 2)

    def test_filter_forwards_active_rows_and_drops_out_of_range_ids(self):
        rows = ['first', 'second']
        active = NS(ROWS=rows, _sort_column='name', _sort_dir=2)
        bridge = NS(search_table=Mock(return_value=np.array([1, 20, 0], dtype=np.int32)))
        api = functions('Kernel/bridge/cabmap_state.py', ['apply_filter'], dict(ACTIVE=active, BRIDGE=bridge))
        api.apply_filter(' sword ', ['exclude'])
        bridge.search_table.assert_called_once_with(rows, 'sword', ('exclude',), 'name', 2)
        self.assertEqual(active.VISIBLE, [1, 0])
        self.assertEqual(active.CURRENT_SUBFOLDERS, [])

    def test_empty_active_table_does_not_search_another_map(self):
        active = NS(ROWS=[], _sort_column='', _sort_dir=0)
        bridge = NS(search_table=Mock())
        api = functions('Kernel/bridge/cabmap_state.py', ['apply_filter'], dict(ACTIVE=active, BRIDGE=bridge))
        api.apply_filter('sword')
        bridge.search_table.assert_not_called()
        self.assertEqual(active.VISIBLE, [])


if __name__ == '__main__':
    unittest.main()
