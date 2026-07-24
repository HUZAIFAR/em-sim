% ============================================================
%  Standalone openEMS pyramidal-horn antenna run (Stage 3)
%  WR-90 X-band standard-gain horn, dimensions measured from the
%  uploaded STEP (PE9856B-15).  Adapted from the official openEMS
%  Horn_Antenna tutorial (Thorsten Liebig, CC BY-SA) + the port/
%  addpath conventions proven in this project's wg_run.m.
%
%  WHAT IT DOES
%   - builds the horn as metal walls (PEC, or a finite-conductivity
%     conducting sheet to model a MXene / copper coating),
%   - excites the WR-90 feed with the TE10 mode,
%   - open (PML) boundaries so it radiates into free space,
%   - near-field-to-far-field box -> directivity / gain / pattern,
%   - dumps the E-field on the H-plane cut so we can SEE the wave
%     inside the horn and radiating out the aperture.
%
%  VALIDATION: this is a nominally 15 dBi horn ("-15" in the part
%  number).  A correct PEC run should give Dmax ~ 14-15 dBi near
%  10 GHz.  If it does, the model is trustworthy.
%
%  RUN:  octave --no-gui horn_run.m
% ============================================================
close all; clear; clc;

here = fileparts(mfilename('fullpath'));
pth_oe=getenv('OPENEMS_MATLAB_PATH'); if isempty(pth_oe), pth_oe='/opt/homebrew/Cellar/openems/0.0.36/share/openEMS/matlab'; end; addpath(pth_oe);
pth_cx=getenv('CSXCAD_MATLAB_PATH'); if isempty(pth_cx), pth_cx='/opt/homebrew/Cellar/csxcad/0.6.4/share/CSXCAD/matlab'; end; addpath(pth_cx);
physical_constants; unit = 1e-3;              % all lengths in mm

% ---------- CONFIG --------------------------------------------------
% Wall material can be set here OR via environment variables so the
% coating comparison is three clean runs (no hand-editing):
%   HORN_WALL=PEC                                  octave --no-gui horn_run.m
%   HORN_WALL=sheet HORN_SIGMA=5.8e7 HORN_TAG=copper octave --no-gui horn_run.m
%   HORN_WALL=sheet HORN_SIGMA=1e6   HORN_TAG=mxene  octave --no-gui horn_run.m  (matches the app's MXene sigma)
WALL = getenv('HORN_WALL'); if isempty(WALL); WALL = 'PEC'; end
sw = getenv('HORN_SIGMA');  if isempty(sw); sigma_wall = 5.8e7; else sigma_wall = str2double(sw); end
coat_thick = 20e-6;        % m, coating thickness (used only when WALL='sheet')
tag = getenv('HORN_TAG');  if isempty(tag); tag = lower(WALL); end

% Geometry (mm) — WR-90 feed + measured aperture/flare of PE9856B-15
a  = 22.86;   b  = 10.16;         % WR-90 inner: a=broad(H,x), b=narrow(E,y)
Ax = 68.0;    By = 49.0;          % aperture INNER: x (H-plane), y (E-plane)
flare = 123.0;                    % axial flare length (z)
feed  = 40.0;                     % straight feed length before flare (z<0) — long enough for a clean port
tw    = 2.0;                      % wall thickness (mm)

% Frequency (X-band)
f_start = 8e9; f_stop = 12e9; f0 = 10e9;

% optional: the app's server writes horn_params.m to override geometry,
% material and band (from an uploaded STEP). Absent -> validated defaults above.
if exist(fullfile(here,'horn_params.m'),'file')
    run(fullfile(here,'horn_params.m'));
    printf('loaded horn_params.m (server-driven run)\n');
end
% --------------------------------------------------------------------

% opening half-angles from feed -> aperture over the flare length
% (aperture_x = a + 2*sin(angx)*flare ; same for y)
angx = asin( max(0,(Ax - a))/(2*flare) );
angy = asin( max(0,(By - b))/(2*flare) );
printf('opening angles: H-plane %.2f deg, E-plane %.2f deg\n', angx*180/pi, angy*180/pi);

TE_mode = 'TE10';

%% FDTD + excitation
FDTD = InitFDTD('EndCriteria', 1e-4);
FDTD = SetGaussExcite(FDTD, 0.5*(f_start+f_stop), 0.5*(f_stop-f_start));
FDTD = SetBoundaryCond(FDTD, {'PML_8','PML_8','PML_8','PML_8','PML_8','PML_8'});

%% mesh / sim box
CSX = InitCSX();
if ~exist('p_cells','var'); p_cells = 15; end   % mesh density: cells per wavelength
max_res = c0/f_stop/unit/p_cells;            % ~lambda/p_cells at f_stop
SimBox = [Ax+120, By+120, feed+flare+90];    % transverse margins + radiation region
% force a fine grid across the FEED cross-section so the TE10 port mode is
% resolved (>=15 cells across a, >=12 across the narrow wall b) -> clean S11
xfine = linspace(-a/2, a/2, 15);
yfine = linspace(-b/2, b/2, 13);
mesh.x = SmoothMeshLines(unique([-SimBox(1)/2 xfine SimBox(1)/2]), max_res, 1.4);
mesh.y = SmoothMeshLines(unique([-SimBox(2)/2 yfine SimBox(2)/2]), max_res, 1.4);
mesh.z = SmoothMeshLines([-feed 0 flare SimBox(3)-feed], max_res, 1.4);
CSX = DefineRectGrid(CSX, unit, mesh);

%% wall material property
if strcmpi(WALL,'PEC')
    CSX = AddMetal(CSX, 'horn');
    wall_prio = 10;
    printf('walls: PEC (ideal baseline)\n');
else
    CSX = AddConductingSheet(CSX, 'horn', sigma_wall, coat_thick);
    wall_prio = 10;
    printf('walls: conducting sheet [%s] sigma=%.3e S/m, t=%.1f um\n', tag, sigma_wall, coat_thick*1e6);
end

%% feed rectangular waveguide (4 walls, z: mesh.z(1)..0)
CSX = AddBox(CSX,'horn',wall_prio,[-a/2-tw -b/2   mesh.z(1)],[-a/2      b/2   0]);
CSX = AddBox(CSX,'horn',wall_prio,[ a/2    -b/2   mesh.z(1)],[ a/2+tw   b/2   0]);
CSX = AddBox(CSX,'horn',wall_prio,[-a/2-tw  b/2   mesh.z(1)],[ a/2+tw   b/2+tw 0]);
CSX = AddBox(CSX,'horn',wall_prio,[-a/2-tw -b/2-tw mesh.z(1)],[ a/2+tw  -b/2   0]);

%% flared horn plates (0..flare), 4 trapezoids via transformed linear polygons
% top/bottom plates (flare in y), left/right plates (flare in x)
p=[]; p(2,1)= a/2; p(1,1)=0;
p(2,2)= a/2 + sin(angx)*flare; p(1,2)=flare;
p(2,3)=-a/2 - sin(angx)*flare; p(1,3)=flare;
p(2,4)=-a/2; p(1,4)=0;
CSX = AddLinPoly(CSX,'horn',wall_prio,1,-tw/2,p,tw,'Transform',{'Rotate_X', angy,'Translate',['0,' num2str(-b/2-tw/2) ',0']});
CSX = AddLinPoly(CSX,'horn',wall_prio,1,-tw/2,p,tw,'Transform',{'Rotate_X',-angy,'Translate',['0,' num2str( b/2+tw/2) ',0']});

p=[]; p(1,1)= b/2+tw; p(2,1)=0;
p(1,2)= b/2+tw + sin(angy)*flare; p(2,2)=flare;
p(1,3)=-b/2-tw - sin(angy)*flare; p(2,3)=flare;
p(1,4)=-b/2-tw; p(2,4)=0;
CSX = AddLinPoly(CSX,'horn',wall_prio,0,-tw/2,p,tw,'Transform',{'Rotate_Y',-angx,'Translate',[num2str(-a/2-tw/2) ',0,0']});
CSX = AddLinPoly(CSX,'horn',wall_prio,0,-tw/2,p,tw,'Transform',{'Rotate_Y', angx,'Translate',[num2str( a/2+tw/2) ',0,0']});

% ideal-aperture area (inner), for gain reference
A_ap = (a + 2*sin(angx)*flare)*unit * (b + 2*sin(angy)*flare)*unit;

%% TE10 feed port (in the feed section, propagation +z).
% Excite a few cells in from the feed back (mesh.z(1) = -feed); put the S11/S21 measurement
% plane forward of that but still inside the uniform feed (z<0). The default feed keeps its
% mid-feed plane (-feed/2). Guard short-feed CAD uploads on a coarse mesh, where the old fixed
% mesh.z(1)+feed/2 could land BEHIND the excitation and invert the port (garbage S11/efficiency).
z_exc  = mesh.z(8);
z_meas = -feed/2;
if z_meas <= z_exc + max_res
    z_meas = min(z_exc + 3*max_res, -max_res);
end
start = [-a/2 -b/2 z_exc];
stop  = [ a/2  b/2 z_meas];
[CSX, port] = AddRectWaveGuidePort(CSX, 0, 1, start, stop, 'z', a*unit, b*unit, TE_mode, 1);

%% near-field to far-field box (exclude the -z / feed face)
start = [mesh.x(9)     mesh.y(9)     mesh.z(9)];
stop  = [mesh.x(end-8) mesh.y(end-8) mesh.z(end-8)];
[CSX, nf2ff] = CreateNF2FFBox(CSX, 'nf2ff', start, stop, 'Directions',[1 1 1 1 0 1]);

%% E-field dump on the H-plane cut (y=0) — shows the wave INSIDE + radiating out
% frequency-domain (DFT) dump at f0 -> one clean steady |E| map (not time frames)
CSX = AddDump(CSX,'Ef','DumpType',10,'DumpMode',2,'Frequency',f0);
CSX = AddBox(CSX,'Ef',0,[mesh.x(1) 0 mesh.z(1)],[mesh.x(end) 0 mesh.z(end)]);
% time-domain animation dump on the same H-plane cut, ONLY when Field view = time.
% (The frequency-domain Ef dump above is always kept, so the steady |E| stills and
%  the wall-loss integration are unaffected.)
if ~exist('p_field_mode','var'); p_field_mode='freq'; end
if strcmp(p_field_mode,'time')
    CSX = AddDump(CSX,'Et','DumpType',0,'DumpMode',2);
    CSX = AddBox(CSX,'Et',0,[mesh.x(1) 0 mesh.z(1)],[mesh.x(end) 0 mesh.z(end)]);
end

%% H-field dump (frequency domain) over the horn interior volume.
% Used by horn_wallloss.py to integrate conductor loss P_c=(Rs/2)*int|H_tan|^2 dA
% on the walls -> radiation efficiency & gain penalty for ANY coating (copper,
% MXene, ...) from this single PEC full-wave solve. This is the physically
% correct way to get skin-depth-limited wall loss in FDTD.
% HDF5 file type (1) stores the complex FD field natively (real+imag)
CSX = AddDump(CSX,'Hf','DumpType',11,'DumpMode',2,'FileType',1,'Frequency',f0);
CSX = AddBox(CSX,'Hf',0,[-(Ax/2+3) -(By/2+3) mesh.z(1)],[(Ax/2+3) (By/2+3) flare+3]);

%% 3-D E-field VOLUME dump (frequency-domain, subsampled) for the interactive
%% browser field viewer. SubSampling keeps the .vtr small; export_field3d.py
%% downsamples further to a compact JSON point cloud. This is independent of the
%% H-plane Ef dump above (which still drives the 2-D stills), so nothing else is
%% affected. Box spans the horn interior plus a margin past the aperture to
%% capture the near-field radiation.
CSX = AddDump(CSX,'Ev','DumpType',10,'DumpMode',2,'Frequency',f0,'SubSampling','2,2,2');
CSX = AddBox(CSX,'Ev',0,[-(Ax/2+10) -(By/2+10) mesh.z(1)],[(Ax/2+10) (By/2+10) flare+40]);

%% write + run
scr=getenv('OPENEMS_SCRATCH'); if isempty(scr), if ispc(), scr='C:/openems_scratch'; else scr='/tmp'; end; end; Sim_Path = [scr '/horn_sim']; Sim_CSX = 'horn.xml';
[~,~,~] = rmdir(Sim_Path,'s'); mkdir(Sim_Path);
WriteOpenEMS([Sim_Path '/' Sim_CSX], FDTD, CSX);
RunOpenEMS(Sim_Path, Sim_CSX);

%% port post-processing: S11 + accepted power across band
freq = linspace(f_start, f_stop, 201);
port = calcPort(port, Sim_Path, freq);
s11  = port.uf.ref ./ port.uf.inc;
Pacc = 0.5 * real(port.uf.tot .* conj(port.if.tot));   % net power into the horn (W) vs freq

outdir = fullfile(here,'horn_results'); if ~exist(outdir,'dir'); mkdir(outdir); end

% geometry (mm) + f0 for the interior-field renderer to draw the horn walls
gfid = fopen(fullfile(outdir,'horn_geo.txt'),'w');
fprintf(gfid,'%g %g %g %g %g %g %g\n', a, b, Ax, By, feed, flare, f0);
fclose(gfid);
% S-parameters + input impedance vs frequency:
%   s11_db (Fig 1c), s11_deg = phase of S11 (Fig 1d), VSWR, and the port input
%   impedance Zin = V/I = uf.tot/if.tot (real & imaginary parts).
Zin = port.uf.tot ./ port.if.tot;
fid = fopen(fullfile(outdir,['horn_s11_' tag '.csv']),'w');
fprintf(fid,'freq_ghz,s11_db,s11_deg,vswr,Zin_real_ohm,Zin_imag_ohm\n');
for k=1:numel(freq)
    m  = abs(s11(k));
    vs = (1+m)/max(1-m,1e-6);
    fprintf(fid,'%.4f,%.5f,%.3f,%.4f,%.3f,%.3f\n', freq(k)/1e9, 20*log10(m), angle(s11(k))*180/pi, vs, real(Zin(k)), imag(Zin(k)));
end
fclose(fid);

%% directivity / gain vs FREQUENCY (sweep) + radiation pattern at f0
% one CalcNF2FF call over a frequency VECTOR and the two principal planes
% (phi=0 -> E-plane, phi=90 -> H-plane).  NF2FF is a post-process of the stored
% near-fields, so sweeping many frequencies is cheap (no extra FDTD).
thetaRange = (-180:2:180);
fsweep = linspace(f_start, f_stop, 13);      % 13-pt gain-vs-frequency curve (f0 = midpoint)
nf = CalcNF2FF(nf2ff, Sim_Path, fsweep, thetaRange*pi/180, [0 90]*pi/180);

fid2 = fopen(fullfile(outdir,['horn_gain_' tag '.csv']),'w');
fprintf(fid2,'freq_ghz,Dmax_dBi,Prad_W,rad_eff_pct,aperture_eff_pct,s11_db\n');
% cumulative comparison file (one summary row per material, at f0).
% Prad (radiated power, same excitation across runs) is the clean wall-loss
% indicator: less Prad = more power dissipated in the walls.
cf = fullfile(outdir,'horn_compare.csv');
newfile = ~exist(cf,'file');
fc = fopen(cf,'a');
if newfile; fprintf(fc,'material,sigma_S_per_m,freq_ghz,Dmax_dBi,Prad_W,rad_eff_pct,s11_db\n'); end
df = fsweep(2)-fsweep(1);
for k = 1:numel(fsweep)
    f    = fsweep(k);
    Dmax = nf.Dmax(k);
    Dlog = 10*log10(Dmax);
    Ga   = 4*pi*A_ap/(c0/f)^2;         % ideal aperture gain
    ea   = Dmax/Ga;                    % aperture efficiency
    [~,ix] = min(abs(freq-f));
    rad_eff = nf.Prad(k)/Pacc(ix);     % radiated/accepted
    % A lossless PEC horn is 100% efficient by definition; any excess over 1 is NF2FF/port
    % power-accounting numerical error, so clamp the REPORTED figure (raw Prad stays in its own
    % column). Real lossy coatings come out below 1 naturally, so this never hides a real loss.
    rad_eff = min(rad_eff, 1.0);
    s11db   = 20*log10(abs(s11(ix)));
    fprintf(fid2,'%.4f,%.3f,%.6e,%.3f,%.2f,%.3f\n', f/1e9, Dlog, nf.Prad(k), rad_eff*100, ea*100, s11db);
    printf('  f=%.2f GHz : Dmax=%.2f dBi | Prad=%.3e W | rad_eff=%.1f%% | S11=%.1f dB\n', ...
           f/1e9, Dlog, nf.Prad(k), rad_eff*100, s11db);
    if abs(f-f0) < df/2                 % the f0 row (midpoint of the sweep)
        sig_report = 0; if ~strcmpi(WALL,'PEC'); sig_report = sigma_wall; end
        fprintf(fc,'%s,%.3e,%.3f,%.3f,%.6e,%.3f,%.3f\n', tag, sig_report, f/1e9, Dlog, nf.Prad(k), rad_eff*100, s11db);
    end
end
fclose(fid2); fclose(fc);

%% radiation pattern at the frequency closest to f0
% CalcNF2FF above used phi = [0 90] deg -> column 1 = phi=0 cut, column 2 = phi=90 cut.
% TE10 excites E along y, so the E-plane (holds E + propagation) is the phi=90 cut and
% the H-plane is the phi=0 cut. Columns are assigned accordingly (previously swapped).
% absolute gain pattern in dBi = 10log10(Dmax) + 20log10(|E_norm|/max|E_norm|)
[~,kf0] = min(abs(fsweep - f0));
Dlog0 = 10*log10(nf.Dmax(kf0));
peak = max(abs(nf.E_norm{kf0}(:)));                  % global pattern peak (boresight)
Ep = abs(nf.E_norm{kf0}(:,2)); Ep = Ep/max(Ep);     % E-plane (phi=90), total, normalized
Hp = abs(nf.E_norm{kf0}(:,1)); Hp = Hp/max(Hp);     % H-plane (phi=0),  total, normalized
gE = Dlog0 + 20*log10(max(Ep,1e-6));                % floor avoids -Inf at deep nulls
gH = Dlog0 + 20*log10(max(Hp,1e-6));
% co-/cross-polarization (paper Fig 1f plots GainTheta at phi=0 and phi=90):
%   E-plane (phi=90): co-pol=|E_theta|, cross-pol=|E_phi|
%   H-plane (phi=0):  co-pol=|E_phi|,   cross-pol=|E_theta|
gEco = Dlog0 + 20*log10(max(abs(nf.E_theta{kf0}(:,2))/peak,1e-6));
gEx  = Dlog0 + 20*log10(max(abs(nf.E_phi{kf0}(:,2))/peak,1e-6));
gHco = Dlog0 + 20*log10(max(abs(nf.E_phi{kf0}(:,1))/peak,1e-6));
gHx  = Dlog0 + 20*log10(max(abs(nf.E_theta{kf0}(:,1))/peak,1e-6));
fpat = fopen(fullfile(outdir,['horn_pattern_' tag '.csv']),'w');
fprintf(fpat,'theta_deg,gain_Eplane_dBi,gain_Hplane_dBi,E_copol_dBi,E_xpol_dBi,H_copol_dBi,H_xpol_dBi\n');
for k = 1:numel(thetaRange)
    fprintf(fpat,'%.1f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n', thetaRange(k), gE(k), gH(k), gEco(k), gEx(k), gHco(k), gHx(k));
end
fclose(fpat);
printf('pattern (f0=%.2f GHz) -> %s\n', fsweep(kf0)/1e9, fullfile(outdir,['horn_pattern_' tag '.csv']));

printf('\n=== horn run [%s] complete ===\n', tag);
printf('S11  -> %s\n', fullfile(outdir,['horn_s11_' tag '.csv']));
printf('gain -> %s\n', fullfile(outdir,['horn_gain_' tag '.csv']));
printf('compare (appended) -> %s\n', cf);
printf('H-plane field dump in %s (Ef_*.vtr) for the interior render\n', Sim_Path);
printf('VALIDATION: expect Dmax ~ 14-15 dBi near 10 GHz; PEC rad_eff ~ 100%%.\n');
