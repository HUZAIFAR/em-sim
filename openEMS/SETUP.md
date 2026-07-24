# openEMS bridge — setup & first-run (macOS, Apple Silicon)

openEMS is a free, open-source full-wave FDTD solver. It is peer-reviewed and
publication-grade — cite it as:

> T. Liebig, A. Rennings, S. Held, D. Erni, "openEMS – a free and open source
> equivalent-circuit (EC) FDTD simulation platform...", *International Journal of
> Numerical Modelling*, 2012. DOI: 10.1002/jnm.1875

Published benchmarks put it within ~3% of commercial full-wave solvers on standard problems.

> **How this project actually drives openEMS.** The Run buttons in
> `waveguide_simulator.html` talk to a local **Flask bridge** (`openems_server.py`, port
> **8731**). On each request the bridge writes a params file, launches **GNU Octave**
> scripts (`wg_run.m`, `wg_farfield.m`, `cad/horn_run.m`) that drive openEMS through its
> **Octave/CSXCAD interfaces**, then post-processes the field dumps with **Python
> (NumPy / PyVista / imageio)**. It does **not** use the openEMS *Python* bindings — the
> solver is driven from Octave. So the toolchain you need is: openEMS + CSXCAD, GNU
> Octave, and a Python with the post-processing libs.

---

## 1. Install the toolchain

**openEMS + CSXCAD (Homebrew, Apple Silicon):**
```
brew tap vinn-ie/openems
brew install openems csxcad
```
This lands them under `/opt/homebrew/Cellar/openems/<ver>` and `/opt/homebrew/Cellar/csxcad/<ver>`.
The Octave interface ships under `.../share/openEMS/matlab` and `.../share/CSXCAD/matlab`;
`wg_run.m` / `horn_run.m` `addpath()` those locations (version-pinned — re-point them after a
`brew upgrade`, see `RESUME_TOMORROW.md`).

**GNU Octave** (drives the solver):
```
brew install octave
```

**Python post-processing libs** (renders, 3-D field export, reports):
```
pip install flask pyvista imageio imageio-ffmpeg numpy      # add --break-system-packages if needed
```
The bridge invokes the interpreter in the `PYTHON` constant at the top of
`openems_server.py` (currently an Anaconda python); the Octave binary is the `OCTAVE`
constant. Genericize both for a new machine.

**Quick sanity check** that the pieces are found:
```
octave --no-gui --eval "disp('octave ok')"
python -c "import flask, numpy, pyvista, imageio; print('python libs ok')"
ls /opt/homebrew/Cellar/openems /opt/homebrew/Cellar/csxcad
```

---

## 2. First run — the bridge on a KNOWN case

```
python "openEMS/openems_server.py"          # prints  http://localhost:8731
```
Open **http://localhost:8731** in a browser, go to **Full-wave (openEMS)**, keep the
default **Solid copper · X-band**, tick *Guided wave* + *S-parameters*, and press
**Run on openEMS**. A solve takes ~1–3 min.

This is the toolchain sanity check: copper WR-90 should track the analytical model
(≈ 0.108 dB/m at 10 GHz on the analytical/dashed curve). openEMS's own magnitude is
coarse-mesh approximate — the app labels it as such and treats the analytical curve as
the precise number. The run appends a row to `run_history.csv` (openEMS vs model,
normalized by the true port-plane separation).

---

## 3. What the bridge produces

1. **Waveguide** (`/run`): S-parameters, insertion loss, R/T/A, field renders (time GIF or
   frequency-domain steady |E| still), a wall-loss map, an angle sweep, and an NF2FF
   far-field pattern. Fixed-name outputs are cleared before each run so a skipped step
   never serves stale data.
2. **Horn** (`/run_horn`): gain-vs-frequency, S11/VSWR/impedance, E-/H-plane radiation
   pattern (E-plane = φ=90°, H-plane = φ=0°) with co-/cross-pol, an interactive 3-D |E|
   volume, and a coating comparison (per-coating efficiency via the surface-impedance
   method from one PEC solve).

The flat-slab R/T/A is exact via the transfer-matrix model, so it isn't run through FDTD.

---

## 4. For the writeup
Cite openEMS (above); validate against the analytic copper value; include a short
mesh-convergence note (halve the cell size, show the result barely moves). That's the
standard, defensible package.
