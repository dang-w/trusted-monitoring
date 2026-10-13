"""The upload path of tm.publish: fresh connections, no xet (E6, 13 October 2026)."""

from huggingface_hub import constants
from huggingface_hub.utils import get_session
from huggingface_hub.utils._runtime import is_xet_available

from tm import publish


def test_uploads_use_fresh_connections_and_no_xet():
    publish.configure_uploads()
    assert get_session().headers["Connection"] == "close"
    assert constants.HF_HUB_DISABLE_XET is True
    assert is_xet_available() is False
