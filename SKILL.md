---
name: toyota-diag
description: |
  Stateless OBD-II diagnostics for Toyota vehicles via ELM327/STN adapters. Supports
  standard (Mode 01) and Toyota enhanced (Mode 21/22) PIDs with config-driven vehicle
  profiles. Reference vehicle: 2019 RAV4 XA50.

  Use when asked to: check vehicle status/health, read DTCs, query tire pressures or
  wheel speeds, discover supported PIDs, or send raw OBD-II queries.

  Requires: python3, jq, pip:obd. Writes: ~/.config/toyota-diag/config.env.
  Network: none (serial only). Hardware: ELM327/STN OBD-II adapter.
  READ-ONLY: modes 01,02,03,07,09,21,22 only. No CAN writes.
metadata:
  openclaw:
    emoji: "🚗"
    requires:
      bins: ["python3", "jq"]
      pip: ["obd"]
    os: ["darwin", "linux"]
---

# Toyota Diag

OBD-II diagnostic CLI for Toyota vehicles. Queries real-time telemetry from engine,
transmission, ABS, and body ECUs — including Toyota-enhanced PIDs that generic OBD apps miss.

## First-Time Setup

```bash
obd2.sh setup
```

Creates `~/.config/toyota-diag/config.env`. Edit to set your serial port:

```bash
# macOS USB (OBDLink EX):      /dev/cu.usbserial-XXXX
# macOS Bluetooth (OBDLink MX): /dev/cu.OBDLinkMX-XXXX
# Linux USB:                    /dev/ttyUSB0
# Emulator (testing):           socket://localhost:35000
SERIAL_PORT="/dev/cu.usbserial-XXXX"
VEHICLE="rav4_xa50"
```

Install the Python dependency:

```bash
pip3 install obd
```

Detect connected adapters:

```bash
ls /dev/cu.usbserial-* /dev/cu.OBDLink* /dev/cu.SLAB* 2>/dev/null
```

## Helper Script

Location: `scripts/obd2.sh` (relative to this skill directory)

```bash
obd2.sh status          # Connection test + basic vitals
obd2.sh health          # Temperatures — is the car happy?
obd2.sh dtc             # Diagnostic trouble codes (stored + pending)
obd2.sh tires           # TPMS tire pressures
obd2.sh wheels          # Individual wheel speeds (ABS sensors)
obd2.sh pid <name>      # Query a specific PID by name
obd2.sh raw <cmd>       # Raw OBD hex command (e.g. 222301)
obd2.sh scan [ecu]      # Discovery scan — find supported PIDs
obd2.sh list            # List all configured PIDs + confidence levels
obd2.sh setup           # First-time configuration
obd2.sh json <cmd>      # Raw JSON output (pipe to jq)
```

## Workflow

1. **Connect adapter** to vehicle OBD-II port (under dash, driver side)
2. **Turn ignition ON** (engine running for full data)
3. **Run commands** — each query opens connection, reads, closes (stateless)
4. **Read JSON output** — structured for AI agent consumption

### Common Patterns

```bash
# Quick health check
obd2.sh health

# Check for trouble codes
obd2.sh dtc

# Query a single enhanced PID
obd2.sh pid trans_temp

# Debug: send raw Mode 22 query to transmission ECU
obd2.sh raw 222301 --header 7E1

# Discover what PIDs the transmission ECU supports
obd2.sh scan 7E1

# Get raw JSON for programmatic use
obd2.sh json group health | jq '.results[] | select(.status == "OK")'
```

## Vehicle Profiles

PID definitions live in `config/vehicles/<name>.json`. Each profile defines:

- Vehicle metadata (year, engine, transmission)
- ECU address map (CAN headers)
- PID definitions with mode, formula, unit, confidence level
- PID groups (status, health, wheels, tires)
- Scan ranges for PID discovery

### Included Profiles

| File | Vehicle | Status |
|------|---------|--------|
| `rav4_xa50.json` | 2019-2024 Toyota RAV4 (non-hybrid) | Standard PIDs verified, enhanced PIDs unverified |

### Adding Your Vehicle

See [references/adding-vehicles.md](references/adding-vehicles.md) for the full guide.

Short version:
1. Copy an existing profile, update vehicle info
2. Run `obd2.sh scan` to discover supported PIDs
3. Use `obd2.sh raw` to test formulas against known values
4. Update confidence levels as you verify PIDs

## PID Confidence Levels

Each PID in the vehicle JSON has a confidence rating:

| Level | Meaning |
|-------|---------|
| **standard** | SAE J1979 universal PID — works on every OBD-II car |
| **verified** | Tested and confirmed on the specific vehicle |
| **unverified** | From community databases (Torque Pro, forums) — formula may be wrong |
| **speculative** | CAN address, mode, and formula all unconfirmed — needs discovery |

The `list` command shows confidence for all configured PIDs.

## Security & Safety

- **Read-only by design** — engine.py validates mode before ANY command is sent
- **Allowed modes:** 01, 02, 03, 07, 09, 21, 22 (all read-only diagnostic services)
- **Blocked modes:** 04 (clear DTCs), 08 (actuator control), 10+ (diagnostic sessions)
- **No CAN frame injection** — only standard OBD-II request/response protocol
- **No persistent connections** — each query opens and closes the serial port
- **10-second timeout** per query to prevent bus hangs

## Adapter Recommendations

| Adapter | Toyota Enhanced | macOS | Notes |
|---------|----------------|-------|-------|
| **OBDLink EX** (USB) | ✅ | ✅ FTDI serial | STN chip, recommended |
| **OBDLink MX+** (BT) | ✅ | ✅ BT serial | STN chip, wireless |
| Generic ELM327 USB | ⚠️ Standard only | ✅ | Clone quality varies |
| BLE adapters (FIXD) | ❌ | ❌ No serial | Proprietary app only |

STN-based adapters (OBDLink) handle Toyota enhanced protocols more reliably than ELM327 clones.

## Reference

- [ELM327 AT Commands](references/elm327-commands.md) — adapter command reference
- [Adding Vehicles](references/adding-vehicles.md) — PID discovery and validation guide
