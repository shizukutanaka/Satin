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
