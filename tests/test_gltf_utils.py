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


if __name__ == "__main__":
    unittest.main()
