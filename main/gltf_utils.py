"""
GLTF/GLB 読み込みの共有ユーティリティ。

avatar_3d_gltf_viewer.py と autonomous_gltf_avatar.py が、最初のメッシュの
頂点座標を取り出すロジックを重複して持っていたため共通化した。GLB のバイナリ
バッファは ``buffer.data`` が空のことがあるため、``buffer.get_data()`` を優先し、
利用できない場合のみ ``buffer.data`` にフォールバックする。

glTF 2.0 仕様（Khronos）のうち本モジュールが依拠する点:
- ``bufferView.byteStride`` は**頂点属性のインターリーブ**を表す。2 つ以上の
  アクセサが同じ bufferView を共有する場合、仕様上 byteStride の定義が必須。
  つまり POSITION と NORMAL が交互に並ぶバッファは普通に存在するので、
  stride を無視して連続読みすると別属性の値を座標として読んでしまう。
- ``primitive.indices`` のアクセサは ``type="SCALAR"``、componentType は
  5121 (UNSIGNED_BYTE) / 5123 (UNSIGNED_SHORT) / 5125 (UNSIGNED_INT) のいずれか
  （5125 は indices 専用）。インデックスは密に詰められる。
- ``primitive.mode`` の既定は 4 (TRIANGLES)。5 (TRIANGLE_STRIP) / 6 (TRIANGLE_FAN)
  も面を成すので三角形リストへ展開する。0–3（点・線）は面を持たない。
- ``indices`` が無いプリミティブは 0..count-1 の暗黙の連番を持つ。
- **NORMAL 属性が無い場合、クライアントはフラット法線を計算しなければならない**
  （"When normals are not specified, client implementations MUST calculate flat
  normals"）。`compute_face_normals` がこれを担う。
"""
from __future__ import annotations

from typing import Any, Optional

# glTF 2.0 の componentType → (numpy dtype 名, バイト幅)
_INDEX_COMPONENT_TYPES = {
    5121: ("uint8", 1),    # UNSIGNED_BYTE
    5123: ("uint16", 2),   # UNSIGNED_SHORT
    5125: ("uint32", 4),   # UNSIGNED_INT（indices 専用）
}

# primitive.mode
MODE_TRIANGLES = 4
MODE_TRIANGLE_STRIP = 5
MODE_TRIANGLE_FAN = 6
#: 面を構成するモード（これ以外は点・線なのでワイヤーフレーム描画へ）
_FACE_MODES = (MODE_TRIANGLES, MODE_TRIANGLE_STRIP, MODE_TRIANGLE_FAN)

_VEC3_FLOAT_BYTES = 12  # VEC3 × float32


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


def _read_vec3_accessor(gltf: Any, accessor_index: Any, np: Any) -> Optional[Any]:
    """VEC3/float32 アクセサを (N, 3) の配列として読み出す。

    ``bufferView.byteStride`` を尊重する点が要。glTF ではひとつの bufferView に
    POSITION と NORMAL を交互に詰める（インターリーブ）のが普通で、仕様も
    「2 つ以上のアクセサが同じ bufferView を使う場合 byteStride は必須」と定める。
    stride を無視して連続 12 バイトずつ読むと、2 頂点目以降で法線の値を座標として
    取り込み、モデルが崩れて描画される（実際にそうなっていた）。

    読めない場合は None（呼び出し側は「頂点なし」として安全に扱う前提）。
    """
    try:
        if accessor_index is None:
            return None
        accessor = gltf.accessors[accessor_index]
        # sparse アクセサ等では bufferView が None。その場合は対象外。
        if getattr(accessor, "bufferView", None) is None:
            return None
        buffer_view = gltf.bufferViews[accessor.bufferView]
        buffer = gltf.buffers[buffer_view.buffer]
        raw = _resolve_buffer_bytes(gltf, buffer)
        if not raw:
            return None

        start = (getattr(buffer_view, "byteOffset", 0) or 0) + \
                (getattr(accessor, "byteOffset", 0) or 0)
        count = getattr(accessor, "count", None)
        stride = getattr(buffer_view, "byteStride", None) or 0

        if not count:
            # count 不明ならインターリーブの判定もできないので密詰めとして読む。
            bv_len = getattr(buffer_view, "byteLength", None)
            end = start + int(bv_len) if bv_len else len(raw)
            data = np.frombuffer(raw[start:end], dtype=np.float32)
            if data.size == 0 or data.size % 3 != 0:
                return None
            return data.reshape(-1, 3)

        count = int(count)
        if stride and stride != _VEC3_FLOAT_BYTES:
            # インターリーブ: stride ごとに先頭 12 バイトだけを拾う。
            # 最後の要素の後ろには stride 分の余白が無いのが普通なので、必要な
            # のは (count-1)*stride + 12 バイト。reshape のために末尾だけ 0 埋め
            # する（埋めた領域は下のスライスで捨てられるので値に影響しない）。
            needed = (count - 1) * stride + _VEC3_FLOAT_BYTES
            segment = raw[start:start + count * stride]
            if len(segment) < needed:
                return None
            padded = segment + b"\x00" * (count * stride - len(segment))
            view = np.frombuffer(padded, dtype=np.uint8).reshape(count, stride)
            packed = view[:, :_VEC3_FLOAT_BYTES].tobytes()
            data = np.frombuffer(packed, dtype=np.float32)
        else:
            nbytes = count * _VEC3_FLOAT_BYTES
            data = np.frombuffer(raw[start:start + nbytes], dtype=np.float32)
        if data.size == 0 or data.size % 3 != 0:
            return None
        return data.reshape(-1, 3)
    except (IndexError, TypeError, ValueError, AttributeError):
        return None


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
        return _read_vec3_accessor(gltf, position, np)
    except (IndexError, TypeError, ValueError, AttributeError):
        return None


def load_first_mesh_normals(gltf: Any, np: Any) -> Optional[Any]:
    """最初のメッシュの NORMAL 属性から (N, 3) の法線配列を返す（無ければ None）。

    NORMAL は必須ではない。無い場合、仕様は「クライアントがフラット法線を計算
    しなければならない」と定めるので、呼び出し側は `compute_face_normals` へ
    フォールバックする。
    """
    try:
        if not gltf.meshes:
            return None
        primitives = gltf.meshes[0].primitives
        if not primitives:
            return None
        attributes = getattr(primitives[0], "attributes", None)
        normal = getattr(attributes, "NORMAL", None) if attributes else None
        return _read_vec3_accessor(gltf, normal, np)
    except (IndexError, TypeError, ValueError, AttributeError):
        return None


def _strip_to_triangles(indices: Any, np: Any) -> Any:
    """TRIANGLE_STRIP のインデックス列を三角形リストへ展開する。

    奇数番目の三角形は巻き方向が反転するので、頂点順を入れ替えて表裏を揃える。
    """
    n = len(indices)
    if n < 3:
        return np.empty((0, 3), dtype=np.uint32)
    tris = []
    for i in range(n - 2):
        a, b, c = indices[i], indices[i + 1], indices[i + 2]
        tris.append((a, c, b) if i % 2 else (a, b, c))
    return np.asarray(tris, dtype=np.uint32)


def _fan_to_triangles(indices: Any, np: Any) -> Any:
    """TRIANGLE_FAN のインデックス列を三角形リストへ展開する（先頭が扇の要）。"""
    n = len(indices)
    if n < 3:
        return np.empty((0, 3), dtype=np.uint32)
    hub = indices[0]
    tris = [(hub, indices[i], indices[i + 1]) for i in range(1, n - 1)]
    return np.asarray(tris, dtype=np.uint32)


def load_first_mesh_faces(gltf: Any, np: Any) -> Optional[Any]:
    """最初のメッシュの三角形インデックスを (M, 3) の uint32 配列で返す。

    面を持たない場合（点群・線分モード、頂点が 3 未満、インデックスが壊れている）
    は None を返し、呼び出し側はワイヤーフレーム描画へフォールバックする。

    仕様に沿った扱い:
      - ``primitive.mode`` 既定は 4 (TRIANGLES)。5/6 は三角形リストへ展開する。
      - ``indices`` が無ければ 0..count-1 の暗黙の連番を使う（非インデックス
        ジオメトリ）。
      - componentType は 5121/5123/5125 のみ。それ以外は不正なので None。
      - 頂点数を超えるインデックスを含む面は捨てる（壊れたモデルで
        IndexError を起こさない）。
    """
    try:
        if not gltf.meshes:
            return None
        primitives = gltf.meshes[0].primitives
        if not primitives:
            return None
        primitive = primitives[0]

        mode = getattr(primitive, "mode", None)
        if mode is None:
            mode = MODE_TRIANGLES  # 仕様上の既定
        if mode not in _FACE_MODES:
            return None

        attributes = getattr(primitive, "attributes", None)
        position = getattr(attributes, "POSITION", None) if attributes else None
        if position is None:
            return None
        vertex_count = int(getattr(gltf.accessors[position], "count", 0) or 0)
        if vertex_count < 3:
            return None

        index_ref = getattr(primitive, "indices", None)
        if index_ref is None:
            # 非インデックスジオメトリ: 暗黙の連番。
            flat = np.arange(vertex_count, dtype=np.uint32)
        else:
            accessor = gltf.accessors[index_ref]
            if getattr(accessor, "bufferView", None) is None:
                return None
            component_type = getattr(accessor, "componentType", None)
            spec = _INDEX_COMPONENT_TYPES.get(component_type)
            if spec is None:
                return None
            dtype_name, width = spec
            buffer_view = gltf.bufferViews[accessor.bufferView]
            buffer = gltf.buffers[buffer_view.buffer]
            raw = _resolve_buffer_bytes(gltf, buffer)
            if not raw:
                return None
            start = (getattr(buffer_view, "byteOffset", 0) or 0) + \
                    (getattr(accessor, "byteOffset", 0) or 0)
            count = int(getattr(accessor, "count", 0) or 0)
            if count < 3:
                return None
            segment = raw[start:start + count * width]
            if len(segment) < count * width:
                return None
            flat = np.frombuffer(segment, dtype=np.dtype(dtype_name)).astype(np.uint32)

        if mode == MODE_TRIANGLE_STRIP:
            faces = _strip_to_triangles(flat, np)
        elif mode == MODE_TRIANGLE_FAN:
            faces = _fan_to_triangles(flat, np)
        else:
            usable = (len(flat) // 3) * 3
            if usable < 3:
                return None
            faces = flat[:usable].reshape(-1, 3).astype(np.uint32)

        if faces.size == 0:
            return None
        # 範囲外インデックスを含む面を落とす（壊れた/切り詰められたモデル対策）。
        valid = np.all(faces < vertex_count, axis=1)
        faces = faces[valid]
        if faces.size == 0:
            return None
        return faces
    except (IndexError, TypeError, ValueError, AttributeError):
        return None


def compute_face_normals(vertices: Any, faces: Any, np: Any) -> Optional[Any]:
    """各三角形の単位法線を (M, 3) で返す（フラット法線）。

    glTF 仕様は NORMAL 属性が無いときクライアントが**フラット法線を計算する**
    ことを求める。外積 (b-a) × (c-a) を正規化して返し、面積ゼロの縮退三角形は
    (0, 0, 1) を割り当てる（0 除算とシェーディングの破綻を避ける）。

    入力が不正なら None。
    """
    try:
        if vertices is None or faces is None:
            return None
        verts = np.asarray(vertices, dtype=np.float32)
        idx = np.asarray(faces)
        if verts.ndim != 2 or verts.shape[1] != 3:
            return None
        if idx.ndim != 2 or idx.shape[1] != 3 or idx.shape[0] == 0:
            return None
        if int(idx.max()) >= verts.shape[0]:
            return None
        a = verts[idx[:, 0]]
        b = verts[idx[:, 1]]
        c = verts[idx[:, 2]]
        normals = np.cross(b - a, c - a)
        lengths = np.sqrt(np.sum(normals * normals, axis=1, keepdims=True))
        degenerate = (lengths[:, 0] <= 0.0)
        safe = np.where(lengths > 0.0, lengths, 1.0)
        normals = (normals / safe).astype(np.float32)
        if np.any(degenerate):
            normals[degenerate] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        return normals
    except (TypeError, ValueError, AttributeError, IndexError):
        return None


def shade_factor(normal: Any, light_dir=(0.4, 0.7, 0.6), ambient: float = 0.35) -> float:
    """法線 1 本に対する拡散シェーディング係数 (ambient..1.0) を返す。

    Lambert の余弦則の素朴版: ``ambient + (1 - ambient) * max(0, n·l)``。
    面が光源に背を向けていても ambient 分は残るので真っ黒にならない。
    GPU もシェーダも要らない純関数なので、ヘッドレスでテストできる。

    法線・光源ベクトルが縮退しているときは ambient を返す（明るさが飛ばない）。
    """
    try:
        nx, ny, nz = (float(normal[0]), float(normal[1]), float(normal[2]))
        lx, ly, lz = (float(light_dir[0]), float(light_dir[1]), float(light_dir[2]))
    except (TypeError, ValueError, IndexError):
        return float(ambient)
    n_len = (nx * nx + ny * ny + nz * nz) ** 0.5
    l_len = (lx * lx + ly * ly + lz * lz) ** 0.5
    if n_len <= 0.0 or l_len <= 0.0:
        return float(ambient)
    cosine = (nx * lx + ny * ly + nz * lz) / (n_len * l_len)
    if cosine < 0.0:
        cosine = 0.0
    amb = min(1.0, max(0.0, float(ambient)))
    return amb + (1.0 - amb) * cosine


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
