# Resume point — openEMS full-wave setup (RESOLVED — kept for history)

> **Status: done.** Everything described below as "to fix" has been fixed. The full-wave
> pipeline runs end-to-end and is automated behind the Flask bridge. Start it with
> `python openEMS/openems_server.py`, open `http://localhost:8731`, and use the Run
> buttons — see `SETUP.md` and `../CLAUDE.md` §4 for the current instructions. This file
> is left as a record of how the toolchain was brought up.

## What was wrong (historical)
The waveguide port's mode-matching box wasn't a clean 2-D plane, so `port_ut1` wasn't
written and `calcPort` failed ("Mode Matching Integration Box is not a surface,
dimension 3"). The manual plan was to fix the port geometry, validate copper WR-90,
then export CSVs and ParaView screenshots into a manual "screenshot panel".

## How it was resolved
- **Ports fixed.** `wg_run.m` places two `AddRectWaveGuidePort` planes a few cells inside
  the domain; `calcPort` returns S11/S21 cleanly. openEMS de-embeds each port to its
  *stop* plane (`measplanepos = stop(dir)`), i.e. `mesh.z(15)` and `mesh.z(end-7)` — that
  separation (not the full guide length) is written to `port_sep.txt` and used for dB/m.
- **Validated.** Copper WR-90 tracks the analytical ~0.108 dB/m; each run appends an
  openEMS-vs-model row to `run_history.csv`.
- **Automated, not manual.** The old ParaView/AppCSXCAD screenshot workflow was replaced:
  the bridge renders field GIFs/stills (`render_field*.py`), a wall-loss map, an NF2FF
  far-field, and an interactive 3-D |E| volume — all served to the tabs automatically.
  The horn pipeline adds gain/S11/pattern (E-plane = φ=90°, H-plane = φ=0°) and a
  coating comparison.

## Key files (current)
- `wg_run.m`, `wg_farfield.m` — waveguide FDTD + far-field.
- `cad/horn_run.m` + `cad/*.py` — horn FDTD + post-processing.
- `openems_server.py` — the Flask bridge (routes `/run`, `/run_horn`).
- `wg_pipeline_test.m` — the original standalone bring-up script (superseded; kept for reference).
