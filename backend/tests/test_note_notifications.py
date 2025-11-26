import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.services import note_notifications


class _FailingClient:
    def table(self, *_args, **_kwargs):  # pragma: no cover - defensive should not run
        raise AssertionError("table should not be called for limited notes")


def test_handle_note_published_skips_limited_visibility():
    client = _FailingClient()
    note_row = {
        "id": "note-1",
        "author_id": "creator-1",
        "slug": "limited-note",
        "visibility": "limited",
    }

    # Should not raise and should not attempt to talk to supabase client
    note_notifications._handle_note_published(client, note_row)
