"""data_erasure — 「私に関するデータを全部消して」の一括消去。

このモジュールは元々 `avatar_3d_autonomous_tts.py` の中にあった。GUI 依存は
1 つも無く、そこに置かれていたのは書かれた場所がそうだっただけである。しかし
GUI モジュールの中にあったせいで対話 CLI から呼べず、その結果 **CLI には
/forget-all が存在しなかった** — 打つと未知のコマンドとして会話へ流れ、
「全部消して」と言った人のデータが黙って残っていた。入口によって消える範囲が
違う privacy 保証は、保証ではない。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import data_erasure as de  # noqa: E402


class EraseAllUserDataTests(unittest.TestCase):
    """_erase_all_user_data must wipe every personal store best-effort, so a
    privacy-first 'delete all my data' actually removes the conversation log,
    mood, profile, and avatar history — not just the profile (which is all
    /forget-me clears)."""

    def test_erases_all_available_stores(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        logpath = os.path.join(tmp, "avatar_event_log.jsonl")
        with open(logpath, "w", encoding="utf-8") as f:
            f.write('{"event_type":"user_comment","details":{"text":"secret"}}\n')
        mood_hist = os.path.join(tmp, "mood_history.jsonl")
        with open(mood_hist, "w", encoding="utf-8") as f:
            f.write("{}\n")

        prof = mock.Mock()
        conv_log = mock.Mock()
        conv_log.logfile = logpath
        tracker = mock.Mock()
        tracker.affinity = 80
        avatar_store = mock.Mock()

        with mock.patch.object(de, "_get_user_profile", return_value=prof), \
             mock.patch.object(de, "_default_profile_path", return_value="/tmp/p.json"), \
             mock.patch.object(de, "get_conversation_log", return_value=conv_log), \
             mock.patch.object(de, "get_mood_tracker", return_value=tracker), \
             mock.patch.object(de, "_default_mood_path", return_value="/tmp/m.json"), \
             mock.patch.object(de, "_default_mood_history_path", return_value=mood_hist), \
             mock.patch.object(de, "_avatar_model_store", avatar_store):
            report = de.erase_all_user_data()

        self.assertEqual(report, {"profile": True, "conversation": True,
                                  "mood": True, "avatar": True})
        prof.clear.assert_called_once()
        # conversation log truncated (the secret is gone)
        self.assertEqual(os.path.getsize(logpath), 0)
        # mood reset to neutral + history file removed
        from mood import AFFINITY_START
        self.assertEqual(tracker.affinity, AFFINITY_START)
        self.assertFalse(os.path.exists(mood_hist))
        avatar_store.clear.assert_called_once()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_stores_reported_false_not_crash(self):
        with mock.patch.object(de, "_get_user_profile", None), \
             mock.patch.object(de, "get_conversation_log", None), \
             mock.patch.object(de, "get_mood_tracker", None), \
             mock.patch.object(de, "_avatar_model_store", None):
            report = de.erase_all_user_data()
        self.assertEqual(report, {"profile": False, "conversation": False,
                                  "mood": False, "avatar": False})


class BothEntryPointsEraseTheSameThingTests(unittest.TestCase):
    """GUI と対話 CLI が同じ消去関数を呼ぶこと。

    以前 `/forget-all` は GUI にしか無かった。CLI で打つと未知のコマンドとして
    会話に流れ、**「全部消して」と言った人のデータが黙って残った**。当時それが
    誰にも気づかれなかったのは、未知のスラッシュコマンドが黙って雑談として
    処理されていたからである（そちらも直した）。

    入口によって消える範囲が違う privacy 保証は、保証ではない。
    """

    def _source(self, filename: str) -> str:
        with open(os.path.join(_MAIN, filename), encoding="utf-8") as fh:
            return fh.read()

    def test_gui_uses_the_shared_function(self):
        src = self._source("avatar_3d_autonomous_tts.py")
        self.assertTrue(
            "from data_erasure import erase_all_user_data" in src,
            "GUI が共有の消去関数を import していない")

    def test_cli_uses_the_shared_function(self):
        src = self._source("persona_cli.py")
        self.assertTrue(
            "from data_erasure import erase_all_user_data" in src,
            "CLI が共有の消去関数を import していない")

    def test_neither_entry_point_defines_its_own_erasure(self):
        """3 つ目の実装を作らないこと（ドリフトの温床になる）。"""
        for filename in ("avatar_3d_autonomous_tts.py", "persona_cli.py"):
            with self.subTest(module=filename):
                self.assertNotIn("def erase_all_user_data", self._source(filename))
                self.assertNotIn("def _erase_all_user_data", self._source(filename))

    def test_cli_knows_the_same_command_aliases_as_the_gui(self):
        import persona_cli
        import avatar_3d_autonomous_tts as gui
        cli_aliases = {a.lstrip("/") for a in persona_cli._FORGET_ALL_COMMANDS}
        gui_aliases = {a.lstrip("/")
                       for a in gui._PENDING_CONFIRMATIONS["_forget_all_pending"]}
        self.assertEqual(cli_aliases, gui_aliases,
                         "別名が食い違うと、片方でだけ通じるコマンドができる")

    def test_erasure_covers_the_same_stores_as_manage_satin(self):
        """`manage_satin data purge` と消す対象が一致すること。

        あちらはアプリ停止中にファイルを削除する管理ツール、こちらは動作中の
        アプリからライブのシングルトンごとリセットする。目的が違うので実装は
        分けているが、**消える対象がずれてはいけない**。
        """
        import manage_satin
        purge_targets = {desc for desc, _ in manage_satin._personal_data_paths()}
        # 管理 CLI 側の説明語 → こちらの report キー
        expected = {
            "会話ログ": "conversation",
            "好感度の状態": "mood",
            "ユーザープロファイル": "profile",
            "アバター選択履歴": "avatar",
        }
        for desc in expected:
            with self.subTest(store=desc):
                self.assertIn(desc, purge_targets,
                              f"manage_satin が {desc} を対象にしていない")

        # 逆向き: erase_all_user_data が実際に返すキーが、上の表と過不足なく
        # 一致すること。ストアを 1 つ足して片方に配線し忘れれば、ここで落ちる。
        # 依存をすべて不在にすると全キーが False で返るので、鍵の集合だけ見る。
        with mock.patch.object(de, "_get_user_profile", None), \
             mock.patch.object(de, "get_conversation_log", None), \
             mock.patch.object(de, "get_mood_tracker", None), \
             mock.patch.object(de, "_avatar_model_store", None):
            report = de.erase_all_user_data()
        self.assertEqual(set(report), set(expected.values()))
        self.assertFalse(any(report.values()), "何も消せないはずの構成で True")

