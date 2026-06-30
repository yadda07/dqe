"""
DQE Chargeur - Telemetry Module
================================

Non-blocking telemetry sender for DQE Chargeur plugin.
Collects system info and sends operation telemetry to a Google Apps Script endpoint.

Design:
  - Daemon thread, fire-and-forget (never blocks UI).
  - Silent failure: logs WARNING on error, never raises.
  - Endpoint URL read from config.json key "telemetry_endpoint".
  - Timeout 10s on HTTP POST.
  - No PII beyond username/hostname/IP (conscious decision, documented).
"""

import json
import os
import platform
import socket
import ssl
import threading
import time
import urllib.request

from .dqe_utils import _logger

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")
_METADATA_PATH = os.path.join(_PLUGIN_DIR, "metadata.txt")
_TRACE_PATH = os.path.join(_PLUGIN_DIR, "dqe_telemetry.log")
_TIMEOUT_SECONDS = 10


def _trace(message):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{ts} {message}\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        pass


def _read_endpoint_url():
    """Read telemetry endpoint URL from config.json.

    Returns
    -------
    str or None
        The endpoint URL, or None if not configured / error.
    """
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
        url = cfg.get("telemetry_endpoint", "")
        _trace(f"endpoint_read configured={bool(url)} url={url[:80]}")
        if url and url.startswith("https://"):
            return url
    except (IOError, json.JSONDecodeError, KeyError) as exc:
        _trace(f"endpoint_read_failed type={type(exc).__name__} msg={exc}")
    return None


def _read_plugin_version():
    """Read plugin version from metadata.txt."""
    try:
        with open(_METADATA_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip().lower().startswith("version="):
                    return line.split("=", 1)[1].strip()
    except IOError:
        pass
    return "unknown"


def _collect_system_info():
    """Collect system and environment information.

    Returns
    -------
    dict
        Keys: host, user, ip, os, arch, python, qgis, plugin_ver.
    """
    info = {
        "host": platform.node() or "unknown",
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        "ip": _get_local_ip(),
        "os": platform.platform() or "unknown",
        "arch": platform.machine() or "unknown",
        "python": platform.python_version() or "unknown",
        "qgis": _get_qgis_version(),
        "plugin_ver": _read_plugin_version(),
    }
    return info


def _get_local_ip():
    """Get local IP address. Returns 'unknown' on failure."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except (socket.error, OSError):
        return "unknown"


def _get_qgis_version():
    """Get QGIS version string. Returns 'unknown' if not available."""
    try:
        from qgis.core import Qgis
        return Qgis.version()
    except (ImportError, AttributeError):
        return "unknown"


def _send_post(url, payload_json):
    """Send JSON POST to endpoint. Raises on failure.

    Parameters
    ----------
    url : str
        Target endpoint URL.
    payload_json : str
        JSON-serialized payload string.
    """
    data = payload_json.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),
    )
    resp = opener.open(req, timeout=_TIMEOUT_SECONDS)
    body = resp.read().decode("utf-8", errors="replace")
    _trace(f"http_done status={resp.status} final_url={getattr(resp, 'url', '')} body={body[:200]}")
    if _logger:
        _logger.debug(
            f"telemetry: HTTP status={resp.status} body={body[:200]}"
        )
    resp.close()


def _send_async(payload):
    """Thread target: serialize, send POST, log result.

    Swallows all exceptions to guarantee non-blocking behaviour.
    """
    _trace(f"send_async_start action={payload.get('action')} mode={payload.get('mode')} sro={payload.get('sro')} verdict={payload.get('verdict')}")
    url = _read_endpoint_url()
    if not url:
        _trace("send_async_skip reason=no_endpoint")
        if _logger:
            _logger.debug("telemetry: no endpoint configured, skipping")
        return

    try:
        payload_json = json.dumps(payload, default=str)
        _trace(f"send_async_post bytes={len(payload_json)}")
        t0 = time.monotonic()
        _send_post(url, payload_json)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _trace(f"send_async_success elapsed_ms={elapsed_ms}")
        if _logger:
            _logger.debug(
                f"telemetry: sent action={payload.get('action')} "
                f"mode={payload.get('mode')} sro={payload.get('sro')} "
                f"elapsed_ms={elapsed_ms}"
            )
    except Exception as exc:
        _trace(f"send_async_failed type={type(exc).__name__} msg={exc}")
        if _logger:
            _logger.warning(f"telemetry: send failed type={type(exc).__name__} msg={exc}")


def send_telemetry(action, mode, sro, **kwargs):
    """Send a telemetry event (non-blocking).

    Parameters
    ----------
    action : str
        "execution" or "validation".
    mode : str
        "PRO", "EXE", or "PGC".
    sro : str
        SRO code.
    **kwargs
        Additional payload fields:
        - troncon : str (PGC only)
        - type : str ("T" or "D", PRO/EXE only)
        - blocage : str ("E", "T", "B", EXE only)
        - mode_code : str ("TE", "DT", etc., EXE only)
        - projet_code : str ("TP", "DP", "TE", "GC", etc.)
        - verdict : str ("success", "failure", "cancelled")
        - n_results : int
        - n_layers : int
        - n_dqe_data : int
        - n_layers_saved : int
        - elapsed_ms : int
        - error_msg : str
        - cancelled : bool
        - redevance_mode : str ("gestionnaire" or "direct", PGC only)
        - excel_generated : bool
        - logs : str
    """
    _trace(f"send_telemetry_called action={action} mode={mode} sro={sro} kwargs={sorted(kwargs.keys())}")
    now = time.strftime("%Y-%m-%d %H:%M:%S").split(" ")
    sys_info = _collect_system_info()

    payload = {
        "ts_date": now[0],
        "ts_time": now[1],
        "host": sys_info["host"],
        "user": sys_info["user"],
        "ip": sys_info["ip"],
        "os": sys_info["os"],
        "arch": sys_info["arch"],
        "python": sys_info["python"],
        "qgis": sys_info["qgis"],
        "plugin_ver": sys_info["plugin_ver"],
        "action": action,
        "mode": mode,
        "sro": sro,
    }

    optional_keys = [
        "troncon", "type", "blocage", "mode_code", "projet_code",
        "verdict", "n_results", "n_layers", "n_dqe_data", "n_layers_saved",
        "elapsed_ms", "error_msg", "cancelled", "redevance_mode",
        "excel_generated", "logs",
    ]
    for key in optional_keys:
        if key in kwargs and kwargs[key] is not None:
            payload[key] = kwargs[key]

    thread = threading.Thread(target=_send_async, args=(payload,), daemon=True)
    thread.start()
    _trace(f"send_telemetry_thread_started action={action} mode={mode} sro={sro} thread={thread.name}")
