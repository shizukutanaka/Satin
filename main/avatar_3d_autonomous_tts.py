import sys
import random
import queue
import logging
import time

logger = logging.getLogger(__name__)

from optional_deps import (  # noqa: E402
    QApplication, QFileDialog, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QTimer,
    np, pygltflib,
)
from autonomous_behavior import AutonomousBehaviorMixin  # noqa: E402
from tts_thread import TTSThread  # noqa: E402,F401
from gl_widget_base import AVATAR_RADIUS, AVATAR_Z, GLViewportMixin  # noqa: E402

# 選んだアバターモデル (.glb/.gltf/.vrm) の頂点を読み込んで描画するための
# 任意依存。未導入・失敗時は従来の球体プレースホルダにフォールバックする。
try:
    from gltf_utils import (  # noqa: E402
        load_first_mesh_vertices,
        load_first_mesh_faces,
        load_first_mesh_normals,
        compute_face_normals,
        normalize_vertices,
        shade_factor,
    )
except Exception:  # pragma: no cover - defensive
    load_first_mesh_vertices = None  # type: ignore[assignment]
    load_first_mesh_faces = None  # type: ignore[assignment]
    load_first_mesh_normals = None  # type: ignore[assignment]
    compute_face_normals = None  # type: ignore[assignment]
    normalize_vertices = None  # type: ignore[assignment]
    shade_factor = None  # type: ignore[assignment]
try:
    import avatar_model_store as _avatar_model_store  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _avatar_model_store = None  # type: ignore[assignment]

# paintGL/draw が使う OpenGL 名 (glClear/glBegin/GL_* 等) を取り込む。
# 共通化リファクタでこの import が抜け、描画時に NameError になっていた。
try:
    from OpenGL.GL import *  # noqa: F401,F403
except ImportError:
    pass

# GLU はプレースホルダ球にしか使わないので明示的に取り込む。
# 星 import にしない理由: mypy は星 import から名前を解決できず、注釈付きの
# 関数（= 検査対象）の中で使うと name-defined エラーになる。実際
# `_paint_placeholder` に `-> None` を付けた瞬間に表面化した。
# 未導入時は None を入れ、利用側でガードする（本ファイルの他の任意依存と同じ様式）。
try:
    from OpenGL.GLU import gluNewQuadric, gluSphere
except ImportError:  # pragma: no cover - defensive
    gluNewQuadric = None  # type: ignore[assignment]
    gluSphere = None  # type: ignore[assignment]

try:
    from conversation_log import get_conversation_log  # noqa: E402
except Exception:  # pragma: no cover - defensive
    get_conversation_log = None  # type: ignore[assignment]

try:
    from mood import (  # noqa: E402
        get_mood_tracker, _default_mood_path, _default_mood_history_path,
        check_level_milestone,
        check_confession_event as _check_confession_event,
        check_interaction_milestone as _check_interaction_milestone,
        check_hurt_event as _check_hurt_event,
    )
except Exception:  # pragma: no cover - defensive
    get_mood_tracker = None  # type: ignore[assignment]
    _default_mood_path = None  # type: ignore[assignment]
    _default_mood_history_path = None  # type: ignore[assignment]
    check_level_milestone = None  # type: ignore[assignment]
    _check_confession_event = None  # type: ignore[assignment]
    _check_interaction_milestone = None  # type: ignore[assignment]
    _check_hurt_event = None  # type: ignore[assignment]

try:
    from fsutil import atomic_write_text as _atomic_write_text
except Exception:  # pragma: no cover - fsutil は main/ の同梱モジュール
    def _atomic_write_text(path, content, *, encoding="utf-8", fsync=True,  # type: ignore[misc]
                           restrict=False, newline=None):
        """fsutil を読めない場合の最小フォールバック（権限制限は落とさない）。"""
        import os as _os
        with open(path, "w", encoding=encoding, newline=newline) as f:
            f.write(content)
        if restrict:
            try:
                _os.chmod(path, 0o600)
            except OSError:
                pass

try:
    from persona_cli import _detect_ritual_event as _detect_ritual_event_gui
    from persona_cli import command_usage as _command_usage_gui
    from persona_cli import confirmation_prompt as _confirmation_prompt_gui
    from persona_cli import unknown_command_reply as _unknown_command_reply_gui
except Exception:  # pragma: no cover - defensive
    _detect_ritual_event_gui = None  # type: ignore[assignment]

    def _command_usage_gui(command, lang="ja"):  # type: ignore[misc]
        """persona_cli を読めない場合のフォールバック（空文字で無害に縮退）。"""
        return ""

    def _confirmation_prompt_gui(command, lang="ja"):  # type: ignore[misc]
        """同上。確認文言が空だと危険なので、汎用の確認文を返す。"""
        return ("Type the command again to confirm." if str(lang).startswith("en")
                else "もう一度同じコマンドを入力すると実行します。")

    def _unknown_command_reply_gui(command, lang="ja"):  # type: ignore[misc]
        """同上。"""
        return ("Sorry, I don't know that command. Type /help to see what I can do."
                if str(lang).startswith("en")
                else "ごめん、そのコマンドは分からないな。/help で一覧が見られるよ。")

try:
    from user_profile import (
        get_user_profile as _get_user_profile_gui,
        personalize as _personalize_gui,
        _default_profile_path as _default_profile_path_gui,
    )
except Exception:  # pragma: no cover - defensive
    _get_user_profile_gui = None  # type: ignore[assignment]
    _personalize_gui = None  # type: ignore[assignment]
    _default_profile_path_gui = None  # type: ignore[assignment]

try:
    from profile_questions import (
        next_unanswered_question as _next_unanswered_question_gui,
        acknowledge_answer as _acknowledge_answer_gui,
    )
except Exception:  # pragma: no cover - defensive
    _next_unanswered_question_gui = None  # type: ignore[assignment]
    _acknowledge_answer_gui = None  # type: ignore[assignment]

try:
    import ai_disclosure as _ai_disclosure
except Exception:  # pragma: no cover - defensive
    _ai_disclosure = None  # type: ignore[assignment]

try:
    from crisis_support import crisis_reply as _crisis_reply_gui
except Exception:  # pragma: no cover - defensive
    _crisis_reply_gui = None  # type: ignore[assignment]

try:
    from farewell_integrity import is_farewell as _is_farewell_gui
except Exception:  # pragma: no cover - defensive
    _is_farewell_gui = None  # type: ignore[assignment]

try:
    from everyday_distress import is_distressed as _is_distressed_gui
except Exception:  # pragma: no cover - defensive
    _is_distressed_gui = None  # type: ignore[assignment]

try:
    from daily_summary import summary_greeting as _summary_greeting_gui
except Exception:  # pragma: no cover - defensive
    _summary_greeting_gui = None  # type: ignore[assignment]

try:
    from user_wellbeing import wellbeing_summary as _wellbeing_summary_gui
    from user_wellbeing import wellbeing_message as _wellbeing_message_gui
except Exception:  # pragma: no cover - defensive
    _wellbeing_summary_gui = None  # type: ignore[assignment]
    _wellbeing_message_gui = None  # type: ignore[assignment]

_HISTORY_DEFAULT_GUI = 10

try:
    from daily_mood import (  # noqa: E402
        get_daily_mood as _get_daily_mood_gui,
        mood_affinity_multiplier as _mood_affinity_multiplier_gui,
    )
except Exception:  # pragma: no cover - defensive
    _get_daily_mood_gui = None  # type: ignore[assignment]
    _mood_affinity_multiplier_gui = None  # type: ignore[assignment]

try:
    from gifts import (  # noqa: E402
        lookup_gift as _lookup_gift_gui,
        lookup_gift_key as _lookup_gift_key_gui,
        gift_catalog_text as _gift_catalog_text_gui,
        cooldown_message as _gift_cooldown_message_gui,
    )
except Exception:  # pragma: no cover - defensive
    _lookup_gift_gui = None  # type: ignore[assignment]
    _lookup_gift_key_gui = None  # type: ignore[assignment]
    _gift_catalog_text_gui = None  # type: ignore[assignment]
    _gift_cooldown_message_gui = None  # type: ignore[assignment]

try:
    from break_reminder import maybe_start_break_reminder  # noqa: E402
except Exception:  # pragma: no cover - defensive
    maybe_start_break_reminder = None  # type: ignore[assignment]

try:
    from first_run import (  # noqa: E402
        is_first_run as _is_first_run,
        welcome_message as _welcome_message,
    )
except Exception:  # pragma: no cover - defensive
    _is_first_run = None  # type: ignore[assignment]
    _welcome_message = None  # type: ignore[assignment]


# N 回のコメントごとにアバターから「聞き返し」質問を添えて会話を続けやすくする
_FOLLOW_UP_EVERY = 4


try:
    from data_erasure import erase_all_user_data as _erase_all_user_data
except Exception:  # pragma: no cover - defensive
    _erase_all_user_data = None  # type: ignore[assignment]


def _load_model_vertices(path):
    """アバターファイル path の正規化済み頂点配列 (N, 3) を返す。失敗時 None。

    pygltflib / numpy / gltf_utils のいずれかが無い、読み込み・解析に失敗した、
    頂点が取れない場合は None を返し、呼び出し側は球体プレースホルダへ安全に
    フォールバックする（GUI を壊さない）。avatar_3d_gltf_viewer.GLTFModel と
    同じ読み込み経路を共有する。
    """
    geometry = _load_model_geometry(path)
    return geometry[0] if geometry else None


def _load_model_geometry(path):
    """アバターファイル path から (頂点, 面, 面法線) を返す。失敗時 None。

    頂点は `normalize_vertices` で正規化済み (N, 3)。面が取れなければ
    (頂点, None, None) を返し、呼び出し側は従来のワイヤーフレーム描画へ
    フォールバックする（点群モデル・線分モデル・インデックス破損時）。

    法線は NORMAL 属性ではなく**面ごとのフラット法線**を使う。glTF 仕様は
    NORMAL 非搭載時にクライアントがフラット法線を計算することを求めており、
    面単位の単色シェーディングでは頂点法線を補間しないため、面法線のほうが
    描画と整合する。

    pygltflib / numpy / gltf_utils のいずれかが無い、読み込み・解析に失敗した、
    頂点が取れない場合は None を返し、呼び出し側は球体プレースホルダへ安全に
    フォールバックする（GUI を壊さない）。
    """
    if (pygltflib is None or np is None or load_first_mesh_vertices is None
            or normalize_vertices is None or not path):
        return None
    try:
        gltf = pygltflib.GLTF2().load(path)
        vertices = normalize_vertices(load_first_mesh_vertices(gltf, np), np)
        if vertices is None:
            return None
        faces = None
        normals = None
        if load_first_mesh_faces is not None and compute_face_normals is not None:
            faces = load_first_mesh_faces(gltf, np)
            if faces is not None:
                normals = compute_face_normals(vertices, faces, np)
                if normals is None:
                    faces = None  # 法線が出せない面は描かない
        return (vertices, faces, normals)
    except Exception as e:  # pragma: no cover - defensive
        logger.info("アバターモデルの読み込みに失敗しました (%s): %s", path, e)
        return None


def make_reminder_speak(viewer, tts_queue):
    """休憩リマインダー用の speak コールバックを生成する。

    アバターが画面上で「見えて」喋るよう comment 表示状態をセットし、TTS にも
    投入する。これにより pyttsx3 が無くてもリマインダーは talk_label に表示され、
    ユーザーに必ず届く（音声のみで無音・不可視になる問題を解消）。

    viewer / tts_queue 非依存の純ロジックとして切り出し、Qt 無しでテスト可能。
    """
    def _speak(text):
        # 自律モード停止とタイマー発火が競合した場合への防御。停止後に発火した
        # リマインダーは無効なので何もしない。さもないと comment_text が
        # 書き込まれたまま（自律ループが止まっているため）消えずに残る。
        if viewer is not None and not getattr(viewer, 'is_autonomous', True):
            return
        if viewer is not None:
            viewer.comment_text = text
            viewer.mode = 'comment'
            viewer.ticks = 0
        if tts_queue is not None:
            tts_queue.put(text)
    return _speak


#: 破壊的コマンドの二段階確認。属性名 → その確認を継続できる入力の集合。
#
# ここに載っていないコマンドは確認を持たない。**逆に言えば、破壊的なのに
# ここに無ければそれが欠陥である**: 実際 /forget-me は確認そのものが無く、
# 打ち間違い 1 回で呼び名・誕生日・趣味・覚えた事実が復元不能に消えていた。
# /forget-all は確認はあったが取り消し処理が書かれておらず、雑談を挟んだ
# あとの単独入力でいきなり実行された。1 コマンドずつ手で書くのをやめて
# 表にすることで、追加時の書き忘れが起きにくくなる。
_PENDING_CONFIRMATIONS = {
    "_clear_log_pending": ("/clear-log", "/clearlog"),
    "_reset_mood_pending": ("/reset-mood", "/resetmood"),
    "_forget_all_pending": ("/forget-all", "/forgetall", "/delete-all", "/erase-all"),
    "_forget_me_pending": ("/forget-me", "/forgetme"),
}


class AutonomousAvatarViewer(
        AutonomousBehaviorMixin, GLViewportMixin,
        QOpenGLWidget if QOpenGLWidget is not None else object):  # type: ignore[misc]
    reset_direction_on_run = True
    EXTRA_TEXT_FIELDS = ('comment_text',)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.mode = 'idle'  # 'run', 'rest', 'talk', 'comment'
        self.position = [0.0, 0.0]
        self.direction = random.uniform(0, 360)
        self.ticks = 0
        self.talk_text = ''
        self.comment_text = ''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_autonomous)
        self.timer.start(50)
        self.is_autonomous = False
        self.talks = [
            'こんにちは！',
            '今日はいい天気ですね。',
            'ちょっと休憩します…',
            '走るの大好き！',
            'あなたも一緒にどう？'
        ]
        self.tts_queue = None
        self.pending_fact_key = None  # 一問一答: 回答待ちの質問キー
        # 破壊的コマンドの二段階確認フラグ（_PENDING_CONFIRMATIONS 参照）
        for _attr in _PENDING_CONFIRMATIONS:
            setattr(self, _attr, False)
        # /avatar で選んだアバターモデルの頂点（無ければ球体を描画）
        self.avatar_model_vertices = None
        # 三角形インデックス (M, 3) と面ごとのフラット法線 (M, 3)。
        # 取れたときは陰影付きのソリッド描画、取れなければ従来のワイヤーフレーム。
        self.avatar_model_faces = None
        self.avatar_model_normals = None
        self.avatar_model_path = None

    def set_tts_queue(self, tts_queue):
        self.tts_queue = tts_queue

    def load_avatar_model(self, path=None):
        """アバターモデルを読み込んで描画対象にする。成功なら True。

        path 未指定なら共有ストア（avatar_model_store）が解決する「最後に選んだ
        アバター」を使う。読み込めなければ状態を変えず False を返す（従来の球体
        プレースホルダのまま）。GUI 起動時と /avatar コマンドから呼ばれる。
        """
        if path is None:
            if _avatar_model_store is None:
                return False
            try:
                path = _avatar_model_store.resolve_selected_avatar()
            except Exception:
                path = None
        if not path:
            return False
        geometry = _load_model_geometry(path)
        if geometry is None:
            return False
        vertices, faces, normals = geometry
        self.avatar_model_vertices = vertices
        self.avatar_model_faces = faces
        self.avatar_model_normals = normals
        self.avatar_model_path = path
        try:
            self.update()
        except Exception:
            pass  # ヘッドレス/未初期化ウィジェットでも状態更新は成立させる
        return True

    def speak_comment(self, comment):
        # ペルソナが応答を返せばそれを表示・読み上げ、無ければ入力をそのまま
        # 読み上げる（後方互換のオウム返し）。respond の失敗で TTS は壊さない。
        if not isinstance(comment, str) or not comment.strip():
            return  # 空・空白のみの入力は無音で無視する
        reply = comment
        # 好感度レベルを取得して関係性に応じた応答を選ばせる
        level = None
        if get_mood_tracker is not None:
            try:
                level = get_mood_tracker().level
            except Exception as e:
                logger.debug("好感度レベルの取得に失敗（応答は継続）: %s", e)
        persona = self.persona
        lang = getattr(persona, 'lang', 'ja') if persona is not None else 'ja'

        # 確認待ちが他の発話（スラッシュ・非スラッシュ問わず）で挟まれたら
        # 取り消す。persona_cli.py の同種フラグ処理と同じロジック。
        # 表にまとめてあるのは、以前これを 1 コマンドずつ書いており
        # /forget-all のぶんが**書かれないまま**だったため — 確認が取り消され
        # ないと、雑談を何度挟んだあとの単独の /forget-all がいきなり実行される。
        # getattr の既定値 False は、__init__ を経由しないテスト用インスタンス
        # で属性未設定でも落ちないようにするための防御。
        _typed = comment.strip().lower()
        for _attr, _aliases in _PENDING_CONFIRMATIONS.items():
            if getattr(self, _attr, False) and _typed not in _aliases:
                setattr(self, _attr, False)

        # ---------- スラッシュコマンド (/gift, /callme) ----------
        if isinstance(comment, str) and comment.lstrip().startswith("/"):
            if self._handle_slash_command_gui(comment.lstrip()[1:], lang, level):
                self.pending_fact_key = None  # コマンドで Q&A フローを中断
                return
            # 一致しなかった "/..." は未知のコマンド。会話として扱わない
            # （persona_cli の同じ箇所と対。理由は unknown_command_reply の
            # docstring）。
            self.pending_fact_key = None
            self._speak_reply(_unknown_command_reply_gui(comment.lstrip()[1:], lang))
            return

        # ---------- 危機表明（自傷・自殺念慮）----------
        # 他のどの処理よりも先に扱う。ここで打ち切ることで、危機の開示が
        # 好感度・会話回数・プロフィール記憶・聞き返し質問といった
        # 「関係を進める」仕掛けに一切流れ込まないようにする（ゲーム化しない）。
        # 検知しなければ空文字が返るので通常フローへ進む。
        if _crisis_reply_gui is not None:
            try:
                support = _crisis_reply_gui(comment, lang=lang)
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("危機表明の判定に失敗（通常応答へ継続）: %s", e)
                support = ""
            if support:
                self.pending_fact_key = None  # Q&A の答えとして記録しない
                if get_conversation_log is not None:
                    try:
                        get_conversation_log().log_exchange(comment, support)
                    except Exception as e:
                        logger.warning("会話履歴の記録に失敗しました: %s", e)
                self._speak_reply(support)
                return

        # 一問一答の回答待ちなら今回の発話を答えとして記録する（失敗しても会話は続ける）。
        ack_msg = ""
        if self.pending_fact_key is not None:
            if _get_user_profile_gui is not None and _acknowledge_answer_gui is not None:
                try:
                    prof = _get_user_profile_gui()
                    if prof is not None:
                        saved = prof.set_fact(self.pending_fact_key, comment)
                        if saved:
                            ack_msg = _acknowledge_answer_gui(self.pending_fact_key, saved, lang=lang)
                            if _default_profile_path_gui is not None:
                                prof.save(_default_profile_path_gui())
                except Exception as e:
                    logger.debug("一問一答の回答記録に失敗（GUI）: %s", e)
            self.pending_fact_key = None

        if persona is not None:
            try:
                generated = persona.respond(comment, level=level)
            except Exception as e:
                logger.debug("ペルソナ応答生成に失敗（オウム返しにフォールバック）: %s", e)
                generated = ""
            if generated:
                reply = generated
        # 好感度を更新し、即時保存 + 日次スナップショットを記録する。
        # レベルが変化（昇格/降格）したらマイルストーン台詞を応答に添える。
        if get_mood_tracker is not None:
            try:
                tracker = get_mood_tracker()
                before_affinity = tracker.affinity
                before_interactions = tracker.interactions
                raw_delta = tracker.register(comment)
                # 謝罪・おやすみルーティン: 小さな好感度ボーナス（繰り返せるので
                # earn() で日次予算を通す。CLI 側と対）
                if _detect_ritual_event_gui is not None:
                    ritual = _detect_ritual_event_gui(comment)
                    if ritual is not None:
                        tracker.earn(ritual[1])
                # 傷つきイベント: 通常応答を感情反応で上書き
                if _check_hurt_event is not None:
                    hurt = _check_hurt_event(raw_delta, lang=lang)
                    if hurt:
                        reply = hurt
                after_affinity = tracker.affinity
                # 告白イベント（friendly→close 初回のみ）
                milestone_msg = ""
                if _check_confession_event is not None:
                    confession = _check_confession_event(tracker, before_affinity, after_affinity, lang=lang)
                    if confession:
                        milestone_msg = confession
                # 関係ステージ変化
                if not milestone_msg and check_level_milestone is not None:
                    ms = check_level_milestone(before_affinity, after_affinity, lang=lang)
                    if ms and ms.get("message"):
                        milestone_msg = ms["message"]
                # 会話回数マイルストーン
                if not milestone_msg and _check_interaction_milestone is not None:
                    inter_ms = _check_interaction_milestone(
                        before_interactions, tracker.interactions, lang=lang
                    )
                    if inter_ms:
                        milestone_msg = inter_ms
                if milestone_msg:
                    reply = (reply + " " + milestone_msg).strip()
                if _default_mood_path is not None:
                    tracker.save(_default_mood_path())
                if _default_mood_history_path is not None:
                    tracker.snapshot_to_history(_default_mood_history_path())
            except Exception as e:
                # 関係性の状態更新/保存が失敗＝ユーザー体験の劣化。沈黙せず記録する
                # （TTS/UI は壊さないが、原因を追えるようにする）。
                logger.warning("好感度の更新・保存に失敗しました: %s", e)
        # 数回のやりとりごとにアバターから話題を振る（受け身すぎないように）。
        # 既に疑問文で終わっている応答には添えない（二重質問を避ける）。
        #
        # 別れの挨拶には絶対に付けない。「またね！ところでストレス発散は
        # どうしてる？」は、去ろうとしている相手に応答の義務を作る形であり、
        # farewell_integrity が PRESSURE_TO_RESPOND として禁じている型そのもの
        # である（persona_cli の同じ箇所と対で修正した — 片方だけ直すと
        # GUI と CLI で振る舞いがずれる）。
        # つらさを打ち明けられた直後にも付けない（persona_cli の同じ箇所と対）。
        _leaving_gui = _is_farewell_gui is not None and _is_farewell_gui(comment)
        _hurting_gui = _is_distressed_gui is not None and _is_distressed_gui(comment)
        if persona is not None and _FOLLOW_UP_EVERY > 0 \
                and not _leaving_gui and not _hurting_gui \
                and not reply.rstrip().endswith(("？", "?")):
            try:
                interactions = None
                if get_mood_tracker is not None:
                    interactions = get_mood_tracker().interactions
                if interactions and interactions % _FOLLOW_UP_EVERY == 0:
                    question = ""
                    # getting-to-know-you Q&A: neutral+ かつ回答待ち無しのとき半々の確率で
                    # プロフィール質問を優先する（persona.follow_up_question より具体的）。
                    if (level in {"neutral", "friendly", "close"}
                            and self.pending_fact_key is None
                            and _next_unanswered_question_gui is not None
                            and _get_user_profile_gui is not None):
                        if random.random() < 0.5:
                            try:
                                prof = _get_user_profile_gui()
                                qpair = _next_unanswered_question_gui(prof, lang)
                                if qpair:
                                    self.pending_fact_key, question = qpair
                            except Exception:
                                question = ""
                    if not question:
                        question = persona.follow_up_question(level=level)
                    if question:
                        reply = (reply + " " + question).strip()
            except Exception as e:
                logger.debug("聞き返し質問の生成に失敗しました: %s", e)
        # ユーザーの趣味への言及（興味を持ち続けている演出）。
        # 既に質問で終わっている場合・Q&A 待機中は追加しない。15% の確率で発動。
        if (persona is not None
                and self.pending_fact_key is None
                and not reply.rstrip().endswith(("？", "?"))
                and _get_user_profile_gui is not None
                and random.random() < 0.15):
            try:
                prof = _get_user_profile_gui()
                if prof is not None and prof.interests:
                    interest = random.choice(prof.interests)
                    mention = persona.interest_mention(interest, lang=lang)
                    if mention:
                        reply = (reply + " " + mention).strip()
            except Exception as e:
                logger.debug("趣味への言及生成に失敗しました: %s", e)
        # 会話履歴を記録（失敗しても UI/TTS を壊さない）
        if get_conversation_log is not None:
            try:
                get_conversation_log().log_exchange(comment, reply)
            except Exception as e:
                logger.warning("会話履歴の記録に失敗しました: %s", e)
        # 一問一答の回答確認文を前置き（「ちゃんと聞いてる」感を演出）
        if ack_msg:
            reply = (ack_msg + " " + reply).strip() if reply else ack_msg
        # AI であることの定期開示（前回から 3 時間以上の継続利用で 1 回）。
        # 演出の外側に置くため、応答の先頭に別行で付ける。
        reply = self._prepend_ai_disclosure(reply, lang)
        # 表示・TTS 投入は _speak_reply に一本化（{user} 解決もそこで実施）。
        self._speak_reply(reply)

    def _prepend_ai_disclosure(self, reply: str, lang: str) -> str:
        """3 時間ごとの AI 開示が必要なら reply の先頭へ付けて返す。

        ここが受け持つのは**間隔**のほうだけで、セッション開始時の開示は
        `MainWindow._show_ai_disclosure` が出したうえで `_last_ai_disclosure_ts`
        を打つ。よってタイムスタンプが未設定なら「セッションが始まったばかり」と
        みなし、黙って時計を開始する（開始直後の 1 通目に重ねて出さない）。

        状態はプロセス内メモリのみ。アプリを起動し直せば新しいセッションとして
        開始時通知が出るので永続化しない（個人データも増やさない）。
        """
        if _ai_disclosure is None:
            return reply
        try:
            last = getattr(self, "_last_ai_disclosure_ts", None)
            if last is None:
                self._last_ai_disclosure_ts = time.time()
                return reply
            if not _ai_disclosure.is_due(last):
                return reply
            notice = _ai_disclosure.periodic_notice(lang)
            self._last_ai_disclosure_ts = time.time()
            return (notice + "\n" + reply) if reply else notice
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("AI 開示の付与に失敗（応答は継続）: %s", e)
            return reply

    def _speak_reply(self, reply: str) -> None:
        """コメント表示と TTS 投入の共通処理（全コメント応答の唯一の出口）。

        ここで {user} プレースホルダを呼び名へ解決する。speak_comment だけでなく
        ギフト・プロフィール質問・スラッシュコマンド応答も含む全経路がこの関数を
        通るため、将来どの台詞に {user} を足しても literal が読み上げ／表示へ
        漏れない（personalize は {user} が無ければ無変換なので無害）。
        """
        if _personalize_gui is not None and reply and "{user}" in reply:
            try:
                prof = _get_user_profile_gui() if _get_user_profile_gui is not None else None
                lang = getattr(self.persona, "lang", "ja") if self.persona is not None else "ja"
                reply = _personalize_gui(reply, prof, lang)
            except Exception:
                pass
        self.comment_text = reply
        self.mode = 'comment'
        self.ticks = 0
        if self.tts_queue:
            self.tts_queue.put(reply)

    def _handle_slash_command_gui(self, cmd_text: str, lang: str, level) -> bool:
        """GUI スラッシュコマンドを処理する。認識したコマンドなら True を返す。"""
        cmd_l = cmd_text.lower()
        if cmd_l == "gift" or cmd_l.startswith("gift "):
            self._cmd_gift_gui(cmd_text[4:].strip(), lang, level)
            return True
        if cmd_l == "callme" or cmd_l.startswith("callme "):
            self._cmd_callme_gui(cmd_text[6:].strip(), lang)
            return True
        if cmd_l == "like" or cmd_l.startswith("like "):
            self._cmd_like_gui(cmd_text[4:].strip(), lang)
            return True
        # /forget-all / /forget-me / /forget-fact は /forget より具体的なので先に判定する
        if cmd_l in ("forget-all", "forgetall", "delete-all", "erase-all"):
            self._cmd_forget_all_gui(lang)
            return True
        if cmd_l == "forget-me" or cmd_l.startswith("forget-me ") or cmd_l == "forgetme":
            self._cmd_forget_me_gui(lang)
            return True
        if cmd_l == "forget-fact" or cmd_l.startswith("forget-fact "):
            self._cmd_forget_fact_gui(cmd_text[len("forget-fact"):].strip(), lang)
            return True
        if cmd_l == "forget" or cmd_l.startswith("forget "):
            self._cmd_forget_gui(cmd_text[6:].strip(), lang)
            return True
        if cmd_l == "mood":
            self._cmd_mood_gui(lang)
            return True
        if cmd_l == "birthday" or cmd_l.startswith("birthday "):
            self._cmd_birthday_gui(cmd_text[8:].strip(), lang)
            return True
        if cmd_l == "whoami":
            self._cmd_whoami_gui(lang)
            return True
        if cmd_l == "stats":
            self._cmd_stats_gui(lang)
            return True
        if cmd_l == "reset-mood" or cmd_l == "resetmood":
            self._cmd_reset_mood_gui(lang)
            return True
        if cmd_l == "export-log" or cmd_l.startswith("export-log "):
            self._cmd_export_log_gui(cmd_text[len("export-log"):].strip(), lang)
            return True
        if cmd_l == "clear-log" or cmd_l == "clearlog":
            self._cmd_clear_log_gui(lang)
            return True
        if cmd_l == "history":
            self._cmd_history_gui(lang)
            return True
        if cmd_l == "search" or cmd_l.startswith("search "):
            self._cmd_search_gui(cmd_text[len("search"):].strip(), lang)
            return True
        if cmd_l == "recap":
            self._cmd_recap_gui(lang)
            return True
        if cmd_l in ("feeling", "checkin"):
            self._cmd_feeling_gui(lang)
            return True
        if cmd_l == "avatar":
            self._cmd_avatar_gui(lang)
            return True
        if cmd_l == "help":
            self._cmd_help_gui(lang)
            return True
        return False  # 未知のコマンドは通常の respond() へ

    def _cmd_help_gui(self, lang: str) -> None:
        """GUI の /help コマンドを処理する（利用可能なコマンド一覧を表示）。"""
        if lang == "en":
            reply = ("Commands: /gift <item>, /callme <name>, /birthday MM-DD, "
                     "/like <thing>, /forget <thing>, /forget-fact <text>, "
                     "/whoami, /forget-me, /forget-all, /mood, /reset-mood, /stats, "
                     "/export-log [path], /clear-log, /history, /search <keyword>, "
                     "/recap, /feeling, /avatar, /help")
        else:
            reply = ("コマンド: /gift <プレゼント>、/callme <名前>、/birthday MM-DD、"
                     "/like <好きなもの>、/forget <好きなもの>、/forget-fact <内容>、"
                     "/whoami、/forget-me、/forget-all、/mood、/reset-mood、/stats、"
                     "/export-log [パス]、/clear-log、/history、/search <キーワード>、"
                     "/recap、/feeling、/avatar、/help")
        # 「これは何なのか」を確かめに来る場所なので、ここでも AI である旨を示す
        if _ai_disclosure is not None:
            reply = reply + "\n" + _ai_disclosure.session_notice(lang)
        self._speak_reply(reply)

    def _cmd_gift_gui(self, item: str, lang: str, level) -> None:
        """GUI の /gift <item> コマンドを処理する。"""
        if not item or item.lower() == "list":
            if _gift_catalog_text_gui is not None:
                cat = _gift_catalog_text_gui(lang)
                hdr = "Available gifts (bonus):\n" if lang == "en" else "贈れるプレゼント一覧（ボーナス）:\n"
                self._speak_reply(hdr + cat)
            else:
                self._speak_reply("/gift <プレゼント>  例: /gift 花")
            return

        if _lookup_gift_gui is None:
            self._speak_reply("(プレゼント機能は利用できません)")
            return

        # デイリークールダウン: 同じギフトを今日すでに贈った場合は断る
        if get_mood_tracker is not None and _lookup_gift_key_gui is not None:
            try:
                tracker = get_mood_tracker()
                gift_key = _lookup_gift_key_gui(item, lang=lang)
                if (gift_key and hasattr(tracker, "gift_received_today")
                        and tracker.gift_received_today(gift_key)):
                    msg = (_gift_cooldown_message_gui(lang)
                           if _gift_cooldown_message_gui is not None else "また明日ね。")
                    self._speak_reply(msg)
                    return
            except Exception as e:
                logger.debug("ギフトクールダウンの確認に失敗（GUI）: %s", e)

        result = _lookup_gift_gui(item, lang=lang, level=level)
        if result is None:
            if lang == "en":
                reply = (f"Hmm, I'm not sure about {item}. "
                         "Try /gift list to see options.")
            else:
                reply = f"「{item}」はよく分からないな。/gift list で確認してね。"
            self._speak_reply(reply)
            return

        bonus, avatar_reply = result
        # デイリームードの倍率を好感度ボーナスに適用
        effective_bonus = bonus
        if bonus > 0.0 and _get_daily_mood_gui is not None and _mood_affinity_multiplier_gui is not None:
            try:
                mult = _mood_affinity_multiplier_gui(_get_daily_mood_gui())
                effective_bonus = bonus * mult
            except Exception:
                pass
        # earn() は日次上限（max_daily_gain）を通す — 会話とプレゼントで予算を
        # 共有しないと、上限が成長弧の長さを決めなくなる（CLI 側と対）。
        applied = effective_bonus
        if effective_bonus > 0.0 and get_mood_tracker is not None:
            try:
                tracker = get_mood_tracker()
                applied = tracker.earn(effective_bonus)
                # 受け取り記録（デイリークールダウン用）
                if _lookup_gift_key_gui is not None and hasattr(tracker, "record_gift"):
                    try:
                        gk = _lookup_gift_key_gui(item, lang=lang)
                        if gk:
                            tracker.record_gift(gk)
                    except Exception:
                        pass
                if _default_mood_path is not None:
                    tracker.save(_default_mood_path())
                if _default_mood_history_path is not None:
                    tracker.snapshot_to_history(_default_mood_history_path())
            except Exception as e:
                logger.debug("プレゼントの好感度ボーナス適用に失敗（GUI）: %s", e)

        # 上限に達していて実際には 0 だったときは数字を出さない（CLI 側と対）。
        if round(applied) >= 1:
            avatar_reply = (f"{avatar_reply} (+{round(applied)} affinity)" if lang == "en"
                            else f"{avatar_reply}（好感度 +{round(applied)}）")

        if get_conversation_log is not None:
            try:
                get_conversation_log().log_exchange(f"/gift {item}", avatar_reply)
            except Exception:
                pass
        self._speak_reply(avatar_reply)

    def _cmd_callme_gui(self, name: str, lang: str) -> None:
        """GUI の /callme <name> コマンドを処理する。"""
        if not name:
            self._speak_reply(_command_usage_gui("callme", lang))
            return

        # set_name() でサニタイズ（長さ上限・制御文字除去）した値を採用する。
        # 直接 prof.name = name すると未検証の文字列が TTS/あいさつに混入する。
        saved = name
        if _get_user_profile_gui is not None:
            try:
                prof = _get_user_profile_gui()
                if prof is not None:
                    saved = prof.set_name(name) or name
                    if _default_profile_path_gui is not None:
                        prof.save(_default_profile_path_gui())
            except Exception as e:
                logger.debug("/callme プロフィール保存に失敗（GUI）: %s", e)

        reply = (f"{saved}? That's a lovely name! I'll remember it." if lang == "en"
                 else f"{saved}って呼べばいいんだね！覚えたよ。")
        if get_conversation_log is not None:
            try:
                get_conversation_log().log_exchange(f"/callme {name}", reply)
            except Exception:
                pass
        self._speak_reply(reply)

    def _cmd_like_gui(self, thing: str, lang: str) -> None:
        """GUI の /like <thing> コマンドを処理する。"""
        if not thing:
            self._speak_reply(_command_usage_gui("like", lang))
            return

        saved = ""
        if _get_user_profile_gui is not None:
            try:
                prof = _get_user_profile_gui()
                if prof is not None:
                    saved = prof.add_interest(thing)
                    if saved and _default_profile_path_gui is not None:
                        prof.save(_default_profile_path_gui())
            except Exception as e:
                logger.debug("/like プロフィール保存に失敗（GUI）: %s", e)

        if saved:
            reply = (f"Oh, you like {saved}? I'll remember that!" if lang == "en"
                     else f"{saved}が好きなんだね！覚えておくよ。")
            if get_conversation_log is not None:
                try:
                    get_conversation_log().log_exchange(f"/like {thing}", reply)
                except Exception:
                    pass
        else:
            reply = ("Couldn't save that (list may be full)." if lang == "en"
                     else "うまく覚えられなかったよ（リストがいっぱいかも）。")
        self._speak_reply(reply)

    def _cmd_forget_gui(self, thing: str, lang: str) -> None:
        """GUI の /forget <thing> コマンドを処理する。"""
        if not thing:
            self._speak_reply(_command_usage_gui("forget", lang))
            return

        removed = False
        if _get_user_profile_gui is not None:
            try:
                prof = _get_user_profile_gui()
                if prof is not None:
                    removed = prof.remove_interest(thing)
                    if removed and _default_profile_path_gui is not None:
                        prof.save(_default_profile_path_gui())
            except Exception as e:
                logger.debug("/forget プロフィール保存に失敗（GUI）: %s", e)

        if removed:
            reply = (f"Got it, I'll forget about {thing}." if lang == "en"
                     else f"{thing}のこと、忘れたよ。")
            if get_conversation_log is not None:
                try:
                    get_conversation_log().log_exchange(f"/forget {thing}", reply)
                except Exception:
                    pass
        else:
            reply = (f"I don't think I had {thing} on my list." if lang == "en"
                     else f"{thing}はリストにないみたい。")
        self._speak_reply(reply)

    def _cmd_forget_fact_gui(self, text: str, lang: str) -> None:
        """GUI の /forget-fact <内容> コマンドを処理する。

        一問一答で覚えた事実のうち、指定したテキストが回答（値）に部分一致
        するものを 1 件忘れさせる。/whoami はキーではなく値のみを表示するため、
        値の大文字小文字を無視した部分一致でキーを逆引きする
        （persona_cli._remove_fact と同一ロジック）。
        """
        if not text:
            self._speak_reply(_command_usage_gui("forget-fact", lang))
            return
        if _get_user_profile_gui is None:
            self._speak_reply("(プロファイルは利用できません)" if lang != "en"
                              else "(Profile unavailable)")
            return
        try:
            prof = _get_user_profile_gui()
            if prof is None:
                self._speak_reply("(プロファイルは利用できません)" if lang != "en"
                                  else "(Profile unavailable)")
                return
            facts = getattr(prof, "facts", {}) or {}
            needle = text.strip().lower()
            matched_key = None
            for key, value in facts.items():
                if needle in str(value).strip().lower():
                    matched_key = key
                    break
            removed = False
            if matched_key is not None:
                removed = prof.remove_fact(matched_key)
                if removed and _default_profile_path_gui is not None:
                    prof.save(_default_profile_path_gui())
        except Exception as e:
            logger.debug("/forget-fact に失敗（GUI）: %s", e)
            self._speak_reply("(削除に失敗しました)" if lang != "en"
                              else "(Failed to forget that)")
            return

        if removed:
            reply = ("Okay, I've forgotten that." if lang == "en"
                     else "わかった、そのこと忘れておくね。")
            if get_conversation_log is not None:
                try:
                    get_conversation_log().log_exchange(f"/forget-fact {text}", reply)
                except Exception:
                    pass
        else:
            reply = (f"I don't have anything like '{text}' in my memory." if lang == "en"
                     else f"「{text}」に近いことは覚えてないよ。")
        self._speak_reply(reply)

    def _cmd_forget_me_gui(self, lang: str) -> None:
        """GUI の /forget-me コマンドを処理する（プロフィールの個人情報を消去）。

        呼び名・誕生日・趣味・会話で覚えた事実（プロフィール）を消す。会話履歴は
        /clear-log、好感度は /reset-mood が担当。会話履歴・好感度も含めて**全部**
        消したい場合は /forget-all を使う。

        **二段階確認する。** 以前はここだけ確認が無く、`/forget-me` を一度
        打っただけで呼び名・誕生日・趣味・覚えた事実が復元不能に消えていた。
        兄弟の破壊的コマンド（/clear-log・/reset-mood・/forget-all）と CLI 側の
        同名コマンドはいずれも確認を持っており、ここだけが抜けていた。
        打ち間違いで人の記憶が消える経路を残さない。
        """
        if not getattr(self, "_forget_me_pending", False):
            self._forget_me_pending = True
            self._speak_reply(_confirmation_prompt_gui("forget-me", lang))
            return
        self._forget_me_pending = False
        if _get_user_profile_gui is None:
            self._speak_reply("(プロファイルは利用できません)" if lang != "en"
                              else "(Profile unavailable)")
            return
        try:
            prof = _get_user_profile_gui()
            if prof is None:
                self._speak_reply("(プロファイルは利用できません)" if lang != "en"
                                  else "(Profile unavailable)")
                return
            prof.clear()
            if _default_profile_path_gui is not None:
                prof.save(_default_profile_path_gui())
            reply = ("Okay — I've forgotten everything personal about you. "
                     "We can start fresh whenever you like." if lang == "en"
                     else "わかった、あなたのことは全部忘れたよ。また、いつでも教えてね。")
        except Exception as e:
            logger.debug("/forget-me に失敗（GUI）: %s", e)
            reply = ("(Couldn't erase your data)" if lang == "en"
                     else "(個人情報の消去に失敗しました)")
        self._speak_reply(reply)

    def _cmd_forget_all_gui(self, lang: str) -> None:
        """GUI の /forget-all コマンド: 全個人データを一括消去（二段階確認）。

        /forget-me はプロフィールのみ、/clear-log は会話履歴のみ、/reset-mood は
        好感度のみを消す。プライバシー優先の製品として「私に関するデータを全部
        消して」を 1 コマンドで叶えるのがこれ（プロフィール＋会話履歴＋好感度＋
        アバター履歴を一括）。破壊的なので /clear-log 等と同じ二段階確認を行う。
        """
        is_en = lang.startswith("en")
        if not getattr(self, "_forget_all_pending", False):
            reply = _confirmation_prompt_gui("forget-all", lang)
            self._forget_all_pending = True
            self._speak_reply(reply)
            return
        self._forget_all_pending = False
        try:
            report = _erase_all_user_data()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("/forget-all に失敗（GUI）: %s", e)
            self._speak_reply("(Failed to erase your data)" if is_en
                              else "(データの消去に失敗しました)")
            return
        erased = sum(1 for v in report.values() if v)
        if erased == 0:
            self._speak_reply("(Nothing to erase)" if is_en
                              else "(消すデータはありませんでした)")
            return
        reply = ("Done — I've erased everything personal: profile, conversation "
                 "history, affinity, and avatar selection. We can start fresh."
                 if is_en else
                 "全部消したよ — プロフィール・会話履歴・好感度・アバター選択。"
                 "また一から始めよう。")
        self._speak_reply(reply)

    def _cmd_mood_gui(self, lang: str) -> None:
        """GUI の /mood コマンドを処理する。"""
        if get_mood_tracker is None:
            self._speak_reply("(好感度情報は利用できません)" if lang != "en"
                              else "(Affinity info unavailable)")
            return
        try:
            tracker = get_mood_tracker()
            level_label = tracker.label(lang="en" if lang == "en" else "ja")
            affinity = int(tracker.affinity)
            if lang == "en":
                reply = f"Affinity: {level_label} ({affinity} pts)"
            else:
                reply = f"好感度: {level_label}（{affinity}pt）"
        except Exception as e:
            logger.debug("/mood 情報取得に失敗（GUI）: %s", e)
            reply = ("(Couldn't get mood info)" if lang == "en"
                     else "(好感度情報の取得に失敗)")
        self._speak_reply(reply)

    def _cmd_whoami_gui(self, lang: str) -> None:
        """GUI の /whoami コマンドを処理する（プロファイル概要を表示）。"""
        if _get_user_profile_gui is None:
            self._speak_reply("(プロファイルは利用できません)" if lang != "en"
                              else "(Profile unavailable)")
            return
        try:
            prof = _get_user_profile_gui()
            if prof is None:
                self._speak_reply("(プロファイルは利用できません)" if lang != "en"
                                  else "(Profile unavailable)")
                return
            parts = []
            if prof.name:
                parts.append(f"名前: {prof.name}" if lang != "en" else f"Name: {prof.name}")
            if prof.birthday:
                parts.append(f"誕生日: {prof.birthday}" if lang != "en"
                             else f"Birthday: {prof.birthday}")
            if prof.interests:
                joined = "、".join(prof.interests) if lang != "en" else ", ".join(prof.interests)
                parts.append(f"好きなもの: {joined}" if lang != "en"
                             else f"Interests: {joined}")
            # 一問一答で覚えた事実（CLI の /whoami と同等の表示）
            facts = getattr(prof, "facts", {})
            if facts:
                parts.append("覚えていること:" if lang != "en"
                             else "Things I remember about you:")
                for value in facts.values():
                    parts.append(f"  - {value}")
            reply = "\n".join(parts) if parts else (
                "まだ何も知らないよ。教えてね！" if lang != "en"
                else "I don't know anything about you yet. Tell me!")
        except Exception as e:
            logger.debug("/whoami プロファイル取得に失敗（GUI）: %s", e)
            reply = "(情報の取得に失敗)" if lang != "en" else "(Couldn't get profile)"
        self._speak_reply(reply)

    def _cmd_stats_gui(self, lang: str) -> None:
        """GUI の /stats コマンドを処理する（会話統計を表示）。"""
        parts = []
        if get_mood_tracker is not None:
            try:
                tracker = get_mood_tracker()
                if lang == "en":
                    parts.append(f"Total interactions: {tracker.interactions}")
                    parts.append(f"Affinity: {int(tracker.affinity)} pts ({tracker.label('en')})")
                else:
                    parts.append(f"会話回数: {tracker.interactions}回")
                    parts.append(f"好感度: {int(tracker.affinity)}pt（{tracker.label('ja')}）")
            except Exception as e:
                logger.debug("/stats 好感度取得に失敗（GUI）: %s", e)
        if get_conversation_log is not None:
            try:
                log = get_conversation_log()
                count = len(log.search("", include_archives=False))
                if lang == "en":
                    parts.append(f"Logged exchanges: {count}")
                else:
                    parts.append(f"記録済み会話: {count}件")
            except Exception as e:
                logger.debug("/stats 会話ログ取得に失敗（GUI）: %s", e)
        reply = "\n".join(parts) if parts else (
            "(統計情報は利用できません)" if lang != "en" else "(Stats unavailable)")
        self._speak_reply(reply)

    def _cmd_reset_mood_gui(self, lang: str) -> None:
        """GUI の /reset-mood コマンドを処理する（好感度をニュートラルにリセット・二段階確認）。

        破壊的操作（関係進捗の全消去）のため、/clear-log と同様に明示的な
        二段階確認を行う。以前は確認無しで即座にリセットしており、
        テキスト入力欄への誤操作 1 回で関係進捗が丸ごと消える危険があった
        （persona_cli.py の同コマンドは元々この確認を持っていた）。
        """
        if get_mood_tracker is None:
            self._speak_reply("(好感度は無効です)" if lang != "en" else "(Affinity unavailable)")
            return

        if not getattr(self, "_reset_mood_pending", False):
            reply = _confirmation_prompt_gui("reset-mood", lang)
            self._reset_mood_pending = True
            self._speak_reply(reply)
            return
        self._reset_mood_pending = False

        try:
            from mood import AFFINITY_START
            tracker = get_mood_tracker()
            tracker.affinity = AFFINITY_START
            tracker.interactions = 0
            tracker._last_interaction_time = 0.0
            tracker._first_interaction_time = 0.0
            tracker._last_anniversary_days = 0
            tracker._last_login_date = ""
            tracker._login_streak = 0
            tracker._confession_done = False
            if _default_mood_path is not None:
                tracker.save(_default_mood_path())
            reply = (f"Affinity reset to neutral ({int(AFFINITY_START)}/100)." if lang == "en"
                     else f"好感度をニュートラル（{int(AFFINITY_START)}/100）にリセットしました。")
        except Exception as e:
            logger.debug("/reset-mood に失敗（GUI）: %s", e)
            reply = "(好感度のリセットに失敗しました)" if lang != "en" else "(Reset failed)"
        self._speak_reply(reply)

    def _cmd_export_log_gui(self, dest: str, lang: str) -> None:
        """GUI の /export-log [パス] コマンドを処理する。

        会話履歴（アーカイブ含む全件）を CSV へエクスポートする
        （persona_cli._export_log と同一ロジック）。
        """
        if not dest:
            dest = "conversation_export.csv"
        if get_conversation_log is None:
            self._speak_reply("(会話履歴は利用できません)" if lang != "en"
                              else "(Conversation history unavailable)")
            return
        avatar_label = "Avatar"
        try:
            if self.persona and self.persona.name:
                avatar_label = self.persona.name
        except Exception:
            pass
        try:
            conv_log = get_conversation_log()
            csv_text = conv_log.to_csv(avatar_label=avatar_label, include_archives=True)
            # 0600 で保存している会話ログの完全な複製なので、複製も 0600 に
            # する（CLI 側と対）。newline="" は Windows の改行二重変換対策。
            _atomic_write_text(dest, csv_text, restrict=True, newline="")
        except Exception as e:
            logger.debug("/export-log に失敗（GUI）: %s", e)
            reply = (f"(Failed to export the log to '{dest}')" if lang == "en"
                     else f"(会話履歴のエクスポートに失敗しました: {dest})")
            self._speak_reply(reply)
            return
        reply = (f"Conversation history exported to: {dest}" if lang == "en"
                 else f"会話履歴をエクスポートしました: {dest}")
        self._speak_reply(reply)

    def _cmd_clear_log_gui(self, lang: str) -> None:
        """GUI の /clear-log コマンドを処理する（会話履歴を全消去・二段階確認）。

        ライブファイル + gzip アーカイブを消去する
        （persona_cli._clear_log と同一ロジック）。破壊的操作のため、
        /forget-me と異なり明示的な二段階確認を行う。
        """
        if not getattr(self, "_clear_log_pending", False):
            reply = _confirmation_prompt_gui("clear-log", lang)
            self._clear_log_pending = True
            self._speak_reply(reply)
            return
        self._clear_log_pending = False
        if get_conversation_log is None:
            self._speak_reply("(会話履歴は利用できません)" if lang != "en"
                              else "(Conversation history unavailable)")
            return
        try:
            import os as _os
            from conversation_log import _find_archives
            conv_log = get_conversation_log()
            path = conv_log.logfile
            archives = _find_archives(path)
            total = (1 if _os.path.exists(path) else 0) + len(archives)
            if total == 0:
                self._speak_reply("(ログファイルが存在しません)" if lang != "en"
                                  else "(No log file exists)")
                return
            if _os.path.exists(path):
                open(path, "w", encoding="utf-8").close()
            removed_archives = 0
            for gz in archives:
                try:
                    _os.remove(gz)
                    removed_archives += 1
                except OSError:
                    pass
        except Exception as e:
            logger.debug("/clear-log に失敗（GUI）: %s", e)
            self._speak_reply("(会話履歴の消去に失敗しました)" if lang != "en"
                              else "(Failed to clear the conversation history)")
            return
        if lang == "en":
            note = f" ({removed_archives} archive(s) removed)" if removed_archives else ""
            reply = f"Conversation history cleared.{note}"
        else:
            note = f"（アーカイブ {removed_archives} 件を削除）" if removed_archives else ""
            reply = f"会話履歴を消去しました。{note}"
        self._speak_reply(reply)

    def _cmd_history_gui(self, lang: str) -> None:
        """GUI の /history コマンドを処理する（直近の会話履歴を表示）。"""
        if get_conversation_log is None:
            self._speak_reply("(会話履歴は利用できません)" if lang != "en"
                              else "(Conversation history unavailable)")
            return
        try:
            lines = get_conversation_log().recent_texts(_HISTORY_DEFAULT_GUI)
        except Exception as e:
            logger.debug("/history 取得に失敗（GUI）: %s", e)
            lines = []
        if not lines:
            self._speak_reply("(まだ会話履歴はありません)" if lang != "en"
                              else "(No conversation history yet)")
            return
        self._speak_reply("\n".join(lines))

    def _cmd_search_gui(self, query: str, lang: str) -> None:
        """GUI の /search <キーワード> コマンドを処理する（アーカイブ含む）。"""
        if get_conversation_log is None:
            self._speak_reply("(会話履歴は利用できません)" if lang != "en"
                              else "(Conversation history unavailable)")
            return
        if not query:
            self._speak_reply(_command_usage_gui("search", lang))
            return
        try:
            from conversation_log import USER_EVENT_TYPES
            from datetime import datetime as _dt
            results = get_conversation_log().search(query, include_archives=True)
        except Exception as e:
            logger.debug("/search に失敗（GUI）: %s", e)
            self._speak_reply("(検索に失敗しました)" if lang != "en" else "(Search failed)")
            return
        if not results:
            # 完全一致が無ければ BM25 の関連度検索で「近い会話」を提示する
            # （語順・言い回し違いを越えて想起。研究 A4）。
            related = []
            try:
                related = get_conversation_log().search_relevant(query, n=5, include_archives=True)
            except Exception as e:
                logger.debug("/search 関連度検索に失敗（GUI）: %s", e)
            if related:
                header = (f"「{query}」に一致は無いけど、近い会話だよ:" if lang != "en"
                          else f"No exact match for '{query}', but here's what's related:")
                rel_lines = [header]
                for ev in related:
                    ts = ev.get("timestamp", 0)
                    try:
                        dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    except (OSError, OverflowError, ValueError, TypeError):
                        dt_str = "?"
                    prefix = "You" if ev.get("event_type") in USER_EVENT_TYPES else "Avatar"
                    text = (ev.get("details") or {}).get("text", "")
                    rel_lines.append(f"[{dt_str}] {prefix}: {text}")
                self._speak_reply("\n".join(rel_lines))
                return
            self._speak_reply(f"(「{query}」に一致する会話は見つかりませんでした)" if lang != "en"
                              else f"(No conversations matching '{query}' found)")
            return
        lines = [f"「{query}」の検索結果: {len(results)} 件" if lang != "en"
                 else f"Search results for '{query}': {len(results)}"]
        for ev in results[-20:]:
            ts = ev.get("timestamp", 0)
            try:
                dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, OverflowError, ValueError, TypeError):
                dt_str = "?"
            prefix = "You" if ev.get("event_type") in USER_EVENT_TYPES else "Avatar"
            text = (ev.get("details") or {}).get("text", "")
            lines.append(f"[{dt_str}] {prefix}: {text}")
        self._speak_reply("\n".join(lines))

    def _cmd_recap_gui(self, lang: str) -> None:
        """GUI の /recap コマンドを処理する（今日のまとめと直近のやりとり）。"""
        is_en = lang.startswith("en")
        lines = []
        if _summary_greeting_gui is not None:
            try:
                greeting = _summary_greeting_gui(lang=lang)
                if greeting:
                    lines.append(greeting)
            except Exception as e:
                logger.debug("/recap サマリー取得に失敗（GUI）: %s", e)
        if get_conversation_log is not None:
            try:
                conv_log = get_conversation_log()
                recent = conv_log.recent(3)
                if recent:
                    lines.append("── Recent exchanges ──" if is_en else "── 直近のやりとり ──")
                    from conversation_log import USER_EVENT_TYPES
                    for entry in recent:
                        et = entry.get("event_type", "")
                        text = (entry.get("details") or {}).get("text", "")
                        if not text:
                            continue
                        label = ("You" if is_en else "あなた") if et in USER_EVENT_TYPES else "Satin"
                        lines.append(f"  {label}: {text}")
            except Exception as e:
                logger.debug("/recap 履歴取得に失敗（GUI）: %s", e)
        if not lines:
            self._speak_reply("No conversations yet today." if is_en
                              else "今日はまだ会話が記録されていません。")
            return
        self._speak_reply("\n".join(lines))

    def _cmd_feeling_gui(self, lang: str) -> None:
        """GUI の /feeling (/checkin) コマンドを処理する（気分の寄り添い）。"""
        is_en = lang.startswith("en")
        if _wellbeing_summary_gui is None or _wellbeing_message_gui is None:
            self._speak_reply("(wellbeing unavailable)" if is_en
                              else "(気分の寄り添い機能は利用できません)")
            return
        try:
            summary = _wellbeing_summary_gui(days=3)
            msg = _wellbeing_message_gui(summary, lang=lang)
        except Exception as e:
            logger.debug("/feeling に失敗（GUI）: %s", e)
            summary, msg = {}, ""
        if msg:
            self._speak_reply(msg)
            return
        if summary.get("sample_size", 0) < 3:
            reply = ("Let's talk a bit more and I'll get a feel for how you're doing."
                     if is_en else "もう少しお話ししたら、あなたの調子がわかるよ。")
        else:
            reply = ("You seem steady lately — that's good." if is_en
                     else "最近は落ち着いてるみたいだね。いい感じ。")
        self._speak_reply(reply)

    def _cmd_avatar_gui(self, lang: str) -> None:
        """GUI の /avatar コマンド: モデルを選び直して、その場で描画に反映する。

        以前は「表示中のモデル名を言う」だけで、選ぶには本体を終了して
        `--avatar-loader`（tkinter の別アプリ）を起動し、選んでから**再起動**
        する必要があった。1 つの機能のために GUI ツールキットを 2 つ抱え、
        プロセスを跨いで選択を受け渡し、ユーザーには再起動を強いていた。
        本体は既に PyQt5 を持っているので、QFileDialog を直接開けばよい。
        重複していた `--avatar-loader` は削除済み（tkinter と Pillow への
        依存もそれと一緒に消えた）。
        """
        import os as _os
        is_en = lang.startswith("en")
        picked = self._pick_avatar_file(is_en)
        if picked is None:
            # ダイアログが使えない環境。従来どおり現在の状態を報告する。
            self._report_current_avatar(is_en)
            return
        if not picked:
            return  # ユーザーがキャンセルした（無言で戻る）
        if self.load_avatar_model(picked):
            if _avatar_model_store is not None:
                try:
                    _avatar_model_store.save_selection(picked)
                except Exception as e:
                    logger.debug("アバター選択の保存に失敗しました: %s", e)
            name = _os.path.basename(picked)
            self._speak_reply(f"Switched to {name}." if is_en
                              else f"{name} にしたよ。")
        else:
            self._speak_reply(
                "I couldn't read that model file." if is_en
                else "そのモデルファイル、読めなかった…。")

    #: /avatar のファイル選択ダイアログが受け付ける拡張子。
    AVATAR_FILE_FILTER = ("3D models (*.glb *.gltf *.vrm);;All files (*)")

    def _pick_avatar_file(self, is_en: bool):
        """モデルファイルを選ばせる。

        Returns:
            選ばれたパス、キャンセルなら空文字、ダイアログが使えない環境なら
            None（呼び出し側が従来の報告へフォールバックする）。
        """
        if QFileDialog is None:
            return None
        try:
            path, _sel = QFileDialog.getOpenFileName(
                self,
                "Choose an avatar model" if is_en else "アバターモデルを選ぶ",
                "",
                self.AVATAR_FILE_FILTER,
            )
            return path or ""
        except Exception as e:  # pragma: no cover - ヘッドレス等でダイアログ不可
            logger.debug("ファイル選択ダイアログを開けませんでした: %s", e)
            return None

    def _report_current_avatar(self, is_en: bool) -> None:
        """ダイアログが使えないときのフォールバック: 現在の状態を伝える。"""
        import os as _os
        try:
            self.load_avatar_model()
        except Exception as e:
            logger.debug("/avatar 再読み込みに失敗（GUI）: %s", e)
        path = getattr(self, "avatar_model_path", None)
        if path:
            name = _os.path.basename(path)
            self._speak_reply(f"Currently showing avatar: {name}" if is_en
                              else f"いま表示してるアバター: {name}")
        else:
            self._speak_reply(
                "No avatar model loaded yet." if is_en
                else "アバターモデルはまだ未設定だよ。")

    def _cmd_birthday_gui(self, date_str: str, lang: str) -> None:
        """GUI の /birthday MM-DD コマンドを処理する。"""
        if not date_str:
            self._speak_reply(_command_usage_gui("birthday", lang))
            return

        saved = ""
        if _get_user_profile_gui is not None:
            try:
                prof = _get_user_profile_gui()
                if prof is not None:
                    saved = prof.set_birthday(date_str)
                    if saved and _default_profile_path_gui is not None:
                        prof.save(_default_profile_path_gui())
            except Exception as e:
                logger.debug("/birthday プロフィール保存に失敗（GUI）: %s", e)

        if saved:
            reply = (f"Got it — your birthday is {saved}. I won't forget it!" if lang == "en"
                     else f"覚えた、誕生日は{saved}だね。忘れないよ！")
            if get_conversation_log is not None:
                try:
                    get_conversation_log().log_exchange(f"/birthday {date_str}", reply)
                except Exception:
                    pass
        else:
            reply = ("Hmm, that date doesn't look right. Try MM-DD format." if lang == "en"
                     else "日付の形式が違うみたい。MM-DD の形で教えてね。")
        self._speak_reply(reply)

    def _on_talk_start(self, text):
        if self.tts_queue:
            self.tts_queue.put(text)

    def update_autonomous(self):
        if not self.is_autonomous:
            return
        if self.mode == 'comment':
            # コメント読み上げ中
            self.ticks += 1
            if self.ticks > 60:  # 3秒表示
                self.mode = 'run'
                self.comment_text = ''
                self.talk_text = ''
                self.ticks = 0
        else:
            self._advance_autonomous_state()
        self.update()

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        # z は共有定数。自律移動の境界（autonomous_behavior._movement_bounds）が
        # この距離での可視範囲から算出されるので、ここだけ変えると歩き去る。
        glTranslatef(self.position[0], self.position[1], AVATAR_Z)
        glColor3f(0.6, 0.8, 1.0)
        # 面が取れていれば陰影付きソリッド、頂点だけならワイヤーフレーム、
        # モデルが無ければ球体プレースホルダ。
        vertices = self.avatar_model_vertices
        faces = self.avatar_model_faces
        if vertices is not None and len(vertices) > 0:
            if faces is not None and len(faces) > 0:
                self._paint_solid(vertices, faces, self.avatar_model_normals)
            else:
                glBegin(GL_LINE_STRIP)
                for v in vertices:
                    glVertex3f(float(v[0]), float(v[1]), float(v[2]))
                glEnd()
        else:
            self._paint_placeholder()

    def _paint_placeholder(self) -> None:
        """モデル未読込のときのプレースホルダ球。

        GLU（gluSphere）を使うが、`pip install PyOpenGL` はシステムライブラリ
        libGLU.so を導入しないため、Linux のクリーン環境では実体が無いことが
        ある。しかも import は成功し、呼んだ瞬間に NullFunctionError になる。
        Qt は仮想メソッド内の例外でプロセスを abort するので、ここを裸で
        呼ぶと**アバターを選んでいないだけでアプリごと落ちる**。

        プレースホルダが出ないことは機能の縮退にすぎず、会話も TTS も
        ダッシュボードも動く。落とすほどの価値は無いので握りつぶす。
        必須の描画経路（射影行列）からは GLU をすでに排除してある
        （gl_widget_base 参照）。
        """
        if gluNewQuadric is None or gluSphere is None:
            return
        try:
            quad = gluNewQuadric()
            gluSphere(quad, AVATAR_RADIUS, 32, 32)
        except Exception as e:  # NullFunctionError 等（GLU の実体が無い環境）
            logger.debug("プレースホルダ球を描画できませんでした: %s", e)

    #: ソリッド描画のベース色（陰影係数を掛けて面ごとの明るさを作る）
    SOLID_BASE_COLOR = (0.6, 0.8, 1.0)

    def _paint_solid(self, vertices, faces, normals):
        """三角形を面ごとの拡散シェーディングで描画する。

        GL_LIGHTING を有効化せず、面法線から求めた係数をベース色に掛けて
        `glColor3f` で塗る。固定機能ライティングの状態（光源・マテリアル・
        法線の正規化）を持ち込まずに陰影が付くので、他のウィジェットと共有して
        いる GL ステートを汚さない。明るさの計算は `gltf_utils.shade_factor` の
        純関数なので、GPU 無しでも検証できる。

        法線が無い/数が合わない場合はフラット色で描く（陰影だけ諦める）。
        """
        base_r, base_g, base_b = self.SOLID_BASE_COLOR
        use_shading = (shade_factor is not None and normals is not None
                       and len(normals) == len(faces))
        glBegin(GL_TRIANGLES)
        for i, face in enumerate(faces):
            if use_shading:
                k = shade_factor(normals[i])
                glColor3f(base_r * k, base_g * k, base_b * k)
            for vertex_index in face:
                v = vertices[int(vertex_index)]
                glVertex3f(float(v[0]), float(v[1]), float(v[2]))
        glEnd()

class MainWindow(QMainWindow if QMainWindow is not None else object):  # type: ignore[misc]
    def __init__(self):
        super().__init__()
        _persona = None
        try:
            from persona import get_persona as _gp
            _persona = _gp()
            _title_name = _persona.name
        except Exception:
            _title_name = "Satin"
        # GUI クローム（ボタン・プレースホルダ・タイトル）の言語。会話応答と同じく
        # persona.lang に従う。従来はチェーム文言が日本語ハードコードで、英語ユーザーに
        # 「自律モードON」等が日本語のまま出ていた（多言語対応の看板に反していた）。
        self._lang = getattr(_persona, "lang", "ja") if _persona is not None else "ja"
        is_en = self._lang.startswith("en")
        self.setWindowTitle(f"{_title_name} — "
                            + ("3D Companion" if is_en else "3D コンパニオン"))
        self.tts_queue = queue.Queue()
        self.tts_thread = TTSThread(self.tts_queue)
        self.tts_thread.start()
        # ポモドーロ式ブレークリマインダー（自律モード ON 中のみ稼働）
        self.break_reminder = None
        self.viewer = AutonomousAvatarViewer(self)
        self.viewer.set_tts_queue(self.tts_queue)
        # 前回 /avatar で選んだアバターがあれば起動時に読み込んで描画する。
        try:
            self.viewer.load_avatar_model()
        except Exception as e:
            logger.debug("起動時のアバターモデル読み込みに失敗: %s", e)
        self.setCentralWidget(self.viewer)
        self.autonomous_btn = QPushButton(self._autonomous_label(False), self)
        self.autonomous_btn.setGeometry(10, 10, 120, 30)
        self.autonomous_btn.clicked.connect(self.toggle_autonomous)
        self.talk_label = QLabel('', self)
        self.talk_label.setGeometry(150, 10, 400, 30)
        self.talk_label.setStyleSheet('font-size:18px; color:#222; background:#eee;')
        self.comment_input = QLineEdit(self)
        self.comment_input.setGeometry(10, 50, 400, 30)
        # プレースホルダは新規ユーザーが最初に読む唯一の手がかり。「読み上げ」だけ
        # だと TTS ツールに見えるので、会話できることと /help の存在を示す。
        self.comment_input.setPlaceholderText(
            "Talk to me and press Enter  —  type /help for commands" if is_en
            else "話しかけて Enter  —  「/help」で使えることの一覧")
        self.comment_input.returnPressed.connect(self.handle_comment)
        # テキスト更新タイマー
        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self.update_talk_text)
        self.text_timer.start(100)
        # 起動時の 2 つのメッセージ（初回のみの歓迎と、毎回の AI 開示）を
        # **1 つにまとめて**出す。_speak_reply は comment_text を置き換えるので、
        # 続けて呼ぶと後者が前者を消す — 実際そうなっており、初回起動のユーザーに
        # 歓迎メッセージは一度も見えていなかった（開示だけが残る）。
        # first_run.py はまさに「初回接触時に製品の価値が見えない」問題のために
        # 書かれたのに、その表示が別の起動メッセージに上書きされていた。
        self._show_startup_messages()

    def _show_startup_messages(self) -> None:
        """起動時のメッセージ（初回歓迎 + AI 開示）を 1 つにまとめて出す。

        `_speak_reply` は comment_text を置き換えるため、2 回続けて呼ぶと後者が
        前者を消す。それぞれを個別に呼んでいたので、初回起動のユーザーには
        歓迎メッセージが見えていなかった。
        """
        parts = []
        welcome = self._welcome_text()
        if welcome:
            parts.append(welcome)
        notice = self._ai_disclosure_text()
        if notice:
            parts.append(notice)
        if not parts:
            return
        try:
            self.viewer._speak_reply("\n".join(parts))
            if notice:
                self.viewer._last_ai_disclosure_ts = time.time()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("起動メッセージの表示に失敗: %s", e)

    def _ai_disclosure_text(self) -> str:
        """セッション開始時の AI 開示の本文（出せなければ空文字）。"""
        if _ai_disclosure is None:
            return ""
        try:
            return _ai_disclosure.session_notice(self._lang)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("AI 開示（セッション開始）の生成に失敗: %s", e)
            return ""

    def _show_ai_disclosure(self) -> bool:
        """セッション開始時の AI 開示を表示する。表示したら True。

        NY AI Companion Models 法 / CA SB 243 が求める「セッション開始時 +
        3 時間ごと」の前半。後半（3 時間ごと）は
        `AutonomousAvatarViewer._prepend_ai_disclosure` が担う。ここで
        タイムスタンプを打つので、開始直後に重ねて出ることはない。
        """
        if _ai_disclosure is None:
            return False
        try:
            self.viewer._speak_reply(_ai_disclosure.session_notice(self._lang))
            self.viewer._last_ai_disclosure_ts = time.time()
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("AI 開示（セッション開始）の表示に失敗: %s", e)
            return False

    def _welcome_text(self) -> str:
        """初回起動なら歓迎＋できることの案内を返す（2 回目以降は空文字）。

        第一原理: 製品の価値（覚えてくれる・関係が育つ）が初回接触時に一切
        見えず「読み上げツール」と誤解されうる問題への対処。過去の利用痕跡
        （交流回数・呼び名・会話履歴）が 1 つでもあれば表示しない。
        """
        if _is_first_run is None or _welcome_message is None:
            return False
        try:
            interactions = 0
            if get_mood_tracker is not None:
                interactions = getattr(get_mood_tracker(), "interactions", 0)
            has_name = False
            if _get_user_profile_gui is not None:
                prof = _get_user_profile_gui()
                has_name = bool(getattr(prof, "name", "")) if prof is not None else False
            has_history = False
            if get_conversation_log is not None:
                has_history = bool(get_conversation_log().recent(1))
            if not _is_first_run(interactions, has_name, has_history):
                return ""
            return _welcome_message(self._lang)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("初回オンボーディングの生成に失敗: %s", e)
            return ""

    def _maybe_show_welcome(self) -> bool:
        """初回起動なら歓迎を表示する。表示したら True（単体テスト用の入口）。

        通常の起動経路は `_show_startup_messages()` を通る — そちらは AI 開示と
        1 つのメッセージにまとめる（別々に出すと後者が前者を上書きするため）。
        """
        text = self._welcome_text()
        if not text:
            return False
        try:
            self.viewer._speak_reply(text)
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("初回オンボーディングの表示に失敗: %s", e)
            return False

    def _autonomous_label(self, is_on: bool) -> str:
        """自律モードボタンのラベル（言語に応じて）。"""
        if self._lang.startswith("en"):
            return "Autonomous OFF" if is_on else "Autonomous ON"
        return "自律モードOFF" if is_on else "自律モードON"

    def toggle_autonomous(self):
        if not self.viewer.is_autonomous:
            self.viewer.start_autonomous()
            self.autonomous_btn.setText(self._autonomous_label(True))
            self._start_break_reminder()
        else:
            self.viewer.stop_autonomous()
            self.autonomous_btn.setText(self._autonomous_label(False))
            self.talk_label.setText('')
            self._stop_break_reminder()

    def _start_break_reminder(self):
        """自律モード ON 時、設定が許せば休憩リマインダーを開始する。"""
        if maybe_start_break_reminder is None or self.break_reminder is not None:
            return
        lang = getattr(self.viewer.persona, 'lang', 'ja') if self.viewer.persona else 'ja'
        try:
            self.break_reminder = maybe_start_break_reminder(
                speak_func=make_reminder_speak(self.viewer, self.tts_queue), lang=lang
            )
        except Exception as e:
            logger.warning("休憩リマインダーの開始に失敗しました: %s", e)
            self.break_reminder = None

    def _stop_break_reminder(self):
        if self.break_reminder is not None:
            try:
                self.break_reminder.stop()
            except Exception as e:
                logger.debug("休憩リマインダーの停止に失敗しました: %s", e)
            self.break_reminder = None

    def update_talk_text(self):
        if self.viewer.comment_text:
            self.talk_label.setText(self.viewer.comment_text)
        elif self.viewer.talk_text:
            self.talk_label.setText(self.viewer.talk_text)
        else:
            self.talk_label.setText('')

    def handle_comment(self):
        comment = self.comment_input.text().strip()
        if comment:
            self.viewer.speak_comment(comment)
            self.comment_input.clear()

    def closeEvent(self, event):
        # タイマーを止めてから破棄する。止めないとウィンドウ破棄後にも
        # update_talk_text / update_autonomous が発火し、破棄済みウィジェットへ
        # アクセスしてクラッシュしうる。
        for _timer_attr, _owner in (("text_timer", self),
                                    ("timer", getattr(self, "viewer", None))):
            _timer = getattr(_owner, _timer_attr, None) if _owner is not None else None
            if _timer is not None:
                try:
                    _timer.stop()
                except Exception as e:  # pragma: no cover - defensive
                    logger.debug("タイマー停止に失敗（%s）: %s", _timer_attr, e)
        # TTS スレッドを止めて終了を待つ（daemon なので最悪プロセス終了で回収
        # されるが、join で読み上げ中の中断を穏当にする）。
        if getattr(self, "tts_thread", None) is not None:
            try:
                self.tts_thread.stop()
                self.tts_thread.join(timeout=2.0)
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("TTS スレッド停止に失敗: %s", e)
        self._stop_break_reminder()
        # ウィンドウを閉じるときに好感度を保存する（会話中に保存済みでも上書きで最新を維持）
        if get_mood_tracker is not None and _default_mood_path is not None:
            try:
                get_mood_tracker().save(_default_mood_path())
            except Exception:
                pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
