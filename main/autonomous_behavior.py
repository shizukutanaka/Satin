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
"""
from __future__ import annotations

import random

from optional_deps import np


class AutonomousBehaviorMixin:
    REST_TEXTS = ['ふう…ちょっと休憩。', 'すこし止まります。']
    # talk → run 復帰時に direction をランダムリセットするか（サブクラスで上書き）
    reset_direction_on_run = False
    # start_autonomous / stop_autonomous で空文字へリセットする追加テキスト属性
    EXTRA_TEXT_FIELDS: tuple = ()

    def start_autonomous(self) -> None:
        """自律モードを開始し、run 状態へ遷移する。"""
        self.is_autonomous = True
        self.mode = 'run'
        self.ticks = 0
        self.direction = random.uniform(0, 360)
        self.talk_text = ''
        for field in self.EXTRA_TEXT_FIELDS:
            setattr(self, field, '')

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
                self.talk_text = random.choice(self.REST_TEXTS)
            if self.ticks > 40 + random.randint(0, 20):  # 2秒程度
                self.mode = 'talk'
                self.ticks = 0
        elif self.mode == 'talk':
            # お話し
            if self.ticks == 1:
                self.talk_text = random.choice(self.talks)
                self._on_talk_start(self.talk_text)
            if self.ticks > 40 + random.randint(0, 20):  # 2秒程度
                self.mode = 'run'
                if self.reset_direction_on_run:
                    self.direction = random.uniform(0, 360)
                self.talk_text = ''
                self.ticks = 0
