#!/usr/bin/env python3
"""
Local bridge server for the openEMS automation pipeline.

Start it once:
    /opt/anaconda3/bin/pip install flask        # one time
    /opt/anaconda3/bin/python "<proj>/openEMS/openems_server.py"

Then open   http://localhost:8731   in your browser (this serves your HTML).
In the Full-wave tab, pick band / material / coats and hit "Run on openEMS":
the page POSTs the config here -> we build + solve in openEMS -> render the 3-D
field -> and hand the S-parameter CSV + field images back to the page.
"""
import os, sys, subprocess, time, shutil, math, cmath, json
from flask import Flask, request, jsonify, send_from_directory

def oblique_rta(fGHz, thetaDeg, sigma, d, epsr=1.0, epspp=0.0, mur=1.0, mupp=0.0):
    """Analytical TE oblique-incidence R/T/A for a single lossy wall slab (air on both sides)."""
    EPS0=8.8541878128e-12; MU0=4*math.pi*1e-7; C=299792458.0
    w=2*math.pi*fGHz*1e9; k0=w/C
    th=math.radians(thetaDeg); st=math.sin(th); ct=max(math.cos(th),1e-6)
    epsc = epsr - 1j*(sigma + w*EPS0*epspp)/(w*EPS0)   # complex relative permittivity of the wall
    muc  = mur - 1j*mupp
    kz = k0*cmath.sqrt(epsc*muc - st*st)               # transverse wavenumber inside the slab
    Z  = w*MU0*muc/kz                                   # TE wave impedance in the slab
    Z0 = w*MU0/(k0*ct)                                  # TE wave impedance in air
    ph = kz*d; c=cmath.cos(ph); s=cmath.sin(ph)
    A=c; B=1j*Z*s; Cc=1j*s/Z; D=c                       # slab ABCD (TE)
    den = A*Z0 + B + Z0*(Cc*Z0 + D)
    G = (A*Z0 + B - Z0*(Cc*Z0 + D))/den
    T = 2*Z0/den
    R=abs(G)**2; Tp=abs(T)**2
    return R, Tp, max(0.0, 1.0 - R - Tp)

def analytic_loss_dBpm(fHz, a_m, b_m, sigma, thick, mur=1.0, epspp=0.0, mupp=0.0, epsr=1.0):
    """TE10 conductor attenuation (Pozar), matching the browser model, in dB/m.
    Used to cross-check the openEMS S21 against the validated analytical prediction."""
    EPS0=8.8541878128e-12; MU0=4*math.pi*1e-7; C=299792458.0; ETA0=math.sqrt(MU0/EPS0)
    fc = C/(2*a_m)
    if fHz <= fc: return float('inf')
    w = 2*math.pi*fHz
    sige = sigma + w*EPS0*epspp
    delta = 1.0/math.sqrt(math.pi*fHz*MU0*mur*sige)
    re = w*MU0*mupp/sige; im = w*MU0*mur/sige
    r = math.hypot(re, im); Rs = math.sqrt((r+re)/2)
    if thick is not None and thick > 0: Rs = Rs/math.tanh(thick/delta)
    ratio = fc/fHz
    return (Rs/(b_m*ETA0*math.sqrt(1-ratio*ratio)))*(1+2*(b_m/a_m)*ratio*ratio)*8.685889638

def _rows(path):
    try:
        out=[]
        for ln in open(path).read().splitlines():
            p=ln.split(',')
            try: out.append([float(x) for x in p])
            except Exception: pass
        return out
    except Exception:
        return []

def _nearest(rows, fghz):
    return min(rows, key=lambda r: abs(r[0]-fghz)) if rows else None

# --- machine/OS-portable config (env vars override; macOS defaults preserved) --------
# Project root = the folder that CONTAINS this openEMS/ dir — derived, never hardcoded, so
# the same file works on any machine/OS. (This used to be an absolute /Users/... path.)
_IS_WIN = (os.name == "nt")
OEMS   = os.path.dirname(os.path.abspath(__file__))
PROJ   = os.path.dirname(OEMS)
FIGS   = os.path.join(PROJ, "fullwave_figures")
RESULTS= os.path.join(OEMS, "results")
# Interpreters: set OPENEMS_OCTAVE / OPENEMS_PYTHON on Windows (or any non-mac box).
OCTAVE = os.environ.get("OPENEMS_OCTAVE") or ("/opt/homebrew/bin/octave" if not _IS_WIN
             else (shutil.which("octave-cli") or shutil.which("octave") or "octave-cli"))
PYTHON = os.environ.get("OPENEMS_PYTHON") or ("/opt/anaconda3/bin/python" if not _IS_WIN
             else (sys.executable or "python"))   # must be the python that has pyvista+flask
# Scratch dir shared by the Octave solvers (write dumps) and Python renderers (read them).
# MUST contain no spaces (openEMS shells out). Set OPENEMS_SCRATCH to override.
SCRATCH= os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if _IS_WIN else "/tmp")
try: os.makedirs(SCRATCH, exist_ok=True)
except Exception: pass
os.environ["OPENEMS_SCRATCH"] = SCRATCH        # inherited by every octave/python child process
HOST     = os.environ.get("OPENEMS_HOST", "127.0.0.1")     # 127.0.0.1 is enough behind Tailscale Funnel
PORT     = int(os.environ.get("OPENEMS_PORT", "8731"))
THREADED = os.environ.get("OPENEMS_THREADED", "1") != "0"  # threaded => /progress can poll during a run

# band -> (a_mm, b_mm, fmin_Hz, fmax_Hz)
BANDS = {
    "X":  (22.86, 10.16, 8e9,  12e9),
    "Ku": (15.80,  7.90, 12e9, 18e9),
    "K":  (10.67,  4.32, 18e9, 27e9),
}

app = Flask(__name__)

# ------------------------------------------------------------------ progress streaming
# openEMS is a long-running subprocess; capture_output buffers everything until it exits,
# so nothing reaches the log until a step finishes. stream_run() instead pumps the child's
# stdout line-by-line into the step's log file in real time (a background thread), while
# still enforcing a hard timeout via p.wait(). /progress then tails that log and parses the
# openEMS FDTD energy-decay line so the client can show TRUE progress, not just an estimate.
import threading, re as _re
_PROG_LOGS = {"wg": "last_run.log", "horn": "last_horn_run.log", "rcs": "last_rcs_run.log"}

def stream_run(args, logfile, timeout_s, tag):
    """Run args, streaming merged stdout/stderr into logfile live. Returns an object with
    .returncode/.stdout/.stderr so callers behave exactly as with subprocess.run(). Raises
    subprocess.TimeoutExpired on timeout (same as before) so the existing handler still fires."""
    try:
        with open(logfile, "a") as lf:
            lf.write(f"\n===== {tag} (streaming) =====\n"); lf.flush()
    except Exception:
        pass
    lines = []
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    def _pump():
        try:
            with open(logfile, "a") as lf:
                for line in p.stdout:
                    lines.append(line); lf.write(line); lf.flush()
                    print(line, end="", flush=True)
        except Exception:
            pass
    t = threading.Thread(target=_pump, daemon=True); t.start()
    try:
        p.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill(); t.join(timeout=2)
        raise
    t.join(timeout=5)
    class _R: pass
    r = _R(); r.returncode = p.returncode; r.stdout = "".join(lines); r.stderr = ""
    return r

def _parse_progress(text, target_db=40.0):
    """From an openEMS log tail, return {percent,line,energy_db,elapsed_s} for the newest
    progress marker. FDTD prints '[@  24s] Timestep: N || ... || Energy: ~x (-YY.YYdB)';
    the run ends when the energy has decayed by ~target_db, so percent = decay/target."""
    last = None
    for m in _re.finditer(r"\[@\s*(\d+)s\][^\n]*?Energy:[^\(]*\(\s*(-?\d+(?:\.\d+)?)\s*dB\)", text):
        last = (float(m.group(1)), float(m.group(2)), m.group(0))
    if last is not None:
        elapsed, edb, line = last
        pct = max(1.0, min(99.0, (-edb) / max(1.0, target_db) * 100.0))
        return {"percent": round(pct, 1), "line": line.strip(), "energy_db": edb, "elapsed_s": elapsed}
    # horn / sweep style: bare 'NN.N%' tokens
    pcts = _re.findall(r"(\d+(?:\.\d+)?)%", text)
    if pcts:
        return {"percent": max(1.0, min(99.0, float(pcts[-1]))), "line": pcts[-1] + "%"}
    return None

@app.route("/progress")
def progress():
    kind = request.args.get("kind", "rcs")
    fn = _PROG_LOGS.get(kind, "last_rcs_run.log")
    path = os.path.join(OEMS, fn)
    try:
        target = float(request.args.get("target_db", 40.0))
    except Exception:
        target = 40.0
    try:
        with open(path, "r") as f:
            f.seek(0, os.SEEK_END); size = f.tell()
            f.seek(max(0, size - 20000)); tail = f.read()
    except Exception:
        return jsonify({"ok": False, "stage": None, "percent": None})
    # last "===== <tag> =====" header is the current stage
    stages = _re.findall(r"=====\s*(.+?)\s*(?:\(streaming\)|\(returncode)", tail)
    prog = _parse_progress(tail, target)
    return jsonify({"ok": True, "kind": kind, "stage": (stages[-1] if stages else None),
                    "percent": (prog or {}).get("percent"), "line": (prog or {}).get("line"),
                    "energy_db": (prog or {}).get("energy_db")})

@app.errorhandler(Exception)
def _json_error(e):
    # Return a proper error JSON for ANY unhandled exception (subprocess timeout, bad numeric
    # cast, malformed request body, ...) so the client shows the real error instead of choking on
    # an HTML 500 and mislabelling it "Could not reach the bridge". HTTP errors pass through.
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    import traceback
    tb = traceback.format_exc()
    print("UNHANDLED:", tb, flush=True)
    return jsonify({"ok": False, "stage": "server",
                    "log": f"{type(e).__name__}: {e}", "trace": tb[-2000:]}), 500

@app.route("/")
def index():
    return send_from_directory(PROJ, "waveguide_simulator.html")

@app.route("/fullwave_figures/<path:fn>")
def figs(fn):
    return send_from_directory(FIGS, fn)

@app.route("/results/<path:fn>")
def results(fn):
    return send_from_directory(RESULTS, fn)

CAD = os.path.join(OEMS, "cad")

@app.route("/cad/<path:fn>")
def cadfiles(fn):
    return send_from_directory(CAD, fn)

@app.route("/run", methods=["POST"])
def run():
    cfg = request.get_json(force=True)
    band = cfg.get("band", "X")
    if band not in BANDS:
        return jsonify({"ok": False, "error": f"unknown band {band}"}), 400
    a, b, fmin, fmax = BANDS[band]
    material = cfg.get("material", "mxene")
    coats    = int(cfg.get("coats", 20))
    length   = float(cfg.get("length", 200))
    shape    = cfg.get("shape", "waveguide")
    if shape not in ("waveguide", "block", "cylinder", "sphere"):
        shape = "waveguide"
    ports = int(cfg.get("ports", 2))            # 1 = reflection only (S11); 2 = thru (S11 + S21)
    if ports not in (1, 2):
        ports = 2
    cells = max(10, min(int(cfg.get("cells", 20)), 40))   # mesh density (cells per wavelength)
    field_mode = cfg.get("field_mode", "time")            # 'time' = animation, 'freq' = steady |E| DFT at f0
    if field_mode not in ("time", "freq"): field_mode = "time"

    # complex permittivity / permeability loss terms (only meaningful for the MXene test material)
    epsr = float(cfg.get("epsr", 1.0)); epspp = float(cfg.get("epspp", 0.0))
    mur  = float(cfg.get("mur", 1.0));  mupp  = float(cfg.get("mupp", 0.0))

    if material == "copper":
        sigma, thick, label = 5.8e7, 40e-6, "Copper"
        epsr, epspp, mur, mupp = 1.0, 0.0, 1.0, 0.0
    elif material == "aluminum":
        sigma, thick, label = 3.5e7, 40e-6, "Aluminum"
        epsr, epspp, mur, mupp = 1.0, 0.0, 1.0, 0.0
    elif material == "wood":
        # bare basswood: non-metal wall (modelled as a very poor conductor) -> strongly lossy/leaky,
        # so the field visibly decays along the guide (sigma low => high wall loss)
        sigma, thick, label = 1.0, 1.5e-3, "Basswood"
        epsr, epspp, mur, mupp = 1.9, 0.05, 1.0, 0.0
    elif material == "custom":
        # arbitrary material/combination from the Compare tab or Materials tab:
        # the caller supplies the wall conductivity, thickness, label and (optional) loss terms.
        sigma = float(cfg.get("sigma", 1.0e6))
        thick = max(float(cfg.get("thick", 20e-6)), 1e-7)
        label = str(cfg.get("label", "Custom material"))
    else:  # mxene-coated wood
        sigma, thick, label = 1.0e6, max(coats*1e-6, 1e-6), f"MXene-coated wood ({coats} coats)"

    # Escape the label for the Octave single-quoted string it is written into: double any
    # apostrophe (Octave's escape), drop newlines/control chars, and cap length. Without this a
    # material named e.g. "Adam's alloy" breaks the run, and a crafted label could inject Octave.
    label_oct = "".join(ch for ch in str(label) if ch >= " ").replace("'", "''")[:120]

    def write_params(shape):
        p = (f"p_a = {a};\np_b = {b};\np_len = {length};\n"
             f"p_fmin = {fmin};\np_fmax = {fmax};\n"
             f"p_sigma = {sigma};\np_thick = {thick};\n"
             f"p_epsr = {epsr};\np_epspp = {epspp};\n"
             f"p_mur = {mur};\np_mupp = {mupp};\n"
             f"p_shape = '{shape}';\n"
             f"p_ports = {ports};\n"
             f"p_cells = {cells};\n"
             f"p_field_mode = '{field_mode}';\n"
             f"p_label = '{label_oct} {band}-band {shape}';\n"
             f"p_outdir = '{RESULTS}';\n")
        with open(os.path.join(OEMS, "wg_params.m"), "w") as f:
            f.write(p)

    OCT = [OCTAVE, "--no-gui"]
    LOGFILE = os.path.join(OEMS, "last_run.log")
    try: open(LOGFILE, "w").write(f"openEMS run log — {time.strftime('%Y-%m-%d %H:%M:%S')}\nconfig: {cfg}\n")
    except Exception: pass
    def _log(tag, r):
        # append this step's full stdout/stderr to last_run.log AND print to the server console
        block = (f"\n===== {tag}  (returncode={r.returncode}) =====\n"
                 + "--- stdout ---\n" + (r.stdout or "")[-6000:]
                 + "\n--- stderr ---\n" + (r.stderr or "")[-6000:] + "\n")
        try: open(LOGFILE, "a").write(block)
        except Exception: pass
        print(block, flush=True)
    stdout_by = {}
    def solve(shp):
        write_params(shp)
        r = stream_run(OCT + [os.path.join(OEMS, "wg_run.m")], LOGFILE, 1800, f"octave wg_run.m [{shp}]")
        stdout_by[shp] = r.stdout or ""
        return None if r.returncode == 0 else (r.stdout[-2500:] + "\n" + r.stderr[-1500:])
    def render(base, title, mode=None):
        args = [PYTHON, os.path.join(OEMS, "render_field.py"), base, title]
        if mode: args.append(mode)
        r = subprocess.run(args, capture_output=True, text=True, timeout=1800)
        _log(f"render {base} {mode or ''}", r)
        return None if r.returncode == 0 else (r.stdout[-1200:] + "\n" + r.stderr[-1200:])
    def render_freq(base, title):
        # frequency-domain steady |E| still from the openEMS DFT dump (Ef_*.vtr)
        r = subprocess.run([PYTHON, os.path.join(OEMS, "render_field_freq.py"), base, title],
                           capture_output=True, text=True, timeout=1800)
        _log(f"render_freq {base}", r)
        return None if r.returncode == 0 else (r.stdout[-1200:] + "\n" + r.stderr[-1200:])
    sims = cfg.get("sims") or ["guided", "reflection"]
    stamp = int(time.time())
    def cp(folder, src, dst):
        s = os.path.join(folder, src)
        if os.path.exists(s):
            try: shutil.copy(s, os.path.join(folder, dst)); return True
            except Exception: return False
        return False

    t0 = time.time()
    results, errors = {}, {}
    il_url = None

    # Clear fixed-name outputs from any previous run so a skipped/failed step can never serve or
    # log stale data (each solve/render below rewrites only the files it actually produces). The
    # accuracy-history block and 1-port runs read these fixed names, so staleness would corrupt them.
    for _stale in ("insertion_loss.csv", "rta_reflector.csv", "rta_waveguide.csv",
                   "sparams_waveguide.csv", "sparams_reflector.csv", "farfield_wg.csv", "port_sep.txt"):
        try: os.remove(os.path.join(RESULTS, _stale))
        except OSError: pass
    for _stale in ("field_guide.gif", "field_guide_still.png", "field_guide_loss.png",
                   "field_reflector.gif", "field_reflector_still.png"):
        try: os.remove(os.path.join(FIGS, _stale))
        except OSError: pass

    # ---- rectangular waveguide: guided solve feeds guided / sparams / fieldmap ----
    if any(s in sims for s in ("guided", "sparams", "fieldmap")):
        e = solve(shape)
        if e: errors["guided"] = e
        else:
            ic = f"insertion_loss_{stamp}.csv"; cp(RESULTS, "insertion_loss.csv", ic); il_url = f"/results/{ic}"
            sp = f"sparams_{stamp}.csv"; has_sp = cp(RESULTS, f"sparams_{shape}.csv", sp)
            gs_url = gg_url = None
            if ("guided" in sims) or ("fieldmap" in sims):
                if field_mode == "freq":
                    # frequency-domain: single steady |E| still (no animation)
                    er = render_freq("field_guide", f"{label} {band}-band  -  steady |E| at f0 (frequency-domain)")
                    if er: errors["guided_render"] = er
                    else:
                        gs = f"field_guide_{stamp}_still.png"; cp(FIGS, "field_guide_still.png", gs); gs_url = f"/fullwave_figures/{gs}"
                else:
                    er = render("field_guide", f"{label} {band}-band  -  guided wave")
                    if er: errors["guided_render"] = er
                    else:
                        gg = f"field_guide_{stamp}.gif"; cp(FIGS, "field_guide.gif", gg); gg_url = f"/fullwave_figures/{gg}"
                        gs = f"field_guide_{stamp}_still.png"; cp(FIGS, "field_guide_still.png", gs); gs_url = f"/fullwave_figures/{gs}"
            if "guided" in sims:
                results["guided"] = {"gif": gg_url, "still": gs_url, "il": il_url}
            if "sparams" in sims:
                results["sparams"] = {"csv": (f"/results/{sp}" if has_sp else None), "il": il_url}
            if "fieldmap" in sims:
                el = render("field_guide", f"{label} {band}-band  -  loss density", "loss")
                fm_url = None
                if not el:
                    fm = f"field_loss_{stamp}.png"
                    if cp(FIGS, "field_guide_loss.png", fm): fm_url = f"/fullwave_figures/{fm}"
                results["fieldmap"] = {"loss": fm_url, "field": gs_url}

    # ---- reflection ----
    if "reflection" in sims:
        e = solve("reflector")
        if e: errors["reflection"] = e
        else:
            rc = f"rta_reflector_{stamp}.csv"; cp(RESULTS, "rta_reflector.csv", rc)
            rg_url = rs_url = None
            er = render("field_reflector", f"{label} {band}-band  -  reflection")
            if er: errors["reflection_render"] = er
            else:
                rg = f"field_reflector_{stamp}.gif"; cp(FIGS, "field_reflector.gif", rg); rg_url = f"/fullwave_figures/{rg}"
                rs = f"field_reflector_{stamp}_still.png"; cp(FIGS, "field_reflector_still.png", rs); rs_url = f"/fullwave_figures/{rs}"
            results["reflection"] = {"gif": rg_url, "still": rs_url, "rta": f"/results/{rc}"}

    # ---- angle-of-incidence sweep (analytical oblique model) ----
    if "angle" in sims:
        try:
            fc = 0.5 * (fmin + fmax) / 1e9
            fn = f"angle_{stamp}.csv"
            with open(os.path.join(RESULTS, fn), "w") as f:
                f.write("angle_deg,R,T,A\n")
                for th in range(0, 86, 5):
                    R, T, A = oblique_rta(fc, th, sigma, thick, epsr, epspp, mur, mupp)
                    f.write(f"{th},{R:.5f},{T:.5f},{A:.5f}\n")
            results["angle"] = {"csv": f"/results/{fn}", "note": "analytical oblique-incidence model"}
        except Exception as ex:
            errors["angle"] = str(ex)

    # ---- far-field radiation pattern (openEMS NF2FF from the open end) ----
    if "farfield" in sims:
        try:
            write_params("waveguide")     # reset shape (reflection may have left 'reflector')
            rff = subprocess.run(OCT + [os.path.join(OEMS, "wg_farfield.m")],
                                 capture_output=True, text=True, timeout=1800)
            _log("octave wg_farfield.m", rff)
            if rff.returncode != 0:
                errors["farfield"] = (rff.stdout[-2500:] + "\n" + rff.stderr[-1500:])
            else:
                ff = f"farfield_{stamp}.csv"
                if cp(RESULTS, "farfield_wg.csv", ff):
                    results["farfield"] = {"csv": f"/results/{ff}",
                                           "note": "openEMS NF2FF far-field (normalized E/H-plane)"}
                else:
                    errors["farfield"] = "far-field solve produced no farfield_wg.csv"
        except Exception as ex:
            errors["farfield"] = str(ex)

    # true S21 measurement-plane separation (mm), written by wg_run.m; fall back to full length
    try:
        with open(os.path.join(RESULTS, "port_sep.txt")) as _pf: port_sep_mm = float(_pf.read().strip())
    except Exception:
        port_sep_mm = float(length)
    sep_m = (port_sep_mm/1000.0) if port_sep_mm > 0 else (length/1000.0)

    # ---- append an accuracy row to run_history.csv: openEMS result vs analytical model ----
    try:
        il = _rows(os.path.join(RESULTS, "insertion_loss.csv"))
        if il:  # a guided solve ran
            fmid = 0.5*(fmin+fmax)/1e9
            def _f(v): return "" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
            ilrow = _nearest(il, fmid); oe_s21 = ilrow[1] if ilrow else None
            oe_pwr = (10**(oe_s21/10)*100) if oe_s21 is not None else None
            # normalise by the port-plane separation the S21 was actually measured over (not p_len)
            oe_ins = (abs(oe_s21)/sep_m) if oe_s21 is not None else None
            rt = _rows(os.path.join(RESULTS, "rta_reflector.csv")); rtrow = _nearest(rt, fmid)
            oe_R = (rtrow[1]*100) if rtrow else None
            # match the browser model: the thin-film (tanh) correction applies only to a
            # thin conductor coating; a thick dielectric/solid wall uses thick=None.
            _thk = thick if sigma >= 1e4 else None
            mloss = analytic_loss_dBpm(fmid*1e9, a/1000.0, b/1000.0, sigma, _thk, mur, epspp, mupp, epsr)
            # model S21 over the SAME measurement distance, so S21_err_dB is apples-to-apples
            mS21  = (-mloss*sep_m) if math.isfinite(mloss) else None
            err   = (oe_s21 - mS21) if (oe_s21 is not None and mS21 is not None) else None
            conv  = "N" if ("Max. number of timesteps was reached" in stdout_by.get(shape, "")) else "Y"
            note  = ("leaky/dielectric wall (block model - not expected to match analytical)"
                     if sigma < 1e4 else "conductor - openEMS should track the analytical model")
            hist = os.path.join(OEMS, "run_history.csv")
            if not os.path.exists(hist):
                open(hist, "w").write("timestamp,material,band,length_mm,coats,sims,"
                    "oe_S21_dB,oe_power_pct,oe_ins_dB_per_m,oe_R_pct,"
                    "model_loss_dB_per_m,model_S21_dB,S21_err_dB,converged,note\n")
            open(hist, "a").write(",".join([
                time.strftime("%Y-%m-%d %H:%M:%S"), '"'+str(label)+'"', band, str(length), str(coats),
                "|".join(sims), _f(oe_s21), _f(oe_pwr), _f(oe_ins), _f(oe_R),
                _f(mloss), _f(mS21), _f(err), conv, '"'+note+'"']) + "\n")
    except Exception as ex:
        print("history log error:", ex, flush=True)

    ok = len(results) > 0
    g = results.get("guided", {}); r = results.get("reflection", {})
    resp = {
        "ok": ok,
        "label": f"{label} · {band}-band",
        "seconds": round(time.time() - t0, 1),
        "sims": sims, "results": results, "errors": errors,
        "material": label, "band": band, "coats": coats, "length": length,
        "port_sep_mm": round(port_sep_mm, 3),   # true S21 measurement-plane separation for dB/m
        # backward-compatible fields used by the existing Full-wave UI
        "csv": il_url, "rta": r.get("rta"),
        "guide_gif": g.get("gif"), "guide_still": g.get("still"),
        "reflector_gif": r.get("gif"), "reflector_still": r.get("still"),
    }
    if not ok:
        resp["stage"] = next(iter(errors.keys()), "run")
        resp["log"]   = next(iter(errors.values()), "no simulations produced output")
    return jsonify(resp), (200 if ok else 500)

COAT_SIGMA = {"mxene": 1.0e6, "copper": 5.8e7, "silver": 6.3e7,
              "aluminum": 3.5e7, "pec": float("inf")}
COAT_LABEL = {"mxene": "MXene", "copper": "Copper", "silver": "Silver",
              "aluminum": "Aluminum", "pec": "PEC (ideal)"}

def _csv_dicts(path):
    import csv
    try:
        return list(csv.DictReader(open(path)))
    except Exception:
        return []

@app.route("/run_horn", methods=["POST"])
def run_horn():
    """Horn-antenna pipeline: (optional) STEP upload -> STL -> derive dims ->
    openEMS full-wave solve (gain, S11, interior field) -> conductor-loss for
    every coating from that one field. Returns an image + numbers for a new tab."""
    import json, glob, csv as _csv
    CADRES = os.path.join(CAD, "horn_results")
    os.makedirs(CAD, exist_ok=True)
    band = (request.form.get("band") or "X")
    coating = (request.form.get("coating") or "mxene").lower()
    try: cells = max(10, min(int(request.form.get("cells", 15)), 30))   # mesh density
    except Exception: cells = 15
    field_mode = (request.form.get("field_mode") or "freq")   # 'freq' = steady |E| still, 'time' = animation
    if field_mode not in ("time", "freq"): field_mode = "freq"
    if band not in BANDS: band = "X"
    a, b, fmin, fmax = BANDS[band]
    f0 = 0.5 * (fmin + fmax)

    LOG = os.path.join(OEMS, "last_horn_run.log")
    try: open(LOG, "w").write(f"horn run — {time.strftime('%Y-%m-%d %H:%M:%S')}  band={band} coating={coating}\n")
    except Exception: pass
    def logstep(tag, r):
        blk = (f"\n===== {tag} (rc={r.returncode}) =====\n--- stdout ---\n{(r.stdout or '')[-6000:]}"
               f"\n--- stderr ---\n{(r.stderr or '')[-6000:]}\n")
        try: open(LOG, "a").write(blk)
        except Exception: pass
        print(blk, flush=True)

    t0 = time.time()
    stl = os.path.join(CAD, "horn.stl")

    # 1) if a STEP file was uploaded, convert it and derive dimensions
    dims = None
    up = request.files.get("step")
    try:
        if up and up.filename:
            up_path = os.path.join(CAD, "uploaded.step")
            up.save(up_path)
            r = subprocess.run([PYTHON, os.path.join(CAD, "step2stl.py"), up_path, stl],
                               capture_output=True, text=True, timeout=600)
            logstep("step2stl", r)
            if r.returncode != 0:
                return jsonify({"ok": False, "stage": "convert",
                                "log": (r.stdout or "")[-1500:] + "\n" + (r.stderr or "")[-1500:]}), 500
            r = subprocess.run([PYTHON, os.path.join(CAD, "derive_horn_params.py"), stl,
                                "--a", str(a), "--b", str(b)], capture_output=True, text=True, timeout=300)
            logstep("derive", r)
            try: dims = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception: dims = None
    except Exception as ex:
        return jsonify({"ok": False, "stage": "convert", "log": str(ex)}), 500

    # validated defaults (used when no upload, or derivation failed)
    if not dims:
        dims = {"Ax": 68.0, "By": 49.0, "feed": 40.0, "flare": 123.0}
    if not os.path.exists(stl):
        return jsonify({"ok": False, "stage": "geometry",
                        "log": "No horn.stl and no uploaded STEP. Upload a .step file."}), 500

    # 2) write horn_params.m (PEC solve; wall loss for every coating is computed after)
    params = (f"a={a}; b={b}; Ax={dims['Ax']}; By={dims['By']}; "
              f"feed={dims['feed']}; flare={dims['flare']}; tw=2.0;\n"
              f"f_start={fmin}; f_stop={fmax}; f0={f0};\n"
              f"WALL='PEC'; sigma_wall=5.8e7; coat_thick=20e-6; tag='pec';\n"
              f"p_cells={cells};\n"
              f"p_field_mode='{field_mode}';\n")
    open(os.path.join(CAD, "horn_params.m"), "w").write(params)

    try:
        # 3) full-wave solve (streamed live into the log so /progress can track it)
        r = stream_run([OCTAVE, "--no-gui", os.path.join(CAD, "horn_run.m")], LOG, 1800, "horn_run.m")
        if r.returncode != 0:
            return jsonify({"ok": False, "stage": "solve",
                            "log": (r.stdout or "")[-2000:] + "\n" + (r.stderr or "")[-1500:]}), 500
        # 4) interior-field render
        r = subprocess.run([PYTHON, os.path.join(CAD, "render_horn.py"), field_mode],
                           capture_output=True, text=True, timeout=900)
        logstep("render_horn", r)
        # 4b) export the 3-D E-field volume -> compact JSON for the interactive field viewer (fail-soft)
        r = subprocess.run([PYTHON, os.path.join(CAD, "export_field3d.py")],
                           capture_output=True, text=True, timeout=300)
        logstep("export_field3d", r)
        # 5) geometry snapshot (nice-to-have)
        try:
            subprocess.run([PYTHON, os.path.join(CAD, "view_stl.py"), stl, "--shots", "--no-window"],
                           capture_output=True, text=True, timeout=300)
        except Exception: pass
        # 6) conductor loss for every coating
        r = subprocess.run([PYTHON, os.path.join(CAD, "horn_wallloss.py")],
                           capture_output=True, text=True, timeout=600)
        logstep("horn_wallloss", r)
        # 7) derived antenna metrics (HPBW, sidelobe, F/B, effs) + paper-style Excel
        r = subprocess.run([PYTHON, os.path.join(CAD, "horn_report.py"), "pec"],
                           capture_output=True, text=True, timeout=600)
        logstep("horn_report", r)
    finally:
        try: os.remove(os.path.join(CAD, "horn_params.m"))   # restore standalone defaults
        except Exception: pass

    # ---- collect results ----
    stamp = int(time.time())
    def _num(x):
        try: return float(x)
        except Exception: return None
    gain = _csv_dicts(os.path.join(CADRES, "horn_gain_pec.csv"))
    grow = min(gain, key=lambda x: abs(float(x["freq_ghz"]) - f0/1e9)) if gain else None
    table = _csv_dicts(os.path.join(CADRES, "horn_coating_loss.csv"))
    sel = None
    want = COAT_LABEL.get(coating, "MXene")
    for row in table:
        if row.get("material", "").startswith(want.split()[0]):
            sel = row; break

    # gain-vs-frequency curve
    gain_curve = [{"freq_ghz": _num(r.get("freq_ghz")), "Dmax_dBi": _num(r.get("Dmax_dBi")),
                   "s11_db": _num(r.get("s11_db")), "rad_eff_pct": _num(r.get("rad_eff_pct")),
                   "aperture_eff_pct": _num(r.get("aperture_eff_pct"))} for r in gain]
    # S11-vs-frequency curve
    s11rows = _csv_dicts(os.path.join(CADRES, "horn_s11_pec.csv"))
    s11_curve = [{"freq_ghz": _num(r.get("freq_ghz")), "s11_db": _num(r.get("s11_db"))} for r in s11rows]
    # radiation pattern at f0 (E-plane phi=0, H-plane phi=90)
    prows = _csv_dicts(os.path.join(CADRES, "horn_pattern_pec.csv"))
    pattern = {"theta": [_num(r.get("theta_deg")) for r in prows],
               "E": [_num(r.get("gain_Eplane_dBi")) for r in prows],
               "H": [_num(r.get("gain_Hplane_dBi")) for r in prows]}
    # derived metrics (HPBW, sidelobe, F/B, efficiencies)
    metrics = {}
    for r in _csv_dicts(os.path.join(CADRES, "horn_metrics.csv")):
        metrics[r.get("metric")] = _num(r.get("value"))

    def _img(name, base=CADRES):
        return f"/cad/horn_results/{name}?t={stamp}" if os.path.exists(os.path.join(base, name)) else None
    field_lin = _img("horn_field_lin.png"); field_db = _img("horn_field_db.png")
    field_img = field_lin or _img("horn_field.png")
    field_anim = _img("horn_field.gif")   # present only when Field view = time-domain
    geom_img  = f"/cad/horn_iso.png?t={stamp}" if os.path.exists(os.path.join(CAD, "horn_iso.png")) else None
    excel_url = _img("horn_results.xlsx")
    field3d   = _img("field3d.json")   # interactive 3-D E-field point cloud (None if export failed)

    resp = {
        "ok": True,
        "seconds": round(time.time() - t0, 1),
        "band": band, "coating": want,
        "dims": {"a": a, "b": b, **dims},
        "field_img": field_img, "field_img_lin": field_lin, "field_img_db": field_db,
        "field_anim": field_anim,
        "geom_img": geom_img, "excel_url": excel_url, "field3d": field3d,
        "gain": ({"Dmax_dBi": float(grow["Dmax_dBi"]), "s11_db": float(grow["s11_db"])} if grow else None),
        "selected": ({"material": sel["material"], "rad_eff_pct": float(sel["rad_eff_pct"]),
                      "gain_dBi": float(sel["gain_dBi"]), "gain_penalty_dB": float(sel["gain_penalty_dB"])}
                     if sel else None),
        "table": [{"material": row["material"], "rad_eff_pct": float(row["rad_eff_pct"]),
                   "gain_penalty_dB": float(row["gain_penalty_dB"]), "gain_dBi": float(row["gain_dBi"])}
                  for row in table],
        "gain_curve": gain_curve, "s11_curve": s11_curve, "pattern": pattern, "metrics": metrics,
    }
    return jsonify(resp), 200

@app.route("/upload_rcs", methods=["POST"])
def upload_rcs():
    """Accept a STEP/STL upload for the RCS import path: convert STEP->STL (step2stl.py),
    then recenter + convert to mm (normalize_stl.py). Returns the server-side STL path plus
    the normalized half-extent so the client can show the size and apply the electrical-size guard."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "log": "No file uploaded."}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".stl", ".step", ".stp"):
        return jsonify({"ok": False, "log": "Upload a .stl, .step or .stp file."}), 400
    updir = os.path.join(OEMS, "uploads"); os.makedirs(updir, exist_ok=True)
    src = os.path.join(updir, "rcs_upload" + ext)
    f.save(src)
    raw_stl = src
    if ext in (".step", ".stp"):
        raw_stl = os.path.join(updir, "rcs_upload_raw.stl")
        r = subprocess.run([PYTHON, os.path.join(CAD, "step2stl.py"), src, raw_stl],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.isfile(raw_stl):
            return jsonify({"ok": False, "stage": "step2stl",
                            "log": (r.stdout or "")[-1500:] + "\n" + (r.stderr or "")[-1500:]}), 500
    norm = os.path.join(updir, "rcs_target.stl")
    r = subprocess.run([PYTHON, os.path.join(CAD, "normalize_stl.py"), raw_stl, norm],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not os.path.isfile(norm):
        return jsonify({"ok": False, "stage": "normalize",
                        "log": (r.stdout or "")[-1500:] + "\n" + (r.stderr or "")[-1500:]}), 500
    try:
        info = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception as e:
        return jsonify({"ok": False, "stage": "normalize", "log": f"parse: {e}\n{r.stdout}"}), 500
    info["ok"] = True; info["stl"] = norm; info["stl_scale"] = 1.0   # already mm + centred
    return jsonify(info), 200

@app.route("/upload_cad", methods=["POST"])
def upload_cad():
    """STEP -> segmented triangle-mesh JSON for the ANALYTICAL CAD-RCS tab (gmsh/OCC).
    Each STEP solid becomes a named segment. STL is parsed client-side (no server needed);
    this route handles .step/.stp only. Returns the full facet JSON (verts + per-segment
    triangles, mm, recentred) inline so the browser PO+PTD engine can consume it directly."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "log": "No file uploaded."}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".step", ".stp"):
        return jsonify({"ok": False, "log": "This route accepts .step/.stp (STL is read in the browser)."}), 400
    updir = os.path.join(OEMS, "uploads"); os.makedirs(updir, exist_ok=True)
    src = os.path.join(updir, "cad_upload" + ext)
    f.save(src)
    outjson = os.path.join(updir, "cad_facets.json")
    try:
        if os.path.isfile(outjson):
            os.remove(outjson)                      # never serve a stale mesh on failure
    except Exception:
        pass
    try:
        r = subprocess.run([PYTHON, os.path.join(CAD, "step_facets.py"), src, outjson, "--max-tri", "40000"],
                           capture_output=True, text=True, timeout=600)
    except Exception as e:
        return jsonify({"ok": False, "stage": "tessellate", "log": str(e)}), 500
    if r.returncode != 0 or not os.path.isfile(outjson):
        return jsonify({"ok": False, "stage": "step_facets",
                        "log": (r.stdout or "")[-2000:] + "\n" + (r.stderr or "")[-2000:]}), 500
    try:
        with open(outjson) as jf:
            data = jf.read()
    except Exception as e:
        return jsonify({"ok": False, "stage": "read", "log": str(e)}), 500
    return app.response_class(data, mimetype="application/json")   # full mesh JSON, verbatim

@app.route("/run_rcs", methods=["POST"])
def run_rcs():
    # Radar cross section via a plane-wave (TF/SF) solve + NF2FF (see rcs_run.m).
    # Always runs the bare (PEC) target; if a coating is selected, also runs the coated target
    # and reports the RCS reduction in dB. Sphere -> Mie anchor, plate -> physical-optics anchor.
    cfg = request.get_json(force=True)
    shape = cfg.get("shape", "sphere")
    if shape not in ("sphere", "plate", "cylinder", "dihedral", "import"): shape = "sphere"
    band = cfg.get("band", "X")
    if band in BANDS:
        fmin, fmax = BANDS[band][2], BANDS[band][3]
    else:
        # custom band: clamp to a sane FDTD range and a bounded fractional bandwidth
        fmin = max(0.5, min(float(cfg.get("fmin_ghz", 8)), 110.0)) * 1e9
        fmax = max(0.5, min(float(cfg.get("fmax_ghz", 12)), 110.0)) * 1e9
        if fmax <= fmin: fmax = fmin * 1.2
        if fmax / fmin > 4.0: fmax = fmin * 4.0
        band = "custom"
    size1 = max(1.0, min(float(cfg.get("size1", 15.0)), 200.0))
    size2 = max(1.0, min(float(cfg.get("size2", size1)), 200.0))
    size3 = max(2.0, min(float(cfg.get("size3", 60.0)), 300.0))   # cylinder/dihedral height
    inc   = float(cfg.get("inc_deg", 0.0)) % 360.0
    cells = max(12, min(int(cfg.get("cells", 24)), 40))
    construct = cfg.get("construct", "coated" if cfg.get("coated") else "pec")
    if construct not in ("pec", "coated", "solid"): construct = "pec"
    coated = 1 if construct == "coated" else 0
    pol = "h" if str(cfg.get("pol", "v")).lower() == "h" else "v"
    nfreq = int(cfg.get("nfreq", 101));  nfreq = nfreq if nfreq in (51, 101, 201) else 101
    endcrit = float(cfg.get("endcrit", 1e-4))
    if endcrit not in (1e-3, 1e-4, 1e-5): endcrit = 1e-4
    sigma = max(0.0, float(cfg.get("sigma", 1.0e6))); thick = max(float(cfg.get("thick", 1e-3)), 1e-6)
    epsr  = max(1.0, float(cfg.get("epsr", 1.0))); epspp = max(0.0, float(cfg.get("epspp", 0.0)))
    mur   = max(0.1, float(cfg.get("mur", 1.0)));  mupp  = max(0.0, float(cfg.get("mupp", 0.0)))
    label = "".join(ch for ch in str(cfg.get("label", "target")) if ch >= " ").replace("'", "''")[:120]

    # imported CAD mesh (shape='import'): PEC-only, size1 carries the half-extent (mm) from /upload_rcs
    stl_path = ""; stl_scale = 1.0
    if shape == "import":
        stl_path = str(cfg.get("stl", ""))
        stl_scale = float(cfg.get("stl_scale", 1.0))
        construct = "pec"; coated = 0          # arbitrary meshes are solved as PEC (no coated/solid)
        if (not stl_path) or (not os.path.isfile(stl_path)):
            return jsonify({"ok": False, "stage": "config",
                            "log": "No imported mesh found on the server — upload a STEP/STL file first."}), 400

    # electrical-size guard: FDTD cost grows as (size/lambda)^3; refuse configurations that would
    # mesh into tens of millions of cells (a whole-vehicle problem — that's PO/SBR territory).
    lam_min_mm = 299792458e3 / fmax
    if shape in ("import", "sphere"):                 # size1 = mesh half-extent / radius
        obj_half_mm = size1
    elif shape in ("cylinder", "dihedral"):
        obj_half_mm = max(size1, size3 / 2.0)         # radius/arm in-plane, height/2 in z
    else:                                             # plate: half of the larger in-plane dim
        obj_half_mm = max(size1, size2) / 2.0
    # (mirrors rcs_run.m:59-70 — the guard must match the geometry the solver actually builds)
    if obj_half_mm > 5.0 * lam_min_mm:
        return jsonify({"ok": False, "stage": "config",
                        "log": (f"Target is too electrically large for full-wave FDTD here: half-extent "
                                f"{obj_half_mm:.0f} mm > 5x the shortest wavelength ({lam_min_mm:.1f} mm at "
                                f"{fmax/1e9:.1f} GHz). Reduce the size or the top frequency — electrically "
                                f"huge targets are what PO/SBR codes are for (see the RCS physics notes).")}), 400

    # which analyses were ticked; monostatic + H-plane are always computed (cheap, one solve).
    sims = cfg.get("sims") or ["monostatic", "bistatic-h"]
    do_field  = 1 if "field"      in sims else 0   # scattered-field GIF + still
    do_eplane = 1 if "bistatic-e" in sims else 0   # E-plane bistatic cut
    do_lobe   = 1 if "lobe3d"     in sims else 0   # 3-D scattering lobe
    do_polar  = 1 if "polar"      in sims else 0   # full 2x2 polarimetric matrix (needs a flipped-pol solve)
    stamp = str(int(time.time()))
    title = f"{cfg.get('label','target')} {band}-band"

    def write_params(tag, this_construct, inc_deg=None, this_cells=None, this_nfreq=None,
                     field=None, eplane=None, lobe=None, pol_override=None):
        p = (f"p_shape = '{shape}';\np_size1 = {size1};\np_size2 = {size2};\np_size3 = {size3};\n"
             f"p_fmin = {fmin};\np_fmax = {fmax};\np_inc_deg = {inc if inc_deg is None else inc_deg};\n"
             f"p_coated = 0;\np_construct = '{this_construct}';\np_pol = '{pol if pol_override is None else pol_override}';\n"
             f"p_sigma = {sigma};\np_thick = {thick};\n"
             f"p_epsr = {epsr};\np_epspp = {epspp};\np_mur = {mur};\np_mupp = {mupp};\n"
             f"p_cells = {cells if this_cells is None else this_cells};\n"
             f"p_nfreq = {nfreq if this_nfreq is None else this_nfreq};\np_endcrit = {endcrit};\n"
             f"p_stl = '{stl_path}';\np_stl_scale = {stl_scale};\n"
             f"p_tag = '{tag}';\np_outdir = '{RESULTS}';\n"
             f"p_do_field = {do_field if field is None else field};\n"
             f"p_do_eplane = {do_eplane if eplane is None else eplane};\n"
             f"p_do_lobe = {do_lobe if lobe is None else lobe};\n"
             f"p_label = '{label} {band}-band {shape}';\n")
        with open(os.path.join(OEMS, "rcs_params.m"), "w") as f:
            f.write(p)

    OCT = [OCTAVE, "--no-gui"]
    LOGFILE = os.path.join(OEMS, "last_rcs_run.log")
    try: open(LOGFILE, "w").write(f"RCS run log — {time.strftime('%Y-%m-%d %H:%M:%S')}\nconfig: {cfg}\n")
    except Exception: pass
    def solve(tag, this_construct, timeout_s=1800, **kw):
        write_params(tag, this_construct, **kw)
        r = stream_run(OCT + [os.path.join(OEMS, "rcs_run.m")], LOGFILE, timeout_s, f"octave rcs_run.m [{tag}]")
        return None if r.returncode == 0 else (r.stdout[-2500:] + "\n" + r.stderr[-1500:])

    # clear stale fixed-name RCS outputs so a failed run never serves a previous one's curves
    for tag in ("bare", "coated", "aspect"):
        for nm in (f"rcs_freq_{tag}.csv", f"rcs_bistatic_{tag}.csv", f"rcs_eplane_{tag}.csv", f"rcs_lobe_{tag}.csv"):
            try: os.remove(os.path.join(RESULTS, nm))
            except OSError: pass

    def read_curves(tag):
        fr = _rows(os.path.join(RESULTS, f"rcs_freq_{tag}.csv"))
        bi = _rows(os.path.join(RESULTS, f"rcs_bistatic_{tag}.csv"))
        ep = _rows(os.path.join(RESULTS, f"rcs_eplane_{tag}.csv"))
        if not fr: return None
        def _bi(r):
            d = {"phi": r[0], "m2": r[1], "dbsm": r[2]}
            if len(r) >= 5: d["co"] = r[3]; d["xpol"] = r[4]   # polarization split columns
            return d
        def _fr(r):
            d = {"f": r[0], "m2": r[1], "dbsm": r[2]}
            if len(r) >= 7:      # co/xpol dBsm + complex co-pol backscatter (for range profile & polarimetry)
                d["co"] = r[3]; d["xpol"] = r[4]; d["hco_re"] = r[5]; d["hco_im"] = r[6]
            return d
        d = {"freq":     [_fr(r) for r in fr],
             "bistatic": [_bi(r) for r in bi] if bi else []}
        if ep: d["eplane"] = [{"beta": r[0], "m2": r[1], "dbsm": r[2]} for r in ep]
        lo = _rows(os.path.join(RESULTS, f"rcs_lobe_{tag}.csv"))   # theta,phi,dbsm grid → interactive 3-D lobe
        if lo: d["lobe_grid"] = [{"t": r[0], "p": r[1], "d": r[2]} for r in lo]
        return d

    def stamp_files(tag):
        # copy fixed-name CSVs to stamped names so download links survive later solves (aspect loop
        # and future runs overwrite the fixed names). Returns {kind: url}.
        out = {}
        for kind, nm in (("freq", f"rcs_freq_{tag}.csv"), ("bistatic", f"rcs_bistatic_{tag}.csv"),
                         ("eplane", f"rcs_eplane_{tag}.csv"), ("lobe", f"rcs_lobe_{tag}.csv")):
            src = os.path.join(RESULTS, nm)
            if os.path.exists(src):
                dst = f"rcs_{kind}_{tag}_{stamp}.csv"
                try:
                    shutil.copyfile(src, os.path.join(RESULTS, dst))
                    out[kind] = f"/results/{dst}"
                except Exception:
                    pass
        return out

    def render(tag, curves):
        # Produce the scattered-field GIF/still and/or the 3-D lobe for this target. Fail-soft:
        # a render error is logged into `errors` but never fails the run (the charts still show).
        if curves is None: return
        if do_field:
            base = f"rcs_field_{tag}_{stamp}"
            rr = subprocess.run([PYTHON, os.path.join(OEMS, "render_rcs.py"), "field",
                                 os.path.join(SCRATCH, f"rcs_sim_{tag}"), base, title], capture_output=True, text=True, timeout=600)
            if rr.returncode == 0:
                curves["field_gif"]   = f"/fullwave_figures/{base}.gif?t={stamp}"
                curves["field_still"] = f"/fullwave_figures/{base}_still.png?t={stamp}"
            else:
                errors[f"field_render_{tag}"] = (rr.stderr or rr.stdout or "")[-500:]
        if do_lobe:
            base = f"rcs_lobe_{tag}_{stamp}"
            rr = subprocess.run([PYTHON, os.path.join(OEMS, "render_rcs.py"), "lobe",
                                 os.path.join(RESULTS, f"rcs_lobe_{tag}.csv"), base, title], capture_output=True, text=True, timeout=600)
            if rr.returncode == 0:
                curves["lobe_gif"]   = f"/fullwave_figures/{base}_lobe.gif?t={stamp}"
                curves["lobe_still"] = f"/fullwave_figures/{base}_lobe.png?t={stamp}"
            else:
                errors[f"lobe_render_{tag}"] = (rr.stderr or rr.stdout or "")[-500:]

    t0 = time.time()
    errors = {}
    files = {}
    # ---- bare-PEC reference solve (always; the analytical anchor + reduction baseline) ----
    e = solve("bare", "pec")
    if e:
        return jsonify({"ok": False, "stage": "bare", "log": e}), 500
    bare = read_curves("bare")
    if bare is None:
        return jsonify({"ok": False, "stage": "bare",
                        "log": "Octave exited cleanly but produced no rcs_freq_bare.csv — see openEMS/last_rcs_run.log for the solver output."}), 500
    render("bare", bare)                 # geometry is identical, so render the bare fields now
    files["bare"] = stamp_files("bare")
    # ---- material solve (coated PEC or solid material) ----
    coated_curves = None
    if construct != "pec":
        e = solve("coated", construct)
        if e: errors["material"] = e
        else:
            coated_curves = read_curves("coated")
            render("coated", coated_curves)
            files["coated"] = stamp_files("coated")

    f0 = 0.5 * (fmin + fmax) / 1e9
    def near(curve):
        return min(curve["freq"], key=lambda p: abs(p["f"] - f0)) if curve and curve["freq"] else None
    reduction = None
    b0, c0row = near(bare), near(coated_curves)
    if b0 and c0row:
        reduction = round(b0["dbsm"] - c0row["dbsm"], 2)   # positive = material lowers RCS vs bare metal

    # ---- polarimetric: a second solve with the OPPOSITE incident polarization, so the primary
    # solve (co,cross) + this flipped solve (co,cross) fill the full 2x2 scattering matrix. ----
    polar = None
    if do_polar:
        flip = "v" if pol == "h" else "h"
        try:
            e = solve("polar", construct, pol_override=flip, this_cells=min(cells, 24),
                      field=0, eplane=0, lobe=0, timeout_s=900)
            if e:
                errors["polar"] = e[-300:]
            else:
                pc = read_curves("polar"); prow = near(pc) if pc else None
                prim = near(coated_curves if coated_curves else bare)   # the primary result curve at f0
                if prow and prim and ("co" in prow) and ("co" in prim):
                    polar = {"pol_main": pol, "pol_flip": flip, "f0_ghz": round(f0, 3),
                             "main_co_dbsm": round(prim["co"], 2), "main_x_dbsm": round(prim["xpol"], 2),
                             "flip_co_dbsm": round(prow["co"], 2), "flip_x_dbsm": round(prow["xpol"], 2),
                             # complex co-pol of each solve (calibrated: |hco|^2 = co-pol RCS, consistent phase
                             # reference across the two solves) → lets the client do the Pauli decomposition
                             "main_hco": [prim.get("hco_re"), prim.get("hco_im")],
                             "flip_hco": [prow.get("hco_re"), prow.get("hco_im")]}
        except subprocess.TimeoutExpired:
            errors["polar"] = "polarimetric solve exceeded its time cap; skipped"

    # ---- monostatic-vs-aspect-angle turntable sweep (one coarse solve per angle; SLOW) ----
    aspect = None
    if "aspect" in sims:
        try:
            a0 = float(cfg.get("aspect_start", 0.0)); a1 = float(cfg.get("aspect_stop", 90.0))
            st = max(2.0, float(cfg.get("aspect_step", 15.0)))
        except Exception:
            a0, a1, st = 0.0, 90.0, 15.0
        if a1 < a0: a0, a1 = a1, a0
        n = int((a1 - a0) / st) + 1
        if n > 13: st = (a1 - a0) / 12.0; n = 13   # hard cap: 13 solves
        aspect = []
        for k in range(n):
            ang = round(a0 + k * st, 2)
            # coarse + fast per angle: capped mesh, 51 freq pts, no extras, and a 7-min per-angle
            # cap so a pathological config can't burn 13 x 30 min inside one HTTP request
            try:
                e = solve("aspect", construct, inc_deg=ang, this_cells=min(cells, 18),
                          this_nfreq=51, field=0, eplane=0, lobe=0, timeout_s=420)
            except subprocess.TimeoutExpired:
                errors[f"aspect_{ang}"] = "solve exceeded the 7-min per-angle cap; skipped"
                continue
            if e:
                errors[f"aspect_{ang}"] = e[-300:]
                continue
            fr = _rows(os.path.join(RESULTS, "rcs_freq_aspect.csv"))
            if fr:
                row = min(fr, key=lambda r: abs(r[0] - f0))
                aspect.append({"deg": ang, "dbsm": row[2]})
        if aspect:
            try:
                asp_name = f"rcs_aspect_{stamp}.csv"
                with open(os.path.join(RESULTS, asp_name), "w") as fa:
                    fa.write("aspect_deg,rcs_dbsm\n")
                    for p in aspect: fa.write(f"{p['deg']},{p['dbsm']}\n")
                files["aspect"] = {"aspect": f"/results/{asp_name}"}
            except Exception:
                pass

    return jsonify({
        "ok": bare is not None,
        "label": f"{cfg.get('label','target')} · {band}-band",
        "seconds": round(time.time() - t0, 1),
        "shape": shape, "band": band, "size1": size1, "size2": size2, "size3": size3,
        "inc_deg": inc, "construct": construct, "pol": pol,
        "f0_ghz": round(f0, 3), "sims": sims,
        "bare": bare, "coated": coated_curves, "reduction_db": reduction,
        "aspect": aspect, "polar": polar, "files": files,
        "errors": errors,
    }), 200

if __name__ == "__main__":
    print(f"\nopenEMS bridge running.")
    print(f"  Local:   http://localhost:{PORT}")
    print(f"  Share:   run  `tailscale funnel {PORT}`  then give out your https://<machine>.<tailnet>.ts.net URL")
    print(f"  octave={OCTAVE}\n  python={PYTHON}\n  scratch={SCRATCH}\n")
    app.run(host=HOST, port=PORT, threaded=THREADED)
