# windows_for_claude.md — task brief for Claude Code on the Windows host

You are Claude Code running on a **Windows PC**, connected to this repository. Your job: **get the
openEMS bridge running on this machine** so a single remote tester (reached via Tailscale Funnel) can
use the whole tool — the instant analytical features **and** the full-wave openEMS "Run" buttons.

This app already runs **perfectly on the author's Mac**. Nothing about the physics, the HTML, or the
analytical engine is broken. Your scope is **only the Windows host environment** (installing the
solver stack and pointing the code at it). Treat this as a bring-up + debugging task, not a rewrite.

---

## 0. Ground rules (read before touching anything)

1. **Do not hardcode Windows paths into source files.** The code is deliberately OS-portable: it reads
   a handful of **environment variables** and falls back to macOS defaults when they're unset (§3).
   Configure the machine with env vars — do **not** replace the macOS defaults or bake in `C:\...`
   paths. If you find a genuine cross-platform *bug*, fix it with the same env-var-with-default
   pattern so the Mac stays byte-for-byte unchanged.
2. **Do not modify** `waveguide_simulator.html` or any analytical/physics code. It's validated. If you
   ever touch it, `node verify_math.js` must still print `19 passed, 0 failed`.
3. **Prefer installs + env vars over code edits.** Most failures here are "tool not found / wrong
   path," not code bugs.
4. **Read first:** `CLAUDE.md` (repo root — full project context, standing rules, gotchas) and
   `openEMS/WINDOWS_SETUP.md` (the intended Windows setup this brief expands on).
5. When you change or install something, **re-test in layers** (§5) and report what actually happened
   (paste the real error), don't declare success until a solve completes end-to-end.

---

## 1. What "working" means (acceptance criteria)

- [ ] `python openEMS/openems_server.py` starts and prints `Local: http://localhost:8731`.
- [ ] Opening `http://localhost:8731` shows the page; the **analytical** tabs compute, and the
      **Reflection-loss** tab accepts a **file upload** (CSV/Excel) and draws curves.
- [ ] A **waveguide** full-wave solve (Full-wave tab → Run) completes and draws an S21 curve.
- [ ] An **RCS** solve (RCS ▾ → RCS openEMS → Run) completes; bare-PEC/coated numbers appear.
- [ ] The page is reachable over a **Tailscale Funnel** HTTPS URL from another network (§8).

Partial credit is fine and useful: if openEMS refuses to cooperate, the **analytical page + upload
still work with zero solver setup** — get that shared first (§8), then keep working on openEMS.

---

## 2. Architecture (2-minute mental model)

- **`waveguide_simulator.html`** — the entire UI. All analytical physics (waveguide loss/weight/cost,
  horn, reflection-loss from measured ε/μ, coated-plate RCS, sweeps) runs **in the browser**. The RL
  file upload is **client-side** (FileReader). None of this needs the server.
- **`openEMS/openems_server.py`** — a Flask "bridge" (default port **8731**) that:
  - serves the HTML at `/`,
  - on POST runs full-wave solves: `/run` (waveguide), `/run_horn`, `/run_rcs`, `/upload_rcs` (STL),
  - streams solver progress at `/progress?kind=wg|horn|rcs`,
  - serves results as static files: `/results/*`, `/fullwave_figures/*`, `/cad/*`.
  All client→server calls are **relative**, so the whole thing works unchanged behind Funnel.
- **Solve pipeline** (what happens on Run): the server writes a per-run params file
  (`wg_params.m` / `rcs_params.m`), launches **`octave-cli --no-gui <script>.m`** (which uses the
  **openEMS Octave interface** and shells out to **`openEMS.exe`**), writes field dumps into the
  **scratch dir**, then runs the **Python renderers** (pyvista/matplotlib) to make PNGs/GIFs into
  `fullwave_figures/`. Numeric results land as CSVs in `openEMS/results/`.
- So the full-wave path depends on **three external tools on this PC: openEMS, GNU Octave, and Python
  (with flask + pyvista)**. That's the whole game.

---

## 3. The environment-variable contract (how the code finds the tools)

`openems_server.py` (near the top) derives the project root from its own location and reads these;
the 5 `.m` solvers and 4 Python renderers read the same vars via `getenv`/`os.environ`. **All optional
— unset = macOS defaults.** On this Windows box you set them:

| Env var | What it points at | Example (Windows) | Consumed by |
|---|---|---|---|
| `OPENEMS_OCTAVE` | the Octave CLI executable | `C:\Program Files\GNU Octave\Octave-9.x\mingw64\bin\octave-cli.exe` | server → launches solvers |
| `OPENEMS_PYTHON` | a Python with **flask + pyvista** | (skip if you launch the server with it) | server → renderers |
| `OPENEMS_MATLAB_PATH` | openEMS Octave-interface folder (contains `InitFDTD.m`) | `C:\openEMS\matlab` | all 5 `.m` (`addpath`) |
| `CSXCAD_MATLAB_PATH` | CSXCAD Octave-interface folder (contains `AddBox.m`) | `C:\openEMS\CSXCAD` | all 5 `.m` (`addpath`) |
| `OPENEMS_SCRATCH` | scratch dir for field dumps — **NO SPACES** | `C:\openems_scratch` | server + `.m` (write) + renderers (read) |
| `OPENEMS_HOST` | bind address (default `127.0.0.1`, fine for Funnel) | leave default | server |
| `OPENEMS_PORT` | port (default `8731`) | leave default | server |
| `OPENEMS_THREADED` | `1` (default) so `/progress` polls during a run | leave default | server |

The server sets `os.environ["OPENEMS_SCRATCH"]` before launching children, so Octave and Python stay
in sync automatically. The `.m`/`.py` files consuming these:
`openEMS/wg_run.m`, `wg_farfield.m`, `rcs_run.m`, `cad/horn_run.m`, `wg_pipeline_test.m`;
`render_field.py`, `render_field_freq.py`, `render_rcs.py`, `cad/render_horn.py`.

Set env vars persistently with `setx NAME "value"` (then **open a new terminal**), or per-session with
`set NAME=value` (cmd) / `$env:NAME="value"` (PowerShell). A `run_bridge.bat` that `set`s them all and
launches the server is a convenient artifact to create.

---

## 4. Install the solver stack — **WSL2 is strongly recommended**

Native-Windows openEMS + Octave is notoriously painful (the Octave↔openEMS bridge, HDF5, locating
`openEMS.exe`). **WSL2 (Ubuntu inside Windows) runs on the same always-on PC but installs openEMS with
`apt` in two commands.** Try WSL2 first; fall back to native only if WSL is off the table.

### Route A — WSL2 (recommended)
```
wsl --install            # PowerShell (admin), once; reboot if prompted, opens Ubuntu
```
Inside Ubuntu:
```
sudo apt update && sudo apt install -y openems octave python3-pip
pip install flask pyvista imageio imageio-ffmpeg numpy matplotlib
find /usr -name InitFDTD.m 2>/dev/null      # -> its folder = OPENEMS_MATLAB_PATH
find /usr -name AddBox.m   2>/dev/null       # -> its folder = CSXCAD_MATLAB_PATH
```
Then set env vars (put in `~/.bashrc` to persist) and run the bridge against the repo on the Windows
drive (`/mnt/c/...`), with a **Linux** scratch dir for speed:
```
export OPENEMS_OCTAVE=octave-cli
export OPENEMS_MATLAB_PATH=/usr/share/openEMS/matlab       # use what `find` reported
export CSXCAD_MATLAB_PATH=/usr/share/CSXCAD/matlab
export OPENEMS_SCRATCH=/tmp/oems
export OPENEMS_HOST=0.0.0.0
python3 "/mnt/c/<path-to-repo>/openEMS/openems_server.py"
```
(If `apt` doesn't have `openems` on this Ubuntu version, build it per openems.de's Linux instructions —
a straightforward cmake build.)

### Route B — native Windows (only if WSL is not an option)
1. **openEMS Windows build** from <https://www.openems.de/> (Install → Windows) or the
   `thliebig/openEMS-Project` GitHub releases. Extract to a short path, e.g. `C:\openEMS`. Add the
   folder containing `openEMS.exe` to `PATH` (`setx PATH "%PATH%;C:\openEMS"`, reopen terminal).
2. **GNU Octave** from <https://octave.org/download>. CLI = `...\mingw64\bin\octave-cli.exe`.
3. **Miniconda** + `pip install flask pyvista imageio imageio-ffmpeg numpy matplotlib`.
4. Locate the interface folders: search the extracted openEMS tree for `InitFDTD.m` (→
   `OPENEMS_MATLAB_PATH`) and `AddBox.m` (→ `CSXCAD_MATLAB_PATH`). If openEMS ships a single combined
   `matlab` folder, point **both** vars at it.
5. Set the env vars from §3.

---

## 5. Bring-up in layers — diagnose in this order (don't skip)

**Layer 1 — the web/analytical layer (no solver needed).**
```
python openEMS/openems_server.py     # (the python that has flask)
```
Open `http://localhost:8731`. If the page loads and the analytical tabs compute and the RL tab accepts
a file upload → Layer 1 done. (If flask is missing → you're using the wrong Python; use the conda one.)

**Layer 2 — openEMS + Octave in isolation (NO server, NO bridge).** This is the make-or-break test.
With the env vars set, run the self-contained smoke test:
```
octave-cli --no-gui openEMS/wg_pipeline_test.m     # native
# or in WSL:  octave-cli --no-gui /mnt/c/<repo>/openEMS/wg_pipeline_test.m
```
Success = it writes an XML, launches openEMS, and finishes without error (prints port results). If
this fails, **fix it here** — the bridge cannot work until this does. Common failures in §6. A quick
sub-check that the interface paths are right:
```
octave-cli --no-gui --eval "addpath(getenv('OPENEMS_MATLAB_PATH')); addpath(getenv('CSXCAD_MATLAB_PATH')); InitFDTD"
```
"`InitFDTD` undefined" ⇒ wrong `OPENEMS_MATLAB_PATH`/`CSXCAD_MATLAB_PATH`.

**Layer 3 — the full bridge solve.** With the server running, open the page and click **Run** on the
Full-wave (waveguide) tab. Watch the terminal **and** tail the log:
```
# the server writes these in openEMS/ :  last_run.log (wg), last_horn_run.log, last_rcs_run.log
```
If the solve returns numbers but field **images** are missing, that's the Python/pyvista renderer, not
openEMS (see §6) — the numeric result is still valid.

---

## 6. Known failure modes → fixes

| Symptom | Cause / fix |
|---|---|
| `octave-cli: not found` (server log) | Set `OPENEMS_OCTAVE` to the full exe path, or add Octave's `mingw64\bin` to PATH. |
| `.m` error: `'InitFDTD' undefined` / `'AddBox' undefined` | Wrong `OPENEMS_MATLAB_PATH` / `CSXCAD_MATLAB_PATH`. Re-find `InitFDTD.m` / `AddBox.m` and set them. |
| `RunOpenEMS` fails / `openEMS.exe` not found | Add the folder containing `openEMS.exe` to PATH; confirm `openEMS --version` runs in a terminal. |
| HDF5 read/write errors from Octave | openEMS↔Octave HDF5 mismatch (classic native-Windows issue). Easiest fix: use **WSL2** (Route A). |
| Solve dumps go nowhere / renderer says "no .vtr" | `OPENEMS_SCRATCH` mismatch or **contains spaces**. Use a no-space path; confirm the `.m` wrote into it. |
| `ModuleNotFoundError: flask` | Server launched with the wrong Python. Run it with the conda Python that has flask+pyvista. |
| Field GIF/still missing, but curves present | pyvista off-screen rendering failed (OpenGL). Try `set PYVISTA_OFF_SCREEN=true`; install a software-GL if needed. **Numeric results are unaffected** — renderers are fail-soft. |
| Page loads but Run says "could not reach bridge" | You opened the HTML file directly instead of via `http://localhost:8731`. Open the served URL. |
| Everything works locally but not over Funnel | Funnel not enabled on the tailnet, or you funneled the wrong port. `tailscale funnel status`; §8. |

---

## 7. Verify (before declaring done)
- Page loads at `localhost:8731`; analytical + RL upload work (Layer 1).
- `octave-cli --no-gui openEMS/wg_pipeline_test.m` completes (Layer 2).
- A waveguide Run and an RCS Run complete via the UI (Layer 3); numbers look sane
  (e.g., bare-PEC 180×180 mm plate ≈ **10.75 dBsm** on the RL tab's RCS panel — that's analytical, a
  good cross-check that the page is intact).
- Optional, if Node is available and you touched the HTML: `node verify_math.js` → `19 passed, 0 failed`.

---

## 8. Share it (Tailscale Funnel)
Install Tailscale for Windows, sign in. With the bridge running:
```
tailscale funnel 8731
tailscale funnel status        # prints the public URL to share
```
First run may print an admin link to enable Funnel/HTTPS on the tailnet — open it once. Share
`https://<pc>.<tailnet>.ts.net`. (Run Tailscale on the **Windows** side even if the bridge is in WSL —
WSL2 forwards `localhost`, so Windows `localhost:8731` reaches the WSL server.) The Funnel URL is
public and unauthenticated — fine for one trusted tester; solves run on this PC.

**Keep it alive 24/7:** put the `export`/`set` env lines + the launch in a startup mechanism —
a Windows **Task Scheduler** task "at log on/at startup" running the bridge (native) or
`wsl -d Ubuntu -e bash -lc "…openems_server.py"` (WSL); enable `systemd` in WSL if you want a proper
service. Tailscale's Funnel config persists across reboots via the Windows Tailscale service.

---

## 9. Where to look when something breaks
- **Server stdout** (the terminal running `openems_server.py`) — top-level errors, the resolved
  octave/python/scratch it printed at startup.
- **`openEMS/last_run.log`, `last_horn_run.log`, `last_rcs_run.log`** — the live Octave/openEMS output
  per solve (this is what `/progress` tails).
- **`openEMS/results/`** — result CSVs; **`fullwave_figures/`** — rendered PNG/GIF.
- **`openEMS/run_history.csv`** — one line per run.
- A global Flask error handler returns error JSON (never a bare 500), so the browser shows the real
  message — check the Network tab / the status line on the tab.

## 10. Do NOT
- hardcode `C:\...` paths into `.py`/`.m`/HTML (use the env vars);
- edit the analytical engine, physics, or `waveguide_simulator.html`;
- change ports/URLs in the client (they're relative on purpose);
- run concurrent solves (single scratch dir — one tester at a time, by design);
- commit or expose any credentials.

If you get stuck at Layer 2 on native Windows for more than a short while, **switch to WSL2** (§4
Route A) — it resolves the large majority of these issues and runs on the same always-on machine.
