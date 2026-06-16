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

import logging
import random

from optional_deps import np

logger = logging.getLogger(__name__)

try:
    from persona import get_persona
except Exception:  # pragma: no cover - persona は常に import 可能なはずだが防御的に
    get_persona = None

try:
    from mood import (
        get_mood_tracker as _get_mood_tracker,
        _default_mood_history_path as _mood_history_path,
        _default_mood_path as _mood_path,
        absence_message as _absence_message,
        anniversary_message as _anniversary_message,
        check_daily_login as _check_daily_login,
    )
except Exception:  # pragma: no cover - defensive
    _get_mood_tracker = None
    _mood_history_path = None
    _mood_path = None
    _absence_message = None  # type: ignore
    _anniversary_message = None  # type: ignore
    _check_daily_login = None  # type: ignore

try:
    from daily_summary import yesterday_greeting as _yesterday_greeting
except Exception:  # pragma: no cover - defensive
    _yesterday_greeting = None

try:
    from user_profile import get_user_profile as _get_user_profile, \
        _default_profile_path as _profile_path
except Exception:  # pragma: no cover - defensive
    _get_user_profile = None
    _profile_path = None

try:
    from special_days import (
        seasonal_greeting as _seasonal_greeting,
        birthday_greeting as _birthday_greeting,
        BIRTHDAY_AFFINITY_BONUS as _BIRTHDAY_BONUS,
    )
except Exception:  # pragma: no cover - defensive
    _seasonal_greeting = None
    _birthday_greeting = None
    _BIRTHDAY_BONUS = 0.0

try:
    from daily_mood import (
        get_daily_mood as _get_daily_mood,
        mood_description as _mood_description,
        mood_affinity_multiplier as _mood_affinity_multiplier,
    )
except Exception:  # pragma: no cover - defensive
    _get_daily_mood = None
    _mood_description = None
    _mood_affinity_multiplier = None


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
            except Exception as e:
                logger.debug("起動時の好感度処理に失敗しました: %s", e)
        persona = self.persona
        if persona is not None:
            greeting = persona.greeting(level=level)
            lang = getattr(persona, 'lang', 'ja')
            # 前回から 24h 以上経過していた場合は不在への言及を挨拶に添える
            if _absence_message is not None and _get_mood_tracker is not None:
                try:
                    absence = _absence_message(_get_mood_tracker(), lang=lang)
                    if absence:
                        greeting = (greeting + " " + absence).strip() if greeting else absence
                except Exception as e:
                    logger.debug("不在メッセージの生成に失敗しました: %s", e)
            # デイリーログイン: その日初回なら好感度ボーナス＋お祝いを挨拶へ添える。
            # check_daily_login はログイン日付・連続日数を更新するので保存して重複を防ぐ。
            if _check_daily_login is not None and _get_mood_tracker is not None:
                try:
                    tr = _get_mood_tracker()
                    login_msg = _check_daily_login(tr, lang=lang)
                    if login_msg:
                        greeting = (greeting + " " + login_msg).strip() if greeting else login_msg
                        if _mood_path is not None:
                            tr.save(_mood_path())
                except Exception as e:
                    logger.debug("デイリーログインの処理に失敗しました: %s", e)
            # 出会ってからの節目（記念日）に達していたら祝いを添える。
            # anniversary_message は達成済みフラグを更新するので保存して重複を防ぐ。
            if _anniversary_message is not None and _get_mood_tracker is not None:
                try:
                    tr = _get_mood_tracker()
                    anniv = _anniversary_message(tr, lang=lang)
                    if anniv:
                        greeting = (greeting + " " + anniv).strip() if greeting else anniv
                        if _mood_path is not None:
                            tr.save(_mood_path())
                except Exception as e:
                    logger.debug("記念日メッセージの生成に失敗しました: %s", e)
            # 誕生日なら祝う（年 1 回、好感度ボーナス付き）— 恋愛ゲームの定番演出
            if _birthday_greeting is not None and _get_user_profile is not None:
                try:
                    prof = _get_user_profile()
                    bday = _birthday_greeting(prof, lang=lang)
                    if bday:
                        greeting = (greeting + " " + bday).strip() if greeting else bday
                        if _get_mood_tracker is not None and _BIRTHDAY_BONUS:
                            tr = _get_mood_tracker()
                            tr.adjust(_BIRTHDAY_BONUS)
                            if _mood_path is not None:
                                tr.save(_mood_path())
                        if _profile_path is not None:
                            prof.save(_profile_path())
                except Exception as e:
                    logger.debug("誕生日メッセージの生成に失敗しました: %s", e)
            # 季節イベント（正月・バレンタイン・クリスマス等）の特別あいさつ
            # 好感度レベルがあれば関係の深さに応じた特別版を優先する
            if _seasonal_greeting is not None:
                try:
                    season = _seasonal_greeting(lang=lang, level=level)
                    if season:
                        greeting = (greeting + " " + season).strip() if greeting else season
                except Exception as e:
                    logger.debug("季節あいさつの生成に失敗しました: %s", e)
            # デイリームード（その日の気質を一言で添える）
            if _get_daily_mood is not None and _mood_description is not None:
                try:
                    prof = _get_user_profile() if _get_user_profile is not None else None
                    salt = prof.name if prof is not None else ""
                    dmood = _get_daily_mood(salt=salt)
                    desc = _mood_description(dmood, lang=lang)
                    if desc:
                        greeting = (greeting + " " + desc).strip() if greeting else desc
                except Exception as e:
                    logger.debug("デイリームードの生成に失敗しました: %s", e)
            # 朝（6〜10時）は昨日のアクティビティサマリーをあいさつに添える
            if _yesterday_greeting is not None:
                import datetime as _dt
                hour = _dt.datetime.now().hour
                if 6 <= hour < 10:
                    try:
                        yday = _yesterday_greeting(lang=lang)
                        if yday:
                            greeting = (greeting + " " + yday).strip() if greeting else yday
                    except Exception as e:
                        logger.debug("昨日のサマリー取得に失敗しました: %s", e)
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

    # 趣味に言及した自律発話テンプレート（ペルソナ台詞の代わりに差し込む）
    _INTEREST_TALK_TEMPLATES = {
        "ja": [
            "{item}って最近気になってるんだけど。",
            "そういえば{item}のこと、ちょっと考えてたんだ。",
            "{item}って好きだったよね？最近どう？",
        ],
        "en": [
            "I keep thinking about {item} lately.",
            "Hey, weren't you into {item}? I was curious!",
            "{item} — I thought of you when I saw it.",
        ],
    }
    # 趣味に言及する好感度レベルの下限（distant には言及しない）
    _INTEREST_TALK_LEVELS = {"neutral", "friendly", "close"}

    def _pick_talk_text(self) -> str:
        """雑談台詞を返す。ペルソナ優先、無ければ self.talks にフォールバック。

        mood トラッカーが利用可能なら好感度レベルを persona.talk() に渡し、
        関係性に応じた台詞を選択する。デイリームードも台詞選択に影響する。
        記憶した趣味があれば 1/6 の確率で趣味に言及した一言を差し込む
        （neutral 以上のレベルのみ）。
        """
        level = None
        if _get_mood_tracker is not None:
            try:
                level = _get_mood_tracker().level
            except Exception as e:
                logger.debug("好感度レベルの取得に失敗しました: %s", e)
        mood_key = None
        if _get_daily_mood is not None:
            try:
                prof = _get_user_profile() if _get_user_profile is not None else None
                salt = prof.name if prof is not None else ""
                mood_key = _get_daily_mood(salt=salt)
            except Exception as e:
                logger.debug("デイリームードキーの取得に失敗しました: %s", e)

        # 趣味ベース発話（neutral+ レベルで 1/6 の確率）
        if level in self._INTEREST_TALK_LEVELS and _get_user_profile is not None:
            try:
                prof = _get_user_profile()
                interests = getattr(prof, "interests", [])
                if interests and random.random() < 0.16:
                    item = random.choice(interests)
                    persona = self.persona
                    lang_str = getattr(persona, "lang", "ja") if persona else "ja"
                    lang_key = "en" if str(lang_str).lower().startswith("en") else "ja"
                    templates = self._INTEREST_TALK_TEMPLATES[lang_key]
                    return random.choice(templates).format(item=item)
            except Exception as e:
                logger.debug("趣味ベース雑談の生成に失敗しました: %s", e)

        persona = self.persona
        if persona is not None:
            text = persona.talk(level=level, mood_key=mood_key)
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
