# toyota-diag

Stateless OBD-II diagnostic CLI for **Toyota** vehicles (standard + Toyota-enhanced PIDs) built as an OpenClaw / ClawHub skill.

Reference vehicle: **2019 Toyota RAV4 XA50** ("Raven").

This repo is intentionally **read-only** and **stateless**:

- Open connection → query PID → parse → close → emit JSON
- No background logging daemon
- No CAN injection
- No DTC clearing
- No actuator tests

---

## Why this exists

Generic OBD-II (Mode 01) is table stakes. The useful Toyota stuff (trans temp, wheel speeds, TPMS, etc.) often lives in **manufacturer-enhanced services** (Mode **21/22**) and/or non-engine ECUs.

`toyota-diag` is designed to:

- Keep the user in control (terminal + JSON)
- Avoid proprietary apps (no FIXD / Carista lock-in)
- Be extensible via **vehicle profile JSON**, not code changes

---

## Features

- **`obd2.sh status`** — connection test + basic vitals (RPM, speed, coolant, throttle)
- **`obd2.sh health`** — temperature/voltage check (includes enhanced candidates like trans temp)
- **`obd2.sh dtc`** — read stored + pending diagnostic trouble codes
- **`obd2.sh wheels`** — individual wheel speeds (ABS ECU)
- **`obd2.sh tires`** — TPMS tire pressures (currently speculative until validated)
- **`obd2.sh scan`** — discovery scan to find what your Toyota actually supports
- **`obd2.sh raw`** — send raw OBD hex commands for debugging

Output is structured JSON (and can be formatted to human-readable text via the Bash wrapper).

---

## Safety model (read-only)

The Python engine **blocks all write-like services**.

Allowed OBD service modes:

- `01` (current data)
- `02` (freeze frame)
- `03` (stored DTCs)
- `07` (pending DTCs)
- `09` (vehicle information)
- `21` / `22` (Toyota enhanced reads)

Explicitly blocked:

- `04` (clear DTCs)
- `08` (actuator control)
- `10+` (UDS diagnostic sessions / potentially stateful behavior)

Formulas for PID conversions are evaluated with a **safe AST evaluator** (no `eval()`), supporting only arithmetic and variables `A-D`.

---

## Hardware

### Recommended

- **OBDLink EX (USB)** — STN chipset, reliable Toyota enhanced support, shows up on macOS as `/dev/cu.usbserial-*`

### Also works (with limitations)

- Generic ELM327 USB: standard PIDs are usually fine; enhanced Toyota reads may fail depending on clone quality

### Not supported

- BLE-only dongles like **FIXD** (no serial port exposure on macOS; proprietary app ecosystem)

---

## Installation (standalone CLI)

Clone the repo:

```bash
git clone https://github.com/eddygk/toyota-diag
cd toyota-diag
```

Install dependencies:

- `python3`
- `jq` (macOS: `brew install jq`)
- python package:

```bash
pip3 install obd
```

Create config:

```bash
./scripts/obd2.sh setup
# then edit:
$EDITOR ~/.config/toyota-diag/config.env
```

Detect adapters (macOS):

```bash
ls /dev/cu.usbserial-* /dev/cu.OBDLink* /dev/cu.SLAB* 2>/dev/null
```

---

## Usage

### Human-friendly commands

```bash
./scripts/obd2.sh status
./scripts/obd2.sh health
./scripts/obd2.sh dtc
./scripts/obd2.sh wheels
./scripts/obd2.sh tires
```

### Query a single PID by name

```bash
./scripts/obd2.sh pid trans_temp
```

### Raw enhanced query (example)

```bash
# Mode 22 PID 2301 to transmission ECU
./scripts/obd2.sh raw 222301 --header 7E1
```

### Pure JSON output (for agents, scripts, pipes)

```bash
./scripts/obd2.sh json group health | jq '.results[] | select(.status == "OK")'
```

---

## Vehicle profiles (the key idea)

Vehicle profiles live in:

- `config/vehicles/<name>.json`

They define:

- ECU headers (engine/trans/ABS/body)
- Standard PIDs (SAE J1979)
- Enhanced Toyota PIDs (Mode 21/22)
- Conversion formulas, units, min/max
- Confidence level: `standard` | `verified` | `unverified` | `speculative`

### Included profile

- `rav4_xa50.json`
  - ✅ Standard PIDs are solid
  - ❓ Enhanced PIDs are **candidates** until validated on Raven
  - ⚠️ TPMS is **speculative** (addressing differs across Toyota models)

---

## Discovery mode (how you make this real)

Toyota enhanced PIDs are not universal across models/years/trims. The scanner helps you find what your ECU actually answers.

```bash
# Scan all configured ECUs
./scripts/obd2.sh scan

# Scan a specific ECU header (e.g., transmission)
./scripts/obd2.sh scan 7E1
```

Then use `raw` to validate formulas against real-world expected values.

For a step-by-step guide, see:

- `references/adding-vehicles.md`

---

## Testing without a car (emulator)

You can develop the CLI without hardware using **ELM327-emulator**:

```bash
pip3 install ELM327-emulator
elm -s car -n 35000
```

Then set in `~/.config/toyota-diag/config.env`:

```bash
SERIAL_PORT="socket://localhost:35000"
```

Note: emulator scenarios vary; standard Mode 01 commands should work. Enhanced Toyota PIDs will depend on scenario/dictionary.

---

## OpenClaw / ClawHub notes

This repo is structured as an OpenClaw skill directory (`SKILL.md`, `scripts/`, `references/`, etc.).

For local packaging (OpenClaw dev env):

```bash
python3 ~/.openclaw/workspace/skills/skill-creator/scripts/package_skill.py .
```

---

## Roadmap

- Validate RAV4 XA50 enhanced PIDs with OBDLink EX (trans temp, wheel speeds, TPMS)
- Promote confirmed PIDs to `verified`
- Add additional Toyota vehicle profiles (Camry, Tacoma, Highlander, etc.)
- Add richer DTC decoding (Toyota-specific where possible)

---

## Disclaimer

This tool is for informational/diagnostic use. Do not use it while driving. You assume all risk.

---

## License

TBD (recommendation: MIT or Apache-2.0 for maximum adoption).
