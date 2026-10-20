"""Standalone regression for Unity step tangents; needs only NumPy, no host."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('clip_curves', Path(__file__).resolve().parents[1] / 'Kernel/unity/clip_curves.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Steps(unittest.TestCase):
    def test_step_has_finite_values_and_exact_key_boundaries(self):
        c = module.Channel('ctrl', np.array([0., 1., 2.]), np.array([[0.], [1.], [0.]]),
                           np.full((3, 1), np.inf), np.full((3, 1), np.inf))
        actual = c.sample(np.array([-1., 0., .5, 1., 1.5, 2., 3.]))
        np.testing.assert_array_equal(actual[:, 0], [0., 0., 0., 1., 1., 0., 0.])
        self.assertTrue(np.isfinite(actual).all())

    def test_mixed_components_keep_smooth_channels(self):
        c = module.Channel('mixed', np.array([0., 1.]), np.array([[0., 0.], [1., 1.]]),
                           np.array([[np.inf, 1.], [np.inf, 1.]]), np.array([[np.inf, 1.], [np.inf, 1.]]))
        np.testing.assert_allclose(c.sample(np.array([.25, .5, .75])), [[0., .25], [0., .5], [0., .75]])

    def test_finite_hermite_and_clamps_are_unchanged(self):
        c = module.Channel('smooth', np.array([0., 1.]), np.array([[0.], [1.]]),
                           np.zeros((2, 1)), np.zeros((2, 1)))
        np.testing.assert_allclose(c.sample(np.array([-1., 0., .25, .5, .75, 1., 2.]))[:, 0],
                                   [0., 0., .15625, .5, .84375, 1., 1.])

    def test_negative_infinite_tangent_is_also_constant(self):
        c = module.Channel('ctrl', np.array([0., 1.]), np.array([[.2], [.8]]),
                           np.zeros((2, 1)), np.array([[-np.inf], [0.]]))
        np.testing.assert_allclose(c.sample(np.array([.2, .8, 1.]))[:, 0], [.2, .2, .8])


if __name__ == '__main__':
    unittest.main()
