"""
Do It - Step 8: timers, alarms and reminders that SURVIVE a restart.

They are saved in reminders.json (in the DoIt folder). If you close the program
and open it again, they are loaded again. The program must be RUNNING when the
time comes, because it is the program that rings and speaks.
If a reminder came due while the program was closed, it is announced at start-up.
"""
import json
import os
import threading
import time

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")

on_ring = None            # the voice assistant sets this to a function(message)
_items = {}               # id -> {"id", "due", "message", "kind"}
_timers = {}              # id -> threading.Timer
_lock = threading.RLock()


def nice(sec):
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append("%d hour%s" % (h, "" if h == 1 else "s"))
    if m:
        parts.append("%d minute%s" % (m, "" if m == 1 else "s"))
    if s or not parts:
        parts.append("%d second%s" % (s, "" if s == 1 else "s"))
    return " ".join(parts)


def _save():
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(list(_items.values()), f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def ring(message):
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(1000, 300)
            time.sleep(0.15)
    except Exception:
        print("\a")
    print("\nASSISTANT: %s\n" % message)
    if on_ring is not None:
        on_ring(message)


def _fire(rid):
    with _lock:
        item = _items.pop(rid, None)
        _timers.pop(rid, None)
        _save()
    if item:
        ring(item["message"])


def _schedule(item):
    t = threading.Timer(max(0.0, item["due"] - time.time()), _fire, args=(item["id"],))
    t.daemon = True
    t.start()
    _timers[item["id"]] = t


def add(due, message, kind="reminder"):
    with _lock:
        rid = int(time.time() * 1000)
        while rid in _items:
            rid += 1
        item = {"id": rid, "due": float(due), "message": message, "kind": kind}
        _items[rid] = item
        _schedule(item)
        _save()
    return rid


def add_in(seconds, message, kind="timer"):
    add(time.time() + seconds, message, kind)


def next_occurrence(h, m):
    now = time.localtime()
    target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, h, m, 0, 0, 0, -1))
    if target <= time.time():
        target += 86400
    return target


def add_at(h, m, message, kind="alarm"):
    add(next_occurrence(h, m), message, kind)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def cancel_all():
    with _lock:
        n = len(_items)
        for t in _timers.values():
            t.cancel()
        _timers.clear()
        _items.clear()
        _save()
    return n


def listing():
    """A short spoken sentence about everything that is waiting."""
    with _lock:
        items = sorted(_items.values(), key=lambda i: i["due"])
    if not items:
        return "You have no timers, alarms or reminders."
    out = []
    for i in items[:5]:
        left = nice(max(0, i["due"] - time.time()))
        at = time.strftime("%I:%M %p", time.localtime(i["due"])).lstrip("0")
        if i["kind"] == "timer":
            out.append("a timer with %s left" % left)
        elif i["kind"] == "alarm":
            out.append("an alarm at %s" % at)
        else:
            out.append("a reminder at %s: %s" % (at, i["message"]))
    more = len(items) - 5
    return "You have %s%s." % ("; ".join(out), " and %d more" % more if more > 0 else "")


def load():
    """Call once at start. Re-schedules saved items. Returns messages that were missed."""
    missed = []
    try:
        with open(FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return missed
    with _lock:
        for item in saved:
            try:
                item = {"id": int(item["id"]), "due": float(item["due"]),
                        "message": str(item["message"]), "kind": str(item.get("kind", "reminder"))}
            except (KeyError, TypeError, ValueError):
                continue
            if item["due"] <= time.time():
                missed.append(item["message"])
            else:
                _items[item["id"]] = item
                _schedule(item)
        _save()
    return missed
