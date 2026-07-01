"""
Unit tests for autonomous_gltf_avatar.GLTFModel — the glTF vertex/animation
loader used by AutonomousGLTFAvatarViewer.

GLTFModel is a plain Python class with no Qt/OpenGL coupling in its own
logic (only draw() calls GL functions, and only after an early-return guard
for empty geometry), so it is directly testable without a display, without
PyQt5, and without pygltflib/numpy installed — load_gltf() gracefully
no-ops when those optional dependencies are absent (see optional_deps.py).
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from autonomous_gltf_avatar import GLTFModel  # noqa: E402


class GLTFModelMissingDepsTests(unittest.TestCase):
    """load_gltf() must degrade gracefully when pygltflib/numpy are unavailable
    (or the file doesn't exist / isn't a valid glTF), rather than raising."""

    def test_construct_with_nonexistent_file_does_not_raise(self):
        model = GLTFModel("/nonexistent/path/to/file.gltf")
        self.assertEqual(model.vertices, [])
        self.assertEqual(model.faces, [])
        self.assertEqual(model.animations, [])

    def test_filename_stored(self):
        model = GLTFModel("/some/path.glb")
        self.assertEqual(model.filename, "/some/path.glb")

    def test_initial_animation_state(self):
        model = GLTFModel("/nonexistent.gltf")
        self.assertEqual(model.current_animation, 0)
        self.assertEqual(model.current_time, 0.0)

    def test_draw_on_empty_model_does_not_raise(self):
        """draw() must early-return without touching undefined GL names when
        there is no geometry to render (OpenGL may not even be importable)."""
        model = GLTFModel("/nonexistent.gltf")
        model.draw()  # must not raise NameError/AttributeError


class GLTFModelAnimationAdvanceTests(unittest.TestCase):
    """advance_animation() drives current_time forward and loops back to 0.0
    once it passes the last keyframe time of the active channel."""

    def _model_with_fake_animation(self, times):
        model = GLTFModel("/nonexistent.gltf")
        model.animations = [{
            "channels": [{
                "target": "translation",
                "times": times,
                "values": [],
                "interpolation": "LINEAR",
            }]
        }]
        model.current_time = 0.0
        return model

    def test_time_accumulates_while_under_duration(self):
        model = self._model_with_fake_animation([0.0, 0.5, 1.0])
        model.advance_animation(0.3, 0)
        self.assertAlmostEqual(model.current_time, 0.3)
        model.advance_animation(0.3, 0)
        self.assertAlmostEqual(model.current_time, 0.6)

    def test_time_loops_to_zero_past_last_keyframe(self):
        model = self._model_with_fake_animation([0.0, 0.5, 1.0])
        model.current_time = 0.9
        model.advance_animation(0.5, 0)  # 0.9 + 0.5 = 1.4 > 1.0 -> loop
        self.assertEqual(model.current_time, 0.0)

    def test_time_at_exact_boundary_does_not_loop(self):
        """current_time == times[-1] is not > times[-1], so it must not loop yet."""
        model = self._model_with_fake_animation([0.0, 0.5, 1.0])
        model.current_time = 0.5
        model.advance_animation(0.5, 0)  # exactly 1.0
        self.assertAlmostEqual(model.current_time, 1.0)

    def test_time_still_accumulates_without_any_animations(self):
        """With no animations loaded, current_time must still advance (only
        the loop-reset logic is gated behind `if self.animations`)."""
        model = GLTFModel("/nonexistent.gltf")
        self.assertEqual(model.animations, [])
        model.advance_animation(0.25)
        self.assertAlmostEqual(model.current_time, 0.25)

    def test_advance_animation_default_anim_idx_is_zero(self):
        model = self._model_with_fake_animation([0.0, 1.0])
        model.advance_animation(0.1)  # anim_idx defaults to 0
        self.assertAlmostEqual(model.current_time, 0.1)


if __name__ == "__main__":
    unittest.main()
