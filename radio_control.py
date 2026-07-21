#!/usr/bin/env python3
"""
radio_control.py -- the "Radio" tab: direct rig control via Hamlib's rigctld
daemon (https://hamlib.github.io/), independent of WSJT-X's own UDP API
(which has no frequency/mode/PTT control at all -- that's the rig's job).

rigctld is a small TCP daemon that owns the actual CAT/serial connection to
the radio; this module is just a thin client for its plain-text protocol.
Each call opens a short-lived socket, sends one "long command" (the
backslash-prefixed form, e.g. "\\get_freq"), reads until a line starting
with "RPRT" (rigctld's per-command result code), and closes -- no persistent
connection or background thread, so a rigctld that isn't running yet (or
that briefly drops) just surfaces as a clean per-request error rather than
wedging a shared connection.
"""

from __future__ import annotations

import dataclasses
import glob
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from typing import Optional

from flask import Blueprint, jsonify, render_template, request

log = logging.getLogger("radio_control")

# Standard FT8 calling (QSY) frequency per band -- what the band buttons jump
# to. Not the only frequency in use on a band, just the conventional start
# point most operators tune from.
FT8_CALLING_FREQ_HZ = {
    "160M": 1_840_000, "80M": 3_573_000, "60M": 5_357_000, "40M": 7_074_000,
    "30M": 10_136_000, "20M": 14_074_000, "17M": 18_100_000, "15M": 21_074_000,
    "12M": 24_915_000, "10M": 28_074_000, "6M": 50_313_000, "2M": 144_174_000,
}

_BAND_TABLE = [
    (1.8, 2.0, "160M"), (3.5, 4.0, "80M"), (5.3, 5.4, "60M"), (7.0, 7.3, "40M"),
    (10.1, 10.15, "30M"), (14.0, 14.35, "20M"), (18.068, 18.168, "17M"),
    (21.0, 21.45, "15M"), (24.89, 24.99, "12M"), (28.0, 29.7, "10M"),
    (50.0, 54.0, "6M"), (70.0, 70.5, "4M"), (144.0, 148.0, "2M"),
]


def freq_to_band(hz: Optional[float]) -> Optional[str]:
    if not hz:
        return None
    mhz = hz / 1_000_000.0
    for lo, hi, name in _BAND_TABLE:
        if lo <= mhz <= hi:
            return name
    return None


@dataclasses.dataclass
class RigctldConfig:
    host: str = "127.0.0.1"
    port: int = 4532
    timeout_s: float = 2.0


class RigctldError(Exception):
    """rigctld reached but returned a non-zero RPRT code (bad command,
    unsupported by this rig, rig not responding over CAT, etc.)."""


class RigctldConnectionError(Exception):
    """Could not reach rigctld at all -- almost always means it isn't
    running, or is listening on a different host/port."""


class RigctldClient:
    def __init__(self, config: RigctldConfig):
        self.config = config

    def _command(self, cmd: str, expect_lines: int = 0) -> list:
        """Send one long-form command. `expect_lines` is how many data lines
        a *successful* call returns (0 for "set" commands).

        rigctld's protocol is asymmetric in a way that's easy to get wrong:
        a successful "get" returns exactly its data lines and NOTHING else
        -- no RPRT trailer at all. RPRT only ever appears as a command's
        *entire* response, either because it's a "set" (whose only possible
        response is RPRT) or because a "get" failed (RPRT replaces the data
        it would have returned). So the read loop can't "read until RPRT" --
        for a successful get that line never comes and it just hangs until
        the socket times out. Instead: read up to `expect_lines`, and treat
        the *first* line as an error if it starts with RPRT."""
        try:
            with socket.create_connection(
                (self.config.host, self.config.port), timeout=self.config.timeout_s
            ) as sock:
                sock.sendall((cmd + "\n").encode("ascii"))
                f = sock.makefile("r", encoding="ascii", errors="replace")
                lines = []
                for _ in range(max(expect_lines, 1)):
                    raw = f.readline()
                    if not raw:
                        raise RigctldConnectionError("rigctld closed the connection unexpectedly")
                    line = raw.rstrip("\r\n")
                    if line.startswith("RPRT"):
                        code = int(line.split()[1])
                        if code != 0:
                            raise RigctldError(f"{cmd} failed (RPRT {code})")
                        return lines  # success response to a "set" command -- no data
                    lines.append(line)
                return lines
        except (OSError, socket.timeout) as exc:
            raise RigctldConnectionError(
                f"Could not reach rigctld at {self.config.host}:{self.config.port} -- {exc}"
            ) from exc

    def get_freq(self) -> float:
        return float(self._command("\\get_freq", expect_lines=1)[0])

    def set_freq(self, hz: float):
        self._command(f"\\set_freq {int(hz)}")

    def get_mode(self) -> tuple:
        lines = self._command("\\get_mode", expect_lines=2)
        mode = lines[0]
        passband = int(lines[1]) if len(lines) > 1 and lines[1].strip() else 0
        return mode, passband

    def set_mode(self, mode: str, passband: int = 0):
        self._command(f"\\set_mode {mode} {passband}")

    def get_ptt(self) -> bool:
        return self._command("\\get_ptt", expect_lines=1)[0].strip() == "1"

    def set_ptt(self, on: bool):
        self._command(f"\\set_ptt {1 if on else 0}")

    def get_strength(self) -> int:
        """S-meter reading in dBS (Hamlib convention: 0 = S9, negative below
        S9 -- roughly 6dB per S-unit on HF, though the exact scale is rig-
        dependent and not standardized above S9)."""
        return int(float(self._command("\\get_level STRENGTH", expect_lines=1)[0]))

    def get_rit(self) -> int:
        return int(self._command("\\get_rit", expect_lines=1)[0])

    def set_rit(self, hz: int):
        self._command(f"\\set_rit {int(hz)}")

    def get_xit(self) -> int:
        return int(self._command("\\get_xit", expect_lines=1)[0])

    def set_xit(self, hz: int):
        self._command(f"\\set_xit {int(hz)}")

    def get_rfpower(self) -> float:
        """Hamlib's RFPOWER level is a 0.0-1.0 fraction of the rig's max, not
        watts -- there's no direct watts unit since max power varies by rig/
        band/mode. See power_to_watts()/set_power_watts() for watts."""
        return float(self._command("\\get_level RFPOWER", expect_lines=1)[0])

    def set_rfpower(self, fraction: float):
        self._command(f"\\set_level RFPOWER {fraction}")

    def get_miclevel(self) -> float:
        """Hamlib's MICGAIN level, 0.0-1.0 fraction of max -- not universally
        supported by every rig backend over CAT (unlike RFPOWER/RIT/XIT,
        which the IC-7300 backend exposes reliably), so callers should treat
        a RigctldError here as "this rig/backend doesn't support it" rather
        than a real failure."""
        return float(self._command("\\get_level MICGAIN", expect_lines=1)[0])

    def set_miclevel(self, fraction: float):
        self._command(f"\\set_level MICGAIN {fraction}")

    def power_to_watts(self, fraction: float, freq_hz: float, mode: str) -> float:
        mw = float(self._command(f"\\power2mW {fraction} {int(freq_hz)} {mode}", expect_lines=1)[0])
        return mw / 1000.0

    def watts_to_power(self, watts: float, freq_hz: float, mode: str) -> float:
        mw = watts * 1000.0
        return float(self._command(f"\\mW2power {mw} {int(freq_hz)} {mode}", expect_lines=1)[0])

    def set_power_watts(self, watts: float, freq_hz: float, mode: str):
        self.set_rfpower(self.watts_to_power(watts, freq_hz, mode))

    def status(self) -> dict:
        """Best-effort combined snapshot for the status readout -- every
        field is fetched as its own rigctld command (its protocol has no
        single combined query), so a rig that's mid-retune between calls can
        occasionally show values that don't quite line up; the next poll
        (roughly once a second) corrects itself.

        Everything past frequency/mode is treated as optional: PTT, S-meter,
        RIT/XIT, and RFPOWER all commonly fail on rigs/configs that don't
        wire up that particular feature over CAT, and one missing feature
        shouldn't blank out a freq/mode readout that's working fine."""
        freq_hz = self.get_freq()
        mode, passband = self.get_mode()

        def optional(fn):
            # Catches RigctldConnectionError too, not just RigctldError:
            # status() makes several back-to-back short-lived connections,
            # and rigctld can occasionally reset one of them under that kind
            # of rapid-fire connect/disconnect churn even though it's still
            # very much alive (observed directly against a live rigctld) --
            # that's a transient hiccup on one optional field, not grounds
            # to fail the whole poll the way a freq/mode failure would.
            try:
                return fn(), None
            except (RigctldError, RigctldConnectionError) as exc:
                return None, str(exc)

        ptt, ptt_error = optional(self.get_ptt)
        strength, strength_error = optional(self.get_strength)
        rit, rit_error = optional(self.get_rit)
        xit, xit_error = optional(self.get_xit)
        rfpower, rfpower_error = optional(self.get_rfpower)
        rfpower_watts = None
        if rfpower is not None:
            try:
                rfpower_watts = self.power_to_watts(rfpower, freq_hz, mode)
            except (RigctldError, RigctldConnectionError):
                pass

        return {
            "connected": True,
            "frequency_hz": freq_hz,
            "band": freq_to_band(freq_hz),
            "mode": mode,
            "passband": passband,
            "ptt": ptt, "ptt_error": ptt_error,
            "strength_dbs": strength, "strength_error": strength_error,
            "rit_hz": rit, "rit_error": rit_error,
            "xit_hz": xit, "xit_error": xit_error,
            "rfpower_fraction": rfpower, "rfpower_watts": rfpower_watts, "rfpower_error": rfpower_error,
        }


# ---------------------------------------------------------------------------
# rigctld process management -- start/stop/restart/configure the daemon
# itself. Not bundled: this only finds and supervises whatever rigctld
# binary is already installed (e.g. via `brew install hamlib`).
# ---------------------------------------------------------------------------

_BINARY_SEARCH_PATHS = ["/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin"]

# Serial device names that show up in /dev/cu.* but are never a radio's CAT
# interface -- filtered out of the device picker so it isn't cluttered.
_SERIAL_DEVICE_IGNORE = {"cu.Bluetooth-Incoming-Port", "cu.debug-console"}


def find_rigctld_binary(override: Optional[str] = None) -> Optional[str]:
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    found = shutil.which("rigctld")
    if found:
        return found
    for d in _BINARY_SEARCH_PATHS:
        candidate = os.path.join(d, "rigctld")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def list_serial_devices() -> list:
    return [
        path for path in sorted(glob.glob("/dev/cu.*"))
        if os.path.basename(path) not in _SERIAL_DEVICE_IGNORE
    ]


@dataclasses.dataclass
class RigctldProcessConfig:
    rig_model: Optional[int] = None
    device: str = ""
    baud: Optional[int] = None
    listen_host: str = "127.0.0.1"
    listen_port: int = 4532
    extra_args: str = ""
    binary_path: str = ""  # override; empty = auto-detect

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RigctldProcessConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


class RigctldProcessManager:
    """Finds, configures, and supervises an external rigctld process. Config
    and the PID of anything we've spawned are both persisted to disk so a
    Flask reload (which restarts the worker process -- see AllTxtCache's
    comments in qsl_helper.py about the debug reloader's watcher+child
    duality) doesn't orphan a rigctld we started; we can still find and
    stop/restart it afterwards."""

    def __init__(self, config_path: str, state_path: str, log_path: str):
        self.config_path = config_path
        self.state_path = state_path
        self.log_path = log_path
        self._rig_models_cache: Optional[list] = None

    # -- config --
    def load_config(self) -> RigctldProcessConfig:
        if not os.path.exists(self.config_path):
            return RigctldProcessConfig()
        try:
            with open(self.config_path, "r") as f:
                return RigctldProcessConfig.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError):
            log.exception("Could not read %s", self.config_path)
            return RigctldProcessConfig()

    def save_config(self, cfg: RigctldProcessConfig):
        tmp = self.config_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg.to_dict(), f, indent=2)
        os.replace(tmp, self.config_path)

    # -- state (tracks a PID we spawned) --
    def _load_state(self) -> dict:
        if not os.path.exists(self.state_path):
            return {}
        try:
            with open(self.state_path, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.state_path)

    def _clear_state(self):
        if os.path.exists(self.state_path):
            os.remove(self.state_path)

    def _tracked_pid(self) -> Optional[int]:
        """The PID we last spawned, but only if it's still alive AND still
        actually a rigctld process -- a bare PID number surviving in a JSON
        file is worthless once the OS has recycled it for something else."""
        state = self._load_state()
        pid = state.get("pid")
        if not pid:
            return None
        try:
            os.kill(pid, 0)
        except OSError:
            self._clear_state()
            return None
        try:
            comm = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, timeout=2,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            comm = ""
        if "rigctld" not in comm:
            self._clear_state()
            return None
        return pid

    def rig_models(self) -> list:
        """Parses `rigctld -l`'s fixed-width table (id/mfg/model/version/
        status/macro) into a list of dicts for the model picker. Cached in
        memory -- it's static per Hamlib install and the command takes a
        moment to enumerate every backend."""
        if self._rig_models_cache is not None:
            return self._rig_models_cache
        binary = find_rigctld_binary(self.load_config().binary_path or None)
        if not binary:
            return []
        try:
            out = subprocess.run(
                [binary, "-l"], capture_output=True, text=True, timeout=15,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            log.exception("Failed to list rig models via %s -l", binary)
            return []
        models = []
        for line in out.splitlines()[1:]:
            if not line.strip():
                continue
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            models.append({
                "id": int(parts[0]), "mfg": parts[1], "model": parts[2],
                "version": parts[3], "status": parts[4],
            })
        self._rig_models_cache = models
        return models

    def status(self) -> dict:
        cfg = self.load_config()
        pid = self._tracked_pid()
        try:
            with socket.create_connection((cfg.listen_host, cfg.listen_port), timeout=0.5):
                listen_reachable = True
        except OSError:
            listen_reachable = False
        state = self._load_state()
        return {
            "managed_pid": pid,
            "managed_running": pid is not None,
            "listen_reachable": listen_reachable,
            "external_running": listen_reachable and pid is None,
            "binary_path": find_rigctld_binary(cfg.binary_path or None),
            "started_at": state.get("started_at") if pid else None,
            "config": cfg.to_dict(),
        }

    def start(self) -> tuple:
        cfg = self.load_config()
        if self._tracked_pid() is not None:
            return False, "Already running (managed by this app)"
        binary = find_rigctld_binary(cfg.binary_path or None)
        if not binary:
            return False, "rigctld binary not found -- install Hamlib (e.g. 'brew install hamlib') or set a binary path override"
        if not cfg.rig_model:
            return False, "Set a rig model before starting"
        if not cfg.device:
            return False, "Set a serial device before starting"

        cmd = [binary, "-m", str(cfg.rig_model), "-r", cfg.device,
               "-t", str(cfg.listen_port), "-T", cfg.listen_host]
        if cfg.baud:
            cmd += ["-s", str(cfg.baud)]
        if cfg.extra_args.strip():
            cmd += cfg.extra_args.strip().split()

        try:
            log_f = open(self.log_path, "a")
            log_f.write(f"\n--- starting {' '.join(cmd)} ---\n")
            log_f.flush()
            proc = subprocess.Popen(
                cmd, stdout=log_f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return False, f"Failed to start rigctld: {exc}"

        time.sleep(0.5)
        if proc.poll() is not None:
            return False, f"rigctld exited immediately (code {proc.returncode}) -- check the log"

        self._save_state({"pid": proc.pid, "started_at": time.time(), "command": cmd})
        return True, f"Started (PID {proc.pid})"

    def stop(self) -> tuple:
        pid = self._tracked_pid()
        if pid is None:
            return False, "Not managed by this app -- nothing to stop (may be running externally)"
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._clear_state()
            return True, "Already stopped"
        for _ in range(30):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._clear_state()
        return True, "Stopped"

    def restart(self) -> tuple:
        if self._tracked_pid() is not None:
            ok, msg = self.stop()
            if not ok:
                return ok, msg
        return self.start()

    def log_tail(self, n: int = 60) -> str:
        if not os.path.exists(self.log_path):
            return ""
        try:
            with open(self.log_path, "r", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-n:])
        except OSError:
            return ""


# ---------------------------------------------------------------------------
# Flask wiring
# ---------------------------------------------------------------------------

radio_bp = Blueprint("radio", __name__, template_folder="templates")

_client: Optional[RigctldClient] = None
_process: Optional[RigctldProcessManager] = None


def _rebuild_client(process_cfg: RigctldProcessConfig, timeout_s: float = 2.0):
    global _client
    _client = RigctldClient(RigctldConfig(
        host=process_cfg.listen_host, port=process_cfg.listen_port, timeout_s=timeout_s,
    ))


def get_client() -> Optional[RigctldClient]:
    """Shared rigctld client for other modules to drive the rig directly
    (e.g. rigdial_bridge.py) -- mirrors live_monitor.get_monitor(). None
    until init_radio_control() has run."""
    return _client


def init_radio_control(app, config: RigctldConfig,
                        process_config_path: str = "radio_process_config.json",
                        process_state_path: str = "radio_process_state.json",
                        process_log_path: str = "rigctld.log"):
    global _process
    _process = RigctldProcessManager(process_config_path, process_state_path, process_log_path)
    if os.path.exists(process_config_path):
        # A saved process config exists -- its listen host/port is the
        # source of truth for where the client connects.
        _rebuild_client(_process.load_config(), config.timeout_s)
    else:
        # First run: seed the process config from the passed-in client
        # config so the two start out in sync.
        seed_cfg = _process.load_config()
        seed_cfg.listen_host = config.host
        seed_cfg.listen_port = config.port
        _process.save_config(seed_cfg)
        _rebuild_client(seed_cfg, config.timeout_s)
    app.register_blueprint(radio_bp)


@radio_bp.route("/radio")
def radio_view():
    return render_template("radio.html", bands=list(FT8_CALLING_FREQ_HZ.keys()))


@radio_bp.route("/radio/status")
def radio_status():
    try:
        return jsonify(_client.status())
    except RigctldConnectionError as exc:
        return jsonify({"connected": False, "error": str(exc)})
    except RigctldError as exc:
        return jsonify({"connected": True, "error": str(exc)})


@radio_bp.route("/radio/frequency", methods=["POST"])
def radio_set_frequency():
    body = request.get_json(silent=True) or {}
    try:
        hz = float(body.get("frequency_hz"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "frequency_hz is required and must be numeric"}), 400
    try:
        _client.set_freq(hz)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@radio_bp.route("/radio/mode", methods=["POST"])
def radio_set_mode():
    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "").strip()
    if not mode:
        return jsonify({"ok": False, "error": "mode is required"}), 400
    try:
        passband = int(body.get("passband") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "passband must be an integer"}), 400
    try:
        _client.set_mode(mode, passband)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@radio_bp.route("/radio/ptt", methods=["POST"])
def radio_set_ptt():
    body = request.get_json(silent=True) or {}
    on = bool(body.get("on"))
    try:
        _client.set_ptt(on)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "ptt": on})


@radio_bp.route("/radio/rit", methods=["POST"])
def radio_set_rit():
    body = request.get_json(silent=True) or {}
    try:
        hz = int(body.get("hz", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "hz must be an integer"}), 400
    try:
        _client.set_rit(hz)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@radio_bp.route("/radio/xit", methods=["POST"])
def radio_set_xit():
    body = request.get_json(silent=True) or {}
    try:
        hz = int(body.get("hz", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "hz must be an integer"}), 400
    try:
        _client.set_xit(hz)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@radio_bp.route("/radio/power", methods=["POST"])
def radio_set_power():
    body = request.get_json(silent=True) or {}
    try:
        watts = float(body.get("watts"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "watts is required and must be numeric"}), 400
    try:
        freq_hz = _client.get_freq()
        mode, _passband = _client.get_mode()
        _client.set_power_watts(watts, freq_hz, mode)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@radio_bp.route("/radio/band/<band>", methods=["POST"])
def radio_qsy_band(band):
    hz = FT8_CALLING_FREQ_HZ.get(band.upper())
    if hz is None:
        return jsonify({"ok": False, "error": f"Unknown band {band!r}"}), 400
    try:
        _client.set_freq(hz)
    except RigctldConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except RigctldError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "frequency_hz": hz})


# ---------------------------------------------------------------------------
# rigctld process management routes
# ---------------------------------------------------------------------------

@radio_bp.route("/radio/process/status")
def radio_process_status():
    return jsonify(_process.status())


@radio_bp.route("/radio/process/config", methods=["GET", "POST"])
def radio_process_config():
    if request.method == "GET":
        return jsonify(_process.load_config().to_dict())

    body = request.get_json(silent=True) or {}
    try:
        cfg = RigctldProcessConfig(
            rig_model=int(body["rig_model"]) if body.get("rig_model") not in (None, "") else None,
            device=(body.get("device") or "").strip(),
            baud=int(body["baud"]) if body.get("baud") not in (None, "") else None,
            listen_host=(body.get("listen_host") or "127.0.0.1").strip(),
            listen_port=int(body.get("listen_port") or 4532),
            extra_args=(body.get("extra_args") or "").strip(),
            binary_path=(body.get("binary_path") or "").strip(),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"bad config: {exc}"}), 400

    _process.save_config(cfg)
    _rebuild_client(cfg)
    return jsonify({"ok": True, "config": cfg.to_dict()})


@radio_bp.route("/radio/process/rig_models")
def radio_process_rig_models():
    return jsonify({"models": _process.rig_models()})


@radio_bp.route("/radio/process/serial_devices")
def radio_process_serial_devices():
    return jsonify({"devices": list_serial_devices()})


@radio_bp.route("/radio/process/start", methods=["POST"])
def radio_process_start():
    ok, message = _process.start()
    return jsonify({"ok": ok, "message": message})


@radio_bp.route("/radio/process/stop", methods=["POST"])
def radio_process_stop():
    ok, message = _process.stop()
    return jsonify({"ok": ok, "message": message})


@radio_bp.route("/radio/process/restart", methods=["POST"])
def radio_process_restart():
    ok, message = _process.restart()
    return jsonify({"ok": ok, "message": message})


@radio_bp.route("/radio/process/log")
def radio_process_log():
    return jsonify({"log": _process.log_tail()})
