#!/usr/bin/env bash
# toyota-diag — OBD-II diagnostic CLI for Toyota vehicles
# Pattern: idrac.sh (stateless query, JSON output, jq formatting)
#
# Safety: READ-ONLY. No CAN bus writes. No DTC clearing.
# Modes allowed: 01, 02, 03, 07, 09, 21, 22

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ENGINE="$SCRIPT_DIR/engine.py"
CONFIG_DIR="$SKILL_DIR/config"
USER_CONFIG_DIR="$HOME/.config/toyota-diag"
USER_CONFIG="$USER_CONFIG_DIR/config.env"

# ── Dependency check ──────────────────────────────────────────────────
check_deps() {
  local missing=()
  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  command -v jq      >/dev/null 2>&1 || missing+=("jq")

  if [ ${#missing[@]} -gt 0 ]; then
    echo "Error: Missing dependencies: ${missing[*]}" >&2
    echo "Install with: brew install ${missing[*]}" >&2
    exit 1
  fi

  # Check python-obd (only for commands that need it)
  if [[ "${1:-}" != "list" && "${1:-}" != "help" && "${1:-}" != "setup" ]]; then
    if ! python3 -c "import obd" 2>/dev/null; then
      echo "Error: python-obd not installed" >&2
      echo "Install with: pip3 install obd" >&2
      exit 1
    fi
  fi
}

# ── Setup ─────────────────────────────────────────────────────────────
cmd_setup() {
  echo "Toyota Diag — First-Time Setup"
  echo ""

  if [ -f "$USER_CONFIG" ]; then
    echo "Config already exists at: $USER_CONFIG"
    echo "Edit it manually or delete to re-run setup."
    return
  fi

  mkdir -p "$USER_CONFIG_DIR"
  cp "$CONFIG_DIR/config.env" "$USER_CONFIG"
  echo "✅ Config created at: $USER_CONFIG"
  echo ""
  echo "Edit the config to set your serial port:"
  echo "  \$EDITOR $USER_CONFIG"
  echo ""
  echo "Common port patterns:"
  echo "  macOS USB (FTDI/OBDLink EX):  /dev/cu.usbserial-XXXX"
  echo "  macOS Bluetooth (OBDLink MX):  /dev/cu.OBDLinkMX-XXXX"
  echo "  Linux USB:                     /dev/ttyUSB0"
  echo "  Emulator (testing):            socket://localhost:35000"
  echo ""
  echo "Detect connected serial ports:"
  echo "  ls /dev/cu.usbserial-* /dev/cu.OBDLink* /dev/cu.SLAB* 2>/dev/null"
}

# ── Formatting helpers ────────────────────────────────────────────────
format_status() {
  local json="$1"
  local connected
  connected=$(echo "$json" | jq -r '.connected')

  if [ "$connected" = "true" ]; then
    echo "=== Vehicle Status ==="
    echo "$json" | jq -r '
      "Connection: ✅ Connected",
      "Port:       \(.port)",
      "Protocol:   \(.protocol)",
      "Vehicle:    \(.vehicle)\(if .alias != "" then " (\(.alias))" else "" end)",
      ""
    '
    if echo "$json" | jq -e '.vitals' >/dev/null 2>&1; then
      echo "--- Vitals ---"
      echo "$json" | jq -r '.vitals[] |
        if .status == "OK" then
          "  \(.name): \(.value) \(.unit)"
        else
          "  \(.name): ⚠️  \(.status)"
        end'
    fi
  else
    echo "=== Connection Failed ==="
    echo "$json" | jq -r '"Status: \(.status)", "Port: \(.port)"'
  fi
}

format_group() {
  local json="$1"
  local name
  name=$(echo "$json" | jq -r '.name')
  echo "=== $name ==="
  echo "$json" | jq -r '
    "Vehicle: \(.vehicle)\(if .alias != "" then " (\(.alias))" else "" end)",
    ""
  '
  echo "$json" | jq -r '.results[] |
    if .status == "OK" then
      "  \(.name): \(.value) \(.unit)\(if .confidence != "standard" then " [\(.confidence)]" else "" end)"
    else
      "  \(.name): ⚠️  \(.status)\(if .confidence == "speculative" then " [speculative — needs validation]" else "" end)"
    end'
}

format_dtc() {
  local json="$1"
  local status
  status=$(echo "$json" | jq -r '.status')

  echo "=== Diagnostic Trouble Codes ==="
  if [ "$status" = "ALL_CLEAR" ]; then
    echo "✅ No trouble codes found"
  else
    local stored pending
    stored=$(echo "$json" | jq '.stored | length')
    pending=$(echo "$json" | jq '.pending | length')

    if [ "$stored" -gt 0 ]; then
      echo "Stored DTCs ($stored):"
      echo "$json" | jq -r '.stored[] | "  ⚠️  \(.code): \(.description)"'
    fi
    if [ "$pending" -gt 0 ]; then
      echo "Pending DTCs ($pending):"
      echo "$json" | jq -r '.pending[] | "  🔶 \(.code): \(.description)"'
    fi
  fi
}

format_list() {
  local json="$1"
  echo "=== Configured PIDs ==="
  echo "$json" | jq -r '
    "Vehicle: \(.vehicle)",
    "Total: \(.pid_count) | Standard: \(.standard) | Unverified: \(.unverified) | Speculative: \(.speculative)",
    ""
  '
  echo "$json" | jq -r '.pids[] |
    "  [\(.confidence | if . == "standard" then "✅" elif . == "unverified" then "❓" else "⚠️ " end)] \(.pid) — \(.name)  (Mode \(.mode), Header \(.header))"'
}

format_scan() {
  local json="$1"
  local found
  found=$(echo "$json" | jq '.pids_found')
  echo "=== Discovery Scan Results ==="
  echo "$json" | jq -r '"ECUs scanned: \(.ecus_scanned | join(", "))", "PIDs found: \(.pids_found)", ""'
  if [ "$found" -gt 0 ]; then
    echo "$json" | jq -r '.results[] | "  \(.header) Mode \(.mode) PID \(.pid): \(.raw_response)"'
  fi
}

# ── Main dispatch ─────────────────────────────────────────────────────
case "${1:-help}" in
  status)
    check_deps status
    result=$(python3 "$ENGINE" status)
    format_status "$result"
    ;;

  health)
    check_deps health
    result=$(python3 "$ENGINE" group health)
    format_group "$result"
    ;;

  dtc)
    check_deps dtc
    result=$(python3 "$ENGINE" dtc)
    format_dtc "$result"
    ;;

  tires)
    check_deps tires
    result=$(python3 "$ENGINE" group tires)
    format_group "$result"
    ;;

  wheels)
    check_deps wheels
    result=$(python3 "$ENGINE" group wheels)
    format_group "$result"
    ;;

  pid)
    check_deps pid
    [ -z "${2:-}" ] && echo "Usage: $0 pid <pid_name>" >&2 && exit 1
    result=$(python3 "$ENGINE" pid "$2")
    echo "$result" | jq -r '
      if .status == "OK" then
        "\(.name): \(.value) \(.unit)"
      else
        "\(.name): ⚠️  \(.status)"
      end'
    ;;

  raw)
    check_deps raw
    [ -z "${2:-}" ] && echo "Usage: $0 raw <hex_command> [--header 7E0]" >&2 && exit 1
    header="${4:-7E0}"
    if [ "${3:-}" = "--header" ]; then
      header="$4"
    fi
    result=$(python3 "$ENGINE" raw "$2" --header "$header")
    echo "$result" | jq '.'
    ;;

  scan)
    check_deps scan
    ecu_arg=""
    if [ -n "${2:-}" ]; then
      ecu_arg="--ecu $2"
    fi
    result=$(python3 "$ENGINE" scan $ecu_arg)
    format_scan "$result"
    ;;

  list)
    check_deps list
    result=$(python3 "$ENGINE" list)
    format_list "$result"
    ;;

  setup)
    cmd_setup
    ;;

  json)
    # Pass-through: any subcommand with raw JSON output
    check_deps "${2:-help}"
    shift
    python3 "$ENGINE" "$@"
    ;;

  help|*)
    cat <<EOF
Toyota Diag — OBD-II Diagnostic CLI for Toyota Vehicles

Usage: $(basename "$0") <command> [args]

Commands:
  status          Connection test + basic vitals (RPM, speed, coolant)
  health          Temperature check (trans, oil, coolant, ambient)
  dtc             Read diagnostic trouble codes
  tires           TPMS tire pressures
  wheels          Individual wheel speeds
  pid <name>      Query a specific PID by name
  raw <cmd>       Send raw OBD hex command (e.g. 010C, 222301)
  scan [ecu]      Discovery scan for supported PIDs
  list            List all configured PIDs and confidence levels
  setup           First-time configuration
  json <cmd>      Raw JSON output (pass-through to engine.py)
  help            Show this help

Examples:
  $(basename "$0") status                  # Basic connection + vitals
  $(basename "$0") health                  # Is Raven happy?
  $(basename "$0") pid trans_temp          # Single PID query
  $(basename "$0") raw 222301 --header 7E1 # Raw enhanced query
  $(basename "$0") scan 7E1               # Scan transmission ECU
  $(basename "$0") json group health       # Health group as raw JSON

Config: ${USER_CONFIG}
Vehicle: ${CONFIG_DIR}/vehicles/
Safety: READ-ONLY (modes 01,02,03,07,09,21,22 only)

First run? Start with: $(basename "$0") setup
EOF
    ;;
esac
