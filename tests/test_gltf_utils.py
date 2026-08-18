"""
Unit tests for gltf_utils — the shared GLTF vertex-loading helper extracted
from avatar_3d_gltf_viewer.py and autonomous_gltf_avatar.py.

These tests use lightweight stubs so they run without numpy/pygltflib installed.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import gltf_utils  # noqa: E402


class _GetDataBuffer:
    """Buffer exposing get_data() (the GLB-safe path)."""
    def __init__(self, payload, data=b""):
        self._payload = payload
        self.data = data

    def get_data(self):
        return self._payload


class _DataOnlyBuffer:
    """Buffer exposing only .data (legacy path)."""
    def __init__(self, data):
        self.data = data


class _RaisingGetDataBuffer:
    """Buffer whose get_data() raises — must fall back to .data."""
    def __init__(self, data):
        self.data = data

    def get_data(self):
        raise RuntimeError("no binary blob loaded")


class BufferBytesTests(unittest.TestCase):
    def test_prefers_get_data(self):
        buf = _GetDataBuffer(b"PAYLOAD", data=b"STALE")
        self.assertEqual(gltf_utils._buffer_bytes(buf), b"PAYLOAD")

    def test_falls_back_to_data_attr(self):
        buf = _DataOnlyBuffer(b"LEGACY")
        self.assertEqual(gltf_utils._buffer_bytes(buf), b"LEGACY")

    def test_falls_back_when_get_data_raises(self):
        buf = _RaisingGetDataBuffer(b"FALLBACK")
        self.assertEqual(gltf_utils._buffer_bytes(buf), b"FALLBACK")

    def test_none_data_yields_empty_bytes(self):
        buf = _DataOnlyBuffer(None)
        self.assertEqual(gltf_utils._buffer_bytes(buf), b"")


class _FakeGLTF:
    def __init__(self, meshes=None):
        self.meshes = meshes or []
        self.accessors = []
        self.bufferViews = []
        self.buffers = []


class _Attrs:
    def __init__(self, position=None):
        self.POSITION = position


class _Prim:
    def __init__(self, position=None):
        self.attributes = _Attrs(position)


class _Mesh:
    def __init__(self, primitives=None):
        self.primitives = primitives if primitives is not None else []


class _Accessor:
    def __init__(self, buffer_view=0):
        self.bufferView = buffer_view


class _BufView:
    def __init__(self, buffer=0):
        self.buffer = buffer


class LoadFirstMeshVerticesTests(unittest.TestCase):
    def test_returns_none_when_no_meshes(self):
        gltf = _FakeGLTF(meshes=[])
        self.assertIsNone(gltf_utils.load_first_mesh_vertices(gltf, np=object()))

    def test_returns_none_when_mesh_has_no_primitives(self):
        gltf = _FakeGLTF(meshes=[_Mesh(primitives=[])])
        self.assertIsNone(gltf_utils.load_first_mesh_vertices(gltf, np=object()))

    def test_returns_none_when_no_position_attribute(self):
        # POSITION is not a required glTF attribute; absent -> None, not crash.
        gltf = _FakeGLTF(meshes=[_Mesh(primitives=[_Prim(position=None)])])
        self.assertIsNone(gltf_utils.load_first_mesh_vertices(gltf, np=object()))

    def test_returns_none_for_sparse_accessor_without_bufferview(self):
        gltf = _FakeGLTF(meshes=[_Mesh(primitives=[_Prim(position=0)])])
        gltf.accessors = [_Accessor(buffer_view=None)]  # sparse -> no bufferView
        self.assertIsNone(gltf_utils.load_first_mesh_vertices(gltf, np=object()))

    def test_returns_none_on_out_of_range_accessor_index(self):
        gltf = _FakeGLTF(meshes=[_Mesh(primitives=[_Prim(position=5)])])
        gltf.accessors = []  # index 5 out of range -> IndexError -> None
        self.assertIsNone(gltf_utils.load_first_mesh_vertices(gltf, np=object()))


class LoadFirstMeshVerticesNumpyTests(unittest.TestCase):
    """Cases that exercise the numpy path (skipped if numpy is unavailable)."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

    def _gltf_with_payload(self, payload):
        gltf = _FakeGLTF(meshes=[_Mesh(primitives=[_Prim(position=0)])])
        gltf.accessors = [_Accessor(buffer_view=0)]
        gltf.bufferViews = [_BufView(buffer=0)]
        gltf.buffers = [_DataOnlyBuffer(payload)]
        return gltf

    def test_valid_multiple_of_3_floats_reshapes(self):
        import numpy as np
        payload = np.array([1, 2, 3, 4, 5, 6], dtype=np.float32).tobytes()
        out = gltf_utils.load_first_mesh_vertices(self._gltf_with_payload(payload), np)
        self.assertEqual(out.shape, (2, 3))

    def test_non_multiple_of_3_returns_none(self):
        import numpy as np
        payload = np.array([1, 2, 3, 4], dtype=np.float32).tobytes()  # 4 floats
        self.assertIsNone(
            gltf_utils.load_first_mesh_vertices(self._gltf_with_payload(payload), np))

    def test_empty_buffer_returns_none(self):
        import numpy as np
        self.assertIsNone(
            gltf_utils.load_first_mesh_vertices(self._gltf_with_payload(b""), np))


class NormalizeVerticesTests(unittest.TestCase):
    """normalize_vertices centers on the centroid and scales max radius to 1,
    so avatar models with arbitrary scale/offset render inside the viewport."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

    def test_centers_on_centroid(self):
        import numpy as np
        v = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=np.float32)
        out = gltf_utils.normalize_vertices(v, np)
        self.assertTrue(np.allclose(out.mean(axis=0), 0, atol=1e-6))

    def test_max_radius_becomes_one(self):
        import numpy as np
        v = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=np.float32)
        out = gltf_utils.normalize_vertices(v, np)
        radii = np.sqrt((out * out).sum(axis=1))
        self.assertAlmostEqual(float(np.max(radii)), 1.0, places=5)

    def test_translation_and_scale_invariant_shape(self):
        # Same shape at different offset/scale normalizes to (near) identical.
        import numpy as np
        base = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        shifted = base * 5.0 + np.array([100, -50, 7], dtype=np.float32)
        a = gltf_utils.normalize_vertices(base, np)
        b = gltf_utils.normalize_vertices(shifted, np)
        self.assertTrue(np.allclose(a, b, atol=1e-5))

    def test_none_returns_none(self):
        import numpy as np
        self.assertIsNone(gltf_utils.normalize_vertices(None, np))

    def test_empty_returns_none(self):
        import numpy as np
        self.assertIsNone(
            gltf_utils.normalize_vertices(np.zeros((0, 3), dtype=np.float32), np))

    def test_wrong_shape_returns_none(self):
        import numpy as np
        self.assertIsNone(
            gltf_utils.normalize_vertices(np.zeros((4, 2), dtype=np.float32), np))

    def test_non_finite_returns_none(self):
        import numpy as np
        v = np.array([[0, 0, 0], [np.inf, 0, 0]], dtype=np.float32)
        self.assertIsNone(gltf_utils.normalize_vertices(v, np))

    def test_all_identical_points_centers_without_scaling(self):
        # Zero max radius must not divide-by-zero; centering yields origin.
        import numpy as np
        v = np.array([[3, 3, 3], [3, 3, 3]], dtype=np.float32)
        out = gltf_utils.normalize_vertices(v, np)
        self.assertIsNotNone(out)
        self.assertTrue(np.allclose(out, 0, atol=1e-6))


class RealGlbRoundTripTests(unittest.TestCase):
    """End-to-end against a real .glb built with pygltflib — the stub tests
    can't catch API drift. Regression: pygltflib 1.16 GLB Buffers expose
    neither get_data() nor .data (the binary lives in gltf.binary_blob()),
    so the loader silently returned nothing for real files until
    _resolve_buffer_bytes was added."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
            import pygltflib  # noqa: F401
        except ImportError:
            self.skipTest("numpy/pygltflib not installed")

    def _build_glb(self, verts, path):
        import pygltflib
        blob = verts.tobytes()
        gltf = pygltflib.GLTF2(
            scene=0,
            scenes=[pygltflib.Scene(nodes=[0])],
            nodes=[pygltflib.Node(mesh=0)],
            meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=0))])],
            accessors=[pygltflib.Accessor(
                bufferView=0, componentType=pygltflib.FLOAT, count=len(verts),
                type=pygltflib.VEC3, max=verts.max(axis=0).tolist(),
                min=verts.min(axis=0).tolist())],
            bufferViews=[pygltflib.BufferView(
                buffer=0, byteOffset=0, byteLength=len(blob))],
            buffers=[pygltflib.Buffer(byteLength=len(blob))],
        )
        gltf.set_binary_blob(blob)
        gltf.save(path)

    def test_loads_vertices_from_real_glb(self):
        import numpy as np
        import tempfile
        import pygltflib
        verts = np.array([[0, 0, 0], [2, 0, 0], [0, 3, 0], [0, 0, 4]],
                         dtype=np.float32)
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "tetra.glb")
            self._build_glb(verts, p)
            g = pygltflib.GLTF2().load(p)
            out = gltf_utils.load_first_mesh_vertices(g, np)
            self.assertIsNotNone(out)
            self.assertEqual(out.shape, (4, 3))
            self.assertTrue(np.allclose(np.sort(out, axis=0),
                                        np.sort(verts, axis=0), atol=1e-5))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_atts_load_model_vertices_end_to_end(self):
        # The main GUI's _load_model_vertices: parse + normalize in one call.
        import numpy as np
        import tempfile
        _atts_main = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
        sys.path.insert(0, _atts_main)
        import avatar_3d_autonomous_tts as atts
        verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=np.float32)
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "tri.glb")
            self._build_glb(verts, p)
            out = atts._load_model_vertices(p)
            self.assertIsNotNone(out)
            self.assertEqual(out.shape, (3, 3))
            # normalized: centered, max radius 1
            self.assertTrue(np.allclose(out.mean(axis=0), 0, atol=1e-5))
            radii = np.sqrt((out * out).sum(axis=1))
            self.assertAlmostEqual(float(np.max(radii)), 1.0, places=4)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
