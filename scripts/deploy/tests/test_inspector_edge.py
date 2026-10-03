import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).parents[1] / "enable_inspector_edge.py"
spec = importlib.util.spec_from_file_location("inspector_edge", path)
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)

class InspectorEdgeTests(unittest.TestCase):
    def test_narrow_route_preserves_other_sites_and_denials(self):
        before = "site {\n" + edge.MARKER + "\n}\nadmin-site { secret }\n"
        after = edge.update(before)
        self.assertIn(edge.MARKER, after)
        self.assertIn("method POST", after)
        self.assertIn("/inspector$", after)
        self.assertTrue(after.endswith("admin-site { secret }\n"))
        self.assertLess(after.index("handle @inspector"), after.index(edge.MARKER))
        self.assertEqual(edge.update(after), after)

    def test_unrecognized_config_fails_closed(self):
        for value in ["", edge.MARKER + "\n" + edge.MARKER]:
            with self.assertRaises(ValueError):
                edge.update(value)
