% ============================================================
%  Open-ended rectangular-waveguide FAR-FIELD (openEMS NF2FF)
%  --------------------------------------------------------
%  Driven by wg_params.m (same file wg_run.m uses). Builds the
%  guide with conducting-sheet walls, OPENS the far end so it
%  radiates like an aperture antenna, excites the TE10 mode at
%  the input, surrounds the structure with a near-field-to-far-
%  field box (feed face excluded) and PML boundaries, then does
%  one CalcNF2FF at band centre for the two principal planes:
%     phi = 90 deg  ->  E-plane   (E-field along the narrow wall b)
%     phi = 0  deg  ->  H-plane   (along the broad wall a)
%  Writes <outdir>/farfield_wg.csv :  theta_deg, E_plane_dB, H_plane_dB
%  (each normalized to its own main-beam peak, matching the tool's
%   analytical open-ended-TE10 pattern).
%
%  Method + NF2FF conventions follow the official openEMS
%  Horn_Antenna tutorial (T. Liebig, CC BY-SA) and this project's
%  proven horn_run.m / wg_run.m.
%
%  RUN:  octave --no-gui wg_farfield.m
% ============================================================
close all; clear; clc;

here = fileparts(mfilename('fullpath'));
pth_oe=getenv('OPENEMS_MATLAB_PATH'); if isempty(pth_oe), pth_oe='/opt/homebrew/Cellar/openems/0.0.36/share/openEMS/matlab'; end; addpath(pth_oe);
pth_cx=getenv('CSXCAD_MATLAB_PATH'); if isempty(pth_cx), pth_cx='/opt/homebrew/Cellar/csxcad/0.6.4/share/CSXCAD/matlab'; end; addpath(pth_cx);
run(fullfile(here, 'wg_params.m'));   % p_a,p_b,p_len,p_fmin,p_fmax,p_sigma,p_thick,p_label,p_outdir,...

physical_constants; unit = 1e-3;
a = p_a; b = p_b; len = p_len;        % mm

% --- optional complex-loss terms (default lossless) ---
if ~exist('p_epsr','var');  p_epsr  = 1; end
if ~exist('p_epspp','var'); p_epspp = 0; end
if ~exist('p_mur','var');   p_mur   = 1; end
if ~exist('p_mupp','var');  p_mupp  = 0; end
if ~exist('p_cells','var'); p_cells = 20; end

% --- effective wall conductivity (fold eps''/mu'' into sigma), as in wg_run.m ---
EPS0_ = 8.8541878128e-12; MU0_ = 1.25663706212e-6;
f0   = 0.5*(p_fmin + p_fmax);
w    = 2*pi*f0;
sig_e = p_sigma + w*EPS0_*p_epspp;
mu_c  = MU0_*(p_mur - 1i*p_mupp);
Zs    = sqrt(1i*w*mu_c / sig_e);
Rs_eff = real(Zs);
if Rs_eff > 0; sig_wall = pi*f0*MU0_ / Rs_eff^2; else sig_wall = p_sigma; end
sig_wall = max(sig_wall, 1e4);        % keep the guide guiding so a clean aperture pattern forms
printf('far-field: sigma_wall=%.3e S/m, f0=%.3f GHz\n', sig_wall, f0/1e9);

lam0 = c0/f0/unit;                    % free-space wavelength (mm)
res  = c0/p_fmax/unit/p_cells;        % ~lambda/p_cells at f_max
tw   = max(1.5, 2*res);               % wall thickness (mm)
marg = max(0.6*lam0, 14*res);         % vacuum margin: room for PML_8 + NF2FF box + a clean far field
margz= max(0.7*lam0, 14*res);         % radiation region beyond the open end

%% FDTD + excitation — OPEN (PML) boundaries so the aperture radiates
FDTD = InitFDTD('EndCriteria', 1e-4);
FDTD = SetGaussExcite(FDTD, 0.5*(p_fmin+p_fmax), 0.5*(p_fmax-p_fmin));
FDTD = SetBoundaryCond(FDTD, {'PML_8','PML_8','PML_8','PML_8','PML_8','PML_8'});

%% mesh
CSX = InitCSX();
mesh.x = SmoothMeshLines([-marg -tw 0 a a+tw a+marg], res);
mesh.y = SmoothMeshLines([-marg -tw 0 b b+tw b+marg], res);
mesh.z = SmoothMeshLines([0 len len+margz], res);   % guide 0..len, then open radiation region
CSX = DefineRectGrid(CSX, unit, mesh);

%% conducting-sheet walls, guide section only (z: 0..len) — open at z=len
CSX = AddConductingSheet(CSX, 'wall', sig_wall, p_thick);
CSX = AddBox(CSX, 'wall', 10, [0 0 0], [0 b len]);   % x = 0 wall
CSX = AddBox(CSX, 'wall', 10, [a 0 0], [a b len]);   % x = a wall
CSX = AddBox(CSX, 'wall', 10, [0 0 0], [a 0 len]);   % y = 0 wall
CSX = AddBox(CSX, 'wall', 10, [0 b 0], [a b len]);   % y = b wall

%% TE10 input port (near z=0), propagation +z
start = [0 0 mesh.z(8)];   stop = [a b mesh.z(15)];
[CSX, port] = AddRectWaveGuidePort(CSX, 0, 1, start, stop, 'z', a*unit, b*unit, 'TE10', 1);

%% near-field-to-far-field box (exclude the -z / feed face), inside the PML
start = [mesh.x(9)     mesh.y(9)     mesh.z(9)];
stop  = [mesh.x(end-8) mesh.y(end-8) mesh.z(end-8)];
[CSX, nf2ff] = CreateNF2FFBox(CSX, 'nf2ff', start, stop, 'Directions',[1 1 1 1 0 1]);

%% write + run
scr=getenv('OPENEMS_SCRATCH'); if isempty(scr), if ispc(), scr='C:/openems_scratch'; else scr='/tmp'; end; end; Sim_Path = [scr '/wg_ff_sim']; Sim_CSX = 'wg_ff.xml';
[~,~,~] = rmdir(Sim_Path,'s'); mkdir(Sim_Path);
WriteOpenEMS([Sim_Path '/' Sim_CSX], FDTD, CSX);
RunOpenEMS(Sim_Path, Sim_CSX);

%% NF2FF at band centre, two principal planes
% phi=0 -> H-plane (broad wall a) ; phi=90 -> E-plane (narrow wall b, E along y)
thetaRange = (-90:2:90);
nf = CalcNF2FF(nf2ff, Sim_Path, f0, thetaRange*pi/180, [0 90]*pi/180);

Hp = abs(nf.E_norm{1}(:,1));  Hp = Hp / max(Hp);   % phi=0   -> H-plane
Ep = abs(nf.E_norm{1}(:,2));  Ep = Ep / max(Ep);   % phi=90  -> E-plane

if ~exist(p_outdir, 'dir'); mkdir(p_outdir); end
fid = fopen(fullfile(p_outdir, 'farfield_wg.csv'), 'w');
fprintf(fid, 'theta_deg,E_plane_dB,H_plane_dB\n');
for k = 1:numel(thetaRange)
    fprintf(fid, '%.1f,%.4f,%.4f\n', thetaRange(k), ...
            20*log10(max(Ep(k),1e-4)), 20*log10(max(Hp(k),1e-4)));
end
fclose(fid);

printf('\n=== far-field %s ===\n', p_label);
printf('Dmax = %.2f dBi at %.3f GHz  (open-ended-guide aperture)\n', 10*log10(nf.Dmax(1)), f0/1e9);
printf('far-field written to %s/farfield_wg.csv\n', p_outdir);
