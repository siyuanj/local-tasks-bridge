"""Stand-in for `local_tasks_bridge.py run-loop` in the app-core tests.

Invoked as: python3 -B fake_run_loop.py --config PATH run-loop --log-file PATH
The scenario comes from FAKE_LOOP_SCENARIO:
  crash  - emit a short cycle, write stray output, exit 1 (the app restarts it)
  linger - emit loop_started, then on SIGTERM take a second before exiting,
           like a loop finishing its cycle
"""

import json
import os
import signal
import sys
import time


def emit(event, **fields):
    sys.stdout.write("@@LTB " + json.dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def main():
    if "run-loop" not in sys.argv or "--log-file" not in sys.argv:
        sys.stderr.write("unexpected arguments: %r\n" % (sys.argv,))
        return 2
    if os.environ.get("LTB_EVENT_STREAM") != "stdout":
        sys.stderr.write("LTB_EVENT_STREAM is not set\n")
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


if __name__ == "__main__":
    sys.exit(main())
