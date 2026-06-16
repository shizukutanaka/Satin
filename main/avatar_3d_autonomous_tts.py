import sys
import random
import threading
import queue
import logging

logger = logging.getLogger(__name__)

from optional_deps import (  # noqa: E402
    np, cv2, QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, Qt, QTimer,
    pyttsx3, sd, pygltflib,
)
from autonomous_behavior import AutonomousBehaviorMixin  # noqa: E402
from tts_thread import TTSThread  # noqa: E402,F401
from gl_widget_base import GLViewportMixin  # noqa: E402

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
    )
except Exception:  # pragma: no cover - defensive
    _get_user_profile_gui = None
    _personalize_gui = None

try:
    from break_reminder import maybe_start_break_reminder  # noqa: E402
except Exception:  # pragma: no cover - defensive
    maybe_start_break_reminder = None


# N 回のコメントごとにアバターから「聞き返し」質問を添えて会話を続けやすくする
_FOLLOW_UP_EVERY = 4


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

    def set_tts_queue(self, tts_queue):
        self.tts_queue = tts_queue

    def speak_comment(self, comment):
        # ペルソナが応答を返せばそれを表示・読み上げ、無ければ入力をそのまま
        # 読み上げる（後方互換のオウム返し）。respond の失敗で TTS は壊さない。
        reply = comment
        # 好感度レベルを取得して関係性に応じた応答を選ばせる
        level = None
        if get_mood_tracker is not None:
            try:
                level = get_mood_tracker().level
            except Exception as e:
                logger.debug("好感度レベルの取得に失敗（応答は継続）: %s", e)
        persona = self.persona
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
                lang = getattr(persona, 'lang', 'ja') if persona is not None else 'ja'
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
                    question = persona.follow_up_question(level=level)
                    if question:
                        reply = (reply + " " + question).strip()
            except Exception as e:
                logger.debug("聞き返し質問の生成に失敗しました: %s", e)
        # 会話履歴を記録（失敗しても UI/TTS を壊さない）
        if get_conversation_log is not None:
            try:
                get_conversation_log().log_exchange(comment, reply)
            except Exception as e:
                logger.warning("会話履歴の記録に失敗しました: %s", e)
        # {user} プレースホルダを呼び名へ解決（GUI は _say() を持たないため個別に処理）
        if _personalize_gui is not None and "{user}" in reply:
            try:
                prof = _get_user_profile_gui() if _get_user_profile_gui is not None else None
                lang = getattr(persona, 'lang', 'ja') if persona is not None else 'ja'
                reply = _personalize_gui(reply, prof, lang)
            except Exception:
                pass
        self.comment_text = reply
        self.mode = 'comment'
        self.ticks = 0
        if self.tts_queue:
            self.tts_queue.put(reply)

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
        quad = gluNewQuadric()
        gluSphere(quad, 1.0, 32, 32)

class MainWindow(QMainWindow if QMainWindow is not None else object):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自律モード＋コメント読み上げ 3Dアバター")
        self.tts_queue = queue.Queue()
        self.tts_thread = TTSThread(self.tts_queue)
        self.tts_thread.start()
        # ポモドーロ式ブレークリマインダー（自律モード ON 中のみ稼働）
        self.break_reminder = None
        self.viewer = AutonomousAvatarViewer(self)
        self.viewer.set_tts_queue(self.tts_queue)
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
