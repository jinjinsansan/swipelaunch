import sys
import types


class _DummyQueue:
    def __init__(self, *args, **kwargs):
        pass

    def enqueue(self, *args, **kwargs):  # pragma: no cover - simple stub
        return None


if "rq" not in sys.modules:
    sys.modules["rq"] = types.SimpleNamespace(Queue=_DummyQueue)
