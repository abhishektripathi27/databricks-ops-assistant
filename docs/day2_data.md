# Day 2: Source data

All equipment and procedures are fictional (Northgate Equipment Co., Northgate Distribution).
I wrote them so the fault codes and limits in the documents match the telemetry. That gives me
known correct answers for evaluation on Day 7.

## Document corpus (`data/docs/`, uploaded to `/Volumes/<catalog>/raw/docs/`)

| File | Content |
|---|---|
| NG_CU-400_Condensing_Unit_Manual.pdf | Walk-in cooler unit. Faults E-21, E-14, E-30, E-42 |
| NG_EV-220_Freezer_Evaporator_Manual.pdf | Freezer evaporator. Faults DF-4, F-11, F-20, F-31 |
| NG_AC-75_Air_Compressor_Manual.pdf | 75 HP screw compressor. Faults V-02, V-03, T-05, P-07 |
| NG_CD-900_Conveyor_Drive_Manual.pdf | Conveyor gearmotor. Faults OL-1, OL-2, JM-3, TH-4 |
| NG_BC-48_Battery_Charger_Manual.pdf | Forklift charger. Faults C-01, C-12, C-20, C-33 |
| SOP-OPS-001_Lockout_Tagout.pdf | LOTO steps and energy sources per equipment type |
| SOP-OPS-002_Cold_Chain_Excursion.pdf | Cooler and freezer limits, product hold rules |
| SOP-OPS-003_Alarm_Escalation.pdf | P1/P2/P3 priorities, fault code to priority map |
| SOP-OPS-004_Preventive_Maintenance.pdf | PM intervals and site exceptions |

Rebuild with `python tools/build_docs.py`.

## Telemetry

- 200 devices across 5 sites (JOL, AUR, LAK, STK, ALN), 5 models
- 30 days, one reading every 15 minutes, about 576k rows
- Raw JSON in `/Volumes/<catalog>/raw/telemetry/readings/event_date=YYYY-MM-DD/`
- Device registry in `<catalog>.raw.devices` (device to model, site, zone, manual file)
- Dirty data on purpose: about 0.2% `temperature_f = -999` sensor errors, 0.1% null status, 0.1% duplicate rows

## Planted incidents (`<catalog>.ai.planted_incidents`)

| Device | Site | Model | What happens | When | Fault codes |
|---|---|---|---|---|---|
| D-114 | JOL | CU-400 | Head pressure 250 to 330 psig, box temp 36F to 44F | Last 3 days | E-21, E-42 |
| D-037 | AUR | AC-75 | Vibration 3 to 9 mm/s | Last 10 days | V-02, V-03 |
| D-162 | STK | CD-900 | Power about 11 kW, motor about 155F | 5 days ago, 14:00 to 16:00 UTC | OL-2, TH-4 |
| D-089 | LAK | EV-220 | Freezer -10F to 15F, above 10F for 1h45m | 7 days ago, 02:00 to 05:30 UTC | DF-4, F-20 |
| D-200 | ALN | BC-48 | No data for 48 hours | 12 to 10 days ago | C-01 on reconnect |

## Questions these support

- Document: "What should I check first when a CU-400 shows E-21?" (condenser fans, then coil)
- Data: "Which devices raised alarms in the last 24 hours?" (D-114, D-037)
- Combined: "D-089 had a temperature problem last week. Does the product need to be quarantined?"
  (yes: above 10F for more than 60 minutes per SOP-OPS-002)
- Combined: "What priority is the D-037 issue and what should the technician do?" (P1 under SOP-OPS-003, V-03 steps)
