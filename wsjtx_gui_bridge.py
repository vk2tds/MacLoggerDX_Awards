#!/usr/bin/env python3
"""
wsjtx_gui_bridge.py -- drives WSJT-X's own GUI directly via AppleScript/
System Events accessibility scripting, for the handful of controls that
have no UDP equivalent at all (Monitor, Decode, Stop, and the band/mode
buttons). Everything else in the Remote tab goes through wsjtx_udp.py
instead, which is far more robust -- this module only exists because those
specific controls genuinely aren't reachable any other way.

This is inherently more fragile than the UDP path: it only works if WSJT-X
is running with "wsjtx" as its process name, if this app (or whatever
spawns it) has been granted Accessibility permission (System Settings ->
Privacy & Security -> Accessibility), and if a future WSJT-X version
doesn't rename these widgets -- verified interactively against a live
WSJT-X v3.0.1 instance rather than assumed, the same way the rigctld
protocol assumptions were checked earlier (see radio_control.py's history):
`value of checkbox` coerces oddly when concatenated with `&` inline (yields
a mangled "0, ," instead of "0"), so every value is coerced with an
explicit `as string` on its own line first -- skipping that produced
corrupted output during testing.

Enable Tx and Tune are deliberately NOT exposed here (2026-07-16): clicking
them via AppleScript -- both the accessibility "press" action and a real
synthetic mouse click at the checkbox's exact screen coordinates -- toggles
the checkbox's visible/accessible state (Tune even repaints red) but does
NOT actually key the transmitter, confirmed against rigctld's live PTT
reading as ground truth while comparing to a genuine manual click (which
did key it). Wiring them up anyway would be actively misleading -- looks
armed/tuning when it isn't. Revisit later; see project_wsjtx_gui_bridge.md.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("wsjtx_gui_bridge")

PROCESS_NAME = "wsjtx"

# Checkbox controls (stateful toggles), by their exact accessible name.
# Enable Tx and Tune are intentionally excluded -- see module docstring.
CHECKBOXES = ("Monitor", "Decode")

# Plain momentary buttons -- band selector, mode selector, and Stop.
BAND_BUTTONS = ("160", "80", "60", "40", "30", "20", "17", "15", "12", "10", "6", "2", "70")
MODE_BUTTONS = ("FT8", "FT4", "MSK", "Q65", "JT65")

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


def get_checkbox_states() -> dict:
    """One combined AppleScript call reading all four checkboxes at once --
    GUI-scripting round trips (accessibility IPC, not a socket) are slow
    enough that this shouldn't be polled as tightly as the UDP status feed,
    and there's no reason to pay for four separate subprocess calls."""
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
    out = _run_osascript(script)
    values = [v.strip() == "1" for v in out.split("|")]
    return dict(zip(CHECKBOXES, values))


def set_checkbox(name: str, on: bool) -> bool:
    if name not in CHECKBOXES:
        raise ValueError(f"Unknown checkbox {name!r}")
    script = f'''
    tell application "System Events"
        {_WINDOW_REF}
            if ((value of checkbox "{name}" of win) as string) is not "{1 if on else 0}" then
                click checkbox "{name}" of win
            end if
            return (value of checkbox "{name}" of win) as string
        end tell
    end tell
    '''
    return _run_osascript(script).strip() == "1"


def click_button(name: str):
    """One-shot momentary button: Stop, a band button, or a mode button."""
    script = f'''
    tell application "System Events"
        {_WINDOW_REF}
            click button "{name}" of win
        end tell
    end tell
    '''
    _run_osascript(script)
