# ELM327 AT Command Reference

Quick reference for the AT commands used by the OBD-II adapter. These are handled by the
python-obd library internally, but useful for debugging.

## Connection & Init

| Command | Description |
|---------|-------------|
| `ATZ` | Reset adapter |
| `ATE0` | Echo off (cleaner responses) |
| `ATL0` | Linefeeds off |
| `ATS0` | Spaces off |
| `ATH1` | Headers on (show CAN IDs in response) |
| `ATSP6` | Set protocol: ISO 15765-4 CAN 11/500 |
| `ATDP` | Display current protocol |

## Header Control

| Command | Description |
|---------|-------------|
| `AT SH 7E0` | Set header to engine ECU |
| `AT SH 7E1` | Set header to transmission ECU |
| `AT SH 7E2` | Set header to ABS ECU |
| `AT SH 750` | Set header to body ECU |
| `AT D` | Reset to defaults (header back to 7E0) |

## Querying

| Command | Description |
|---------|-------------|
| `0100` | Mode 01 supported PIDs [01-20] |
| `0120` | Mode 01 supported PIDs [21-40] |
| `0140` | Mode 01 supported PIDs [41-60] |
| `010C` | RPM |
| `010D` | Vehicle speed |
| `0105` | Coolant temp |
| `03` | Read stored DTCs |
| `07` | Read pending DTCs |
| `222301` | Mode 22 PID 2301 (enhanced) |
| `210105` | Mode 21 PID 0105 (enhanced) |

## Diagnostics

| Command | Description |
|---------|-------------|
| `ATI` | Adapter identification string |
| `ATRV` | Read battery voltage |
| `ATMA` | Monitor all CAN traffic (use with caution — floods output) |
| `AT@1` | Device description |

## STN Chip Extensions (OBDLink adapters)

STN-based adapters (OBDLink EX/MX) support additional commands beyond ELM327:

| Command | Description |
|---------|-------------|
| `STI` | STN firmware version |
| `STDI` | Device hardware ID |
| `STPX` | Protocol expansion (enhanced diagnostics) |

## Notes

- python-obd handles AT initialization automatically
- Custom headers are set via `OBDCommand(header="7E1")` — the library sends AT SH internally
- Responses prefixed with `7E8` = engine ECU, `7E9` = transmission, `7EA` = ABS
- `NO DATA` response means the ECU doesn't support that PID or the header is wrong
- `?` response means the adapter doesn't understand the command
