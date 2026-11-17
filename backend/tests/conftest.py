def run_inline(coro):
    """Run a fake-only coroutine whose awaits complete synchronously, without a loop."""
    try:
        coro.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Offline fake unexpectedly suspended for I/O")
