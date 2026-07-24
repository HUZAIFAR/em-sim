% ============================================================
%  Parametrized openEMS waveguide run (driven by wg_params.m)
%  - good-conductor walls -> surface-impedance conducting sheets (accurate loss)
%  - leaky/dielectric walls -> finite material blocks (wave transmits out = leakage)
%  - dumps E-field over guide + vacuum margin for the 3-D render
%  - writes S-parameters (insertion loss) to <outdir>/insertion_loss.csv
%
%  The pipeline server writes wg_params.m, then calls:
%     octave --no-gui wg_run.m
% ============================================================
close all; clear; clc;

here = fileparts(mfilename('fullpath'));
pth_oe=getenv('OPENEMS_MATLAB_PATH'); if isempty(pth_oe), pth_oe='/opt/homebrew/Cellar/openems/0.0.36/share/openEMS/matlab'; end; addpath(pth_oe);
pth_cx=getenv('CSXCAD_MATLAB_PATH'); if isempty(pth_cx), pth_cx='/opt/homebrew/Cellar/csxcad/0.6.4/share/CSXCAD/matlab'; end; addpath(pth_cx);
run(fullfile(here, 'wg_params.m'));     % defines p_a,p_b,p_len,p_fmin,p_fmax,p_sigma,p_thick,p_label,p_outdir

physical_constants; unit = 1e-3;
a = p_a; b = p_b; len = p_len;          % mm

% --- complex permittivity/permeability loss terms (default to lossless if absent) ---
if ~exist('p_epsr','var');  p_epsr  = 1; end
if ~exist('p_epspp','var'); p_epspp = 0; end   % imaginary permittivity eps_r''
if ~exist('p_mur','var');   p_mur   = 1; end
if ~exist('p_mupp','var');  p_mupp  = 0; end   % imaginary permeability mu_r''

% Fold dielectric loss (eps'') and magnetic loss (mu'') into one EFFECTIVE wall
% conductivity so the conducting-sheet wall reproduces the same surface resistance:
%   sigma_eff = sigma + w*eps0*eps'' ;  Zs = sqrt(j*w*mu/sigma_eff), mu = mu0*(mur' - j mur'')
%   Rs = Re(Zs) ;  sigma_wall = pi*f*mu0 / Rs^2   (conductivity giving that Rs)
% (define constants explicitly so we don't depend on physical_constants naming)
EPS0_ = 8.8541878128e-12;
MU0_  = 1.25663706212e-6;
fmid   = 0.5*(p_fmin + p_fmax);
w      = 2*pi*fmid;
sig_e  = p_sigma + w*EPS0_*p_epspp;
mu_c   = MU0_*(p_mur - 1i*p_mupp);
Zs     = sqrt(1i*w*mu_c / sig_e);
Rs_eff = real(Zs);
if Rs_eff > 0
    p_sigma_wall = pi*fmid*MU0_ / Rs_eff^2;      % effective conductivity for the sheet
else
    p_sigma_wall = p_sigma;
end
printf('wall loss: sigma=%.3e S/m, eps_pp=%.3g, mu_pp=%.3g -> Rs=%.4g ohm, sigma_wall=%.3e S/m\n', ...
       p_sigma, p_epspp, p_mupp, Rs_eff, p_sigma_wall);

FDTD = InitFDTD('NrTS', 60000, 'EndCriteria', 1e-4);
FDTD = SetGaussExcite(FDTD, 0.5*(p_fmin+p_fmax), 0.5*(p_fmax-p_fmin));
% walls are conducting sheets (below); domain edges just absorb any leakage
FDTD = SetBoundaryCond(FDTD, {'MUR','MUR','MUR','MUR','MUR','MUR'});

CSX = InitCSX();
if ~exist('p_cells','var'); p_cells = 20; end   % mesh density: cells per wavelength
res  = c0 / p_fmax / unit / p_cells;    % ~lambda/p_cells at f_max
tw   = max(1.5, 2*res);                 % wall thickness (mm) — finite so the wave can transmit through a leaky wall
padx = 10*res; pady = 10*res;           % vacuum margin outside the walls (room to SEE leakage)
mesh.x = SmoothMeshLines([-padx -tw 0 a a+tw a+padx], res);
mesh.y = SmoothMeshLines([-pady -tw 0 b b+tw b+pady], res);
mesh.z = SmoothMeshLines([0 len], res);
CSX = DefineRectGrid(CSX, unit, mesh);

% write the guide vs domain extents so the renderer can draw the guide outline
% inside the larger field region and show any field that leaks OUT past the walls.
gfid = fopen(fullfile(here, 'render_geo.txt'), 'w');
fprintf(gfid, '%g %g %g %g %g %g %g %g %g %g %g %g\n', ...
        mesh.x(1), mesh.x(end), mesh.y(1), mesh.y(end), mesh.z(1), mesh.z(end), ...
        0, a, 0, b, 0, len);
fclose(gfid);

% --- wall model chosen by conductivity ---
if p_sigma_wall > 1e4
    % GOOD CONDUCTOR (metals, MXene): surface-impedance conducting sheet. Accurate
    % wall loss (skin depth << mesh cell can't be volume-meshed) and it contains the wave.
    CSX = AddConductingSheet(CSX, 'wall', p_sigma_wall, p_thick);
    CSX = AddBox(CSX, 'wall', 10, [0 0 0], [0 b len]);     % x = 0 wall
    CSX = AddBox(CSX, 'wall', 10, [a 0 0], [a b len]);     % x = a wall
    CSX = AddBox(CSX, 'wall', 10, [0 0 0], [a 0 len]);     % y = 0 wall
    CSX = AddBox(CSX, 'wall', 10, [0 b 0], [a b len]);     % y = b wall
else
    % LEAKY / DIELECTRIC / MAGNETIC wall (bare basswood, poor conductors, ferrite absorbers):
    % finite-thickness material block so the wave TRANSMITS through and you see it leak OUT.
    % Use the material's REAL complex properties (the good-conductor surface-impedance fold-in
    % used above is invalid for a transmissive block): electric conductivity = sigma + w*eps0*eps''
    % and magnetic conductivity Sigma = w*mu0*mu'' (Ohm/m) so magnetic absorbers (magnetite,
    % carbonyl iron) actually keep their permeability instead of silently becoming mu_r = 1.
    kappa_e = p_sigma + w*EPS0_*p_epspp;      % electric conductivity + dielectric loss  (S/m)
    sigma_m = w*MU0_*p_mupp;                  % magnetic loss as magnetic conductivity    (Ohm/m)
    CSX = AddMaterial(CSX, 'wall');
    CSX = SetMaterialProperty(CSX, 'wall', 'Epsilon', p_epsr, 'Mue', p_mur, 'Kappa', kappa_e, 'Sigma', sigma_m);
    CSX = AddBox(CSX, 'wall', 10, [-tw 0   0], [0    b   len]);   % x = 0 wall (outward)
    CSX = AddBox(CSX, 'wall', 10, [a   0   0], [a+tw b   len]);   % x = a wall
    CSX = AddBox(CSX, 'wall', 10, [0  -tw  0], [a    0   len]);   % y = 0 wall
    CSX = AddBox(CSX, 'wall', 10, [0   b   0], [a    b+tw len]);  % y = b wall
end

% --- optional structure shape inside the guide (scatterer) ---
if ~exist('p_shape','var'); p_shape = 'waveguide'; end
if ~exist('p_ports','var'); p_ports = 2; end   % 1 = reflection only (S11); 2 = thru (S11 + S21)
zc = len/2;
if strcmp(p_shape,'block')
    CSX = AddMetal(CSX, 'obj');
    CSX = AddBox(CSX, 'obj', 20, [a/3 0 zc-6], [2*a/3 b zc+6]);
elseif strcmp(p_shape,'cylinder')
    CSX = AddMetal(CSX, 'obj');
    CSX = AddCylinder(CSX, 'obj', 20, [a/2 0 zc], [a/2 b zc], b/4);
elseif strcmp(p_shape,'sphere')
    CSX = AddMetal(CSX, 'obj');
    CSX = AddSphere(CSX, 'obj', 20, [a/2 b/2 zc], b/3);
elseif strcmp(p_shape,'reflector')
    % full-cross-section MXene wall near the far end -> the wave hits it and
    % reflects, forming a standing wave (shows how well the material reflects)
    CSX = AddConductingSheet(CSX, 'cap', p_sigma_wall, p_thick);
    CSX = AddBox(CSX, 'cap', 20, [0 0 mesh.z(end-3)], [a b mesh.z(end-3)]);
end

% --- TE10 waveguide ports (cross-section x:0..a, y:0..b) ---
% HOW THE WAVE IS INSERTED: Port 1 is a rectangular-waveguide port at the input,
% EXCITED with the TE10 mode (a Gaussian pulse spanning the band; the trailing
% "1" is the excitation amplitude). That is the wave launched into the guide.
%   2-port (thru):  Port 2 at the far end is a matched waveguide port that
%                   captures the transmitted wave  ->  S11 (reflection) + S21 (thru).
%   1-port (refl):  only Port 1; the far end is absorbed by the MUR boundary
%                   (a matched termination)        ->  only S11 is measured.
start = [0 0 mesh.z(8)];   stop = [a b mesh.z(15)];
[CSX, port{1}] = AddRectWaveGuidePort(CSX, 0, 1, start, stop, 'z', a*unit, b*unit, 'TE10', 1);
if p_ports == 2
    start = [0 0 mesh.z(end-14)]; stop = [a b mesh.z(end-7)];
    [CSX, port{2}] = AddRectWaveGuidePort(CSX, 0, 2, start, stop, 'z', a*unit, b*unit, 'TE10');
end

% --- E-field dump for the 3-D render ---
CSX = AddDump(CSX, 'Et', 'DumpType', 0, 'DumpMode', 2, 'SubSampling', '2,2,2');
% dump the FULL cross-section (guide + surrounding vacuum) so field that leaks
% through lossy/leaky walls is captured and can be rendered escaping the guide
CSX = AddBox(CSX, 'Et', 0, [mesh.x(1) mesh.y(1) 0], [mesh.x(end) mesh.y(end) len]);
% frequency-domain (DFT) dump at band centre -> steady-state |E| field view.
% Added ONLY when the "Field view" toggle is set to frequency-domain; the time
% dump above is always present so animations / loss-map / reflection are unaffected.
if ~exist('p_field_mode','var'); p_field_mode = 'time'; end
if strcmp(p_field_mode, 'freq')
    CSX = AddDump(CSX, 'Ef', 'DumpType', 10, 'DumpMode', 2, 'Frequency', fmid, 'SubSampling', '2,2,2');
    CSX = AddBox(CSX, 'Ef', 0, [mesh.x(1) mesh.y(1) 0], [mesh.x(end) mesh.y(end) len]);
end

% --- run ---
scr=getenv('OPENEMS_SCRATCH'); if isempty(scr), if ispc(), scr='C:/openems_scratch'; else scr='/tmp'; end; end; Sim_Path = [scr '/wg_sim'];
[~,~,~] = rmdir(Sim_Path,'s'); mkdir(Sim_Path);
WriteOpenEMS([Sim_Path '/wg.xml'], FDTD, CSX);
RunOpenEMS(Sim_Path, 'wg.xml');

% --- S-parameters ---
% S11 = reflected/incident at Port 1 (input match). In 2-port mode S21 = the
% forward wave at Port 2 / incident at Port 1 (both ports share the +z forward
% direction, so Port 2's "inc" IS the transmitted wave). By reciprocity S12=S21.
freq = linspace(p_fmin, p_fmax, 201);
port = calcPort(port, Sim_Path, freq);
S11 = port{1}.uf.ref ./ port{1}.uf.inc;
if p_ports == 2
    S21 = port{2}.uf.inc ./ port{1}.uf.inc;
else
    S21 = nan(size(S11));                    % 1-port: reflection only, no S21
end

if ~exist(p_outdir, 'dir'); mkdir(p_outdir); end

% S21 measurement-plane separation. openEMS de-embeds each port to its stop plane
% (AddWaveGuidePort: measplanepos = stop(dir)): port 1 -> mesh.z(15), port 2 -> mesh.z(end-7).
% This propagation distance — NOT the full p_len — is what the S21 attenuation accrues over,
% so it is the correct length for dB/m and for overlaying the analytical model.
if p_ports == 2
    port_sep_mm = abs(mesh.z(end-7) - mesh.z(15));    % mesh is in mm (unit = 1e-3)
    fps = fopen(fullfile(p_outdir, 'port_sep.txt'), 'w');
    fprintf(fps, '%.4f\n', port_sep_mm);
    fclose(fps);
end

% insertion loss (S21) — only in 2-port (thru) mode, and NOT for the reflector
% (its far end is shorted, so port 2's "S21" is a meaningless ~0 dB that would otherwise
% overwrite the guided run's real insertion_loss.csv and corrupt the accuracy history).
if p_ports == 2 && ~strcmp(p_shape,'reflector')
    fid = fopen(fullfile(p_outdir, 'insertion_loss.csv'), 'w');
    fprintf(fid, 'freq_ghz,s21_db\n');
    for k = 1:numel(freq)
        fprintf(fid, '%.4f,%.5f\n', freq(k)/1e9, 20*log10(abs(S21(k))));
    end
    fclose(fid);
end

% R / T / A from the S-parameters (needs both R and T -> 2-port only)
if p_ports == 2
    Rr = abs(S11).^2; Tt = abs(S21).^2;
    if strcmp(p_shape,'reflector')
        % far end is shorted -> no forward transmission out of the guide.
        Tt = zeros(size(Tt));
    end
    Aa = max(0, 1 - Rr - Tt);
    fid2 = fopen(fullfile(p_outdir, ['rta_' p_shape '.csv']), 'w');
    fprintf(fid2, 'freq_ghz,R,T,A\n');
    for k = 1:numel(freq)
        fprintf(fid2, '%.4f,%.5f,%.5f,%.5f\n', freq(k)/1e9, Rr(k), Tt(k), Aa(k));
    end
    fclose(fid2);
end

% S-parameters vs frequency for the "S-parameters" option (S11 always; S21 in 2-port)
fid3 = fopen(fullfile(p_outdir, ['sparams_' p_shape '.csv']), 'w');
if p_ports == 2
    fprintf(fid3, 'freq_ghz,s11_db,s21_db\n');
    for k = 1:numel(freq)
        fprintf(fid3, '%.4f,%.5f,%.5f\n', freq(k)/1e9, 20*log10(abs(S11(k))), 20*log10(abs(S21(k))));
    end
else
    fprintf(fid3, 'freq_ghz,s11_db\n');
    for k = 1:numel(freq)
        fprintf(fid3, '%.4f,%.5f\n', freq(k)/1e9, 20*log10(abs(S11(k))));
    end
end
fclose(fid3);

ii = find(freq >= 0.5*(p_fmin+p_fmax), 1);
printf('\n=== %s (%d-port) ===\n', p_label, p_ports);
if p_ports == 2
    printf('mid-band  S21 = %.4f dB   S11 = %.1f dB   (over %.0f mm)\n', ...
           20*log10(abs(S21(ii))), 20*log10(abs(S11(ii))), len);
else
    printf('mid-band  S11 = %.1f dB   (1-port reflection, over %.0f mm)\n', ...
           20*log10(abs(S11(ii))), len);
end
printf('S-parameters written to %s\n', p_outdir);
