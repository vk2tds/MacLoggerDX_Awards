#!/usr/bin/env python3
"""
wsjtx_gui_bridge.py -- drives WSJT-X's own GUI directly, for the handful of
controls that have no UDP equivalent at all (Monitor, Decode, Enable Tx,
Tune, Stop, and the band/mode buttons). Everything else in the Remote tab
goes through wsjtx_udp.py instead, which is far more robust -- this module
only exists because those specific controls genuinely aren't reachable any
other way.

Two different mechanisms are used here, and the distinction matters a lot:

1. Reading state (get_checkbox_states) uses AppleScript/System Events
   accessibility queries -- fine for reads, always worked reliably.

2. Clicking uses a genuine OS-level HID-tap mouse click via Quartz/CGEvent
   (see _hid_click), NOT AppleScript's `click`/`click at`. This was a real,
   verified-the-hard-way finding (2026-07-16): WSJT-X's Enable Tx, Tune,
   Decode, and Monitor are all *checkable* QPushButtons whose red/highlight
   styling is pure CSS driven by the `checked` property, but whose actual
   application logic lives in Qt's auto-connected `on_<name>_clicked(bool)`
   slots -- which Qt only invokes from a genuine click()/user interaction,
   never from a property change alone. Both AppleScript's accessibility
   "press" action AND a coordinate-based `click at` (which is *also*
   accessibility-mediated on macOS, not a raw hardware event) only flip the
   `checked` property -- confirmed by checking WSJT-X's own source
   (widgets/mainwindow.cpp) and, conclusively, by watching rigctld's live
   PTT reading and the UDP Status message's `tx_enabled` field stay
   unchanged no matter how many times those methods "clicked" Enable Tx or
   Tune. A genuine CGEvent posted at the kCGHIDEventTap level -- the closest
   thing to real hardware input software can generate -- does reliably
   trigger the real signal chain, verified against both ground-truth
   signals. It isn't perfectly reliable on the first attempt in practice
   (observed needing 2-3 tries with a longer settle delay), hence the retry
   loop in arm_tx_checkbox().

3. Turning Enable Tx or Tune back OFF does NOT use a GUI click at all: it
   goes through the existing, already-reliable UDP HaltTx command instead
   (see wsjtx_remote.py's routes). WSJT-X's own halt_tx handler internally
   calls `ui->autoButton->click()` / `ui->stopTxButton->click()` -- genuine
   in-process method calls (not GUI scripting), which Qt fully honours --
   so disarming has a solid mechanism already; only arming needed a new one.

This is all inherently more fragile than the UDP path: it needs WSJT-X
running (process name "wsjtx", not "WSJT-X"), Accessibility permission
granted to whatever process runs this code, pyobjc-framework-Quartz
installed, and a future WSJT-X version could rename these widgets or change
their screen layout in ways that require re-verifying against the real app.
"""

from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger("wsjtx_gui_bridge")

PROCESS_NAME = "wsjtx"

# Checkbox controls (stateful toggles), by their exact accessible name.
CHECKBOXES = ("Monitor", "Decode", "Enable Tx", "Tune")

# The two checkboxes that actually key/arm the transmitter -- handled with
# the more careful HID-click-with-retry path, and never auto-toggled off
# via a GUI click (see module docstring point 3).
TX_ARM_CHECKBOXES = ("Enable Tx", "Tune")

# Plain momentary buttons -- band selector, mode selector, and Stop.
BAND_BUTTONS = ("160", "80", "60", "40", "30", "20", "17", "15", "12", "10", "6", "2", "70")
MODE_BUTTONS = ("FT8", "FT4", "MSK", "Q65", "JT65")

# AppleScript element class per control name, for position/click lookups.
_ELEMENT_CLASS = {name: "checkbox" for name in CHECKBOXES}
_ELEMENT_CLASS.update({name: "button" for name in ("Stop",) + BAND_BUTTONS + MODE_BUTTONS})

_WINDOW_REF = (
    'if not (exists process "{proc}") then error "WSJT-X is not running"\n'
    '        tell process "{proc}"\n'
    '            set win to first window whose name starts with "WSJT-X"\n'
).format(proc=PROCESS_NAME)


class WsjtxGuiError(Exception):
    """AppleScript couldn't find/drive WSJT-X's window -- not running, no
    Accessibility permission, or a widget name changed."""


def _run_osascript(script: str, timeout: float = 5.0) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WsjtxGuiError("osascript timed out") from exc
    if result.returncode != 0:
        raise WsjtxGuiError(result.stderr.strip() or "osascript failed")
    return result.stdout.strip()


# Markers seen on reads of Enable Tx/Tune WHILE THEY ARE GENUINELY ENGAGED --
# confirmed via diagnose_tune.py against rigctld's live PTT (2026-07-17):
# clicking Tune succeeds immediately (a read microseconds later shows
# value=1), but from ~0.3s onward, for the ENTIRE remaining duration Tune is
# actively keying (PTT stayed True the whole time), *every* accessibility
# read of that checkbox fails -- both `value of checkbox "Tune"` (-1700,
# "Can't make ... into type string") and even `name of checkbox "Tune"`
# (-1728, "Can't get checkbox ... of window"). This isn't a brief
# transitional race; it appears WSJT-X's real-time audio thread blocks the
# accessibility bridge from servicing queries about that widget for as long
# as it's actively tuning. Treated as "busy, not broken" throughout this
# module: never grounds for raising a hard error to the caller, and
# critically never grounds for clicking again (see arm_tx_checkbox).
_TRANSIENT_BUSY_MARKERS = ("-1700", "Can't make", "-1728", "Can't get")


def _is_transient_busy(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _TRANSIENT_BUSY_MARKERS)


def _run_osascript_reading_value(script: str, retries: int = 3, retry_delay: float = 0.2) -> str:
    """Like _run_osascript, but retries a few times through the transient
    "busy" failure (see _TRANSIENT_BUSY_MARKERS) in case it clears within a
    fraction of a second. It often doesn't -- Tune can stay busy for many
    seconds -- so this is only a first line of defense; callers that need to
    survive a longer busy window use _read_checkbox_or_none / the
    last-known-state fallback in get_checkbox_states instead of relying on
    this retry alone. Any other error (WSJT-X not running, wrong widget
    name, etc.) is raised straight away rather than retried needlessly."""
    last_exc = None
    for _ in range(retries):
        try:
            return _run_osascript(script)
        except WsjtxGuiError as exc:
            if not _is_transient_busy(exc):
                raise
            last_exc = exc
            time.sleep(retry_delay)
    raise last_exc


def _bring_frontmost():
    _run_osascript(f'tell application "System Events" to set frontmost of process "{PROCESS_NAME}" to true')


def _element_center(name: str) -> tuple:
    ax_class = _ELEMENT_CLASS.get(name, "button")
    script = f'''
    tell application "System Events"
        {_WINDOW_REF}
            set p to position of {ax_class} "{name}" of win
            set s to size of {ax_class} "{name}" of win
            return ((item 1 of p) as string) & "," & ((item 2 of p) as string) & "," & ((item 1 of s) as string) & "," & ((item 2 of s) as string)
        end tell
    end tell
    '''
    px, py, sw, sh = (float(v) for v in _run_osascript(script).split(","))
    return px + sw / 2, py + sh / 2


def _post_hid_click(x: float, y: float):
    """A genuine HID-tap-level synthetic mouse click -- see module docstring
    point 2 for why this, and not AppleScript's `click`, is required."""
    try:
        import Quartz
    except ImportError as exc:
        raise WsjtxGuiError(
            "pyobjc-framework-Quartz is not installed -- required for real button clicks "
            "(pip install pyobjc-framework-Quartz)"
        ) from exc
    down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, (x, y), Quartz.kCGMouseButtonLeft)
    up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.05)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


# Timestamp of the most recent HID click on any control, used by
# get_checkbox_states to avoid trusting a read taken too close to a click
# (see _STATUS_READ_GRACE_S below).
_last_click_time = 0.0


def _hid_click_named(name: str, settle_s: float = 0.8):
    global _last_click_time
    x, y = _element_center(name)
    _bring_frontmost()
    time.sleep(settle_s)
    _post_hid_click(x, y)
    _last_click_time = time.time()


def _read_checkbox(name: str) -> bool:
    script = f'''
    tell application "System Events"
        {_WINDOW_REF}
            return (value of checkbox "{name}" of win) as string
        end tell
    end tell
    '''
    return _run_osascript_reading_value(script).strip() == "1"


def _read_checkbox_or_none(name: str):
    """Like _read_checkbox, but returns None instead of raising when the
    read hits the transient "busy" failure. Callers use this to tell
    "confirmed off" (False) apart from "couldn't tell right now" (None) --
    a distinction that matters because treating an inconclusive read the
    same as a confirmed-off read would make arm_tx_checkbox click again on
    a checkbox that's actually already armed, toggling it back off."""
    try:
        return _read_checkbox(name)
    except WsjtxGuiError as exc:
        if _is_transient_busy(exc):
            return None
        raise


# Last successfully-read full checkbox snapshot, used by get_checkbox_states
# as a fallback when WSJT-X's accessibility tree is transiently unreadable
# (see _TRANSIENT_BUSY_MARKERS) so the Remote tab's status poll doesn't
# surface a raw AppleScript error for the entire time Tune is engaged.
_last_known_states: dict = {}


def set_cached_checkbox_state(name: str, value: bool):
    """Explicitly record a checkbox's state in the get_checkbox_states
    fallback cache. Needed because a plain successful read is not the only
    way we learn a checkbox's true state: arm_tx_checkbox knows a checkbox
    is armed even when it can no longer read it back (busy), and
    wsjtx_remote.py's halt_tx disarm path changes state without going
    through this module's read/click functions at all. Without this, the
    cache would keep serving a stale pre-click snapshot for the whole busy
    window -- e.g. reporting Tune as off while it's genuinely transmitting,
    which is misleading in the UI even though it never raises an error."""
    _last_known_states[name] = value


# How long after any HID click to avoid even ATTEMPTING a live combined
# read in get_checkbox_states, serving the cache instead. Needed because a
# read taken right as a click lands isn't just prone to throwing (see
# _TRANSIENT_BUSY_MARKERS) -- it can also *succeed* with a genuinely wrong
# value for a checkbox that was never touched (observed: Monitor read as 0
# in the same combined script call where Tune correctly read 1, right after
# clicking Tune, even though Monitor was untouched and still 1 a moment
# later). Matches the settle delays already used elsewhere in this module.
_STATUS_READ_GRACE_S = 1.5


def get_checkbox_states() -> dict:
    """One combined AppleScript call reading every checkbox at once --
    GUI-scripting round trips (accessibility IPC, not a socket) are slow
    enough that this shouldn't be polled as tightly as the UDP status feed,
    and there's no reason to pay for four separate subprocess calls."""
    if _last_known_states and (time.time() - _last_click_time) < _STATUS_READ_GRACE_S:
        return dict(_last_known_states)
    reads = "\n".join(
        f'            set v{i} to (value of checkbox "{name}" of win) as string'
        for i, name in enumerate(CHECKBOXES)
    )
    joined = " & \"|\" & ".join(f"v{i}" for i in range(len(CHECKBOXES)))
    script = f'''
    tell application "System Events"
        {_WINDOW_REF}
{reads}
            return {joined}
        end tell
    end tell
    '''
    try:
        out = _run_osascript_reading_value(script)
    except WsjtxGuiError as exc:
        if _is_transient_busy(exc) and _last_known_states:
            return dict(_last_known_states)
        raise
    values = [v.strip() == "1" for v in out.split("|")]
    states = dict(zip(CHECKBOXES, values))
    _last_known_states.update(states)
    return states


def set_checkbox(name: str, on: bool) -> bool:
    """For Monitor/Decode only -- no Tx-arming stakes, so a single HID click
    (with one retry) is proportionate. Enable Tx/Tune use arm_tx_checkbox()
    for turning on; turning them off should go through UDP HaltTx instead
    (see wsjtx_remote.py), not this function."""
    if name not in CHECKBOXES:
        raise ValueError(f"Unknown checkbox {name!r}")
    if name in TX_ARM_CHECKBOXES:
        raise ValueError(f"{name!r} must use arm_tx_checkbox()/UDP HaltTx, not set_checkbox()")
    if _read_checkbox(name) == on:
        set_cached_checkbox_state(name, on)
        return on
    for attempt in range(2):
        _hid_click_named(name, settle_s=0.5 + attempt * 0.3)
        time.sleep(0.5)
        if _read_checkbox(name) == on:
            set_cached_checkbox_state(name, on)
            return on
    result = _read_checkbox(name)
    set_cached_checkbox_state(name, result)
    return result


def arm_tx_checkbox(name: str, max_attempts: int = 4, poll_timeout_s: float = 6.0) -> bool:
    """Turn ON Enable Tx or Tune via a genuine HID-level click -- the only
    mechanism that actually arms them (see module docstring). Retries with
    a growing settle delay since a single attempt isn't reliable in
    practice. Returns the final observed checkbox state; callers should
    treat a returned False as "did not arm" and report that clearly rather
    than assume success.

    Important safety property: after clicking, this polls for up to
    poll_timeout_s but will only click AGAIN on a *confirmed* off read
    (_read_checkbox_or_none returning False). An inconclusive read (None --
    WSJT-X's accessibility tree busy, see _TRANSIENT_BUSY_MARKERS) is never
    treated as "the click failed", because it isn't -- diagnose_tune.py
    confirmed (via rigctld PTT) that this busy state only occurs while the
    checkbox is genuinely already engaged. Clicking again in that window
    would toggle an already-armed Tx back OFF, which is worse than a slow or
    uncertain status report."""
    if name not in TX_ARM_CHECKBOXES:
        raise ValueError(f"{name!r} is not a Tx-arming checkbox")
    if _read_checkbox_or_none(name):
        set_cached_checkbox_state(name, True)
        return True
    for _attempt in range(max_attempts):
        _hid_click_named(name, settle_s=0.8 + _attempt * 0.4)
        deadline = time.time() + poll_timeout_s
        state = None
        while time.time() < deadline:
            state = _read_checkbox_or_none(name)
            if state is not False:
                break  # True (armed) or None (busy -- also means armed)
            time.sleep(0.3)
        if state is not False:
            set_cached_checkbox_state(name, True)
            return True
    final = _read_checkbox_or_none(name)
    set_cached_checkbox_state(name, bool(final))
    return bool(final)


def click_button(name: str):
    """One-shot momentary button: Stop, a band button, or a mode button."""
    if name not in ("Stop",) + BAND_BUTTONS + MODE_BUTTONS:
        raise ValueError(f"Unknown button {name!r}")
    _hid_click_named(name)
