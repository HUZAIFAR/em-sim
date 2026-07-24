#!/usr/bin/env python3
"""
Conductor-loss / radiation-efficiency for the horn, computed from the full-wave
field solution (the physically correct way to get skin-depth-limited wall loss
in FDTD — the surface-impedance method used for finite-conductivity
boundaries).

Reads the PEC full-wave H-field HDF5 dump (Hf.h5 from horn_run.m) and integrates
the conductor loss on the four horn walls
        P_c = (Rs/2) * closed_integral |H_tan|^2 dA ,   Rs = sqrt(pi f mu0 / sigma)
for each coating conductivity, then reports
        radiation efficiency = Prad / (Prad + P_c)
        gain penalty (dB)     = 10 log10(efficiency)
        realized gain (dBi)   = Dmax + gain penalty
Because P_c scales as 1/sqrt(sigma), ONE PEC run covers every material.

Run (after `HORN_WALL=PEC HORN_TAG=pec octave --no-gui horn_run.m`):
    /opt/anaconda3/bin/python horn_wallloss.py
Output: horn_results/horn_coating_loss.csv
"""
import glob, os, sys, csv
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_SCR = os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if os.name == "nt" else "/tmp")
SIM  = os.path.join(_SCR, "horn_sim")
OUT  = os.path.join(HERE, "horn_results")
MU0  = 1.25663706212e-6

COATINGS = [("PEC (ideal)", np.inf), ("Silver", 6.3e7), ("Copper", 5.8e7),
            ("Aluminum", 3.5e7), ("MXene", 1.0e6)]

# ---- geometry (mm -> m) ----
try:
    a,b,Ax,By,feed,flare,f0 = [float(v) for v in open(os.path.join(OUT,"horn_geo.txt")).read().split()]
except Exception as e:
    sys.exit(f"need horn_geo.txt (run horn_run.m first): {e}")
mm=1e-3; a*=mm;b*=mm;Ax*=mm;By*=mm;feed*=mm;flare*=mm

# ---- Prad + directivity from the PEC gain csv ----
Prad=Dmax_dBi=None
gp=os.path.join(OUT,"horn_gain_pec.csv")
if os.path.isfile(gp):
    for row in csv.DictReader(open(gp)):
        if abs(float(row["freq_ghz"])*1e9 - f0) < 1e6:
            Prad=float(row["Prad_W"]); Dmax_dBi=float(row["Dmax_dBi"])
if Prad is None: sys.exit("could not read Prad from horn_gain_pec.csv")

# ---- load complex H from the HDF5 dump ----
try:
    import h5py
    from scipy.interpolate import RegularGridInterpolator as RGI
except Exception as e:
    sys.exit(f"need h5py+scipy: {e}\n  /opt/anaconda3/bin/pip install h5py scipy")

h5s = sorted(glob.glob(os.path.join(SIM,"Hf*.h5")))
if not h5s: sys.exit(f"no Hf*.h5 in {SIM} (re-run horn_run.m with the HDF5 dump)")
f = h5py.File(h5s[-1],"r")
x=np.array(f["/Mesh/x"]); y=np.array(f["/Mesh/y"]); z=np.array(f["/Mesh/z"])
# openEMS may store mesh in mm; if so, convert to m
if max(abs(x).max(),abs(y).max(),abs(z).max()) > 10: x*=mm; y*=mm; z*=mm
fd=f["/FieldData/FD"]
keys=list(fd.keys())
rk=[k for k in keys if "real" in k.lower()]; ik=[k for k in keys if "imag" in k.lower()]
if not rk or not ik: sys.exit(f"unexpected FD layout, keys={keys}")
Dre=np.array(fd[rk[0]]); Dim=np.array(fd[ik[0]])
print(f"H5 mesh: nx={len(x)} ny={len(y)} nz={len(z)} | FD dataset shape {Dre.shape}")

def to_xyz3(D):
    # move the length-3 (component) axis to last, then order spatial axes to (nx,ny,nz)
    ax3=[i for i,s in enumerate(D.shape) if s==3]
    if not ax3: sys.exit(f"no component axis of size 3 in {D.shape}")
    D=np.moveaxis(D, ax3[0], -1)                       # (.,.,.,3)
    sp=D.shape[:3]; want=(len(x),len(y),len(z))
    perm=[]
    used=[False,False,False]
    for target in want:
        for i,s in enumerate(sp):
            if not used[i] and s==target: perm.append(i); used[i]=True; break
    if len(perm)!=3: sys.exit(f"cannot match spatial axes {sp} to mesh {want}")
    return np.transpose(D, perm+[3])
Hre=to_xyz3(Dre); Him=to_xyz3(Dim)                     # (nx,ny,nz,3)

reI=[RGI((x,y,z),Hre[...,i],bounds_error=False,fill_value=0.0) for i in range(3)]
imI=[RGI((x,y,z),Him[...,i],bounds_error=False,fill_value=0.0) for i in range(3)]
def H_at(P): return np.stack([reI[i](P)+1j*imI[i](P) for i in range(3)],axis=1)

# ---- horn walls ----
def hx(z): return np.where(z<=0, a/2, a/2+(Ax/2-a/2)*np.clip(z,0,flare)/flare)
def hy(z): return np.where(z<=0, b/2, b/2+(By/2-b/2)*np.clip(z,0,flare)/flare)
dhx=(Ax/2-a/2)/flare; dhy=(By/2-b/2)/flare
Nz,Nt=200,80
zc=np.linspace(-feed,flare,Nz); dz=(flare+feed)/Nz

def integral(kind):
    tot=0.0
    for zz in zc:
        deriv=((dhx if zz>0 else 0.0) if kind=='x' else (dhy if zz>0 else 0.0))
        jac=np.sqrt(1.0+deriv**2)
        if kind=='x':
            H=float(hy(np.array([zz]))[0]); dv=2*H/Nt; v=np.linspace(-H+dv/2,H-dv/2,Nt)
            n0=np.array([1.0,0.0,-deriv])
            for sgn in (+1,-1):
                nn=n0*np.array([sgn,1,1]); nn=nn/np.linalg.norm(nn)
                P=np.column_stack([np.full(Nt,sgn*float(hx(np.array([zz]))[0])),v,np.full(Nt,zz)])
                Hc=H_at(P); H2=np.sum(np.abs(Hc)**2,1); Hn=np.abs(Hc@nn)**2
                tot+=np.sum(H2-Hn)*dv*dz*jac
        else:
            H=float(hx(np.array([zz]))[0]); dv=2*H/Nt; v=np.linspace(-H+dv/2,H-dv/2,Nt)
            n0=np.array([0.0,1.0,-deriv])
            for sgn in (+1,-1):
                nn=n0*np.array([1,sgn,1]); nn=nn/np.linalg.norm(nn)
                P=np.column_stack([v,np.full(Nt,sgn*float(hy(np.array([zz]))[0])),np.full(Nt,zz)])
                Hc=H_at(P); H2=np.sum(np.abs(Hc)**2,1); Hn=np.abs(Hc@nn)**2
                tot+=np.sum(H2-Hn)*dv*dz*jac
    return tot

I_tot=integral('x')+integral('y')
print(f"Prad={Prad:.4e} W | integral|Htan|^2 dA = {I_tot:.4e}")

rows=[]
print(f"\n f0={f0/1e9:.1f} GHz   (PEC directivity Dmax={Dmax_dBi:.2f} dBi)")
print(f"{'material':<12}{'Rs(ohm)':>10}{'P_wall(W)':>13}{'rad_eff%':>10}{'penalty dB':>12}{'gain dBi':>10}")
for name,sig in COATINGS:
    Rs=0.0 if np.isinf(sig) else np.sqrt(np.pi*f0*MU0/sig)
    Pc=0.5*Rs*I_tot
    eff=Prad/(Prad+Pc); pen=10*np.log10(eff); gain=Dmax_dBi+pen
    rows.append((name,sig,Rs,Pc,eff*100,pen,gain))
    print(f"{name:<12}{Rs:>10.4f}{Pc:>13.3e}{eff*100:>10.3f}{pen:>12.4f}{gain:>10.3f}")

os.makedirs(OUT,exist_ok=True)
with open(os.path.join(OUT,"horn_coating_loss.csv"),"w",newline="") as fo:
    w=csv.writer(fo); w.writerow(["material","sigma_S_per_m","Rs_ohm","P_wall_W","rad_eff_pct","gain_penalty_dB","gain_dBi","freq_ghz"])
    for r in rows: w.writerow([r[0],r[1],f"{r[2]:.5f}",f"{r[3]:.5e}",f"{r[4]:.4f}",f"{r[5]:.5f}",f"{r[6]:.4f}",f0/1e9])
print("\nwrote",os.path.join(OUT,"horn_coating_loss.csv"))
