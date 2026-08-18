"""
Tests for the glTF face/normal path added for work order W-08 (shaded solids).

The avatar rendered as a GL_LINE_STRIP through the raw vertex list — a
scribble, not a figure — because nothing ever read the index buffer. Adding
that surfaced a second, worse problem in the vertex loader itself, which these
tests pin down first:

**Interleaved models were being read wrong.** `bufferView.byteStride` was
ignored, so on any glTF that packs POSITION and NORMAL into one buffer view
(the spec *requires* byteStride whenever two accessors share a view, and many
exporters do interleave) the loader read normal components as coordinates.
InterleavedBufferTests builds exactly that file and asserts the values.

The rest follows the glTF 2.0 spec:
  - primitive.mode defaults to 4 (TRIANGLES); 5/6 are strip/fan and expand to
    triangle lists; 0-3 are points/lines and have no faces;
  - index accessors are SCALAR with componentType 5121/5123/5125 (5125 being
    indices-only);
  - a primitive without `indices` has an implicit 0..count-1 sequence;
  - "When normals are not specified, client implementations MUST calculate
    flat normals" — compute_face_normals is that calculation.

Everything here runs headless: shade_factor is a pure function and no GL
context is created.

Run: python -m unittest tests.test_gltf_faces -v
"""
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)

import gltf_utils  # noqa: E402


def _deps():
    try:
        import numpy  # noqa: F401
        import pygltflib  # noqa: F401
        return True
    except ImportError:
        return False


class ShadeFactorTests(unittest.TestCase):
    """Pure Lambert-ish diffuse term — no GPU, no GL state."""

    def test_facing_the_light_is_brightest(self):
        k = gltf_utils.shade_factor((1.0, 0.0, 0.0), light_dir=(1.0, 0.0, 0.0))
        self.assertAlmostEqual(k, 1.0, places=6)

    def test_facing_away_falls_back_to_ambient(self):
        k = gltf_utils.shade_factor((-1.0, 0.0, 0.0), light_dir=(1.0, 0.0, 0.0),
                                    ambient=0.35)
        self.assertAlmostEqual(k, 0.35, places=6)

    def test_never_returns_black(self):
        """A face turned away must stay visible, not vanish into the背景."""
        for normal in ((-1, 0, 0), (0, -1, 0), (0, 0, -1)):
            self.assertGreater(gltf_utils.shade_factor(normal), 0.0)

    def test_always_within_ambient_and_one(self):
        import itertools
        for normal in itertools.product((-1, 0, 1), repeat=3):
            if normal == (0, 0, 0):
                continue
            k = gltf_utils.shade_factor(normal, ambient=0.35)
            self.assertGreaterEqual(k, 0.35 - 1e-6, normal)
            self.assertLessEqual(k, 1.0 + 1e-6, normal)

    def test_magnitude_does_not_matter_only_direction(self):
        a = gltf_utils.shade_factor((0.0, 0.0, 1.0))
        b = gltf_utils.shade_factor((0.0, 0.0, 7.0))
        self.assertAlmostEqual(a, b, places=6)

    def test_degenerate_inputs_return_ambient(self):
        self.assertAlmostEqual(gltf_utils.shade_factor((0, 0, 0), ambient=0.4), 0.4)
        self.assertAlmostEqual(
            gltf_utils.shade_factor((1, 0, 0), light_dir=(0, 0, 0), ambient=0.4), 0.4)
        self.assertAlmostEqual(gltf_utils.shade_factor(None, ambient=0.4), 0.4)
        self.assertAlmostEqual(gltf_utils.shade_factor(("x", 0, 0), ambient=0.4), 0.4)


@unittest.skipUnless(_deps(), "numpy/pygltflib not installed")
class ComputeFaceNormalsTests(unittest.TestCase):
    def test_unit_normal_of_a_known_triangle(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        out = gltf_utils.compute_face_normals(verts, faces, np)
        self.assertTrue(np.allclose(out, [[0, 0, 1]], atol=1e-6))

    def test_winding_determines_direction(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        ccw = gltf_utils.compute_face_normals(verts, np.array([[0, 1, 2]]), np)
        cw = gltf_utils.compute_face_normals(verts, np.array([[0, 2, 1]]), np)
        self.assertTrue(np.allclose(ccw, -cw, atol=1e-6))

    def test_all_normals_are_unit_length(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [3, 0, 0], [0, 4, 0], [0, 0, 5]],
                         dtype=np.float32)
        faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]],
                         dtype=np.uint32)
        out = gltf_utils.compute_face_normals(verts, faces, np)
        lengths = np.sqrt((out * out).sum(axis=1))
        self.assertTrue(np.allclose(lengths, 1.0, atol=1e-5))

    def test_degenerate_triangle_gets_a_usable_normal(self):
        """Zero-area faces would divide by zero and blow up the shading."""
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32)
        out = gltf_utils.compute_face_normals(verts, np.array([[0, 1, 2]]), np)
        self.assertIsNotNone(out)
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertAlmostEqual(float(np.sqrt((out[0] * out[0]).sum())), 1.0, places=5)

    def test_invalid_inputs_return_none(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        self.assertIsNone(gltf_utils.compute_face_normals(None, None, np))
        self.assertIsNone(gltf_utils.compute_face_normals(verts, None, np))
        self.assertIsNone(gltf_utils.compute_face_normals(
            verts, np.empty((0, 3), dtype=np.uint32), np))
        # index past the end of the vertex array
        self.assertIsNone(gltf_utils.compute_face_normals(
            verts, np.array([[0, 1, 99]], dtype=np.uint32), np))


@unittest.skipUnless(_deps(), "numpy/pygltflib not installed")
class _GlbBuilder(unittest.TestCase):
    """Builds real .glb files with pygltflib — stubs cannot catch API drift."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _save(self, gltf, blob, name):
        gltf.set_binary_blob(blob)
        path = os.path.join(self._tmp, name)
        gltf.save_binary(path)
        import pygltflib
        return pygltflib.GLTF2().load(path)

    def _indexed_glb(self, verts, indices, component_type, mode=None, name="m.glb"):
        """POSITION + an index buffer, in two separate buffer views."""
        import numpy as np
        import pygltflib
        dtype = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[component_type]
        vbytes = verts.astype(np.float32).tobytes()
        ibytes = np.asarray(indices, dtype=dtype).tobytes()
        # bufferView byteOffsets must respect 4-byte alignment for safety
        pad = (-len(vbytes)) % 4
        blob = vbytes + b"\x00" * pad + ibytes
        primitive = pygltflib.Primitive(
            attributes=pygltflib.Attributes(POSITION=0), indices=1)
        if mode is not None:
            primitive.mode = mode
        gltf = pygltflib.GLTF2(
            scene=0,
            scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[primitive])],
            accessors=[
                pygltflib.Accessor(bufferView=0, componentType=pygltflib.FLOAT,
                                   count=len(verts), type=pygltflib.VEC3),
                pygltflib.Accessor(bufferView=1, componentType=component_type,
                                   count=len(indices), type=pygltflib.SCALAR),
            ],
            bufferViews=[
                pygltflib.BufferView(buffer=0, byteOffset=0,
                                     byteLength=len(vbytes)),
                pygltflib.BufferView(buffer=0, byteOffset=len(vbytes) + pad,
                                     byteLength=len(ibytes)),
            ],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        return self._save(gltf, blob, name)


class InterleavedBufferTests(_GlbBuilder):
    """byteStride: the bug that made real models render as garbage.

    The spec requires byteStride whenever two accessors share a buffer view, so
    POSITION and NORMAL packed together is ordinary, not exotic. Reading 12
    bytes at a time through such a view yields position[0], then normal[0] as
    if it were position[1] — the model comes out scrambled.
    """

    def _interleaved_glb(self, positions, normals):
        import numpy as np
        import pygltflib
        inter = np.hstack([positions, normals]).astype(np.float32)
        blob = inter.tobytes()
        stride = 24  # two VEC3 float32
        gltf = pygltflib.GLTF2(
            scene=0,
            scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=0, NORMAL=1))])],
            accessors=[
                pygltflib.Accessor(bufferView=0, byteOffset=0,
                                   componentType=pygltflib.FLOAT,
                                   count=len(positions), type=pygltflib.VEC3),
                pygltflib.Accessor(bufferView=0, byteOffset=12,
                                   componentType=pygltflib.FLOAT,
                                   count=len(normals), type=pygltflib.VEC3),
            ],
            bufferViews=[pygltflib.BufferView(
                buffer=0, byteOffset=0, byteLength=len(blob), byteStride=stride)],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        return self._save(gltf, blob, "interleaved.glb")

    def test_positions_are_not_contaminated_by_normals(self):
        import numpy as np
        positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        normals = np.array([[0, 0, 1]] * 3, dtype=np.float32)
        g = self._interleaved_glb(positions, normals)
        out = gltf_utils.load_first_mesh_vertices(g, np)
        self.assertIsNotNone(out)
        self.assertEqual(out.shape, (3, 3))
        self.assertTrue(np.allclose(out, positions, atol=1e-6),
                        f"interleaved POSITION misread: {out.tolist()}")

    def test_normals_read_from_the_same_view(self):
        import numpy as np
        positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        normals = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]], dtype=np.float32)
        g = self._interleaved_glb(positions, normals)
        out = gltf_utils.load_first_mesh_normals(g, np)
        self.assertIsNotNone(out)
        self.assertTrue(np.allclose(out, normals, atol=1e-6))

    def test_tightly_packed_still_works(self):
        """byteStride equal to the element size must behave as before."""
        import numpy as np
        import pygltflib
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = verts.tobytes()
        gltf = pygltflib.GLTF2(
            scene=0, scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=0))])],
            accessors=[pygltflib.Accessor(
                bufferView=0, componentType=pygltflib.FLOAT, count=3,
                type=pygltflib.VEC3)],
            bufferViews=[pygltflib.BufferView(
                buffer=0, byteOffset=0, byteLength=len(blob), byteStride=12)],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        g = self._save(gltf, blob, "packed.glb")
        out = gltf_utils.load_first_mesh_vertices(g, np)
        self.assertTrue(np.allclose(out, verts, atol=1e-6))


class LoadFacesTests(_GlbBuilder):
    def test_unsigned_short_indices_round_trip(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                         dtype=np.float32)
        indices = [0, 1, 2, 1, 3, 2]
        g = self._indexed_glb(verts, indices, 5123)
        faces = gltf_utils.load_first_mesh_faces(g, np)
        self.assertIsNotNone(faces)
        self.assertEqual(faces.tolist(), [[0, 1, 2], [1, 3, 2]])

    def test_unsigned_byte_indices(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2], 5121, name="u8.glb")
        self.assertEqual(gltf_utils.load_first_mesh_faces(g, np).tolist(),
                         [[0, 1, 2]])

    def test_unsigned_int_indices(self):
        """5125 is legal only for indices — a large mesh needs it."""
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2], 5125, name="u32.glb")
        self.assertEqual(gltf_utils.load_first_mesh_faces(g, np).tolist(),
                         [[0, 1, 2]])

    def test_explicit_triangles_mode(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2], 5123,
                              mode=gltf_utils.MODE_TRIANGLES, name="tri.glb")
        self.assertEqual(gltf_utils.load_first_mesh_faces(g, np).tolist(),
                         [[0, 1, 2]])

    def test_triangle_strip_expands_with_alternating_winding(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                         dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2, 3], 5123,
                              mode=gltf_utils.MODE_TRIANGLE_STRIP,
                              name="strip.glb")
        faces = gltf_utils.load_first_mesh_faces(g, np)
        # every other triangle is flipped so all of them face the same way
        self.assertEqual(faces.tolist(), [[0, 1, 2], [1, 3, 2]])

    def test_triangle_strip_normals_all_point_the_same_way(self):
        """That flip is the whole point — otherwise half the surface goes dark."""
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                         dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2, 3], 5123,
                              mode=gltf_utils.MODE_TRIANGLE_STRIP,
                              name="strip2.glb")
        faces = gltf_utils.load_first_mesh_faces(g, np)
        normals = gltf_utils.compute_face_normals(
            gltf_utils.load_first_mesh_vertices(g, np), faces, np)
        self.assertTrue(np.allclose(normals[0], normals[1], atol=1e-6),
                        f"strip winding not corrected: {normals.tolist()}")

    def test_triangle_fan_expands_around_the_hub(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                         dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2, 3], 5123,
                              mode=gltf_utils.MODE_TRIANGLE_FAN, name="fan.glb")
        self.assertEqual(gltf_utils.load_first_mesh_faces(g, np).tolist(),
                         [[0, 1, 2], [0, 2, 3]])

    def test_point_and_line_modes_have_no_faces(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        for mode in (0, 1, 2, 3):
            g = self._indexed_glb(verts, [0, 1, 2], 5123, mode=mode,
                                  name=f"mode{mode}.glb")
            self.assertIsNone(gltf_utils.load_first_mesh_faces(g, np), mode)

    def test_out_of_range_indices_are_dropped(self):
        """A truncated or hand-edited model must not crash the renderer."""
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2, 0, 1, 99], 5123, name="oob.glb")
        faces = gltf_utils.load_first_mesh_faces(g, np)
        self.assertEqual(faces.tolist(), [[0, 1, 2]])

    def test_trailing_partial_triangle_is_ignored(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        g = self._indexed_glb(verts, [0, 1, 2, 0, 1], 5123, name="partial.glb")
        self.assertEqual(gltf_utils.load_first_mesh_faces(g, np).tolist(),
                         [[0, 1, 2]])

    def test_implicit_indices_when_primitive_has_none(self):
        import numpy as np
        import pygltflib
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
                          [2, 0, 0], [2, 1, 0]], dtype=np.float32)
        blob = verts.tobytes()
        gltf = pygltflib.GLTF2(
            scene=0, scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=0))])],
            accessors=[pygltflib.Accessor(
                bufferView=0, componentType=pygltflib.FLOAT, count=len(verts),
                type=pygltflib.VEC3)],
            bufferViews=[pygltflib.BufferView(
                buffer=0, byteOffset=0, byteLength=len(blob))],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        g = self._save(gltf, blob, "noindex.glb")
        self.assertEqual(gltf_utils.load_first_mesh_faces(g, np).tolist(),
                         [[0, 1, 2], [3, 4, 5]])

    def test_too_few_vertices_has_no_faces(self):
        import numpy as np
        import pygltflib
        verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        blob = verts.tobytes()
        gltf = pygltflib.GLTF2(
            scene=0, scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=0))])],
            accessors=[pygltflib.Accessor(
                bufferView=0, componentType=pygltflib.FLOAT, count=2,
                type=pygltflib.VEC3)],
            bufferViews=[pygltflib.BufferView(
                buffer=0, byteOffset=0, byteLength=len(blob))],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        g = self._save(gltf, blob, "twoverts.glb")
        self.assertIsNone(gltf_utils.load_first_mesh_faces(g, np))

    def test_no_mesh_returns_none(self):
        import numpy as np
        import pygltflib
        self.assertIsNone(gltf_utils.load_first_mesh_faces(pygltflib.GLTF2(), np))


class GuiGeometryWiringTests(_GlbBuilder):
    """_load_model_geometry — what the flagship GUI actually calls."""

    def _atts(self):
        import avatar_3d_autonomous_tts as atts
        return atts

    def test_returns_vertices_faces_and_normals(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=np.float32)
        path = os.path.join(self._tmp, "solid.glb")
        self._indexed_glb(verts, [0, 1, 2], 5123, name="solid.glb")
        geometry = self._atts()._load_model_geometry(path)
        self.assertIsNotNone(geometry)
        vertices, faces, normals = geometry
        self.assertEqual(vertices.shape, (3, 3))
        self.assertEqual(faces.tolist(), [[0, 1, 2]])
        self.assertEqual(normals.shape, (1, 3))
        # normalized vertices: centred, max radius 1
        self.assertTrue(np.allclose(vertices.mean(axis=0), 0, atol=1e-5))

    def test_point_only_model_falls_back_to_wireframe(self):
        """No faces means the old GL_LINE_STRIP path, not a crash."""
        import numpy as np
        import pygltflib
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = verts.tobytes()
        gltf = pygltflib.GLTF2(
            scene=0, scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=0), mode=0)])],
            accessors=[pygltflib.Accessor(
                bufferView=0, componentType=pygltflib.FLOAT, count=3,
                type=pygltflib.VEC3)],
            bufferViews=[pygltflib.BufferView(
                buffer=0, byteOffset=0, byteLength=len(blob))],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        self._save(gltf, blob, "points.glb")
        geometry = self._atts()._load_model_geometry(
            os.path.join(self._tmp, "points.glb"))
        self.assertIsNotNone(geometry)
        vertices, faces, normals = geometry
        self.assertIsNotNone(vertices)
        self.assertIsNone(faces)
        self.assertIsNone(normals)

    def test_legacy_vertices_helper_still_works(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=np.float32)
        self._indexed_glb(verts, [0, 1, 2], 5123, name="legacy.glb")
        out = self._atts()._load_model_vertices(
            os.path.join(self._tmp, "legacy.glb"))
        self.assertIsNotNone(out)
        self.assertEqual(out.shape, (3, 3))

    def test_missing_file_returns_none(self):
        self.assertIsNone(
            self._atts()._load_model_geometry(os.path.join(self._tmp, "nope.glb")))
        self.assertIsNone(self._atts()._load_model_geometry(None))


class PaintSolidTests(unittest.TestCase):
    """paintGL's solid path, with the GL calls captured instead of executed."""

    def setUp(self):
        if not _deps():
            self.skipTest("numpy/pygltflib not installed")
        import avatar_3d_autonomous_tts as atts
        self.atts = atts
        self.viewer = object.__new__(atts.AutonomousAvatarViewer)

    def _capture(self, vertices, faces, normals):
        """Run _paint_solid with the GL entry points stubbed out.

        create=True because the GL names reach the module through
        `from OpenGL.GL import *` in optional_deps — with PyOpenGL absent (CI,
        headless) they are simply not bound, and the real paintGL is never
        reached without a GL context anyway.
        """
        from unittest import mock
        calls = {"vertex": [], "color": []}
        with mock.patch.object(self.atts, "glBegin", lambda *_: None,
                               create=True), \
             mock.patch.object(self.atts, "glEnd", lambda *_: None,
                               create=True), \
             mock.patch.object(self.atts, "glVertex3f",
                               lambda *a: calls["vertex"].append(a),
                               create=True), \
             mock.patch.object(self.atts, "glColor3f",
                               lambda *a: calls["color"].append(a),
                               create=True), \
             mock.patch.object(self.atts, "GL_TRIANGLES", 4, create=True):
            self.viewer._paint_solid(vertices, faces, normals)
        return calls

    def test_emits_three_vertices_per_face(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                         dtype=np.float32)
        faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32)
        normals = gltf_utils.compute_face_normals(verts, faces, np)
        calls = self._capture(verts, faces, normals)
        self.assertEqual(len(calls["vertex"]), 6)
        self.assertEqual(len(calls["color"]), 2)

    def test_shading_varies_between_differently_angled_faces(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                         dtype=np.float32)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
        normals = gltf_utils.compute_face_normals(verts, faces, np)
        colours = self._capture(verts, faces, normals)["color"]
        self.assertNotEqual(colours[0], colours[1])

    def test_colours_stay_within_the_base_colour(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        normals = gltf_utils.compute_face_normals(verts, faces, np)
        (r, g, b), = self._capture(verts, faces, normals)["color"]
        base_r, base_g, base_b = self.viewer.SOLID_BASE_COLOR
        for value, base in ((r, base_r), (g, base_g), (b, base_b)):
            self.assertGreater(value, 0.0)
            self.assertLessEqual(value, base + 1e-6)

    def test_missing_normals_draw_flat_without_crashing(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        calls = self._capture(verts, faces, None)
        self.assertEqual(len(calls["vertex"]), 3)
        self.assertEqual(calls["color"], [])

    def test_mismatched_normal_count_draws_flat(self):
        import numpy as np
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                         dtype=np.float32)
        faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32)
        normals = np.array([[0, 0, 1]], dtype=np.float32)  # one short
        calls = self._capture(verts, faces, normals)
        self.assertEqual(len(calls["vertex"]), 6)
        self.assertEqual(calls["color"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
