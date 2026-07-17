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


def _resolve_buffer_bytes(gltf: Any, buffer: Any) -> bytes:
    """gltf コンテキストを使って buffer の生バイト列を取得する。

    実運用の pygltflib (1.16+) では、GLB から読み込んだ Buffer は ``get_data()``
    も ``.data`` も持たず、バイナリは ``gltf.binary_blob()`` 側にある。データURI
    の場合は ``gltf.get_data_from_buffer_uri(uri)`` で復号する。これらを優先し、
    取れなければ従来の ``_buffer_bytes(buffer)``（スタブ/旧 API 互換）へ委譲する。
    """
    uri = getattr(buffer, "uri", None)
    if not uri:
        # GLB のバイナリチャンク（buffer.uri なし）。
        blob_getter = getattr(gltf, "binary_blob", None)
        if callable(blob_getter):
            try:
                blob = blob_getter()
                if blob:
                    return blob
            except Exception:
                pass
    else:
        # data URI / 外部ファイル参照。
        uri_getter = getattr(gltf, "get_data_from_buffer_uri", None)
        if callable(uri_getter):
            try:
                data = uri_getter(uri)
                if data:
                    return data
            except Exception:
                pass
    # 旧 API / テストスタブ互換フォールバック。
    return _buffer_bytes(buffer)


def load_first_mesh_vertices(gltf: Any, np: Any) -> Optional[Any]:
    """最初のメッシュの POSITION 属性から (N, 3) の頂点配列を返す。

    抽出できない場合は None を返す（呼び出し側は None を「頂点なし」として安全に
    扱う前提）。次のような不正/エッジケースの glTF でも例外を投げず None を返す:
      - メッシュ/プリミティブが無い
      - プリミティブに POSITION 属性が無い（POSITION は glTF 必須ではない）
      - アクセサが sparse 等で bufferView を持たない（bufferView is None）
      - バッファ長が float3 の倍数でなく reshape に失敗する

    bufferView/accessor の byteOffset と accessor.count を尊重して、対象アクセサ
    の範囲だけを切り出す（バッファに他アクセサのデータが同居していても正しく
    POSITION だけを読む）。pygltflib / numpy が None の呼び出し側は事前にガード
    している前提。
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
        raw = _resolve_buffer_bytes(gltf, buffer)
        if not raw:
            return None
        # bufferView + accessor のオフセットで対象範囲を特定する。
        start = (getattr(buffer_view, "byteOffset", 0) or 0) + \
                (getattr(accessor, "byteOffset", 0) or 0)
        count = getattr(accessor, "count", None)
        if count:
            nbytes = int(count) * 3 * 4  # VEC3 × float32(4 byte)
            segment = raw[start:start + nbytes]
        else:
            bv_len = getattr(buffer_view, "byteLength", None)
            end = start + int(bv_len) if bv_len else len(raw)
            segment = raw[start:end]
        data = np.frombuffer(segment, dtype=np.float32)
        if data.size == 0 or data.size % 3 != 0:
            return None
        return data.reshape(-1, 3)
    except (IndexError, TypeError, ValueError, AttributeError):
        return None


def normalize_vertices(vertices: Any, np: Any) -> Optional[Any]:
    """頂点群 (N, 3) を重心中心・最大半径 1.0 に正規化して返す。

    モデルごとに座標スケール・原点位置がまちまちなので、そのまま描画すると
    画面外に出たり点にしか見えなかったりする。重心を原点へ平行移動し、最大
    半径が 1.0 になるよう一様スケールして、ビューポート内に収める。

    None・空・(N, 3) 以外・非有限値を含む入力は None を返す（呼び出し側は
    「描画しない」で安全に扱う前提）。最大半径が 0（全点同一）ならスケール
    せず中心化のみ行う（ゼロ除算回避）。
    """
    try:
        if vertices is None:
            return None
        arr = np.asarray(vertices, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] != 3:
            return None
        if not np.all(np.isfinite(arr)):
            return None
        centered = arr - arr.mean(axis=0)
        max_radius = float(np.max(np.sqrt(np.sum(centered * centered, axis=1))))
        if max_radius <= 0.0:
            return centered
        return centered / max_radius
    except (TypeError, ValueError, AttributeError):
        return None
