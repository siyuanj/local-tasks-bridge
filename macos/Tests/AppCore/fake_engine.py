"""Stand-in for engine/local_tasks_bridge.py in the app-core tests.

Invoked like the engine: python3 -B fake_engine.py --config PATH COMMAND ...
  run-loop      FAKE_LOOP_SCENARIO=crash: a short cycle, stray output, exit 1
                (the app restarts it); =linger: on SIGTERM take a second to
                finish the cycle, then exit
  config merge  a write command that takes a second
  status        a read-only command that takes ten seconds
  doctor        fails, with reminder titles on stderr
"""

import json
import os
import signal
import sys
import time


def emit(event, **fields):
    sys.stdout.write("@@LTB " + json.dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def run_loop():
    if "--log-file" not in sys.argv or os.environ.get("LTB_EVENT_STREAM") != "stdout":
        sys.stderr.write("run-loop started without --log-file or LTB_EVENT_STREAM\n")
        return 2
    scenario = os.environ.get("FAKE_LOOP_SCENARIO", "crash")
    emit("loop_started", version="0.0.0-test", interval=60)
    if scenario == "crash":
        emit("cycle_started", at="2026-10-01T10:00:00+00:00")
        print("stray stdout line", flush=True)
        sys.stderr.write("stray stderr line\n")
        sys.stderr.flush()
        emit("notification", title="Title", message="Message", severity="problem")
        emit("cycle_finished", at="2026-10-01T10:00:01+00:00", state="ok", condition="healthy", consecutive_failures=0)
        sys.stdout.write("@@LTB {not json\n")
        sys.stdout.flush()
        return 1

    def finish_then_exit(_signum, _frame):
        time.sleep(1)
        emit("cycle_finished", at="2026-10-01T10:00:02+00:00", state="ok", condition="healthy", consecutive_failures=0)
        sys.exit(0)

    signal.signal(signal.SIGTERM, finish_then_exit)
    emit("cycle_started", at="2026-10-01T10:00:01+00:00")
    while True:
        time.sleep(0.1)


def main():
    if os.environ.get("LTB_CALLER") != "app":
        sys.stderr.write("LTB_CALLER is not set\n")
        return 2
    command = sys.argv[3:] if sys.argv[1:2] == ["--config"] else sys.argv[1:]
    if command[:1] == ["run-loop"]:
        return run_loop()
    if command[:2] == ["config", "merge"]:
        sys.stdin.read()
        time.sleep(1)
        print(json.dumps({"ok": True, "config": {"include_lists": ["Work"]}}))
        return 0
    if command[:1] == ["status"]:
        time.sleep(10)
        print(json.dumps({"ok": True}))
        return 0
    if command[:1] == ["doctor"]:
        sys.stderr.write("Buy milk for SECRET-TITLE\n")
        return 1
    sys.stderr.write("unexpected command %r\n" % (command,))
    return 2


if __name__ == "__main__":
    sys.exit(main())
