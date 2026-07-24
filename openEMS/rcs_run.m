% ============================================================
%  Parametrized openEMS RCS (radar cross section) run — driven by rcs_params.m
%  - plane-wave (TF/SF) incidence on a PEC or coated target in vacuum
%  - NF2FF box captures the scattered far field
%  - RCS = 4*pi * P_scattered / P_incident  (validated vs the Mie series for a sphere)
%  Targets: 'sphere' (Mie anchor) and 'plate' (physical-optics anchor).
%  Outputs (per tag): monostatic RCS vs frequency, and a bistatic RCS pattern at f0.
%
%  Convention: incident wave propagates in the x-y plane at angle p_inc_deg to +x,
%  E polarized along z. Monostatic backscatter is (theta=90 deg, phi=180+inc).
%
%  The server writes rcs_params.m, then calls:  octave --no-gui rcs_run.m
% ============================================================
close all; clear; clc;

here = fileparts(mfilename('fullpath'));
pth_oe=getenv('OPENEMS_MATLAB_PATH'); if isempty(pth_oe), pth_oe='/opt/homebrew/Cellar/openems/0.0.36/share/openEMS/matlab'; end; addpath(pth_oe);
pth_cx=getenv('CSXCAD_MATLAB_PATH'); if isempty(pth_cx), pth_cx='/opt/homebrew/Cellar/csxcad/0.6.4/share/CSXCAD/matlab'; end; addpath(pth_cx);
run(fullfile(here, 'rcs_params.m'));   % p_shape,p_size1,p_size2,p_fmin,p_fmax,p_inc_deg,p_coated,p_sigma,...,p_cells,p_tag,p_outdir,p_label

physical_constants; unit = 1e-3;        % mm

% -------- defaults (lossless PEC target if coating terms absent) --------
if ~exist('p_shape','var');   p_shape  = 'sphere'; end
if ~exist('p_size1','var');   p_size1  = 50;  end     % sphere radius, or plate width (mm)
if ~exist('p_size2','var');   p_size2  = 50;  end     % plate height (mm); ignored for sphere
if ~exist('p_inc_deg','var'); p_inc_deg = 0;  end
if ~exist('p_coated','var');  p_coated = 0;   end
if ~exist('p_sigma','var');   p_sigma  = 1e6; end
if ~exist('p_thick','var');   p_thick  = 1e-3; end    % coating thickness (m)
if ~exist('p_epsr','var');    p_epsr   = 1;   end
if ~exist('p_epspp','var');   p_epspp  = 0;   end
if ~exist('p_mur','var');     p_mur    = 1;   end
if ~exist('p_mupp','var');    p_mupp   = 0;   end
if ~exist('p_cells','var');   p_cells  = 24;  end
if ~exist('p_tag','var');     p_tag    = 'bare'; end
if ~exist('p_outdir','var');  p_outdir = fullfile(here,'results'); end
if ~exist('p_label','var');   p_label  = 'target'; end
% -------- which extra analyses to produce (all ride on the SAME single solve) --------
if ~exist('p_do_field','var');  p_do_field  = 0; end   % time-domain E cut-plane dump (for GIF + still)
if ~exist('p_do_eplane','var'); p_do_eplane = 0; end   % E-plane bistatic cut (theta sweep in the x-z plane)
if ~exist('p_do_lobe','var');   p_do_lobe   = 0; end    % full theta-phi grid for the 3-D scattering lobe
% -------- extended user controls --------
if ~exist('p_construct','var'); p_construct = 'pec'; end   % 'pec' | 'coated' | 'solid'
if p_coated; p_construct = 'coated'; end                   % back-compat with the old flag
if ~exist('p_pol','var');      p_pol      = 'v'; end       % 'v': E along z | 'h': E in the incidence plane
if ~exist('p_nfreq','var');    p_nfreq    = 101; end       % frequency points across the band
if ~exist('p_endcrit','var');  p_endcrit  = 1e-4; end      % FDTD energy end criteria (1e-3/-4/-5 = -30/-40/-50 dB)
if ~exist('p_size3','var');    p_size3    = 60; end        % cylinder/dihedral height h (mm)
if ~exist('p_stl','var');      p_stl      = ''; end        % imported STL path (shape='import')
if ~exist('p_stl_scale','var');p_stl_scale= 1.0; end       % multiply STL coords -> mesh units (mm). 1 if STL is in mm

inc  = p_inc_deg/180*pi;
f0   = 0.5*(p_fmin + p_fmax);
lam0 = c0/f0; lam_min = c0/p_fmax;
t_m  = p_thick;                 % coating thickness in metres
t_mm = t_m/unit;                % coating thickness in mm

% -------- object half-extent (mm) --------
if strcmp(p_shape,'sphere')
    obj_half = p_size1;                                   % radius
elseif strcmp(p_shape,'cylinder')
    obj_half = max(p_size1, p_size3/2);                   % radius in x-y, height/2 in z
elseif strcmp(p_shape,'dihedral')
    obj_half = max(p_size1, p_size3/2);                   % arm length a (in -x/-y), height/2 in z
elseif strcmp(p_shape,'import')
    obj_half = p_size1;                                   % max half-extent of the imported mesh (mm), from the server
else
    obj_half = max(p_size1, p_size2)/2;                   % plate: half of the larger in-plane dim
end
tp = max(2, 0.06*obj_half);                   % plate/arm metal thickness (mm), a few cells

% -------- domain: object + vacuum margin; plane-wave box inside; NF2FF at mesh edge; +PML --------
max_res  = lam_min/unit/p_cells;              % cell size ~ lambda_min/p_cells (mm)
% Generous wavelength-scaled vacuum: target -> plane-wave box -> NF2FF box -> PML.
% Too little separation lets PML/box reflections add a spurious frequency ripple to the RCS,
% so each gap is >= ~0.6 lambda at band centre (and never fewer than ~12 cells).
gap      = max(0.8*lam0/unit, 12*max_res);    % vacuum gap (mm) for object->PW and PW->NF2FF
pw_half  = obj_half + t_mm + gap;             % plane-wave box half-extent (clears the target)
half     = pw_half + gap;                     % mesh half-extent (NF2FF sits here, inside the PML)

FDTD = InitFDTD('EndCriteria', p_endcrit);
FDTD = SetGaussExcite(FDTD, f0, 0.5*(p_fmax-p_fmin));
FDTD = SetBoundaryCond(FDTD, [1 1 1 1 1 1]*3);   % 3 = PML on all six faces

CSX = InitCSX();
% Graded mesh: FINE across the target (RCS needs the scatterer well resolved), growing to
% max_res out toward the NF2FF box / PML. Seeding fine fixed lines over the object and letting
% SmoothMeshLines grade outward keeps the cell count bounded while resolving the surface.
is_coat = strcmp(p_construct,'coated');
% NOTE on line seeding: unique() removes only EXACT duplicates. Whenever fixed boundary lines
% are merged into a linspace set below, linspace points within ~half a cell of a fixed line are
% dropped first — a near-coincident pair makes a tiny cell that collapses the CFL timestep ~10x.
if strcmp(p_shape,'sphere')
    fine = min(max_res, obj_half/14);                  % >= ~14 cells across the radius
    nsph = 2*ceil(obj_half/fine)+1;
    sph  = linspace(-obj_half, obj_half, nsph);
    if is_coat   % guarantee the coating shell spans >= 1 cell: fix lines at the metal-core boundary
        rc = max(obj_half - t_mm, obj_half*0.05);
        seeds = [-rc rc]; mind = 0.45*min(fine, t_mm);
        keepS = true(size(sph));
        for kk = 1:numel(seeds); keepS = keepS & (abs(sph - seeds(kk)) > mind); end
        sph = unique([sph(keepS) seeds]);
    end
    L = SmoothMeshLines(unique([-half, sph, half]), max_res, 1.4);
    mesh.x = L; mesh.y = L; mesh.z = L;
elseif strcmp(p_shape,'cylinder')
    % axis along z: fine circle in x-y (radius p_size1), height p_size3 in z
    a = p_size1; h2 = p_size3/2;
    fine = min(max_res, a/12);
    circ = linspace(-a, a, 2*ceil(a/fine)+1);
    zl = linspace(-h2, h2, max(11, 2*ceil(h2/max_res)+1));
    if is_coat   % resolve the coat radially AND on the end caps
        rc = max(a - t_mm, a*0.05);
        zc = max(h2 - t_mm, h2*0.05);
        seeds = [-rc rc]; mind = 0.45*min(fine, t_mm);
        keepC = true(size(circ));
        for kk = 1:numel(seeds); keepC = keepC & (abs(circ - seeds(kk)) > mind); end
        circ = unique([circ(keepC) seeds]);
        seeds = [-zc zc]; mind = 0.45*min(max_res, t_mm);
        keepZ = true(size(zl));
        for kk = 1:numel(seeds); keepZ = keepZ & (abs(zl - seeds(kk)) > mind); end
        zl = unique([zl(keepZ) seeds]);
    end
    Lxy = SmoothMeshLines(unique([-half, circ, half]), max_res, 1.4);
    mesh.x = Lxy; mesh.y = Lxy;
    mesh.z = SmoothMeshLines(unique([-half, zl, half]), max_res, 1.4);
elseif strcmp(p_shape,'dihedral')
    % two perpendicular plates: arm A along -x (thin in y), arm B along -y (thin in x),
    % common edge on the z-axis, height p_size3. Interior corner faces the -x-y quadrant,
    % so bisector illumination is p_inc_deg = 45 (wave travelling into +x+y).
    a = p_size1; h2 = p_size3/2;
    afine = min(max_res, a/10); tfine = min(max_res, max(tp/3, 0.5));
    arm = linspace(-a, 0, ceil(a/afine)+1);
    if is_coat; tkey = [-(tp + t_mm) -tp 0]; else; tkey = [-tp 0]; end   % NO duplicate points (a
    thin = SmoothMeshLines(unique(tkey), tfine, 1.3);                    % near-zero cell collapses the CFL timestep)
    % NEAR-duplicates survive unique(): an arm linspace point can land a hair from a fixed thin
    % line, creating a tiny cell that collapses the CFL timestep ~10x. Drop arm points that fall
    % within 0.6*tfine of any thin line before the union.
    keepA = true(size(arm));
    for kk = 1:numel(thin); keepA = keepA & (abs(arm - thin(kk)) > 0.6*tfine); end
    arm = arm(keepA);
    Lxy = SmoothMeshLines(unique([-half, arm, thin, half]), max_res, 1.4);
    mesh.x = Lxy; mesh.y = Lxy;
    zl = linspace(-h2, h2, max(11, 2*ceil(h2/max_res)+1));
    mesh.z = SmoothMeshLines(unique([-half, zl, half]), max_res, 1.4);
elseif strcmp(p_shape,'import')
    % imported mesh: no analytic surface to seed, so grade a roughly-uniform grid (~max_res)
    % across the object extent and out to the domain box. A Cartesian grid staircases the surface.
    nobj = max(11, 2*ceil(obj_half/max_res)+1);
    obj  = linspace(-obj_half, obj_half, nobj);
    L = SmoothMeshLines(unique([-half, obj, half]), max_res, 1.4);
    mesh.x = L; mesh.y = L; mesh.z = L;
else
    % plate normal along +x (y-z plane), thickness tp in x, coat on the -x (illuminated) face
    xfine = min(max_res, max(tp/3, 0.3));
    xt = SmoothMeshLines(unique([-(tp/2+t_mm*is_coat), -tp/2, 0, tp/2]), xfine, 1.3);
    mesh.x = SmoothMeshLines(unique([-half, xt, half]), max_res, 1.4);
    yl = linspace(-p_size1/2, p_size1/2, max(11, 2*ceil((p_size1/2)/max_res)+1));
    zl = linspace(-p_size2/2, p_size2/2, max(11, 2*ceil((p_size2/2)/max_res)+1));
    mesh.y = SmoothMeshLines(unique([-half, yl, half]), max_res, 1.4);
    mesh.z = SmoothMeshLines(unique([-half, zl, half]), max_res, 1.4);
end

% -------- target geometry: shape x construction (bare PEC / coated PEC / solid material) --------
w = 2*pi*f0;
kappa_e = p_sigma + w*8.8541878128e-12*p_epspp;   % electric conductivity + dielectric loss (S/m)
sigma_m = w*1.25663706212e-6*p_mupp;              % magnetic loss as magnetic conductivity (Ohm/m)
need_mat = is_coat || strcmp(p_construct,'solid');
if need_mat
    CSX = AddMaterial(CSX,'mat');
    CSX = SetMaterialProperty(CSX,'mat','Epsilon',p_epsr,'Mue',p_mur,'Kappa',kappa_e,'Sigma',sigma_m);
end
if strcmp(p_shape,'sphere')
    if strcmp(p_construct,'solid')
        CSX = AddSphere(CSX,'mat',10,[0 0 0],obj_half);            % homogeneous material body
    elseif is_coat
        CSX = AddSphere(CSX,'mat',5,[0 0 0],obj_half);             % outer shell = the coating
        CSX = AddMetal(CSX,'core');
        CSX = AddSphere(CSX,'core',10,[0 0 0],max(obj_half-t_mm,obj_half*0.05));
    else
        CSX = AddMetal(CSX,'sphere');
        CSX = AddSphere(CSX,'sphere',10,[0 0 0],obj_half);
    end
elseif strcmp(p_shape,'cylinder')
    a = p_size1; h2 = p_size3/2;
    if strcmp(p_construct,'solid')
        CSX = AddCylinder(CSX,'mat',10,[0 0 -h2],[0 0 h2],a);
    elseif is_coat
        CSX = AddCylinder(CSX,'mat',5,[0 0 -h2],[0 0 h2],a);       % outer = coating (sides + caps)
        CSX = AddMetal(CSX,'core');
        zc = max(h2 - t_mm, h2*0.05);                              % clamp: a thick coat must never
        CSX = AddCylinder(CSX,'core',10,[0 0 -zc],[0 0 zc],max(a-t_mm,a*0.05));  % invert/protrude the core
    else
        CSX = AddMetal(CSX,'cyl');
        CSX = AddCylinder(CSX,'cyl',10,[0 0 -h2],[0 0 h2],a);
    end
elseif strcmp(p_shape,'dihedral')
    a = p_size1; h2 = p_size3/2;
    % arm A: along -x, thin in y (y in [-tp,0]); arm B: along -y, thin in x
    if strcmp(p_construct,'solid')
        CSX = AddBox(CSX,'mat',10,[-a -tp -h2],[0 0 h2]);
        CSX = AddBox(CSX,'mat',10,[-tp -a -h2],[0 0 h2]);
    else
        CSX = AddMetal(CSX,'dih');
        CSX = AddBox(CSX,'dih',10,[-a -tp -h2],[0 0 h2]);
        CSX = AddBox(CSX,'dih',10,[-tp -a -h2],[0 0 h2]);
        if is_coat   % coat the two ILLUMINATED interior faces (wave arrives from the -x-y quadrant,
                     % so the lit faces are arm A's y=-tp face and arm B's x=-tp face)
            CSX = AddBox(CSX,'mat',5,[-a -(tp+t_mm) -h2],[0 -tp h2]);
            CSX = AddBox(CSX,'mat',5,[-(tp+t_mm) -a -h2],[-tp 0 h2]);
        end
    end
elseif ~strcmp(p_shape,'import')
    % plate: metal slab in the y-z plane  (import is built in its own block below)
    if strcmp(p_construct,'solid')
        CSX = AddBox(CSX,'mat',10,[-tp/2 -p_size1/2 -p_size2/2],[tp/2 p_size1/2 p_size2/2]);
    else
        CSX = AddMetal(CSX,'plate');
        CSX = AddBox(CSX,'plate',10, [-tp/2 -p_size1/2 -p_size2/2], [tp/2 p_size1/2 p_size2/2]);
        if is_coat
            CSX = AddBox(CSX,'mat',5, [-tp/2-t_mm -p_size1/2 -p_size2/2], [-tp/2 p_size1/2 p_size2/2]); % front (-x) face
        end
    end
end
if strcmp(p_shape,'import')
    % arbitrary imported CAD mesh -> solved as a PEC scatterer (staircased on the Cartesian grid).
    % Coated/solid constructions are not supported for imports; the server forces construct='pec'.
    CSX = AddMetal(CSX,'target');
    CSX = ImportSTL(CSX,'target',10, p_stl, 'Transform', {'Scale', p_stl_scale});
end

% -------- plane-wave excitation (must be in vacuum, fully surrounding the target) --------
k_dir = [cos(inc) sin(inc) 0];
if strcmp(p_pol,'h')
    E_dir = [-sin(inc) cos(inc) 0];   % horizontal: E in the incidence (x-y) plane, ⊥ k
else
    E_dir = [0 0 1];                  % vertical: E along z (default)
end
CSX = AddPlaneWaveExcite(CSX, 'plane_wave', k_dir, E_dir, f0);
CSX = AddBox(CSX, 'plane_wave', 0, [-pw_half -pw_half -pw_half], [pw_half pw_half pw_half]);

% -------- NF2FF box (full domain, inside the PML) --------
[CSX, nf2ff] = CreateNF2FFBox(CSX, 'nf2ff', [mesh.x(1) mesh.y(1) mesh.z(1)], [mesh.x(end) mesh.y(end) mesh.z(end)]);

% -------- optional time-domain E-field dump on the z=0 plane (the plane containing k) --------
% This is the TOTAL field (incident + scattered) inside the TF/SF box; it visualises the plane
% wave sweeping in and the target scattering/shadowing it. Rendered to a GIF + still by render_rcs.py.
if p_do_field
    CSX = AddDump(CSX, 'Et', 'DumpType', 0, 'DumpMode', 2, 'SubSampling', '1,1,1');
    CSX = AddBox(CSX, 'Et', 0, [mesh.x(1) mesh.y(1) 0], [mesh.x(end) mesh.y(end) 0]);
    % geometry hint for the renderer: shape, sizes (mm), incidence, plane extent
    gfd = fopen(fullfile(here, 'rcs_geo.txt'), 'w');
    fprintf(gfd, '%s %.4f %.4f %.4f %.4f %.4f\n', p_shape, p_size1, p_size2, p_inc_deg, mesh.x(1), mesh.x(end));
    fclose(gfd);
end

mesh = AddPML(mesh, 8);
CSX  = DefineRectGrid(CSX, unit, mesh);

scr=getenv('OPENEMS_SCRATCH'); if isempty(scr), if ispc(), scr='C:/openems_scratch'; else scr='/tmp'; end; end; Sim_Path = [scr '/rcs_sim_' p_tag];
[s,m,i] = rmdir(Sim_Path,'s'); [s,m,i] = mkdir(Sim_Path);
WriteOpenEMS([Sim_Path '/rcs.xml'], FDTD, CSX);
RunOpenEMS(Sim_Path, 'rcs.xml');

% -------- incident power-density spectrum from the recorded excitation --------
freq = linspace(p_fmin, p_fmax, p_nfreq);
EF   = ReadUI('et', Sim_Path, freq);
Pin  = 0.5*norm(E_dir)^2/Z0 .* abs(EF.FD{1}.val).^2;
[~,kf0] = min(abs(freq - f0));   % band-centre index (used by all f0 cuts)

if ~exist(p_outdir,'dir'); mkdir(p_outdir); end

% -------- monostatic RCS vs frequency (backscatter: theta=90, phi=180+inc) --------
% Also export the COMPLEX co-pol backscatter (magnitude^2 = co-pol RCS, phase = scattering phase)
% so the client can IFFT it into a down-range profile, plus the co-/cross-pol split per frequency
% (the cross-pol here + a flipped-polarization solve give the full 2x2 polarimetric matrix).
nf = CalcNF2FF(nf2ff, Sim_Path, freq, pi/2, pi+inc, 'Mode', 1);
fid = fopen(fullfile(p_outdir, ['rcs_freq_' p_tag '.csv']), 'w');
fprintf(fid, 'freq_ghz,rcs_m2,rcs_dbsm,co_dbsm,xpol_dbsm,hco_re,hco_im\n');
for k = 1:numel(freq)
    rcs = 4*pi/Pin(k)*nf.P_rad{k}(1);
    Eth = nf.E_theta{k}(1);  Eph = nf.E_phi{k}(1);
    if strcmp(p_pol,'h');  Eco = Eph;  Ex = Eth;  else;  Eco = Eth;  Ex = Eph;  end
    p2 = abs(Eco)^2 + abs(Ex)^2;
    co  = rcs * abs(Eco)^2 / max(p2,1e-30);      % co-pol RCS (m^2)
    xp  = rcs * abs(Ex)^2  / max(p2,1e-30);      % cross-pol RCS (m^2)
    hco = Eco * sqrt(co / max(abs(Eco)^2,1e-30));% complex co-pol, |hco|^2 = co, arg = arg(Eco)
    fprintf(fid, '%.4f,%.6e,%.4f,%.4f,%.4f,%.6e,%.6e\n', freq(k)/1e9, rcs, ...
            10*log10(max(rcs,1e-12)), 10*log10(max(co,1e-12)), 10*log10(max(xp,1e-12)), real(hco), imag(hco));
end
fclose(fid);

% -------- bistatic H-plane pattern at f0 (theta=90 -> x-y plane; E is z-polarized so this
%          plane is perpendicular to E => the H-plane). phi swept: 0=forward, 180=backscatter. --------
phi = (-180:2:180);
nfb = CalcNF2FF(nf2ff, Sim_Path, f0, pi/2, phi*pi/180, 'Mode', 1);
% polarization split: for V-pol incidence E_theta is co-pol at theta=90, E_phi is cross-pol
% (for H-pol incidence the roles swap). Ratio-based so the NF2FF normalization cancels.
Eth2 = abs(nfb.E_theta{1}(:)).^2;  Eph2 = abs(nfb.E_phi{1}(:)).^2;
tot  = max(Eth2 + Eph2, 1e-30);
if strcmp(p_pol,'h'); co_fr = Eph2./tot; else; co_fr = Eth2./tot; end
fid2 = fopen(fullfile(p_outdir, ['rcs_bistatic_' p_tag '.csv']), 'w');
fprintf(fid2, 'phi_deg,rcs_m2,rcs_dbsm,co_dbsm,xpol_dbsm\n');
for k = 1:numel(phi)
    rcs = 4*pi/Pin(kf0)*nfb.P_rad{1}(k);
    co  = rcs*co_fr(k);  xp = rcs*(1-co_fr(k));
    fprintf(fid2, '%.1f,%.6e,%.4f,%.4f,%.4f\n', phi(k), rcs, ...
            10*log10(max(rcs,1e-12)), 10*log10(max(co,1e-12)), 10*log10(max(xp,1e-12)));
end
fclose(fid2);

% -------- bistatic E-plane pattern at f0 (x-z plane, contains E(z) and k(x)) --------
% Parametrise the great circle by beta: direction = [cos b, 0, sin b]; b=0 forward(+x),
% b=180 backscatter(-x). In spherical: theta=acos(sin b), phi=0 (cos b>=0) or 180 (cos b<0).
if p_do_eplane
    beta = (-180:2:180); bt = beta*pi/180;
    th_e = acos(max(-1,min(1, sin(bt))));
    isPi = (cos(bt) < 0);
    rcs_e = zeros(size(beta));
    for grp = 0:1
        sel = find(isPi == grp); if isempty(sel); continue; end
        pv = grp*pi;
        nfe = CalcNF2FF(nf2ff, Sim_Path, f0, th_e(sel), pv, 'Mode', 1);
        for kk = 1:numel(sel)
            rcs_e(sel(kk)) = 4*pi/Pin(kf0)*nfe.P_rad{1}(kk);
        end
    end
    fide = fopen(fullfile(p_outdir, ['rcs_eplane_' p_tag '.csv']), 'w');
    fprintf(fide, 'beta_deg,rcs_m2,rcs_dbsm\n');
    for k = 1:numel(beta)
        fprintf(fide, '%.1f,%.6e,%.4f\n', beta(k), rcs_e(k), 10*log10(max(rcs_e(k),1e-12)));
    end
    fclose(fide);
end

% -------- full theta-phi grid at f0 for the 3-D scattering lobe --------
if p_do_lobe
    tg = (0:6:180); pg = (0:6:360);
    nfg = CalcNF2FF(nf2ff, Sim_Path, f0, tg*pi/180, pg*pi/180, 'Mode', 1);
    Pg  = nfg.P_rad{1};                 % [numel(tg) x numel(pg)]
    fidl = fopen(fullfile(p_outdir, ['rcs_lobe_' p_tag '.csv']), 'w');
    fprintf(fidl, 'theta_deg,phi_deg,rcs_dbsm\n');
    for it = 1:numel(tg)
        for ip = 1:numel(pg)
            rcs = 4*pi/Pin(kf0)*Pg(it, ip);
            fprintf(fidl, '%.0f,%.0f,%.4f\n', tg(it), pg(ip), 10*log10(max(rcs,1e-12)));
        end
    end
    fclose(fidl);
end

% -------- backscatter value at f0 for the summary/history --------
rcs_f0  = 4*pi/Pin(kf0)*nf.P_rad{kf0}(1);
printf('\n=== RCS [%s] %s: backscatter @ %.2f GHz = %.4e m^2 (%.2f dBsm) ===\n', ...
       p_tag, p_label, f0/1e9, rcs_f0, 10*log10(max(rcs_f0,1e-12)));
printf('freq  -> %s\n', fullfile(p_outdir, ['rcs_freq_' p_tag '.csv']));
printf('bist  -> %s\n', fullfile(p_outdir, ['rcs_bistatic_' p_tag '.csv']));
