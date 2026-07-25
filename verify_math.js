// Verification harness — functions copied VERBATIM from waveguide_simulator.html
// Goal: independently re-run every physics/math anchor claimed in PROJECT_HANDOFF.md
'use strict';
const MU0=4*Math.PI*1e-7,EPS0=8.8541878128e-12,C=299792458,ETA0=Math.sqrt(MU0/EPS0);
const BANDS={X:{f0:8,f1:12,a:22.86e-3,b:10.16e-3},Ku:{f0:12,f1:18,a:15.80e-3,b:7.90e-3},K:{f0:18,f1:27,a:10.67e-3,b:4.32e-3}};

// ---- core engine (lines 773-797) ----
const sigEff=(f,s,epsPP)=>s + 2*Math.PI*f*EPS0*(epsPP||0);
const skin=(f,s,mur,epsPP)=>1/Math.sqrt(Math.PI*f*MU0*(mur||1)*sigEff(f,s,epsPP));
function surfRs(f,s,mur,epsPP,muPP){
  const w=2*Math.PI*f, se=sigEff(f,s,epsPP);
  const re=w*MU0*(muPP||0)/se, im=w*MU0*(mur||1)/se;
  const r=Math.hypot(re,im); return Math.sqrt((r+re)/2);
}
function Rs(f,s,t,mur,epsPP,muPP){const d=skin(f,s,mur,epsPP);const r=surfRs(f,s,mur,epsPP,muPP);return t==null?r:r/Math.tanh(t/d);}
function atten(f,a,b,s,t,mur,epsPP,muPP){const fc=C/(2*a);if(f<=fc)return NaN;const r=fc/f;const rs=Rs(f,s,t,mur,epsPP,muPP);
  return (rs/(b*ETA0*Math.sqrt(1-r*r)))*(1+2*(b/a)*r*r)*8.685889638;}
function penDepth(f,s,epsR,muR,epsPP){
  const w=2*Math.PI*f, ep=EPS0*(epsR||1), mu=MU0*(muR||1), st=sigEff(f,s,epsPP);
  const term=(w*w*ep*mu/2)*(Math.sqrt(1+Math.pow(st/(w*ep),2))-1);
  return term>0?1/Math.sqrt(term):Infinity;
}
const perim=g=>2*(g.a+g.b);

// ---- material catalogs (lines 804-831) ----
const CONDUCTORS={
  silver:{name:'Silver',sigma:6.3e7,density:10490,price:1000,co2:150},
  copper:{name:'Copper',sigma:5.8e7,density:8960,price:10,co2:3.5},
  gold:{name:'Gold',sigma:4.1e7,density:19300,price:85000,co2:35000},
  aluminum:{name:'Aluminum',sigma:3.5e7,density:2700,price:3.4,co2:9},
  brass:{name:'Brass',sigma:1.5e7,density:8500,price:8,co2:4},
  nickel:{name:'Nickel',sigma:1.43e7,density:8900,price:18,co2:9},
  mxene:{name:'MXene',sigma:1e6,density:3700,price:25000,co2:15},
  graphene:{name:'Graphene film',sigma:1e7,density:2200,price:50000,co2:30},
  graphite:{name:'Graphite/carbon',sigma:2e5,density:2100,price:5,co2:5},
  agpaint:{name:'Silver paint',sigma:5e5,density:3000,price:2000,co2:100},
  magnetite:{name:'Magnetite',sigma:5,density:5170,price:5,co2:2,epsR:10,epsPP:1.0,mur:1.3,muPP:0.4},
  cip:{name:'Carbonyl iron',sigma:2,density:4000,price:60,co2:6,epsR:15,epsPP:1.5,mur:3.0,muPP:1.5}
};
const SUBSTRATES={
  wood:{name:'Basswood',density:415,price:3,epsR:1.9,co2:0.45},
  pla:{name:'PLA',density:1240,price:20,epsR:2.7,co2:2.0},peek:{name:'PEEK',density:1320,price:90,epsR:3.2,co2:12},
  abs:{name:'ABS',density:1050,price:3,epsR:2.9,co2:3.5},ptfe:{name:'PTFE',density:2200,price:20,epsR:2.1,co2:7},
  pc:{name:'PC',density:1200,price:4,epsR:2.9,co2:6},pu:{name:'PU',density:1150,price:5,epsR:3.0,co2:4.5},
  fr4:{name:'FR4',density:1850,price:6,epsR:4.4,co2:5},cfrp:{name:'CFRP',density:1600,price:40,epsR:5.0,co2:30},
  invar:{name:'Invar',density:8100,price:30,epsR:1.0,co2:8},alsub:{name:'Al plated',density:2700,price:3.4,epsR:1.0,co2:9}
};
const PRESETS=[
  {key:'ag-al',display:'Silver-plated aluminum',mode:'coating',coat:'silver',sub:'alsub'},
  {key:'ag-invar',display:'Silver-plated Invar',mode:'coating',coat:'silver',sub:'invar'},
  {key:'cu-cfrp',display:'Copper-plated CFRP',mode:'coating',coat:'copper',sub:'cfrp'},
  {key:'ag-peek',display:'Silver-plated PEEK',mode:'coating',coat:'silver',sub:'peek'},
  {key:'ag-pla',display:'Silver-plated PLA',mode:'coating',coat:'silver',sub:'pla'},
  {key:'cu-pla',display:'Copper-plated PLA',mode:'coating',coat:'copper',sub:'pla'},
  {key:'mx-peek',display:'MXene-coated PEEK',mode:'coating',coat:'mxene',sub:'peek'},
  {key:'cu',display:'Solid copper',mode:'solid',solid:'copper'},
  {key:'al',display:'Solid aluminum',mode:'solid',solid:'aluminum'},
  {key:'ag',display:'Solid silver',mode:'solid',solid:'silver'}
];
function presetSpec(p){
  if(p.mode==='solid'){const c=CONDUCTORS[p.solid];
    return {mode:'solid',display:p.display,solidSigma:c.sigma,solidDensity:c.density,solidPrice:c.price,solidCo2:c.co2||0,
      solidEps:c.epsR||1,solidEpsPP:c.epsPP||0,solidMu:c.mur||1,solidMuPP:c.muPP||0};}
  const c=CONDUCTORS[p.coat], s=SUBSTRATES[p.sub];
  return {mode:'coating',display:p.display,
    coatName:c.name,coatSigma:c.sigma,coatDensity:c.density,coatPrice:c.price,coatCo2:c.co2||0,
    coatEps:c.epsR||1,coatEpsPP:c.epsPP||0,coatMu:c.mur||1,coatMuPP:c.muPP||0,
    subName:s.name,subDensity:s.density,subPrice:s.price,subCo2:s.co2||0,subEps:s.epsR,subEpsPP:0,subMu:1,subMuPP:0};
}
function evalSpec(spec,bandKey,coats,ct,wt,launch,L){
  const g=BANDS[bandKey], fmid=(g.f0+g.f1)/2*1e9, P=perim(g);
  const coating=spec.mode==='coating';
  const sig=coating?spec.coatSigma:spec.solidSigma;
  const mur=coating?(spec.coatMu||1):(spec.solidMu||1);
  const epsPP=coating?(spec.coatEpsPP||0):(spec.solidEpsPP||0);
  const muPP=coating?(spec.coatMuPP||0):(spec.solidMuPP||0);
  const epsR=coating?(spec.coatEps||1):(spec.solidEps||1);
  const tThick=coating?coats*ct:null;
  const loss=atten(fmid,g.a,g.b,sig,tThick,mur,epsPP,muPP);
  const mass=coating?(P*wt*spec.subDensity + P*(coats*ct)*spec.coatDensity):(P*wt*spec.solidDensity);
  const matCost=coating?(P*wt*spec.subDensity*spec.subPrice + P*(coats*ct)*spec.coatDensity*spec.coatPrice):(P*wt*spec.solidDensity*spec.solidPrice);
  const cuMass=P*wt*8960, cuMat=cuMass*10, dW=cuMass-mass;
  let be = dW<=0 ? null : Math.max(0,(matCost-cuMat)/dW);
  const dp=penDepth(fmid,sig,epsR,mur,epsPP), sd=skin(fmid,sig,mur,epsPP);
  return {loss, massPerM:mass, be, sd, dp};
}
// computeBreakeven (lines 1254-1265) — the OTHER break-even path
function computeBreakeven(matKey,band,coats){
  const g=BANDS[band]; if(!g) return null;
  const P=2*(g.a+g.b), wallT=1.5e-3, coatT=(coats||20)*1e-6;
  let wT,matT;
  if(matKey==='copper'){wT=P*wallT*8960;matT=wT*10;}
  else if(matKey==='aluminum'){wT=P*wallT*2700;matT=wT*3.4;}
  else if(matKey==='wood'){wT=P*wallT*415;matT=wT*3;}
  else {wT=P*wallT*415+P*coatT*3700; matT=P*wallT*415*3+P*coatT*3700*25000;}
  const wCu=P*wallT*8960, matCu=wCu*10, dW=wCu-wT;
  if(dW<=0) return null;
  const lc=(matT-matCu)/dW; return lc<=0?0:lc;
}

// ---- transfer matrix R/T/A (lines 1284-1329) ----
const cx=(re,im=0)=>({re,im});
const cadd=(a,b)=>cx(a.re+b.re,a.im+b.im);
const csub=(a,b)=>cx(a.re-b.re,a.im-b.im);
const cmul=(a,b)=>cx(a.re*b.re-a.im*b.im,a.re*b.im+a.im*b.re);
const cdiv=(a,b)=>{const d=b.re*b.re+b.im*b.im;return cx((a.re*b.re+a.im*b.im)/d,(a.im*b.re-a.re*b.im)/d);};
const csdiv=(a,s)=>cx(a.re/s,a.im/s), csmul=(a,s)=>cx(a.re*s,a.im*s);
const cabs2=a=>a.re*a.re+a.im*a.im;
const ccosh=z=>cx(Math.cosh(z.re)*Math.cos(z.im),Math.sinh(z.re)*Math.sin(z.im));
const csinh=z=>cx(Math.sinh(z.re)*Math.cos(z.im),Math.cosh(z.re)*Math.sin(z.im));
const sk=(f,s,mur)=>1/Math.sqrt(Math.PI*f*MU0*(mur||1)*s);
function layer(gd,eta){const ch=ccosh(gd),sh=csinh(gd);return {A:ch,B:cmul(eta,sh),Cc:cdiv(sh,eta),D:ch};}
function matmul(m1,m2){return {
  A:cadd(cmul(m1.A,m2.A),cmul(m1.B,m2.Cc)), B:cadd(cmul(m1.A,m2.B),cmul(m1.B,m2.D)),
  Cc:cadd(cmul(m1.Cc,m2.A),cmul(m1.D,m2.Cc)), D:cadd(cmul(m1.Cc,m2.B),cmul(m1.D,m2.D))};}
function conductor(f,sigma,d,mur){const delta=sk(f,sigma,mur);const dd=Math.min(d,30*delta);
  const gd=cx(dd/delta,dd/delta);const Rs=1/(sigma*delta);return layer(gd,cx(Rs,Rs));}
function dielectric(f,epsr,d,mur){mur=mur||1;const beta=2*Math.PI*f*Math.sqrt(epsr*mur)/C;
  return layer(cx(0,beta*d),cx(ETA0*Math.sqrt(mur/epsr),0));}
function rta(M){const Bn=csdiv(M.B,ETA0),Cn=csmul(M.Cc,ETA0);
  const den=cadd(cadd(M.A,Bn),cadd(Cn,M.D));
  const T=cdiv(cx(2,0),den), G=cdiv(csub(cadd(M.A,Bn),cadd(Cn,M.D)),den);
  const R=cabs2(G),Tp=cabs2(T);return {R,T:Tp,A:Math.max(0,1-R-Tp)};}
function rtaSpec(spec,f,coats){
  const se=spec.subEps||2, sm=spec.subMu||1, CTl=1e-6, WT=1.5e-3;
  if(spec.mode==='coating'){const seff=spec.coatSigma+2*Math.PI*f*EPS0*(spec.coatEpsPP||0);
    return rta(matmul(conductor(f,seff,coats*CTl,spec.coatMu||1),dielectric(f,se,WT,sm)));}
  const seffS=spec.solidSigma+2*Math.PI*f*EPS0*(spec.solidEpsPP||0);
  return rta(conductor(f,seffS,WT,spec.solidMu||1));
}

// ============================ CHECKS ============================
let pass=0, fail=0;
function chk(name,got,exp,tol,unit){
  const ok = Math.abs(got-exp) <= tol;
  (ok?pass++:fail++);
  console.log(`[${ok?'PASS':'FAIL'}] ${name}\n        got=${got}${unit||''}  expected≈${exp}${unit||''}  tol=${tol}`);
}
console.log("================ ANCHOR CHECKS ================");
// 1. Copper WR-90 @10 GHz solid
const cuLoss=atten(10e9,22.86e-3,10.16e-3,5.8e7,null,1,0,0);
chk("Copper WR-90 attenuation @10GHz (Pozar anchor)",+cuLoss.toFixed(4),0.108,0.004," dB/m");
// 2. skin depths
chk("Copper skin depth @10GHz",+(skin(10e9,5.8e7,1,0)*1e6).toFixed(3),0.66,0.03," µm");
chk("MXene skin depth @10GHz (sigma=1e6)",+(skin(10e9,1e6,1,0)*1e6).toFixed(3),5.0,0.2," µm");
// 3. Al/Cu ratio = sqrt(sigma_cu/sigma_al)
const alLoss=atten(10e9,22.86e-3,10.16e-3,3.5e7,null,1,0,0);
chk("Al/Cu loss ratio = sqrt(sig_cu/sig_al)",+(alLoss/cuLoss).toFixed(4),Math.sqrt(5.8e7/3.5e7),0.001,"");
// 4. cutoffs
chk("WR-90 cutoff",+(C/(2*22.86e-3)/1e9).toFixed(3),6.557,0.01," GHz");
chk("WR-62 cutoff",+(C/(2*15.80e-3)/1e9).toFixed(3),9.487,0.01," GHz");
chk("WR-42 cutoff",+(C/(2*10.67e-3)/1e9).toFixed(3),14.05,0.02," GHz");
// 5. penetration depth == skin depth for a good conductor
const dpCu=penDepth(10e9,5.8e7,1,1,0), sdCu=skin(10e9,5.8e7,1,0);
chk("Penetration depth / skin depth (copper) ratio",+(dpCu/sdCu).toFixed(5),1.0,1e-3,"");
// 6. magnetic solids (handoff §16)
const magL=atten(10e9,22.86e-3,10.16e-3,5,null,1.3,1.0,0.4);
chk("Magnetite solid loss @10GHz (handoff 464.585)",+magL.toFixed(3),464.585,0.5," dB/m");
const cipL=atten(10e9,22.86e-3,10.16e-3,2,null,3.0,1.5,1.5);
chk("Carbonyl iron solid loss @10GHz (handoff 1080.194)",+cipL.toFixed(3),1080.194,1.0," dB/m");
// 7. break-evens (handoff §16: Al $0, MXene $17,569, magnetite $0, carbonyl $30)
const mxSpec={mode:'coating',coatSigma:1e6,coatDensity:3700,coatPrice:25000,coatEps:1,coatEpsPP:0,coatMu:1,coatMuPP:0,
  subDensity:415,subPrice:3,subEps:1.9,subEpsPP:0.05,subMu:1};
const beMX=evalSpec(mxSpec,'X',20,1e-6,1.5e-3,7000,1).be;
const beAl=evalSpec(presetSpec({mode:'solid',solid:'aluminum',display:'Al'}),'X',20,1e-6,1.5e-3,7000,1).be;
const beMag=evalSpec(presetSpec({mode:'solid',solid:'magnetite',display:'Mag'}),'X',20,1e-6,1.5e-3,7000,1).be;
const beCip=evalSpec(presetSpec({mode:'solid',solid:'cip',display:'Cip'}),'X',20,1e-6,1.5e-3,7000,1).be;
console.log(`\n  break-even (evalSpec, defaults 20 coats/1um/1.5mm): MXene-basswood=$${beMX==null?'n/a':beMX.toFixed(0)}/kg, Al=$${beAl==null?'n/a':beAl.toFixed(0)}, Magnetite=$${beMag==null?'n/a':beMag.toFixed(0)}, Carbonyl=$${beCip==null?'n/a':beCip.toFixed(0)}`);
console.log(`  break-even (computeBreakeven path): MXene=$${computeBreakeven('mxene','X',20).toFixed(0)}/kg, Al=$${computeBreakeven('aluminum','X',20).toFixed(0)}, Cu=$${computeBreakeven('copper','X',20)}`);

// 7b. RL (metal-backed single layer) + PEC plate RCS — RAM/RCS module anchors (matches the RL tab)
console.log("\n================ RL / PLATE-RCS ANCHORS ================");
function _csqrt(z){const r=Math.hypot(z.re,z.im);let im=Math.sqrt((r-z.re)/2);if(z.im<0)im=-im;return cx(Math.sqrt((r+z.re)/2),im);}
function _ctanh(z){const d=Math.cosh(2*z.re)+Math.cos(2*z.im);return cx(Math.sinh(2*z.re)/d,Math.sin(2*z.im)/d);}
function reflLossDB(f,ep,epp,mup,mupp,dmm){                       // f GHz, d mm; RL=20log10|(Zin-1)/(Zin+1)|
  const eps=cx(ep,-Math.abs(epp)), mu=cx(mup,-Math.abs(mupp));
  const k=2*Math.PI*f*1e9/C, n=_csqrt(cmul(mu,eps));
  const zin=cmul(_csqrt(cdiv(mu,eps)),_ctanh(cmul(cx(0,k*dmm/1000),n)));
  return 20*Math.log10(Math.sqrt(cabs2(cdiv(csub(zin,cx(1,0)),cadd(zin,cx(1,0))))));
}
chk("Reflection loss @0.5GHz,1mm (advisor Excel −0.00979)",+reflLossDB(0.5,12.2621009232187,3.88113647824273,1.1875127393561,0.0545051181958087,1).toFixed(5),-0.00979,0.001," dB");
const pecPlateDBsm=(aM,fG)=>{const lam=C/(fG*1e9),A=aM*aM;return 10*Math.log10(4*Math.PI*A*A/(lam*lam));};
chk("PEC 180mm plate RCS @9GHz (4πA²/λ², advisor case)",+pecPlateDBsm(0.18,9).toFixed(3),10.75,0.05," dBsm");
chk("PEC 180mm plate RCS @13.2GHz (paper CST +14.1)",+pecPlateDBsm(0.18,13.2).toFixed(3),14.08,0.05," dBsm");

// 7c. Analytical horn engine (Balanis aperture integration) — matches the Horn tab
console.log("\n================ HORN ANCHORS ================");
function hslant(feed,ap,L){ if(ap<=feed) return 1e12; const pe=L*ap/(ap-feed); return Math.hypot(pe,ap/2); }
function hApI(W,rho,k,amp){ const N=360,a=-W/2,h=W/N; let re=0,im=0,pw=0;
  for(let i=0;i<=N;i++){ const u=a+i*h, w=(i===0||i===N)?0.5:1, A=amp(u), ph=-k*u*u/(2*rho);
    re+=w*A*Math.cos(ph); im+=w*A*Math.sin(ph); pw+=w*A*A; }
  re*=h; im*=h; pw*=h; return (re*re+im*im)/pw; }               // I = |∫f|²/∫|f|²
function hpyr(Ax,By,L,fa,fb,fG){ const lam=C/(fG*1e9)*1000, k=2*Math.PI/lam;
  const Iy=hApI(By,hslant(fb,By,L),k,()=>1), Ix=hApI(Ax,hslant(fa,Ax,L),k,x=>Math.cos(Math.PI*x/Ax));
  const D=4*Math.PI/(lam*lam)*Ix*Iy; return {D_dBi:10*Math.log10(D), eap:Ix*Iy/(Ax*By)}; }
function hconEap(dm,L,fG){ const lam=C/(fG*1e9)*1000,k=2*Math.PI/lam,am=dm/2,rho=Math.hypot(L,am),N=300;
  let re=0,im=0,nrm=0; for(let i=0;i<=N;i++){const r=am*i/N,w=(i===0||i===N)?0.5:1,ph=-k*r*r/(2*rho);re+=w*Math.cos(ph)*r;im+=w*Math.sin(ph)*r;nrm+=w*r;}
  return 0.836*(re*re+im*im)/(nrm*nrm); }
chk("Horn pyramidal default gain (PE9856B-15, ~15 dBi SGH)",+hpyr(68,49,123,22.86,10.16,10).D_dBi.toFixed(2),15.6,0.6," dBi");
chk("Horn open-ended aperture efficiency (8/π² = 0.811)",+hpyr(22.86,10.16,3e5,22.86,10.16,10).eap.toFixed(3),0.811,0.02,"");
chk("Horn conical illumination-limit ε_ap (TE11 → 0.836)",+hconEap(60,1e6,10).toFixed(3),0.836,0.02,"");

// 8. R/T/A conservation + sanity across all materials
console.log("\n================ R/T/A CONSERVATION ================");
let rtaBad=0;
const mats=[
  {n:'MXene-coated basswood',s:{mode:'coating',coatSigma:1e6,coatEps:1,coatEpsPP:0,coatMu:1,subEps:1.9,subMu:1}},
  {n:'Solid copper',s:{mode:'solid',solidSigma:5.8e7,solidEps:1,solidEpsPP:0,solidMu:1}},
  {n:'Bare basswood',s:{mode:'solid',solidSigma:1,solidEps:1.9,solidEpsPP:0.05,solidMu:1}},
  {n:'Magnetite',s:presetSpec({mode:'solid',solid:'magnetite'})},
  {n:'Carbonyl iron',s:presetSpec({mode:'solid',solid:'cip'})}
];
for(const m of mats){
  const r=rtaSpec(m.s,10e9,20); const sum=r.R+r.T+r.A;
  const ok = Math.abs(sum-1)<1e-9 && r.R>=0 && r.T>=0 && r.A>=0 && r.R<=1.0000001;
  if(!ok) rtaBad++;
  console.log(`  ${ok?'ok ':'BAD'} ${m.n.padEnd(26)} R=${r.R.toFixed(4)} T=${r.T.toExponential(2)} A=${r.A.toFixed(4)}  R+T+A=${sum.toFixed(10)}`);
}
(rtaBad===0?pass++:fail++);
console.log(`  -> ${rtaBad===0?'PASS':'FAIL'}: R/T/A conserves to 1 for all sampled materials`);

// 9. full sweep — no NaN/Inf/negative loss for real materials across bands (solids + coatings)
console.log("\n================ NaN / negative / Inf SWEEP ================");
let bad=0, n=0;
const allSpecs=[
  ...PRESETS.map(p=>({display:p.display,spec:presetSpec(p)})),
  {display:'MXene-coated basswood',spec:mxSpec},
  {display:'Magnetite',spec:presetSpec({mode:'solid',solid:'magnetite'})},
  {display:'Carbonyl iron',spec:presetSpec({mode:'solid',solid:'cip'})}
];
for(const bk of Object.keys(BANDS)){
  const g=BANDS[bk];
  for(const it of allSpecs){
    const r=evalSpec(it.spec,bk,20,1e-6,1.5e-3,7000,1); n++;
    if(!isFinite(r.loss)||r.loss<0){bad++; console.log(`  BAD ${it.display} @${bk}: loss=${r.loss}`);}
  }
}
(bad===0?pass++:fail++);
console.log(`  swept ${n} material×band combos -> ${bad} bad (NaN/neg/Inf). ${bad===0?'PASS':'FAIL'}`);

// 10. cross-file consistency: aluminum sigma must match across app + both openEMS scripts
console.log("\n================ CROSS-FILE CONSISTENCY ================");
const fs=require('fs');
const appAl=3.5e7;
function grabAl(path,re){ try{const m=fs.readFileSync(path,'utf8').match(re); return m?parseFloat(m[1]):null;}catch(e){return null;} }
const hornAl=grabAl('openEMS/cad/horn_wallloss.py',/\("Aluminum",\s*([0-9.eE+]+)\)/);
const srvAl =grabAl('openEMS/openems_server.py',/"aluminum":\s*([0-9.eE+]+)/);
const alOk = hornAl===appAl && srvAl===appAl;
(alOk?pass++:fail++);
console.log(`  [${alOk?'PASS':'FAIL'}] aluminum sigma aligned to ${appAl}: horn_wallloss.py=${hornAl}, openems_server.py=${srvAl}`);

// 11. CAD-RCS analytical engine (PO + first-order PTD facet) — physics anchors.
//     Requires cadrcs_engine.js (the single source of truth also inlined in the HTML).
console.log("\n================ CAD-RCS (PO + PTD FACET ENGINE) ================");
{
  const CAD = require('./cadrcs_engine.js');
  const C0 = 2.99792458e8, lam = C0/10e9;
  const Aplate = 0.30*0.30;
  const P  = CAD.buildPlate(0.30,0.30,60,60);
  const Pf = CAD.prepMesh(P.verts,P.tris), Ped = CAD.buildEdges(P.verts,P.tris);
  // PO plate boresight = 4 pi A^2 / lambda^2 (exact)
  chk('CAD PO plate boresight = 4piA^2/lam^2', CAD.rcsMonostatic(Pf,[-1,0,0],lam).dbsm,
      10*Math.log10(4*Math.PI*Aplate*Aplate/(lam*lam)), 0.02, 'dBsm');
  // PO sphere -> optical/GO limit pi a^2 (PO sits ~0.34 dB above by known PO physics; loose tol)
  const S = CAD.buildSphere(0.05,160,320); const Sf = CAD.prepMesh(S.verts,S.tris);
  chk('CAD PO sphere ~ pi a^2 (optical/PO)', CAD.rcsMonostatic(Sf,[0,0,-1],lam).dbsm,
      10*Math.log10(Math.PI*0.05*0.05), 0.5, 'dBsm');
  // PO cylinder broadside = 2 pi a h^2 / lambda
  const Cy = CAD.buildCylinder(0.02,0.20,180,72); const Cf = CAD.prepMesh(Cy.verts,Cy.tris);
  chk('CAD PO cylinder broadside = 2piah^2/lam', CAD.rcsMonostatic(Cf,[-1,0,0],lam).dbsm,
      10*Math.log10(2*Math.PI*0.02*0.04/lam), 0.15, 'dBsm');
  // PTD plate edge-on floor = L^2/pi (PO alone collapses here)
  const Epol = [0,0,1];
  const eoT = 89.9*Math.PI/180, eoK = [-Math.cos(eoT), -Math.sin(eoT), 0];
  const eo = CAD.rcsPOplusPTD(Pf,Ped,eoK,lam,{Epol});
  chk('CAD PTD plate edge-on floor = L^2/pi', eo.totalDbsm, 10*Math.log10(Aplate/Math.PI), 0.3, 'dBsm');
  // PTD leaves broadside (exact PO) untouched
  const bore = CAD.rcsPOplusPTD(Pf,Ped,[-1,0,0],lam,{Epol});
  chk('CAD PTD broadside preserved (PO ripple)', bore.totalDbsm,
      10*Math.log10(4*Math.PI*Aplate*Aplate/(lam*lam)), 0.05, 'dBsm');
  // PO alone collapses at edge-on -> PTD is what supplies the finite edge return
  const collapseOK = eo.poDbsm < -50;
  (collapseOK?pass++:fail++);
  console.log(`  [${collapseOK?'PASS':'FAIL'}] CAD PO-only collapses at edge-on (got ${eo.poDbsm.toFixed(1)} dBsm < -50) -> PTD supplies the edge diffraction`);
  // a tessellated SMOOTH body must yield ~no "real" edges — otherwise PTD adds huge spurious
  // diffraction (a 1 deg dihedral tolerance made a sphere read +29 dB high). Regression guard.
  const Sed = CAD.buildEdges(S.verts, S.tris);
  const sphNoEdges = Sed.length === 0;
  (sphNoEdges?pass++:fail++);
  console.log(`  [${sphNoEdges?'PASS':'FAIL'}] CAD tessellated sphere has no false sharp edges (got ${Sed.length}) -> PTD adds nothing to a smooth body`);
  chk('CAD PO+PTD sphere = PO sphere (no spurious edge term)',
      CAD.rcsPOplusPTD(Sf, Sed, [0,0,-1], lam, {Epol}).totalDbsm,
      CAD.rcsMonostatic(Sf,[0,0,-1],lam).dbsm, 0.05, 'dBsm');
  // cross-file: the engine inlined in the HTML must match cadrcs_engine.js exactly (no silent drift)
  const stripWs = s => s.replace(/\s+/g,'');
  const between = txt => { const m = txt.match(/\/\/ __CADRCS_ENGINE_START__([\s\S]*?)\/\/ __CADRCS_ENGINE_END__/); return m ? stripWs(m[1]) : null; };
  const eBlk = between(fs.readFileSync('./cadrcs_engine.js','utf8'));
  const hBlk = between(fs.readFileSync('./waveguide_simulator.html','utf8'));
  const engMatch = !!eBlk && !!hBlk && eBlk === hBlk;
  (engMatch?pass++:fail++);
  console.log(`  [${engMatch?'PASS':'FAIL'}] CAD engine block identical in cadrcs_engine.js & waveguide_simulator.html (${eBlk?eBlk.length:0} vs ${hBlk?hBlk.length:0} chars, ws-normalized)`);
}

console.log(`\n================ SUMMARY: ${pass} passed, ${fail} failed ================`);
