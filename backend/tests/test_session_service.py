from backend.app import config
from backend.app.services import session_service


def test_ensure_session_generates_id():
    sid = session_service.ensure_session(None)
    assert sid
    assert sid in session_service.SESSION_MESSAGES
    session_service.reset(sid)


def test_ensure_session_preserves_given_id():
    sid = session_service.ensure_session("abc123")
    assert sid == "abc123"
    session_service.reset(sid)


def test_history_trims_to_limit():
    sid = session_service.ensure_session("trim-test")
    for i in range(config.SESSION_HISTORY_LIMIT + 4):
        session_service.append(sid, "user", f"msg {i}")
    history = session_service.get_history(sid)
    assert len(history) == config.SESSION_HISTORY_LIMIT
    # Oldest messages dropped; newest kept.
    assert history[-1]["content"] == f"msg {config.SESSION_HISTORY_LIMIT + 3}"
    session_service.reset(sid)
