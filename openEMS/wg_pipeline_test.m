% ============================================================
%  openEMS TOOLCHAIN TEST  -  WR-90 rectangular waveguide (PEC walls)
%  Purpose: prove openEMS + Octave runs end-to-end on your Mac.
%  PEC (lossless) walls -> insertion loss should be ~0 dB.
%  Once this runs, we swap in finite-conductivity walls for the real study.
%
%  RUN (note the quotes - the folder name has spaces):
%    /opt/homebrew/bin/octave --no-gui "<path to this file>"
% ============================================================
close all; clear; clc;

% --- openEMS / CSXCAD Octave interface (Homebrew install) ---
% If you upgrade openEMS later, update the version numbers in these paths.
pth_oe=getenv('OPENEMS_MATLAB_PATH'); if isempty(pth_oe), pth_oe='/opt/homebrew/Cellar/openems/0.0.36/share/openEMS/matlab'; end; addpath(pth_oe);
pth_cx=getenv('CSXCAD_MATLAB_PATH'); if isempty(pth_cx), pth_cx='/opt/homebrew/Cellar/csxcad/0.6.4/share/CSXCAD/matlab'; end; addpath(pth_cx);

physical_constants;          % gives c0, etc.
unit = 1e-3;                 % geometry in mm

% --- WR-90 waveguide (X-band) ---
a   = 22.86;                 % width  (mm)
b   = 10.16;                 % height (mm)
len = 200;                   % length (mm)

f_start = 8e9;
f_stop  = 12e9;

% --- FDTD setup ---
FDTD = InitFDTD('NrTS', 50000, 'EndCriteria', 1e-4);
FDTD = SetGaussExcite(FDTD, 0.5*(f_start+f_stop), 0.5*(f_stop-f_start));
% transverse walls = PEC metal; the two z-ends absorb (PML)
BC = {'PEC','PEC','PEC','PEC','MUR','MUR'};   % metal walls; absorb at the two z-ends
FDTD = SetBoundaryCond(FDTD, BC);

% --- geometry + mesh ---
CSX = InitCSX();
res = c0 / f_stop / unit / 20;          % ~ lambda/20 cell size
mesh.x = SmoothMeshLines([0 a],   res);
mesh.y = SmoothMeshLines([0 b],   res);
mesh.z = SmoothMeshLines([0 len], res);
CSX = DefineRectGrid(CSX, unit, mesh);

% --- two TE10 waveguide ports, placed a few cells INSIDE the domain ---
% Per the openEMS API: excitation sits at start[z], the voltage/current probe
% plane at stop[z]. They must be away from the absorbing z-boundaries, or the
% probe lands inside the boundary and no port data is written.
start = [mesh.x(1)   mesh.y(1)   mesh.z(8)];
stop  = [mesh.x(end) mesh.y(end) mesh.z(15)];
[CSX, port{1}] = AddRectWaveGuidePort(CSX, 0, 1, start, stop, 'z', a*unit, b*unit, 'TE10', 1);
start = [mesh.x(1)   mesh.y(1)   mesh.z(end-14)];
stop  = [mesh.x(end) mesh.y(end) mesh.z(end-7)];
[CSX, port{2}] = AddRectWaveGuidePort(CSX, 0, 2, start, stop, 'z', a*unit, b*unit, 'TE10');

% --- field dump for the 3-D colored visualisation ---
% E-field, time-domain, over the whole guide volume -> writes Et_*.vtr frames
% that PyVista/ParaView render as the wave propagating through the guide.
CSX = AddDump(CSX, 'Et', 'DumpType', 0, 'DumpMode', 2, 'SubSampling', '2,2,2');
CSX = AddBox(CSX, 'Et', 0, [mesh.x(1) mesh.y(1) mesh.z(1)], [mesh.x(end) mesh.y(end) mesh.z(end)]);

% --- run the solver ---
scr=getenv('OPENEMS_SCRATCH'); if isempty(scr), if ispc(), scr='C:/openems_scratch'; else scr='/tmp'; end; end; Sim_Path = [scr '/wg_sim'];   % OPENEMS_SCRATCH (no spaces) -> safe for openEMS shell calls
[~,~,~] = rmdir(Sim_Path,'s'); mkdir(Sim_Path);
WriteOpenEMS([Sim_Path '/wg.xml'], FDTD, CSX);
RunOpenEMS(Sim_Path, 'wg.xml');

% --- post-process S-parameters ---
freq = linspace(f_start, f_stop, 201);
port = calcPort(port, Sim_Path, freq);
S11 = port{1}.uf.ref ./ port{1}.uf.inc;
S21 = port{2}.uf.inc ./ port{1}.uf.inc;

idx = find(freq >= 10e9, 1);
printf('\n================ TOOLCHAIN TEST ================\n');
printf('At 10 GHz:  S21 = %.3f dB   S11 = %.1f dB\n', 20*log10(abs(S21(idx))), 20*log10(abs(S11(idx))));
printf('PEC walls -> S21 ~ 0 dB expected. If you see this line, the pipeline works.\n');
printf('===============================================\n');
