# Adding a Vehicle Profile

This guide explains how to validate PIDs on your Toyota and contribute a vehicle JSON file.

## Prerequisites

- OBD-II adapter with enhanced PID support (OBDLink EX recommended for Toyota)
- `toyota-diag` skill installed and configured (`obd2.sh setup`)
- Vehicle ignition ON (engine running for some sensors)

## Step 1: Start with the Template

Copy an existing vehicle JSON from `config/vehicles/` and rename it:

```bash
cp config/vehicles/rav4_xa50.json config/vehicles/camry_xv70.json
```

Edit the `vehicle` section with your car's details.

## Step 2: Verify Standard PIDs

Standard Mode 01 PIDs work on every OBD-II vehicle. Run:

```bash
obd2.sh status
```

All standard PIDs (RPM, coolant, speed, etc.) should return data. If they don't, you have a connection problem — fix that first.

## Step 3: Discovery Scan

Run the discovery scanner to find which enhanced PIDs your ECU responds to:

```bash
# Scan all configured ECUs
obd2.sh scan

# Scan a specific ECU (e.g., transmission)
obd2.sh scan 7E1
```

The scan sends Mode 21/22 requests across PID ranges and reports which ones return data. This takes a few minutes per ECU.

## Step 4: Identify Response Data

For each PID that responds, you need to figure out the formula. Use raw mode:

```bash
# Example: query PID 2301 on transmission ECU
obd2.sh raw 222301 --header 7E1
```

Compare the raw hex response against known values:
- **Transmission temp:** Should correlate with how long the car has been running
- **Wheel speeds:** Should match speedometer (divide by 4 as a starting point)
- **Tire pressures:** Usually 200-250 kPa (29-36 psi) when cold

Common Toyota formulas:
| Pattern | Formula | Use Case |
|---------|---------|----------|
| Single byte temp | A - 40 | Most temperatures |
| Two-byte scaled | (A × 256 + B) / 10 - 40 | High-precision temps |
| Two-byte speed | (A × 256 + B) / 4 | Wheel speeds |
| Percentage | (A × 100) / 255 | Fuel level, throttle |

## Step 5: Update Your Vehicle JSON

For each confirmed PID:
1. Set the correct `formula`
2. Update `confidence` from `"unverified"` to `"verified"`
3. Add your vehicle model/year to `source`

For PIDs that don't respond:
- Try alternate modes (21 vs 22)
- Try different ECU headers
- Remove from your vehicle JSON if no response at all

## Step 6: Contribute

Share your validated vehicle JSON! Toyota owners with different models need exactly this data.

Include in your submission:
- Vehicle year, model, trim, engine
- Which adapter you used
- Which PIDs were confirmed working
- Any PIDs that didn't work (helps others avoid dead ends)

## Toyota ECU Address Reference

| Header | ECU | Typical Data |
|--------|-----|-------------|
| 7E0 | Engine | Standard PIDs, engine temps, fuel |
| 7E1 | Transmission | ATF temp, gear position, torque converter |
| 7E2 | ABS/VSC | Wheel speeds, brake pressure, yaw rate |
| 750 | Body | TPMS, interior sensors, door status |
| 7C0 | TPMS (some models) | Direct tire pressure readings |
| 7E3 | Airbag | Crash sensors (read carefully) |

Note: Not all ECUs respond on all models. Addressing varies by generation.

## Scan Range Configuration

Each vehicle JSON includes a `scan_ranges` section that controls discovery:

```json
"scan_ranges": {
  "7E1": { "modes": ["21", "22"], "pid_range": ["0100", "2FFF"] }
}
```

Adjust ranges based on your findings. Wider ranges = longer scan time.
