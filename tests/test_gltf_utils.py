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


class LoadFirstMeshVerticesTests(unittest.TestCase):
    def test_returns_none_when_no_meshes(self):
        gltf = _FakeGLTF(meshes=[])
        self.assertIsNone(gltf_utils.load_first_mesh_vertices(gltf, np=object()))


if __name__ == "__main__":
    unittest.main()
