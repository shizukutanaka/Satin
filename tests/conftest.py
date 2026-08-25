"""
Shared pytest fixtures for the Satin test suite.

Test isolation for the conversation-log singleton
---------------------------------------------------
Several GUI-command tests call real production code paths
(avatar_3d_autonomous_tts._cmd_*_gui, persona_cli, autonomous_behavior) without
mocking out `get_conversation_log()`. Since that singleton's default resolves
to the real, absolute `conversation_log.DEFAULT_LOGFILE` (the repo's actual
conversation history file — see research/commercial-quality-audit fix), any
such test silently wrote real "/forget-fact ...", "hello", etc. fixture text
into that file on every test run, growing it indefinitely.

conversation_log.get_conversation_log()/ConversationLog() now resolve
DEFAULT_LOGFILE at call time rather than binding it into the function
signature at import time (see conversation_log.py), so redirecting the
module-level constant here transparently isolates every bare
get_conversation_log() call across the whole app — regardless of which
module imported the function — without needing to patch each consumer
module's own namespace individually.
"""
import os
import sys

_MAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main")
sys.path.insert(0, os.path.abspath(_MAIN))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_conversation_log(tmp_path, monkeypatch):
    import conversation_log

    monkeypatch.setattr(
        conversation_log, "DEFAULT_LOGFILE", str(tmp_path / "avatar_event_log.jsonl")
    )
    conversation_log.reset_conversation_log()
    yield
    conversation_log.reset_conversation_log()


@pytest.fixture(autouse=True)
def _isolate_user_profile(tmp_path, monkeypatch):
    """Same isolation for the user_profile singleton: tests that drive real
    code paths (e.g. persona_cli) via get_user_profile()/save without mocking
    the path wrote the user's real config/user_profile.json (name, birthday,
    interests) on every run.

    persona_cli (and other consumers) bind `_default_profile_path` by reference
    at import time, so patching the function alone isn't seen. Instead redirect
    UserProfile.save whenever it targets the real default path — explicit-temp
    saves (the save/load roundtrip tests) pass a different path and pass
    through untouched.
    """
    import user_profile

    real_default = user_profile._default_profile_path()
    tmp_profile = str(tmp_path / "user_profile.json")
    monkeypatch.setattr(user_profile, "_default_profile_path", lambda: tmp_profile)

    _orig_save = user_profile.UserProfile.save

    def _redirected_save(self, path):
        if path == real_default:
            path = tmp_profile
        return _orig_save(self, path)

    monkeypatch.setattr(user_profile.UserProfile, "save", _redirected_save)
    user_profile.reset_user_profile()
    yield
    user_profile.reset_user_profile()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_paths: 既定パスの解決そのものを検証するテスト。個人データ隔離用の "
        "autouse フィクスチャによる差し替えを無効にする（差し替えたパスを検証しても "
        "何も確かめたことにならないため）。",
    )


@pytest.fixture(autouse=True)
def _isolate_mood(request, tmp_path, monkeypatch):
    """Same isolation for the mood singleton — the last personal-data file the
    suite was still writing for real.

    `python -m pytest tests/` mutated the user's actual config/mood.json and
    config/mood_history.jsonl on every run: tests that exercise real code paths
    (persona_cli, autonomous_behavior.start_autonomous, the GUI command
    handlers) call get_mood_tracker() bare, and its default resolves to the
    repo's live affinity file. Running the test suite therefore nudged the
    user's relationship score and appended history rows — a test suite must not
    have opinions about how close you are to your companion.

    Consumers bind `_default_mood_path` by reference at import time, so — as
    with user_profile above — patching the function alone isn't enough; the
    write methods are redirected too, and only when they target the real
    default (explicit-path roundtrip tests pass through untouched).
    """
    import mood

    if request.node.get_closest_marker("real_paths"):
        # 既定パスの解決自体を検証するテスト。差し替えずに素通しする。
        yield
        return

    real_mood = mood._default_mood_path()
    real_history = mood._default_mood_history_path()
    tmp_mood = str(tmp_path / "mood.json")
    tmp_history = str(tmp_path / "mood_history.jsonl")

    monkeypatch.setattr(mood, "_default_mood_path", lambda: tmp_mood)
    monkeypatch.setattr(mood, "_default_mood_history_path", lambda: tmp_history)

    _orig_save = mood.MoodTracker.save
    _orig_snapshot = mood.MoodTracker.snapshot_to_history

    def _redirected_save(self, path):
        return _orig_save(self, tmp_mood if path == real_mood else path)

    def _redirected_snapshot(self, history_path):
        return _orig_snapshot(
            self, tmp_history if history_path == real_history else history_path)

    monkeypatch.setattr(mood.MoodTracker, "save", _redirected_save)
    monkeypatch.setattr(mood.MoodTracker, "snapshot_to_history", _redirected_snapshot)
    mood.reset_mood_tracker()
    yield
    mood.reset_mood_tracker()


# --------------------------------------------------------------------------- #
# Qt ウィジェットのロジックを、Qt 基底クラス抜きで検証するためのヘルパ
# --------------------------------------------------------------------------- #
def _is_qt_class(cls) -> bool:
    return getattr(cls, "__module__", "").startswith("PyQt5")


def make_qt_stub(cls):
    """cls と同じメソッドを持ち、Qt 基底クラスだけを外したインスタンスを返す。

    GUI のロジック（スラッシュコマンド処理・応答生成・ログ記録）を、実際の
    ウィンドウを開かずに検証するために使う。

    **なぜこの形なのか（2 段階の失敗を経て）**

    1. 元は `object.__new__(AutonomousAvatarViewer)` だった。PyQt5 が入って
       いない環境では基底が素の object なのでこれが通る。PyQt5 が入ると基底が
       QOpenGLWidget（C 拡張型）になり `object.__new__(X) is not safe` で
       TypeError。つまり従来のやり方は **PyQt5 が無い環境でしか通らない
       テスト**を作っていた。CI は requirements.txt を全部入れるので、CI が
       有効化された時点で 197 件が落ちる状態だった（この環境へ実際に PyQt5 を
       入れて再現した）。

    2. `cls.__new__(cls)` に変えると確保はできるが、PyQt5 は
       **属性アクセスそのもの**を `__init__` 実行済みかで検査する。
       `getattr(self, "_clear_log_pending", False)` のような既定値付きの
       参照ですら `RuntimeError: super-class __init__() ... was never called`
       になり、AttributeError ではないので既定値は効かない。個々のメソッドを
       no-op で潰しても追いつかない。

    そこで Qt を継承しない同型のクラスを組み立てる。`vars(cls)` の中身
    （speak_comment 等の実装）はそのまま使い、基底から Qt クラスだけを取り除く
    ので、**検証対象の実コードは本物のまま**で、Qt の生存確認だけが外れる。
    PyQt5 の有無に関係なく同じ結果になる。

    描画通知 `update()` は Qt が供給する契約なので no-op を持たせる
    （`AutonomousBehaviorMixin` が `update` を合成先の提供物として宣言している）。
    """
    bases = tuple(b for b in cls.__bases__ if not _is_qt_class(b)) or (object,)
    namespace = {k: v for k, v in vars(cls).items()
                 if k not in ("__dict__", "__weakref__")}
    namespace.setdefault("update", lambda self, *a, **k: None)
    stub_cls = type(f"{cls.__name__}Stub", bases, namespace)
    return stub_cls.__new__(stub_cls)
