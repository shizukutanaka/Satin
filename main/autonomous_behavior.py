"""
自律行動ステートマシン (run / rest / talk) の共有 Mixin。

avatar_3d_autonomous / avatar_3d_autonomous_tts / autonomous_gltf_avatar が
ほぼ同一の update_autonomous() を重複して持っていたため共通化した。
各ウィジェットは position / direction / mode / ticks / talk_text / talks
属性を __init__ で初期化したうえで _advance_autonomous_state() を呼ぶ。

フック:
  - _autonomous_run_extra(): run 中の移動直後に呼ばれる（例: 画面端反射）
  - _on_talk_start(text):    talk 開始時に呼ばれる（例: TTS キュー投入）
  - reset_direction_on_run:  talk → run 復帰時に方向をランダムリセットするか
  - EXTRA_TEXT_FIELDS:       start/stop で空文字にリセットする追加属性名のタプル
                             （例: TTS 版の 'comment_text'）

台詞は config/persona.json で差し替え可能なペルソナ（persona.get_persona()）から
取得する。ペルソナに台詞が無い場合のみ、サブクラスが __init__ で設定した
self.talks / self.REST_TEXTS にフォールバックする（後方互換）。
"""
from __future__ import annotations

import random

from optional_deps import np

try:
    from persona import get_persona
except Exception:  # pragma: no cover - persona は常に import 可能なはずだが防御的に
    get_persona = None

try:
    from mood import (
        get_mood_tracker as _get_mood_tracker,
        _default_mood_history_path as _mood_history_path,
    )
except Exception:  # pragma: no cover - defensive
    _get_mood_tracker = None
    _mood_history_path = None


class AutonomousBehaviorMixin:
    REST_TEXTS = ['ふう…ちょっと休憩。', 'すこし止まります。']
    # talk → run 復帰時に direction をランダムリセットするか（サブクラスで上書き）
    reset_direction_on_run = False
    # start_autonomous / stop_autonomous で空文字へリセットする追加テキスト属性
    EXTRA_TEXT_FIELDS: tuple = ()

    @property
    def persona(self):
        """共有ペルソナ。利用不可なら None。"""
        if get_persona is None:
            return None
        return get_persona()

    def start_autonomous(self) -> None:
        """自律モードを開始し、run 状態へ遷移する。

        開始時、ペルソナが利用可能なら時刻に応じたあいさつを talk_text に表示する
        （朝なら「おはよう！」等）。これによりコンパニオンらしい時間帯対応の挨拶を行う。
        """
        self.is_autonomous = True
        self.mode = 'run'
        self.ticks = 0
        self.direction = random.uniform(0, 360)
        self.talk_text = ''
        for field in self.EXTRA_TEXT_FIELDS:
            setattr(self, field, '')
        # 前回セッションからの経過時間で好感度を自然低下させ、レベルを取得する
        level = None
        if _get_mood_tracker is not None:
            try:
                tracker = _get_mood_tracker()
                tracker.auto_decay()
                level = tracker.level
                # 起動時スナップショット（当日初回のみ履歴に記録される）
                if _mood_history_path is not None:
                    tracker.snapshot_to_history(_mood_history_path())
            except Exception:
                pass
        persona = self.persona
        if persona is not None:
            greeting = persona.greeting(level=level)
            if greeting:
                self.talk_text = greeting
                self._on_talk_start(greeting)

    def stop_autonomous(self) -> None:
        """自律モードを停止し、idle 状態へ戻す。"""
        self.is_autonomous = False
        self.mode = 'idle'
        self.talk_text = ''
        for field in self.EXTRA_TEXT_FIELDS:
            setattr(self, field, '')
        self.update()

    def _autonomous_move(self) -> None:
        """direction 方向へ 1 ティック分移動する。numpy 未導入なら何もしない。"""
        speed = 0.03
        if np is not None:
            self.position[0] += speed * np.cos(np.radians(self.direction))
            self.position[1] += speed * np.sin(np.radians(self.direction))

    def _autonomous_run_extra(self) -> None:
        """run 中の移動直後フック。デフォルトは何もしない。"""

    def _on_talk_start(self, text: str) -> None:
        """talk 開始時フック。デフォルトは何もしない。"""

    def _pick_rest_text(self) -> str:
        """休憩台詞を返す。ペルソナ優先、無ければ self.REST_TEXTS にフォールバック。"""
        persona = self.persona
        if persona is not None:
            text = persona.rest()
            if text:
                return text
        rest_texts = getattr(self, 'REST_TEXTS', None) or ['']
        return random.choice(rest_texts)

    def _pick_talk_text(self) -> str:
        """雑談台詞を返す。ペルソナ優先、無ければ self.talks にフォールバック。

        mood トラッカーが利用可能なら好感度レベルを persona.talk() に渡し、
        関係性に応じた台詞を選択する。
        """
        level = None
        if _get_mood_tracker is not None:
            try:
                level = _get_mood_tracker().level
            except Exception:
                pass
        persona = self.persona
        if persona is not None:
            text = persona.talk(level=level)
            if text:
                return text
        talks = getattr(self, 'talks', None) or ['']
        return random.choice(talks)

    def _advance_autonomous_state(self) -> None:
        """run / rest / talk の 3 状態を 1 ティック進める。"""
        self.ticks += 1
        if self.mode == 'run':
            # 駆け回る
            self._autonomous_move()
            self._autonomous_run_extra()
            # ランダムに方向転換
            if random.random() < 0.05:
                self.direction += random.uniform(-60, 60)
            if self.ticks > 60 + random.randint(0, 40):  # 3秒程度
                self.mode = 'rest'
                self.ticks = 0
        elif self.mode == 'rest':
            # 休憩
            if self.ticks == 1:
                self.talk_text = self._pick_rest_text()
            if self.ticks > 40 + random.randint(0, 20):  # 2秒程度
                self.mode = 'talk'
                self.ticks = 0
        elif self.mode == 'talk':
            # お話し
            if self.ticks == 1:
                self.talk_text = self._pick_talk_text()
                self._on_talk_start(self.talk_text)
            if self.ticks > 40 + random.randint(0, 20):  # 2秒程度
                self.mode = 'run'
                if self.reset_direction_on_run:
                    self.direction = random.uniform(0, 360)
                self.talk_text = ''
                self.ticks = 0
