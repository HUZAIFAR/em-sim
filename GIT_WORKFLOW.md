# GIT_WORKFLOW.md — how this project syncs across machines

> Read this before editing files or committing. It explains how the **Mac** (development) and the
> **Windows PC** (always-on openEMS server) stay in sync via **git**, and the few rules that keep the
> two machines from stepping on each other. This is for both the human and any Claude Code session.

---

## 0. TL;DR

- **Git is the ONLY channel between the two machines.** Commit on the Mac → `push`; `pull` on Windows.
- **Do NOT use FreeFileSync (or any file-copy tool) on this folder anymore.** It cannot merge and it
  would sync the `.git` directory and corrupt the repo. Git replaced it on purpose.
- **Generated output and machine-local installs are not tracked** (see `.gitignore`). Never commit them.
- **The renderers contain `if os.name == "nt":` blocks — keep them.** They are no-ops on macOS.

---

## 1. Why git (and not file sync)

The Mac and Windows box are edited independently. A file-sync tool (FreeFileSync, Dropbox, etc.) copies
**whole files** and has **no concept of merging** — if the same file changed on both sides between
syncs, you silently lose one side's edits. Git merges at the **line** level, keeps history, and lets you
roll back. It also cleanly separates *source* (tracked) from *generated output* and *machine setup*
(ignored / outside the repo).

## 2. The two roles

| Machine | Role | openEMS install | Renderer path |
|---|---|---|---|
| **Mac** | Development. Claude adds features; you run it locally. **Source of truth.** | Homebrew (`/opt/homebrew/...`) | GPU volume render (default) |
| **Windows PC** | Always-on bridge for the remote tester (via Tailscale Funnel). **Consumer of code.** | `C:\opt\openEMS` | Mesa software GL + surface render (headless-safe) |

Develop on the Mac. The Windows box only ever **pulls** code; you don't edit source there (everything
Windows-specific lives *outside* the repo — see §5).

## 3. Daily workflow

**On the Mac (making changes):**
```bash
# ...edit files (Claude feature work, etc.)...
git add -A
git commit -m "short description of the change"
git push
```

**On the Windows PC (picking up changes):**
```powershell
cd "C:\Users\Public\Documents\HTR\School\Khalifa University\Wave Guide Simulator"
git pull
# then relaunch the bridge so it serves the new code:
#   double-click run_bridge.bat   (or re-run it in a terminal)
```

**If a change is made ON Windows** (e.g. a Windows-only fix): commit + push there, then `git pull` on the
Mac. Because the Windows-specific code is `os.name=='nt'`-gated, pulling it to the Mac changes nothing at
runtime on macOS.

## 4. Rules for Claude Code (both machines)

1. **Never hardcode a machine path** (`C:\...`, `/opt/homebrew/...`, `/Users/...`) into `.py`/`.m`/`.html`.
   The code is OS-portable: it reads env vars and falls back to **macOS defaults** when unset. If you must
   add a machine-specific path, do it with the same *env-var-with-macOS-default* pattern so the Mac stays
   unchanged, or put it in a launcher (`run_bridge.bat`), never in source.
2. **Preserve the Windows-gated blocks.** These files have `if os.name == "nt":` sections — a Mesa
   software-OpenGL preload and (for the two waveguide field renderers) a surface-render branch. They are
   **no-ops on macOS/Linux**; do not remove them when editing for a feature:
   - `openEMS/render_field.py`
   - `openEMS/render_field_freq.py`
   - `openEMS/render_rcs.py`
   - `openEMS/cad/render_horn.py`
   - `openEMS/cad/view_stl.py`
3. **Don't commit generated output.** Renders (`fullwave_figures/`), results CSVs (`openEMS/results/`),
   logs, per-run `*_params.m`, `horn_results/`, `.vtr`/`.h5` dumps, `__pycache__/`, `.DS_Store` are all
   git-ignored. If `git status` shows them, the `.gitignore` needs fixing — don't `git add -f` them.
4. **The single-file app rule still holds** (`waveguide_simulator.html`, no build step) and
   `node verify_math.js` must still print `19 passed, 0 failed` after any change that touches the analytic
   engine. (See `CLAUDE.md` for the full standing rules.)
5. **Branch for non-trivial work**; don't force-push shared history. Commit messages: concise; if a Claude
   session made the change it appends `Co-Authored-By: Claude <...>` (harness convention).

## 5. What lives where (tracked vs ignored vs outside the repo)

- **Tracked (in git, travels between machines):** all source — `waveguide_simulator.html`, `verify_math.js`,
  the `openEMS/*.py` and `*.m` solvers/renderers, the vendored `openems_matlab/` + `csxcad_matlab/`
  interfaces, docs (`CLAUDE.md`, `WINDOWS_SETUP.md`, this file, `.docx` guides), the launchers
  (`run_bridge.bat`, `share_funnel.bat`), `openEMS/cad/horn.stl`.
- **Ignored (generated per run, per machine — NOT tracked):** see `.gitignore` — `fullwave_figures/`,
  `openEMS/results/`, `openEMS/cad/horn_results/`, `openEMS/uploads/`, `*.log`, `run_history.csv`,
  per-run `wg_params.m`/`rcs_params.m`/`horn_params.m`, `render_geo.txt`, `*.vtr`, `*.h5`,
  `__pycache__/`, `.DS_Store`, the Python venv.
- **Outside the repo entirely (set up ONCE per machine, never synced):**
  - **Mac:** Homebrew openEMS + Octave; a Python env with `flask pyvista imageio imageio-ffmpeg numpy matplotlib`.
  - **Windows:** `C:\opt\openEMS` (incl. the Octave-11-rebuilt `h5readatt_octave.oct`), `C:\opt\mesa`
    (Mesa software-OpenGL DLLs), the `openems_py314` venv (+ `scipy openpyxl gmsh`), the environment
    variables (`OPENEMS_OCTAVE`, `OPENEMS_MATLAB_PATH`, `CSXCAD_MATLAB_PATH`, `OPENEMS_SCRATCH`,
    `OPENEMS_MESA_GL`, `GALLIUM_DRIVER`), and Tailscale. Full recipe: `openEMS/WINDOWS_SETUP.md`.

Because the runtime is outside the repo, the two machines can have completely different openEMS/OpenGL
setups and **never conflict** — git only carries the portable source.

## 6. Environment knobs the code reads (all optional; unset = macOS behavior)

| Env var | Purpose | Windows value |
|---|---|---|
| `OPENEMS_OCTAVE` | Octave CLI | `...\Octave-11.3.0\mingw64\bin\octave-cli.exe` |
| `OPENEMS_MATLAB_PATH` / `CSXCAD_MATLAB_PATH` | openEMS + CSXCAD `.m` interfaces (combined folder on this build) | `C:\opt\openEMS\matlab` |
| `OPENEMS_SCRATCH` | field-dump scratch dir (no spaces) | `C:\openems_scratch` |
| `OPENEMS_MESA_GL` | dir holding Mesa's software `opengl32.dll` (renderers preload it on Windows) | `C:\opt\mesa` |
| `GALLIUM_DRIVER` | force pure-CPU software GL | `llvmpipe` |
| `OPENEMS_FIELD_RENDER` | `volume` (macOS default) or `surface` (Windows default) waveguide field render | `surface` |

These are set by `run_bridge.bat` on Windows and are simply unset on the Mac (→ macOS defaults).

## 7. How this repo was created (for context)

The Windows box held the **union** of the latest Mac source (via the final FreeFileSync) plus the
Windows-portability fixes, so the repo was initialized there (`git init -b main`, `core.autocrlf false`
to preserve exact bytes), committed, and pushed to a private remote. The Mac then `git clone`d it — the
old Mac folder was renamed to `Wave Guide Simulator.freefilesync-backup` as a safety copy (delete it once
the clone is confirmed working). From that point on, git is the only sync path.

## 8. Gotchas

- **Line endings:** the Windows repo was created with `core.autocrlf false` so bytes are preserved (Mac
  `LF` stays `LF`). Keep it that way; don't enable autocrlf, and don't add a `.gitattributes` that
  normalizes endings — it would create a spurious whole-repo diff.
- **`git pull` conflict:** happens only if the *same lines* were edited on both machines. Since source is
  edited on the Mac and Windows only pulls, this should be rare. If it happens, resolve the conflict
  markers (`<<<<<<<`) and commit; don't blindly discard a side.
- **After `git pull` on Windows,** restart `run_bridge.bat` so the bridge serves the new code (a running
  server holds the old code in memory).
- **Do not re-enable FreeFileSync on this folder.** If it's still configured, delete the sync pair.
