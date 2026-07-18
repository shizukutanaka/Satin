import sys
import random
import queue
import logging

logger = logging.getLogger(__name__)

from optional_deps import (  # noqa: E402
    QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QTimer,
    np, pygltflib,
)
from autonomous_behavior import AutonomousBehaviorMixin  # noqa: E402
from tts_thread import TTSThread  # noqa: E402,F401
from gl_widget_base import GLViewportMixin  # noqa: E402

# 選んだアバターモデル (.glb/.gltf/.vrm) の頂点を読み込んで描画するための
# 任意依存。未導入・失敗時は従来の球体プレースホルダにフォールバックする。
try:
    from gltf_utils import load_first_mesh_vertices, normalize_vertices  # noqa: E402
except Exception:  # pragma: no cover - defensive
    load_first_mesh_vertices = None
    normalize_vertices = None
try:
    import avatar_model_store as _avatar_model_store  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _avatar_model_store = None

# paintGL/draw が使う OpenGL 名 (glClear/glBegin/GL_*/gluSphere 等) を取り込む。
# 共通化リファクタでこの import が抜け、描画時に NameError になっていた。
try:
    from OpenGL.GL import *  # noqa: F401,F403
    from OpenGL.GLU import *  # noqa: F401,F403
except ImportError:
    pass

try:
    from conversation_log import get_conversation_log  # noqa: E402
except Exception:  # pragma: no cover - defensive
    get_conversation_log = None

try:
    from mood import (  # noqa: E402
        get_mood_tracker, _default_mood_path, _default_mood_history_path,
        check_level_milestone,
        check_confession_event as _check_confession_event,
        check_interaction_milestone as _check_interaction_milestone,
        check_hurt_event as _check_hurt_event,
    )
except Exception:  # pragma: no cover - defensive
    get_mood_tracker = None
    _default_mood_path = None
    _default_mood_history_path = None
    check_level_milestone = None
    _check_confession_event = None
    _check_interaction_milestone = None
    _check_hurt_event = None

try:
    from persona_cli import _detect_ritual_event as _detect_ritual_event_gui
except Exception:  # pragma: no cover - defensive
    _detect_ritual_event_gui = None

try:
    from user_profile import (
        get_user_profile as _get_user_profile_gui,
        personalize as _personalize_gui,
        _default_profile_path as _default_profile_path_gui,
    )
except Exception:  # pragma: no cover - defensive
    _get_user_profile_gui = None
    _personalize_gui = None
    _default_profile_path_gui = None

try:
    from profile_questions import (
        next_unanswered_question as _next_unanswered_question_gui,
        acknowledge_answer as _acknowledge_answer_gui,
    )
except Exception:  # pragma: no cover - defensive
    _next_unanswered_question_gui = None
    _acknowledge_answer_gui = None

try:
    from daily_summary import summary_greeting as _summary_greeting_gui
except Exception:  # pragma: no cover - defensive
    _summary_greeting_gui = None

try:
    from user_wellbeing import wellbeing_summary as _wellbeing_summary_gui
    from user_wellbeing import wellbeing_message as _wellbeing_message_gui
except Exception:  # pragma: no cover - defensive
    _wellbeing_summary_gui = None
    _wellbeing_message_gui = None

_HISTORY_DEFAULT_GUI = 10

try:
    from daily_mood import (  # noqa: E402
        get_daily_mood as _get_daily_mood_gui,
        mood_affinity_multiplier as _mood_affinity_multiplier_gui,
    )
except Exception:  # pragma: no cover - defensive
    _get_daily_mood_gui = None
    _mood_affinity_multiplier_gui = None

try:
    from gifts import (  # noqa: E402
        lookup_gift as _lookup_gift_gui,
        lookup_gift_key as _lookup_gift_key_gui,
        gift_catalog_text as _gift_catalog_text_gui,
        cooldown_message as _gift_cooldown_message_gui,
    )
except Exception:  # pragma: no cover - defensive
    _lookup_gift_gui = None
    _lookup_gift_key_gui = None
    _gift_catalog_text_gui = None
    _gift_cooldown_message_gui = None

try:
    from break_reminder import maybe_start_break_reminder  # noqa: E402
except Exception:  # pragma: no cover - defensive
    maybe_start_break_reminder = None


# N 回のコメントごとにアバターから「聞き返し」質問を添えて会話を続けやすくする
_FOLLOW_UP_EVERY = 4


def _erase_all_user_data():
    """ユーザーの個人データを可能な限りすべて消去し、消したものの要約を返す。

    プライバシー優先の製品として「私に関するデータを全部消して」を一括で叶える。
    各ストアは独立してガードし、一部が失敗しても残りは消す（best-effort）。
    消去対象:
      - プロフィール（呼び名・誕生日・趣味・覚えた事実）: config/user_profile.json
      - 会話履歴: avatar_event_log.jsonl + gzip アーカイブ
      - 好感度: config/mood.json をニュートラルへ + config/mood_history.jsonl 削除
      - アバター選択履歴: config/avatar_history.json
    （daily_mood は日付から決定的に導かれ永続状態を持たないため対象外。）

    戻り値は {"profile": bool, "conversation": bool, "mood": bool,
              "avatar": bool} で、各項目を実際に消去できたかを表す。
    """
    import os as _os
    report = {"profile": False, "conversation": False, "mood": False, "avatar": False}

    # 1) プロフィール
    if _get_user_profile_gui is not None:
        try:
            prof = _get_user_profile_gui()
            if prof is not None:
                prof.clear()
                if _default_profile_path_gui is not None:
                    prof.save(_default_profile_path_gui())
                report["profile"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: プロフィール消去に失敗: %s", e)

    # 2) 会話履歴（ライブ + アーカイブ）
    if get_conversation_log is not None:
        try:
            from conversation_log import _find_archives
            conv_log = get_conversation_log()
            path = conv_log.logfile
            if _os.path.exists(path):
                open(path, "w", encoding="utf-8").close()
            for gz in _find_archives(path):
                try:
                    _os.remove(gz)
                except OSError:
                    pass
            report["conversation"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: 会話履歴消去に失敗: %s", e)

    # 3) 好感度（ニュートラルへ + 履歴ファイル削除）
    if get_mood_tracker is not None:
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
            if _default_mood_history_path is not None:
                hist = _default_mood_history_path()
                if _os.path.exists(hist):
                    try:
                        _os.remove(hist)
                    except OSError:
                        pass
            report["mood"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: 好感度消去に失敗: %s", e)

    # 4) アバター選択履歴
    if _avatar_model_store is not None:
        try:
            _avatar_model_store.clear()
            report["avatar"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: アバター履歴消去に失敗: %s", e)

    return report


def _load_model_vertices(path):
    """アバターファイル path の正規化済み頂点配列 (N, 3) を返す。失敗時 None。

    pygltflib / numpy / gltf_utils のいずれかが無い、読み込み・解析に失敗した、
    頂点が取れない場合は None を返し、呼び出し側は球体プレースホルダへ安全に
    フォールバックする（GUI を壊さない）。avatar_3d_gltf_viewer.GLTFModel と
    同じ読み込み経路を共有する。
    """
    if (pygltflib is None or np is None or load_first_mesh_vertices is None
            or normalize_vertices is None or not path):
        return None
    try:
        gltf = pygltflib.GLTF2().load(path)
        vertices = load_first_mesh_vertices(gltf, np)
        return normalize_vertices(vertices, np)
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


class AutonomousAvatarViewer(AutonomousBehaviorMixin, GLViewportMixin, QOpenGLWidget if QOpenGLWidget is not None else object):
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
        self._clear_log_pending = False  # /clear-log の二段階確認フラグ
        self._reset_mood_pending = False  # /reset-mood の二段階確認フラグ
        self._forget_all_pending = False  # /forget-all の二段階確認フラグ
        # --avatar-loader で選んだアバターモデルの頂点（無ければ球体を描画）
        self.avatar_model_vertices = None
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
        vertices = _load_model_vertices(path)
        if vertices is None:
            return False
        self.avatar_model_vertices = vertices
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

        # /clear-log の確認待ちが他の発話（スラッシュ・非スラッシュ問わず）で
        # キャンセルされた場合。persona_cli.py の同種フラグ処理と同じロジック。
        # getattr の既定値 False は、__init__ を経由しないテスト用インスタンス
        # （object.__new__ 経由）で属性未設定でも落ちないようにするための防御。
        if getattr(self, "_clear_log_pending", False) \
                and comment.strip().lower() not in ("/clear-log", "/clearlog"):
            self._clear_log_pending = False

        # /reset-mood も同様の二段階確認。以前は確認無しで即座に好感度を
        # 全リセットしており、テキスト入力欄への誤操作（誤爆・貼り付け・
        # Enter の押し間違い）1回で関係進捗が丸ごと消えた
        # （persona_cli.py は同じコマンドに対して既にこの確認を持っていた
        # ——GUI 側だけこのガードが抜け落ちていた）。
        if getattr(self, "_reset_mood_pending", False) \
                and comment.strip().lower() not in ("/reset-mood", "/resetmood"):
            self._reset_mood_pending = False

        # ---------- スラッシュコマンド (/gift, /callme) ----------
        if isinstance(comment, str) and comment.lstrip().startswith("/"):
            if self._handle_slash_command_gui(comment.lstrip()[1:], lang, level):
                self.pending_fact_key = None  # コマンドで Q&A フローを中断
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
                # 謝罪・おやすみルーティン: 小さな好感度ボーナス
                if _detect_ritual_event_gui is not None:
                    ritual = _detect_ritual_event_gui(comment)
                    if ritual is not None:
                        tracker.adjust(ritual[1])
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
        if persona is not None and _FOLLOW_UP_EVERY > 0 \
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
        # 表示・TTS 投入は _speak_reply に一本化（{user} 解決もそこで実施）。
        self._speak_reply(reply)

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
                           if _gift_cooldown_message_gui else "また明日ね。")
                    self._speak_reply(msg)
                    return
            except Exception as e:
                logger.debug("ギフトクールダウンの確認に失敗（GUI）: %s", e)

        result = _lookup_gift_gui(item, lang=lang, level=level)
        if result is None:
            if lang == "en":
                reply = f"Hmm, I'm not sure about {item}. Try /gift list."
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
        if effective_bonus > 0.0 and get_mood_tracker is not None:
            try:
                tracker = get_mood_tracker()
                tracker.adjust(effective_bonus)
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

        if effective_bonus > 0.0:
            avatar_reply = (f"{avatar_reply} (+{int(effective_bonus)} affinity)" if lang == "en"
                            else f"{avatar_reply}（好感度 +{int(effective_bonus)}）")

        if get_conversation_log is not None:
            try:
                get_conversation_log().log_exchange(f"/gift {item}", avatar_reply)
            except Exception:
                pass
        self._speak_reply(avatar_reply)

    def _cmd_callme_gui(self, name: str, lang: str) -> None:
        """GUI の /callme <name> コマンドを処理する。"""
        if not name:
            self._speak_reply("使い方: /callme <呼んでほしい名前>" if lang != "en"
                              else "Usage: /callme <your name>")
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
            self._speak_reply("使い方: /like <好きなもの>  例: /like アニメ" if lang != "en"
                              else "Usage: /like <thing you enjoy>  e.g. /like anime")
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
            self._speak_reply("使い方: /forget <好きなもの>" if lang != "en"
                              else "Usage: /forget <thing>")
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
            self._speak_reply("使い方: /forget-fact <覚えていることの一部>" if lang != "en"
                              else "Usage: /forget-fact <something I said I remember>")
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
        """
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
            reply = ("This erases EVERYTHING I know about you — profile, the "
                     "entire conversation history (and archives), our affinity, "
                     "and your avatar selection. Say /forget-all again to confirm."
                     if is_en else
                     "あなたに関するデータを全部消します — プロフィール・会話履歴"
                     "（アーカイブ含む）・好感度・アバター選択。本当によければ、"
                     "もう一度 /forget-all と言ってください。")
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
            reply = ("This will reset our relationship to neutral. "
                     "Type /reset-mood again to confirm." if lang == "en"
                     else "好感度をニュートラルにリセットします。"
                          "本当によければ、もう一度 /reset-mood と言ってください。")
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
            with open(dest, "w", encoding="utf-8") as f:
                f.write(csv_text)
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
            reply = ("This will erase the ENTIRE conversation history (including "
                     "archives). Say /clear-log again to confirm." if lang == "en"
                     else "会話履歴を（アーカイブも含めて）すべて消去します。"
                          "本当によければ、もう一度 /clear-log と言ってください。")
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
            self._speak_reply("使用方法: /search <キーワード>" if lang != "en"
                              else "Usage: /search <keyword>")
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
        """GUI の /avatar コマンド: 現在のアバターモデルを表示・再読み込みする。

        --avatar-loader で選び直した直後でも、ここで最新の選択を取り込める。
        """
        import os as _os
        is_en = lang.startswith("en")
        # 直近の選択を取り込む（既に読み込み済みでも上書きで最新化）。
        try:
            self.load_avatar_model()
        except Exception as e:
            logger.debug("/avatar 再読み込みに失敗（GUI）: %s", e)
        path = getattr(self, "avatar_model_path", None)
        if path:
            name = _os.path.basename(path)
            reply = (f"Currently showing avatar: {name}" if is_en
                     else f"いま表示してるアバター: {name}")
        else:
            reply = ("No avatar model loaded — pick one with "
                     "`python satin_launcher.py --avatar-loader` (.glb/.gltf/.vrm), "
                     "then restart." if is_en
                     else "アバターモデルは未設定だよ。`python satin_launcher.py "
                     "--avatar-loader` で .glb/.gltf/.vrm を選んでから起動し直してね。")
        self._speak_reply(reply)

    def _cmd_birthday_gui(self, date_str: str, lang: str) -> None:
        """GUI の /birthday MM-DD コマンドを処理する。"""
        if not date_str:
            self._speak_reply("使い方: /birthday MM-DD  例: /birthday 03-14" if lang != "en"
                              else "Usage: /birthday MM-DD  e.g. /birthday 03-14")
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
            reply = (f"Got it! Your birthday is {saved}. I won't forget!" if lang == "en"
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
        glTranslatef(self.position[0], self.position[1], -5.0)
        glColor3f(0.6, 0.8, 1.0)
        # 読み込み済みアバターモデルがあればワイヤーフレーム描画、無ければ球体。
        vertices = self.avatar_model_vertices
        if vertices is not None and len(vertices) > 0:
            glBegin(GL_LINE_STRIP)
            for v in vertices:
                glVertex3f(float(v[0]), float(v[1]), float(v[2]))
            glEnd()
        else:
            quad = gluNewQuadric()
            gluSphere(quad, 1.0, 32, 32)

class MainWindow(QMainWindow if QMainWindow is not None else object):
    def __init__(self):
        super().__init__()
        try:
            from persona import get_persona as _gp
            _title_name = _gp().name
        except Exception:
            _title_name = "Satin"
        self.setWindowTitle(f"{_title_name} — 3D コンパニオン")
        self.tts_queue = queue.Queue()
        self.tts_thread = TTSThread(self.tts_queue)
        self.tts_thread.start()
        # ポモドーロ式ブレークリマインダー（自律モード ON 中のみ稼働）
        self.break_reminder = None
        self.viewer = AutonomousAvatarViewer(self)
        self.viewer.set_tts_queue(self.tts_queue)
        # --avatar-loader で選んだアバターがあれば起動時に読み込んで描画する。
        try:
            self.viewer.load_avatar_model()
        except Exception as e:
            logger.debug("起動時のアバターモデル読み込みに失敗: %s", e)
        self.setCentralWidget(self.viewer)
        self.autonomous_btn = QPushButton('自律モードON', self)
        self.autonomous_btn.setGeometry(10, 10, 120, 30)
        self.autonomous_btn.clicked.connect(self.toggle_autonomous)
        self.talk_label = QLabel('', self)
        self.talk_label.setGeometry(150, 10, 400, 30)
        self.talk_label.setStyleSheet('font-size:18px; color:#222; background:#eee;')
        self.comment_input = QLineEdit(self)
        self.comment_input.setGeometry(10, 50, 400, 30)
        self.comment_input.setPlaceholderText('コメントを入力してEnterで読み上げ')
        self.comment_input.returnPressed.connect(self.handle_comment)
        # テキスト更新タイマー
        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self.update_talk_text)
        self.text_timer.start(100)

    def toggle_autonomous(self):
        if not self.viewer.is_autonomous:
            self.viewer.start_autonomous()
            self.autonomous_btn.setText('自律モードOFF')
            self._start_break_reminder()
        else:
            self.viewer.stop_autonomous()
            self.autonomous_btn.setText('自律モードON')
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
        self.tts_thread.running = False
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
