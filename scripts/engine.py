#!/usr/bin/env python3
"""
toyota-diag engine — Stateless OBD-II query bridge for Toyota vehicles.

Reads vehicle PID definitions from JSON config, queries via python-obd,
returns structured JSON to stdout. Designed to be called by obd2.sh.

Safety: READ-ONLY. Only modes 01,02,03,07,09,21,22 are allowed.
"""

import argparse
import ast
import json
import operator
import os
import sys
import time
from pathlib import Path

try:
    import obd
    from obd import OBDCommand, OBDStatus
    from obd.protocols import ECU
except ImportError:
    print(json.dumps({
        "error": "python-obd not installed",
        "fix": "pip3 install obd"
    }), file=sys.stdout)
    sys.exit(1)

# ── Safety: read-only mode whitelist ──────────────────────────────────
ALLOWED_MODES = {"01", "02", "03", "07", "09", "21", "22"}

# ── Safe formula evaluator (no eval) ─────────────────────────────────
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval_formula(formula: str, variables: dict) -> float:
    """Evaluate a simple arithmetic formula with named variables.

    Only supports: +, -, *, /, //, %, **, unary -, parentheses,
    numeric literals, and single-letter variable names (A-D).
    No function calls, attribute access, or anything else.
    """
    tree = ast.parse(formula, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        elif isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](_eval(node.operand))
        else:
            raise ValueError(f"Unsupported formula node: {ast.dump(node)}")

    return _eval(tree)


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_DIR = SKILL_DIR / "config"
VEHICLES_DIR = CONFIG_DIR / "vehicles"
USER_CONFIG = Path.home() / ".config" / "toyota-diag" / "config.env"


def err(msg: str, code: int = 1):
    """Print error JSON to stdout and exit."""
    print(json.dumps({"error": msg}))
    sys.exit(code)


def load_config() -> dict:
    """Load config.env from user dir or skill default."""
    config = {
        "SERIAL_PORT": "auto",
        "BAUD_RATE": "",
        "VEHICLE": "rav4_xa50",
        "TIMEOUT": "10",
        "OUTPUT": "json",
    }
    config_path = USER_CONFIG if USER_CONFIG.exists() else CONFIG_DIR / "config.env"
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                val = val.strip().strip('"').strip("'")
                config[key.strip()] = val
    return config


def load_vehicle(name: str) -> dict:
    """Load vehicle PID definition JSON."""
    path = VEHICLES_DIR / f"{name}.json"
    if not path.exists():
        err(f"Vehicle profile not found: {path}")
    return json.loads(path.read_text())


def validate_mode(mode: str):
    """Safety gate — block write modes."""
    mode_clean = mode.upper().lstrip("0") or "0"
    mode_padded = mode.upper().zfill(2)
    if mode_padded not in ALLOWED_MODES:
        err(f"BLOCKED: Mode {mode_padded} is not in read-only whitelist {sorted(ALLOWED_MODES)}")


def build_formula_decoder(pid_def: dict):
    """Build a decoder function from a formula string like '(A * 256 + B) / 4'."""
    formula = pid_def.get("formula", "")
    unit = pid_def.get("unit", "")

    if not formula or formula == "UNKNOWN":
        # Return raw hex for unknown formulas
        def raw_decoder(messages):
            d = messages[0].data
            return d.hex()
        return raw_decoder

    def formula_decoder(messages):
        d = messages[0].data
        # Skip mode echo + PID echo bytes
        # Mode 01 response: 41 PID [A [B [C [D]]]]
        # Mode 22 response: 62 PID_HI PID_LO [A [B [C [D]]]]
        mode_byte = d[0] if len(d) > 0 else 0
        if mode_byte == 0x62:  # Mode 22 response
            payload = d[3:]  # skip 62 + 2-byte PID
        elif mode_byte == 0x61:  # Mode 21 response
            payload = d[3:]  # skip 61 + 2-byte PID
        elif mode_byte >= 0x41 and mode_byte <= 0x49:  # Mode 01-09 response
            payload = d[2:]  # skip mode echo + 1-byte PID
        else:
            payload = d[2:]  # fallback: skip 2

        # Map A, B, C, D to payload bytes (0 if not enough bytes)
        A = payload[0] if len(payload) > 0 else 0
        B = payload[1] if len(payload) > 1 else 0
        C = payload[2] if len(payload) > 2 else 0
        D = payload[3] if len(payload) > 3 else 0

        try:
            result = safe_eval_formula(formula, {
                "A": A, "B": B, "C": C, "D": D
            })
            return round(result, 2) if isinstance(result, float) else result
        except Exception as e:
            return f"FORMULA_ERROR: {e}"

    return formula_decoder


def build_obd_command(pid_name: str, pid_def: dict) -> OBDCommand:
    """Build an OBDCommand from a vehicle JSON PID definition."""
    mode = pid_def["mode"]
    pid = pid_def["pid"]
    header = pid_def.get("header", "7E0")
    expected_bytes = pid_def.get("bytes", 0)
    decoder = build_formula_decoder(pid_def)

    # Command bytes: mode + pid as hex string → bytes
    cmd_hex = f"{mode}{pid}"
    cmd_bytes = bytes.fromhex(cmd_hex) if len(cmd_hex) % 2 == 0 else cmd_hex.encode()

    return OBDCommand(
        pid_name.upper(),
        pid_def.get("name", pid_name),
        cmd_bytes,
        expected_bytes,
        decoder,
        ECU.ALL,
        False,
        header,
    )


def connect(config: dict) -> obd.OBD:
    """Establish OBD connection."""
    port = config["SERIAL_PORT"]
    baud = config["BAUD_RATE"]
    timeout = int(config.get("TIMEOUT", 10))

    kwargs = {}
    if port and port != "auto":
        kwargs["portstr"] = port
    if baud:
        kwargs["baudrate"] = int(baud)
    kwargs["timeout"] = timeout

    # Suppress python-obd's internal logging to keep stdout clean
    obd.logger.setLevel(obd.logging.CRITICAL)

    conn = obd.OBD(**kwargs)
    if conn.status() == OBDStatus.NOT_CONNECTED:
        err("Connection failed: adapter not found or not responding")
    return conn


def query_pid(conn: obd.OBD, pid_name: str, pid_def: dict) -> dict:
    """Query a single PID and return structured result."""
    mode = pid_def["mode"]
    validate_mode(mode)

    cmd = build_obd_command(pid_name, pid_def)
    start = time.time()
    response = conn.query(cmd, force=True)
    elapsed_ms = round((time.time() - start) * 1000)

    result = {
        "pid": pid_name,
        "name": pid_def.get("name", pid_name),
        "mode": mode,
        "command": f"{mode}{pid_def['pid']}",
        "header": pid_def.get("header", "7E0"),
        "response_time_ms": elapsed_ms,
        "confidence": pid_def.get("confidence", "unknown"),
    }

    if response.is_null():
        result["value"] = None
        result["status"] = "NO_DATA"
        result["raw"] = None
    else:
        val = response.value
        # Handle Pint quantities (from python-obd standard commands)
        if hasattr(val, "magnitude"):
            result["value"] = round(val.magnitude, 2) if isinstance(val.magnitude, float) else val.magnitude
            result["unit"] = str(val.units) if hasattr(val, "units") else pid_def.get("unit", "")
        else:
            result["value"] = val
            result["unit"] = pid_def.get("unit", "")
        result["status"] = "OK"

    return result


def query_group(conn: obd.OBD, vehicle: dict, group_name: str) -> dict:
    """Query all PIDs belonging to a group."""
    results = []
    pids = vehicle.get("pids", {})

    for pid_name, pid_def in pids.items():
        groups = pid_def.get("group", [])
        if group_name in groups:
            results.append(query_pid(conn, pid_name, pid_def))

    group_info = vehicle.get("groups", {}).get(group_name, {})
    return {
        "group": group_name,
        "name": group_info.get("name", group_name),
        "description": group_info.get("description", ""),
        "vehicle": vehicle["vehicle"]["name"],
        "alias": vehicle["vehicle"].get("alias", ""),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": results,
    }


def query_dtc(conn: obd.OBD) -> dict:
    """Query diagnostic trouble codes (Mode 03 stored + Mode 07 pending)."""
    results = {"stored": [], "pending": [], "status": "OK"}

    # Stored DTCs (Mode 03)
    try:
        stored = conn.query(obd.commands.GET_DTC, force=True)
        if not stored.is_null() and stored.value:
            results["stored"] = [{"code": c, "description": d} for c, d in stored.value]
    except Exception as e:
        results["stored_error"] = str(e)

    # Pending DTCs (Mode 07)
    try:
        pending = conn.query(obd.commands.GET_FREEZE_DTC, force=True)
        if not pending.is_null() and pending.value:
            results["pending"] = [{"code": c, "description": d} for c, d in pending.value]
    except Exception as e:
        results["pending_error"] = str(e)

    if not results["stored"] and not results["pending"]:
        results["status"] = "ALL_CLEAR"

    results["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return results


def cmd_status(conn: obd.OBD, vehicle: dict) -> dict:
    """Connection test + adapter info."""
    info = {
        "connected": conn.status() != OBDStatus.NOT_CONNECTED,
        "status": str(conn.status()),
        "port": str(conn.port_name()),
        "protocol": str(conn.protocol_name()) if hasattr(conn, "protocol_name") else "unknown",
        "vehicle": vehicle["vehicle"]["name"],
        "alias": vehicle["vehicle"].get("alias", ""),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    # If connected to car (not just adapter), grab basic vitals
    if conn.status() == OBDStatus.CAR_CONNECTED:
        vitals = query_group(conn, vehicle, "status")
        info["vitals"] = vitals["results"]

    return info


def cmd_scan(conn: obd.OBD, vehicle: dict, ecu_header: str = None) -> dict:
    """Discovery scan — iterate PID ranges and report which respond."""
    scan_ranges = vehicle.get("scan_ranges", {})
    results = []

    targets = {}
    if ecu_header:
        if ecu_header in scan_ranges:
            targets[ecu_header] = scan_ranges[ecu_header]
        else:
            err(f"ECU header {ecu_header} not in scan_ranges. Available: {list(scan_ranges.keys())}")
    else:
        targets = scan_ranges

    for header, range_def in targets.items():
        modes = range_def.get("modes", ["01"])
        pid_lo = int(range_def.get("pid_range", ["0100", "01FF"])[0], 16)
        pid_hi = int(range_def.get("pid_range", ["0100", "01FF"])[1], 16)

        print(f"Scanning ECU {header} (PIDs {pid_lo:#06x}-{pid_hi:#06x})...", file=sys.stderr)

        for mode in modes:
            validate_mode(mode)
            for pid_int in range(pid_lo, pid_hi + 1, 16):
                # Scan in steps of 16 to avoid overwhelming the bus
                pid_hex = f"{pid_int:04X}"
                cmd_hex = f"{mode}{pid_hex}"

                try:
                    cmd = OBDCommand(
                        f"SCAN_{header}_{cmd_hex}",
                        f"Scan {header} {cmd_hex}",
                        bytes.fromhex(cmd_hex),
                        0,
                        lambda msgs: msgs[0].data.hex() if msgs else None,
                        ECU.ALL,
                        False,
                        header,
                    )
                    resp = conn.query(cmd, force=True)
                    if not resp.is_null():
                        results.append({
                            "header": header,
                            "mode": mode,
                            "pid": pid_hex,
                            "command": cmd_hex,
                            "raw_response": resp.value,
                        })
                        print(f"  ✓ {header} {mode} {pid_hex}: {resp.value}", file=sys.stderr)
                except Exception:
                    pass  # Skip errors during scan

    return {
        "scan": "discovery",
        "ecus_scanned": list(targets.keys()),
        "pids_found": len(results),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": results,
    }


def cmd_list_pids(vehicle: dict) -> dict:
    """List all configured PIDs (no connection needed)."""
    pids = vehicle.get("pids", {})
    listing = []
    for name, defn in pids.items():
        listing.append({
            "pid": name,
            "name": defn.get("name", name),
            "mode": defn["mode"],
            "command": f"{defn['mode']}{defn['pid']}",
            "header": defn.get("header", "7E0"),
            "unit": defn.get("unit", ""),
            "confidence": defn.get("confidence", "unknown"),
        })
    return {
        "vehicle": vehicle["vehicle"]["name"],
        "pid_count": len(listing),
        "standard": len([p for p in listing if p["confidence"] == "standard"]),
        "unverified": len([p for p in listing if p["confidence"] == "unverified"]),
        "speculative": len([p for p in listing if p["confidence"] == "speculative"]),
        "pids": listing,
    }


def cmd_raw(conn: obd.OBD, raw_cmd: str, header: str = "7E0") -> dict:
    """Send a raw OBD command string."""
    # Extract mode from command for safety check
    mode = raw_cmd[:2]
    validate_mode(mode)

    cmd = OBDCommand(
        "RAW",
        f"Raw command {raw_cmd}",
        bytes.fromhex(raw_cmd),
        0,
        lambda msgs: msgs[0].data.hex() if msgs else None,
        ECU.ALL,
        False,
        header,
    )
    start = time.time()
    resp = conn.query(cmd, force=True)
    elapsed_ms = round((time.time() - start) * 1000)

    return {
        "command": raw_cmd,
        "header": header,
        "response_time_ms": elapsed_ms,
        "raw_response": resp.value if not resp.is_null() else None,
        "status": "OK" if not resp.is_null() else "NO_DATA",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


# ── CLI ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Toyota OBD-II diagnostic engine (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Connection test + basic vitals")

    # group query
    p_group = sub.add_parser("group", help="Query a PID group")
    p_group.add_argument("name", help="Group name (status, health, wheels, tires)")

    # single PID
    p_pid = sub.add_parser("pid", help="Query a specific PID by name")
    p_pid.add_argument("name", help="PID name from vehicle config")

    # DTC
    sub.add_parser("dtc", help="Read diagnostic trouble codes")

    # raw
    p_raw = sub.add_parser("raw", help="Send raw OBD command")
    p_raw.add_argument("cmd", help="Hex command string (e.g. 010C, 222301)")
    p_raw.add_argument("--header", default="7E0", help="CAN header (default: 7E0)")

    # scan
    p_scan = sub.add_parser("scan", help="Discovery scan for supported PIDs")
    p_scan.add_argument("--ecu", default=None, help="Limit scan to specific ECU header")

    # list (no connection needed)
    sub.add_parser("list", help="List configured PIDs")

    args = parser.parse_args()
    config = load_config()
    vehicle = load_vehicle(config["VEHICLE"])

    # Commands that don't need a connection
    if args.command == "list":
        print(json.dumps(cmd_list_pids(vehicle), indent=2))
        return

    # Commands that need a connection
    conn = connect(config)
    try:
        if args.command == "status":
            print(json.dumps(cmd_status(conn, vehicle), indent=2))
        elif args.command == "group":
            print(json.dumps(query_group(conn, vehicle, args.name), indent=2))
        elif args.command == "pid":
            pids = vehicle.get("pids", {})
            if args.name not in pids:
                err(f"PID '{args.name}' not found. Available: {list(pids.keys())}")
            print(json.dumps(query_pid(conn, args.name, pids[args.name]), indent=2))
        elif args.command == "dtc":
            print(json.dumps(query_dtc(conn), indent=2))
        elif args.command == "raw":
            print(json.dumps(cmd_raw(conn, args.cmd, args.header), indent=2))
        elif args.command == "scan":
            print(json.dumps(cmd_scan(conn, vehicle, args.ecu), indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
