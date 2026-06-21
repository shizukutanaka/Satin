"""
GLTF/GLB 読み込みの共有ユーティリティ。

avatar_3d_gltf_viewer.py と autonomous_gltf_avatar.py が、最初のメッシュの
頂点座標を取り出すロジックを重複して持っていたため共通化した。GLB のバイナリ
バッファは ``buffer.data`` が空のことがあるため、``buffer.get_data()`` を優先し、
利用できない場合のみ ``buffer.data`` にフォールバックする。
"""
from __future__ import annotations

from typing import Any, Optional


def _buffer_bytes(buffer: Any) -> bytes:
    """Buffer から生バイト列を取得する。

    pygltflib の Buffer は GLB バイナリ/データ URI を解決する ``get_data()`` を
    持つ。古い経路では ``data`` 属性に直接バイト列が入っていることもあるため、
    get_data() を優先しつつフォールバックする。
    """
    get_data = getattr(buffer, "get_data", None)
    if callable(get_data):
        try:
            return get_data()
        except Exception:
            pass
    return getattr(buffer, "data", b"") or b""


def load_first_mesh_vertices(gltf: Any, np: Any) -> Optional[Any]:
    """最初のメッシュの POSITION 属性から (N, 3) の頂点配列を返す。

    抽出できない場合は None を返す（呼び出し側は None を「頂点なし」として安全に
    扱う前提）。次のような不正/エッジケースの glTF でも例外を投げず None を返す:
      - メッシュ/プリミティブが無い
      - プリミティブに POSITION 属性が無い（POSITION は glTF 必須ではない）
      - アクセサが sparse 等で bufferView を持たない（bufferView is None）
      - バッファ長が float3 の倍数でなく reshape に失敗する

    pygltflib / numpy が None の呼び出し側は事前にガードしている前提。
    """
    try:
        if not gltf.meshes:
            return None
        primitives = gltf.meshes[0].primitives
        if not primitives:
            return None
        attributes = getattr(primitives[0], "attributes", None)
        position = getattr(attributes, "POSITION", None) if attributes else None
        if position is None:
            return None
        accessor = gltf.accessors[position]
        # sparse アクセサ等では bufferView が None。その場合は対象外として None。
        if getattr(accessor, "bufferView", None) is None:
            return None
        buffer_view = gltf.bufferViews[accessor.bufferView]
        buffer = gltf.buffers[buffer_view.buffer]
        data = np.frombuffer(_buffer_bytes(buffer), dtype=np.float32)
        if data.size == 0 or data.size % 3 != 0:
            return None
        return data.reshape(-1, 3)
    except (IndexError, TypeError, ValueError, AttributeError):
        return None
