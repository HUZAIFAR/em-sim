# Running the bridge on Windows + sharing it with Tailscale Funnel

Goal: run the whole thing (analytical page **+** openEMS full-wave) on a Windows PC and give one
person a public link. All computation happens on your PC; the tester just needs a browser.

The code is now **OS-portable** — it reads a few environment variables and falls back to macOS
defaults if they're unset. On Windows you set those vars to point at your installs.

---

## ✅ Verified working on this PC (2026-07-24) — config + the two fixes applied

This machine is now fully bring-up'd. All three engines run natively:
analytical page + RL file-upload, waveguide full-wave (S21), and RCS full-wave (NF2FF).

**Installed stack**
- openEMS `v0.0.36` at `C:\opt\openEMS` (ships a **single combined** `matlab\` folder — both
  `InitFDTD.m` *and* `AddBox.m` live there; there is **no** separate `CSXCAD\` folder).
- GNU Octave **11.3.0** at `C:\Program Files\GNU Octave\Octave-11.3.0`.
- Python venv `C:\Users\Huzaifa\openems_py314` (has flask + pyvista + imageio + numpy + matplotlib).
- Tailscale installed + logged in; Funnel already enabled on the tailnet.

**Env vars (persisted with `setx`)** — same as §3, with the CSXCAD path pointed at the combined folder:
```
OPENEMS_OCTAVE       C:\Program Files\GNU Octave\Octave-11.3.0\mingw64\bin\octave-cli.exe
OPENEMS_MATLAB_PATH  C:\opt\openEMS\matlab
CSXCAD_MATLAB_PATH   C:\opt\openEMS\matlab      <-- combined folder, NOT C:\opt\openEMS\CSXCAD
OPENEMS_SCRATCH      C:\openems_scratch
```

**Launch**: double-click **`run_bridge.bat`** (repo root) — it sets the vars, prepends
`C:\opt\openEMS` to PATH, and starts the server with the venv Python. Share: **`share_funnel.bat`**.

### Fix 1 — `CSXCAD_MATLAB_PATH` pointed at a folder that doesn't exist
This openEMS Windows build has no `C:\opt\openEMS\CSXCAD`; `AddBox.m` (the CSXCAD interface) is in
the combined `C:\opt\openEMS\matlab`. Point **both** `OPENEMS_MATLAB_PATH` and `CSXCAD_MATLAB_PATH`
at `C:\opt\openEMS\matlab` (as §1 already warns for combined builds).

### Fix 2 — Octave-version ABI mismatch broke NF2FF (RCS / horn / wg far-field) with "error 126"
The waveguide solve worked, but **RCS** died right after `nf2ff.exe` with:
```
error: opening the library 'C:\opt\openEMS\matlab\h5readatt_octave.oct' failed (error 126)
```
Cause: that compiled reader imports `liboctave-9.dll` / `liboctinterp-10.dll` (built for **Octave 8.x**),
but the installed Octave is **11.3.0** (`liboctave-13` / `liboctinterp-15`). The waveguide route never
loads that `.oct`; NF2FF (far-field readback) does.

Fix applied — **rebuilt the `.oct` against the installed Octave 11** (no 300 MB Octave downgrade needed,
because Octave 11 ships `mkoctfile`, `hdf5.h`, and `libhdf5.dll.a`):
```
REM back up the original first
copy "C:\opt\openEMS\matlab\h5readatt_octave.oct" "C:\opt\openEMS\matlab\h5readatt_octave.oct.octave8.bak"
REM source: https://raw.githubusercontent.com/thliebig/openEMS/master/matlab/h5readatt_octave.cc
set "PATH=C:\Program Files\GNU Octave\Octave-11.3.0\mingw64\bin;%PATH%"
mkoctfile h5readatt_octave.cc -lhdf5
copy h5readatt_octave.oct "C:\opt\openEMS\matlab\h5readatt_octave.oct"
```
The rebuilt `.oct` links `liboctave-13`/`liboctinterp-15`/`libhdf5` and loads cleanly. (Alternative fix
if you ever prefer it: install **GNU Octave 8.4.0** and point `OPENEMS_OCTAVE` there — that matches the
prebuilt `.oct` with zero compilation. If you ever *reinstall* openEMS, redo this rebuild.)

### Fix 3 — pyvista field/lobe renders were BLACK (then CRASHING) in a headless session
The field GIF/still (and 3-D RCS lobe) came back blank when a solve was triggered while
**no interactive session held the GPU** (the tester hits the page over Funnel, not RDP, so the
Windows session is *disconnected*). Two failure modes, both from the same cause — no usable
system OpenGL off-screen:
- disconnected → **no valid pixel format** → VTK *crashes* (`failed to get wglChoosePixelFormatARB`,
  access violation). Even 2-D polygon rendering dies here.
- weakly-connected (GDI-generic 1.1) → GPU **volume ray-casting renders black** while polygons draw.

Fix applied — **Mesa software OpenGL (llvmpipe)**, so off-screen rendering works in *any* session
state, no GPU needed:
1. `C:\opt\mesa\` holds Mesa's software `opengl32.dll` + `libgallium_wgl.dll` (+`dxil.dll`), from
   the build VTK itself recommends (github.com/pal1000/mesa-dist-win, release-msvc).
2. Each pyvista renderer (`render_field.py`, `render_field_freq.py`, `render_rcs.py`,
   `cad/render_horn.py`, `cad/view_stl.py`) **preloads** `%OPENEMS_MESA_GL%\opengl32.dll` (default
   `C:\opt\mesa`) *before* importing vtk, so VTK's implicit `opengl32` resolves to Mesa. This block is
   **guarded by `os.name=='nt'` and no-ops if Mesa is absent → macOS/Linux are byte-for-byte unchanged.**
3. `run_bridge.bat` sets `OPENEMS_MESA_GL=C:\opt\mesa` and `GALLIUM_DRIVER=llvmpipe` (pure CPU).
4. The two waveguide field renderers ALSO switch to a fast **surface** render (centre |E| cut-planes)
   on Windows — software volume ray-casting 80 GIF frames would be slow; polygons are fast and look
   clean. Controlled by `OPENEMS_FIELD_RENDER=volume|surface` (default surface on Windows, volume elsewhere).

If you ever move/reinstall, keep `C:\opt\mesa\opengl32.dll` + `libgallium_wgl.dll` together, or point
`OPENEMS_MESA_GL` at wherever they live.

**Validation after all fixes** (all live on this PC, in a *disconnected* GL session):
- `octave-cli --no-gui openEMS\wg_pipeline_test.m` → PEC WR-90 S21 ≈ 0 dB (0.006 dB), exit 0.
- Bridge waveguide Run (copper, X-band) → real S21 CSV + field GIF/PNG rendered (~163 s).
- Bridge RCS Run (bare-PEC 15 mm sphere, X-band) → **−31.2 dBsm** backscatter (matches the Mie anchor), NF2FF OK (~105 s).
- Page at `localhost:8731`: copper WR-90 analytical = **0.1084 dB/m**; RL tab CSV upload → 41 pts parsed, curves drawn.
- Renders (Fix 3), all non-black in a disconnected GL session: waveguide guided-wave still + 80-frame
  animated GIF; waveguide freq steady-|E| still; horn field (feed→flare→aperture) at 15.6 dBi @10 GHz
  (rated 15); RCS scattered-field still + 24-frame 3-D scattering-lobe GIF.
- Reachable over Tailscale Funnel at `https://desktop-dbcfmfa.tail53b2e4.ts.net` (HTTP 200).

---

## 0. Reality check (read first)

- **Analytical features + file upload need NO setup** — they run in the tester's browser. If you only
  want those shared, skip straight to §4 (Funnel) and §5. Uploading a lab CSV/Excel works from the
  client because it's parsed in the browser; the RCS STL upload posts to the bridge (same origin) and
  also works over the link.
- **openEMS full-wave is the hard part on Windows.** openEMS's Octave interface can be finicky
  (locating `openEMS.exe`, HDF5). **Get a bare openEMS example to run in Octave BEFORE touching the
  bridge (§2).** If that doesn't run, the bridge can't either. This guide can't be tested from the dev
  machine (macOS), so the first real solve test is yours.

---

## 1. Install the three tools (once)

1. **openEMS (Windows build)** — download from <https://www.openems.de/> → *Install → Windows*
   (or the GitHub releases of `thliebig/openEMS-Project`). Extract to a **path with no spaces**,
   e.g. `C:\openEMS`. Note the two Octave-interface folders inside — typically
   `C:\openEMS\matlab` and `C:\openEMS\CSXCAD` (names may differ by release; use whatever your
   install actually has).
2. **GNU Octave** — installer from <https://octave.org/download> (e.g. `C:\Program Files\GNU Octave\Octave-9.x`).
   The CLI you want is `...\mingw64\bin\octave-cli.exe`.
3. **Python (Miniconda)** — <https://docs.conda.io/en/latest/miniconda.html>. Then, in the
   *Anaconda Prompt*:
   ```
   pip install flask pyvista imageio imageio-ffmpeg numpy matplotlib
   ```
   Remember which `python.exe` this is — you'll launch the bridge with it so it has flask + pyvista.

Add the openEMS folder to your PATH so `openEMS.exe` is found by Octave:
`setx PATH "%PATH%;C:\openEMS"` (reopen the terminal afterwards).

---

## 2. Prove openEMS runs in Octave (the make-or-break step)

Open Octave and run:
```octave
addpath('C:\openEMS\matlab'); addpath('C:\openEMS\CSXCAD');   % your actual folders
confirm_environment                                            % if the package ships it
```
Then run any bundled tutorial (e.g. the rectangular-waveguide or MSL example under
`C:\openEMS\matlab\examples`). If it writes an XML, calls `openEMS.exe`, and returns results —
you're good. **If not, fix this first** (usually PATH to `openEMS.exe`, or an HDF5 mismatch).
Whatever two `addpath(...)` lines make this work are exactly the paths you put in `OPENEMS_MATLAB_PATH`
and `CSXCAD_MATLAB_PATH` below.

---

## 3. Point the bridge at your installs (environment variables)

The bridge reads these (all optional; unset → macOS defaults). Set them **once** with `setx`, then
open a fresh terminal:

```
setx OPENEMS_OCTAVE       "C:\Program Files\GNU Octave\Octave-9.2.0\mingw64\bin\octave-cli.exe"
setx OPENEMS_MATLAB_PATH  "C:\openEMS\matlab"
setx CSXCAD_MATLAB_PATH   "C:\openEMS\CSXCAD"
setx OPENEMS_SCRATCH      "C:\openems_scratch"
```
(Use YOUR actual paths.) `OPENEMS_SCRATCH` must have **no spaces** — the solvers shell out.
`OPENEMS_PYTHON` you can skip if you launch the server with the conda python that has pyvista+flask
(the default is "whatever python runs the server"); otherwise `setx OPENEMS_PYTHON "C:\...\python.exe"`.

Other optional knobs: `OPENEMS_PORT` (default 8731), `OPENEMS_HOST` (default 127.0.0.1 — fine for
Funnel), `OPENEMS_THREADED` (default on).

---

## 4. Start the bridge and test LOCALLY first

In the Anaconda Prompt (the python with flask+pyvista), from a fresh terminal so `setx` vars are live:
```
python "C:\path\to\Wave Guide Simulator\openEMS\openems_server.py"
```
It prints the resolved octave/python/scratch and:
```
  Local:   http://localhost:8731
```
Open <http://localhost:8731> in your browser and **run one openEMS solve** (waveguide/horn/RCS).
Confirm it completes and draws results BEFORE sharing. If a solve fails, the terminal shows the real
error (usually an octave/openEMS path issue from §2).

---

## 5. Share it with Tailscale Funnel

1. Install Tailscale for Windows (<https://tailscale.com/download>) and sign in.
2. Enable Funnel for your tailnet (admin console → *DNS*: enable MagicDNS + HTTPS certificates; and
   allow the `funnel` node attribute). The first `tailscale funnel` command will print an admin link
   if it isn't enabled yet — click it once.
3. With the bridge running, in a second terminal:
   ```
   tailscale funnel 8731
   ```
   (or `tailscale funnel --bg 8731` to run it in the background). This maps the public HTTPS URL to
   your local `:8731` — no firewall changes needed (it's Tailscale's outbound tunnel).
4. Get the URL and send it:
   ```
   tailscale funnel status
   ```
   → share `https://<your-machine>.<your-tailnet>.ts.net`. The tester opens it and gets the full page:
   all analytical features, file upload, and the Run buttons (which execute openEMS on your PC).

To stop sharing: `tailscale funnel --https=443 off` (or Ctrl-C the foreground command). Keep both the
bridge and Tailscale running while they test.

---

## 6. Notes / caveats (single-tester scope)

- The Funnel URL is **public** — anyone who has it can load the page and trigger solves on your PC
  (CPU load, no login). Fine for one trusted tester; don't post the link.
- **One run at a time.** The scratch dirs are shared, so concurrent openEMS runs would collide — not a
  concern for a single tester, as you noted.
- Client uploads work over the link: the **RL lab-file** upload is parsed in the tester's browser; the
  **RCS STL** upload posts to your PC (same origin). Both fine over HTTPS Funnel.
- Nothing here changes macOS behavior — the env vars only take effect when set, so the same files still
  run on the Mac with no config.

---

## 7. Use it on a phone or iPad (install it as an app)

The page is a **PWA**, so the Funnel HTTPS link can be installed to a home screen and runs
full-screen like a native app. Nothing extra to configure — the bridge already serves the
manifest, the service worker and the icons.

1. Start the bridge (`run_bridge.bat`) and the funnel (`share_funnel.bat` / `tailscale funnel 8731`).
2. On the device, open `https://<machine>.<tailnet>.ts.net` in **Safari** (iPhone/iPad) or
   **Chrome** (Android).
3. **iOS:** Share ⇧ → *Add to Home Screen*.  **Android:** ⋮ → *Install app* (or the install prompt).
4. Launch it from the home-screen icon: no browser chrome, dark status bar, own app switcher entry.

What works on mobile: every analytical tab (waveguide, horn, RL, sweeps, material library,
CAD-RCS incl. STL import, which is parsed in the browser), and the openEMS **Run** buttons —
those execute on the Windows PC, so the phone is just the front end. STEP import also works,
because the tessellation happens on the PC too.

Notes:
- **HTTPS is required** for installation and for the service worker; the Tailscale Funnel link
  is HTTPS, so that is satisfied. A plain `http://<lan-ip>:8731` address will still load the app
  but cannot be installed.
- The service worker caches only the app shell and the CDN libraries. It **never** caches
  `/run*`, `/upload*`, `/progress`, `/results`, `/cad` or `/fullwave_figures`, so a solve
  launched from a phone is always a real, fresh solve.
- After a `git pull` + bridge restart, the app updates itself on next launch (the document is
  fetched network-first, and a new service worker triggers a single reload).
- The material library lives in each browser's local storage, so it is per-device — the tester
  pins their own materials.
