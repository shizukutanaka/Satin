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
    from daily_summary import (
        yesterday_greeting as _yesterday_greeting,
        summary_greeting as _summary_greeting,
    )
except Exception:  # pragma: no cover - defensive
    _yesterday_greeting = None
    _summary_greeting = None

try:
    from user_profile import get_user_profile as _get_user_profile, \
        _default_profile_path as _profile_path
except Exception:  # pragma: no cover - defensive
    _get_user_profile = None
    _profile_path = None

try:
    from profile_questions import recall_fact as _recall_fact
except Exception:  # pragma: no cover - defensive
    _recall_fact = None

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

try:
    from user_wellbeing import wellbeing_reflection as _wellbeing_reflection
    from conversation_log import (
        DEFAULT_LOGFILE as _wb_default_logfile,
        get_conversation_log as _get_conversation_log_wb,
    )
except Exception:  # pragma: no cover - defensive
    _wellbeing_reflection = None
    _wb_default_logfile = None
    _get_conversation_log_wb = None

try:
    from usage_guardrails import usage_reflection as _usage_reflection
except Exception:  # pragma: no cover - defensive
    _usage_reflection = None


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
                    # 日付のみで決定（可変の呼び名 salt は使わない）。日中に名前を
                    # 設定/消去しても気分が変わらず、ギフト倍率とも一致する。
                    dmood = _get_daily_mood()
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
            # 昼〜夜（12〜22時）は本日の会話サマリーをあいさつに添える
            if _summary_greeting is not None:
                import datetime as _dt
                hour = _dt.datetime.now().hour
                if 12 <= hour < 22:
                    try:
                        summary = _summary_greeting(lang=lang)
                        if summary:
                            greeting = (greeting + " " + summary).strip() if greeting else summary
                    except Exception as e:
                        logger.debug("本日サマリーの取得に失敗しました: %s", e)
            # ユーザーの最近の気分に寄り添う一言（低調/上向きのときのみ、静かに添える）
            if _wellbeing_reflection is not None:
                try:
                    _wb_path = _wb_default_logfile
                    if _get_conversation_log_wb is not None:
                        try:
                            _wb_path = _get_conversation_log_wb().logfile
                        except Exception:
                            pass
                    wb = _wellbeing_reflection(event_log_path=_wb_path, lang=lang)
                    if wb:
                        greeting = (greeting + " " + wb).strip() if greeting else wb
                except Exception as e:
                    logger.debug("ウェルビーイングチェックインの生成に失敗しました: %s", e)
            # 感情依存への配慮: 深夜利用の常態化・極端な単日集中を検知したら、
            # そっと休息や現実のつながりを促す（過度に依存させない安全ガードレール）。
            # 1 日 1 回までに抑え、しつこく諭さない（_last_usage_nudge_day で cooldown）。
            if _usage_reflection is not None:
                try:
                    import time as _time
                    today_key = _time.strftime("%Y-%m-%d", _time.localtime())
                    if getattr(self, "_last_usage_nudge_day", None) != today_key:
                        _ug_path = _wb_default_logfile
                        if _get_conversation_log_wb is not None:
                            try:
                                _ug_path = _get_conversation_log_wb().logfile
                            except Exception:
                                pass
                        nudge = _usage_reflection(event_log_path=_ug_path, lang=lang)
                        if nudge:
                            greeting = (greeting + " " + nudge).strip() if greeting else nudge
                            self._last_usage_nudge_day = today_key
                except Exception as e:
                    logger.debug("利用強度ガードレールの生成に失敗しました: %s", e)
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
                # 日付のみで決定（可変の呼び名 salt は使わない）— 全経路で同じ気分にする
                mood_key = _get_daily_mood()
            except Exception as e:
                logger.debug("デイリームードキーの取得に失敗しました: %s", e)

        # neutral 以上のレベルでユーザー記憶を参照した発話（事実想起 or 趣味言及）
        if level in self._INTEREST_TALK_LEVELS and _get_user_profile is not None:
            try:
                prof = _get_user_profile()
                _pi = self.persona
                _lang_str = getattr(_pi, "lang", "ja") if _pi else "ja"
                _lang_key = "en" if str(_lang_str).lower().startswith("en") else "ja"

                # 事実想起発話（12% の確率）— 答えてもらった質問を話題に
                if _recall_fact is not None and getattr(prof, "facts", {}):
                    if random.random() < 0.12:
                        recalled = _recall_fact(prof, lang=_lang_str)
                        if recalled:
                            return recalled

                # 趣味ベース発話（16% の確率）
                interests = getattr(prof, "interests", [])
                if interests and random.random() < 0.16:
                    item = random.choice(interests)
                    templates = self._INTEREST_TALK_TEMPLATES[_lang_key]
                    return random.choice(templates).format(item=item)
            except Exception as e:
                logger.debug("趣味・事実ベース雑談の生成に失敗しました: %s", e)

        # 時刻帯（朝/午後/夕/夜）を取得して時刻に合った一言を選べるようにする
        time_bucket = None
        try:
            import datetime as _dt
            _hour = _dt.datetime.now().hour
            if 5 <= _hour < 11:
                time_bucket = "morning"
            elif 11 <= _hour < 17:
                time_bucket = "afternoon"
            elif 17 <= _hour < 22:
                time_bucket = "evening"
            else:
                time_bucket = "night"
        except Exception:
            pass

        persona = self.persona
        if persona is not None:
            text = persona.talk(level=level, mood_key=mood_key, time_bucket=time_bucket)
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
