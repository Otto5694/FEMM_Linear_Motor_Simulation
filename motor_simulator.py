# SPDX-License-Identifier: GPL-3.0-only
"""Configurable FEMM-Qt simulator for ironless tubular linear motors.

Start: python motor_simulator.py motor_parameters.ini --visible
Validate only: python motor_simulator.py motor_parameters.ini --check
Standalone: no previous study scripts or field exports required.
"""
from __future__ import annotations
import argparse,cmath,configparser,csv,importlib.util,json,math,os,shutil,socket,sys,time,traceback,webbrowser
from datetime import datetime
from pathlib import Path

VERSION='1.2.0'
HERE=Path(__file__).resolve().parent
# Types: float, integer, boolean, text, number list, operating targets.
SCHEMA={
 'display':dict(visible=('bool',True),pause_s=('float',.3),keep_open=('bool',True),show_mesh=('bool',False),show_flux_lines=('bool',True),max_field_t=('float',2),view_length_mm=('float',42),window_width_px=('int',600),window_height_px=('int',950)),
 'femm':dict(program_directory=('str','C:/femm-qt/bin'),mesh_mm=('float',.22),air_mesh_mm=('float',8),boundary_padding_mm=('float',180),solver_tolerance=('float',1e-8),min_triangle_angle_deg=('float',20)),
 'magnets':dict(count=('int',26),diameter_mm=('float',10),length_mm=('float',19.5),remanence_20c_t=('float',1.2),temperature_c=('float',60),remanence_coefficient_per_k=('float',-.0012),mu_r=('float',1.05),hcj_20c_a_m=('float',955000),hcj_coefficient_per_k=('float',-.00618)),
 'spacers':dict(thickness_mm=('float',1.5),diameter_mm=('float',10),material=('str','1010 Steel (hot rolled)')),
 'tube':dict(outer_diameter_mm=('float',11)),
 'winding':dict(coils_per_pole_pair=('int',6),pole_pairs=('float',2),inner_diameter_mm=('float',13),wire_copper_mm=('float',.5),wire_coated_mm=('float',.568),wire_resistance_20c_ohm_per_m=('float',.0871),copper_density_kg_m3=('float',8960),copper_coefficient_per_k=('float',.00393),copper_temperature_c=('float',60),layers=('int',6),turns_per_layer=('int',12),max_outer_diameter_mm=('float',0),radial_allowance_mm=('float',.1),axial_allowance_mm=('float',.1),parallel_branches_per_phase=('int',1),connection=('str','star')),
 'motion':dict(payload_g=('float',285),additional_moving_mass_g=('float',50),acceleration_mm_s2=('float',60000),speed_m_s=('float',2),supply_v=('float',48),planning_peak_current_limit_a=('float',25),stroke_mm=('float',300)),
 'operating_points':dict(forces_n=('targets','auto;40'),winding_peak_currents_a=('list','')),
 'simulation':dict(no_load_positions=('int',12),positions_per_period=('int',72),electrical_periods=('int',1),start_position_mm=('str','auto'),calculate_inductance=('bool',True),inductance_step_a=('float',.1),mesh_check=('bool',True),check_mesh_mm=('float',.15),stroke_check_positions_mm=('list','-150;0;150'),counterfield_check=('bool',True),validate_current_correction=('bool',True),correction_positions=('int',24)),
 'thermal':dict(calculate=('bool',True),effective_conductivities_w_mk=('list','.5'),effective_heat_transfer_w_m2k=('list','100;500'),coolant_temperatures_c=('list','60'),duty_cycle=('str','auto')),
 'output':dict(directory=('str','Results'),field_image_every_n_positions=('int',0),keep_all_models=('bool',False),open_report=('bool',True))}
SCHEMA={section:{key.lower():definition for key,definition in fields.items()} for section,fields in SCHEMA.items()}

def number(text):
    value=float(str(text).strip().replace(' ','').replace(',','.'))
    if not math.isfinite(value):raise ValueError('The number must be finite.')
    return value

def convert(text,kind):
    if kind=='str':return str(text).strip()
    if kind=='float':return number(text)
    if kind=='int':
        value=number(text)
        if not value.is_integer():raise ValueError('An integer is required.')
        return int(value)
    if kind=='bool':
        value=str(text).strip().lower()
        if value in ['true','yes','1','on']:return True
        if value in ['false','no','0','off']:return False
        raise ValueError('Expected yes or no.')
    values=[x.strip() for x in str(text).split(';') if x.strip()]
    return [('auto' if x.lower()=='auto' else number(x)) if kind=='targets' else number(x) for x in values]

def read_parameters(path):
    parser=configparser.ConfigParser(interpolation=None,inline_comment_prefixes=('#',))
    if not parser.read(path,encoding='utf-8-sig'):raise ValueError(f'Parameter file not found: {path}')
    for section in parser.sections():
        if section not in SCHEMA:raise ValueError(f'Unknown section [{section}].')
        unknown=set(parser[section])-set(SCHEMA[section])
        if unknown:raise ValueError(f'Unknown parameters in [{section}]: {", ".join(sorted(unknown))}')
    cfg={}
    for section,fields in SCHEMA.items():
        cfg[section]={}
        for key,(kind,default) in fields.items():
            text=parser.get(section,key,fallback=str(default))
            if isinstance(default,bool) and not parser.has_option(section,key):text='yes' if default else 'no'
            try:cfg[section][key]=convert(text,kind)
            except ValueError as exc:raise ValueError(f'[{section}] {key}: {exc}') from exc
    return cfg


def default_parameters(directory=HERE):
    """Create the ignored local configuration once; preserve personal edits."""
    path=directory/'motor_parameters.ini'
    if path.exists():return path
    template=directory/'motor_parameters.example.ini'
    if not template.is_file():raise ValueError(f'Example parameter file missing: {template}')
    try:
        with path.open('x',encoding='utf-8') as stream:stream.write(template.read_text(encoding='utf-8-sig'))
        print(f'Created local parameter file: {path}',flush=True)
    except FileExistsError:pass
    return path

def require(condition,message):
    if not condition:raise ValueError(message)

def derive(c):
    m,d,w,b,s=c['magnets'],c['spacers'],c['winding'],c['motion'],c['simulation']
    for label,value in [('Magnet diameter',m['diameter_mm']),('Magnet length',m['length_mm']),('Spacer diameter',d['diameter_mm']),('Winding inner diameter',w['inner_diameter_mm']),('Wire diameter',w['wire_copper_mm']),('Wire resistance',w['wire_resistance_20c_ohm_per_m']),('Copper density',w['copper_density_kg_m3']),('Mesh size',c['femm']['mesh_mm']),('Boundary padding',c['femm']['boundary_padding_mm']),('Supply voltage',b['supply_v'])]:require(value>0,label+' must be positive.')
    require(m['count']>=4,'Use at least four magnets.')
    require(m['remanence_20c_t']>0 and m['hcj_20c_a_m']>0,'Magnet reference values must be positive.')
    require(m['temperature_c']>-273.15 and w['copper_temperature_c']>-273.15,'Temperatures must be above absolute zero.')
    require(d['thickness_mm']>=0,'Spacer thickness must not be negative.')
    require(m['mu_r']>0,'mu_r must be positive.')
    require(w['wire_coated_mm']>=w['wire_copper_mm'],'Coated wire must not be thinner than its copper core.')
    require(c['tube']['outer_diameter_mm']>=m['diameter_mm'],'Tube outer diameter is smaller than magnet diameter.')
    require(w['inner_diameter_mm']>max(c['tube']['outer_diameter_mm'],m['diameter_mm'],d['diameter_mm']),'The winding would overlap the rod or tube.')
    require(w['coils_per_pole_pair'] in [3,6,12],'coils_per_pole_pair must be 3, 6 or 12.')
    require(w['pole_pairs']>0,'pole_pairs must be positive.')
    count=w['pole_pairs']*w['coils_per_pole_pair']
    require(abs(count-round(count))<1e-9 and round(count)%3==0,'Total coil count must be an integer divisible by three.')
    count=int(round(count));period=2*(m['length_mm']+d['thickness_mm']);pitch=period/w['coils_per_pole_pair']
    require(w['radial_allowance_mm']>=0 and w['axial_allowance_mm']>=0,'Allowances must not be negative.')
    layers=w['layers'];cols=w['turns_per_layer'];coated=w['wire_coated_mm'];inner=w['inner_diameter_mm']
    if layers==0:
        require(w['max_outer_diameter_mm']>inner,'With layers=0, maximum outer diameter must exceed inner diameter.')
        layers=math.floor(((w['max_outer_diameter_mm']-inner)/2-w['radial_allowance_mm'])/coated+1e-9)
    if cols==0:cols=math.floor((pitch-w['axial_allowance_mm'])/coated+1e-9)
    require(layers>=1 and cols>=1,'At least one layer and one turn per layer must fit.')
    require(cols*coated<=pitch-w['axial_allowance_mm']+1e-9,'Too many turns per layer: wire does not fit within coil pitch and axial allowance.')
    outer=inner+2*layers*coated
    if w['max_outer_diameter_mm']>0:require(outer+2*w['radial_allowance_mm']<=w['max_outer_diameter_mm']+1e-9,'Winding and radial allowance exceed the maximum outer diameter.')
    branches=w['parallel_branches_per_phase'];require(branches>=1 and (count//3)%branches==0,'Parallel branches must divide the coil count per phase exactly.')
    require(w['connection'].lower() in ['star','delta'],'connection must be star or delta.')
    require(s['no_load_positions']>=12 and s['no_load_positions']%12==0,'No-load positions must be at least 12 and divisible by 12.')
    require(s['positions_per_period']>=12 and s['positions_per_period']%12==0,'Positions per period must be at least 12 and divisible by 12.')
    require(not s['validate_current_correction'] or s['positions_per_period']>=24,'Current correction requires at least 24 positions per period; 12 undersamples the sixth harmonic.')
    require(s['electrical_periods']>=1,'Simulate at least one electrical period.')
    require(s['correction_positions']>=12 and s['correction_positions']%12==0,'Correction positions must be at least 12 and divisible by 12.')
    require(s['inductance_step_a']>0,'Inductance current step must be positive.')
    require(c['display']['pause_s']>=0 and c['display']['pause_s']<=30,'Display pause must be between 0 and 30 seconds.')
    require(c['display']['view_length_mm']>=0 and c['display']['window_width_px']>=300 and c['display']['window_height_px']>=300,'Invalid view length or window size too small.')
    require(c['output']['field_image_every_n_positions']>=0,'Image interval must not be negative.')
    require(s['check_mesh_mm']>0,'Check mesh size must be positive.')
    require(c['femm']['air_mesh_mm']>0 and 0<c['femm']['solver_tolerance']<1,'Air mesh and solver tolerance must be positive; tolerance must be less than 1.')
    require(all(b[k]>=0 for k in ['payload_g','additional_moving_mass_g','acceleration_mm_s2','speed_m_s','stroke_mm']),'Mass and motion values must not be negative.')
    require(b['planning_peak_current_limit_a']>0,'Planning current limit must be positive.')
    br=m['remanence_20c_t']*(1+m['remanence_coefficient_per_k']*(m['temperature_c']-20));require(br>0,'Calculated remanence is not positive.')
    require(1+w['copper_coefficient_per_k']*(w['copper_temperature_c']-20)>0,'Invalid copper temperature factor.')
    radius=[inner/2+(j+.5)*coated for j in range(layers)]
    wire_length=cols*sum(2*math.pi*r*.001 for r in radius)
    rcoil=wire_length*w['wire_resistance_20c_ohm_per_m']
    copper=wire_length*count*math.pi*w['wire_copper_mm']**2/4*1e-6*w['copper_density_kg_m3']*1000
    mass=(b['payload_g']+b['additional_moving_mass_g']+copper)/1000
    start=-period/2 if s['start_position_mm'].lower()=='auto' else number(s['start_position_mm'])
    forces=[mass*b['acceleration_mm_s2']/1000 if x=='auto' else x for x in c['operating_points']['forces_n']]
    require(all(x>0 for x in forces),'All target forces must be positive; auto requires positive acceleration.')
    require(all(x>0 for x in c['operating_points']['winding_peak_currents_a']),'All peak currents must be positive.')
    require(forces or c['operating_points']['winding_peak_currents_a'],'Specify at least one force or peak current.')
    for k in ['effective_conductivities_w_mk','effective_heat_transfer_w_m2k']:
        require(all(x>0 for x in c['thermal'][k]),'Thermal conductivity and heat transfer coefficient must be positive.')
    require(all(x>-273.15 for x in c['thermal']['coolant_temperatures_c']),'Coolant temperature is below absolute zero.')
    return dict(count=count,density=w['coils_per_pole_pair'],period_mm=period,pitch_mm=pitch,
                packet_mm=count*pitch,wire_span_mm=(count-1)*pitch+cols*coated,inner_mm=inner,outer_mm=outer,
                layers=layers,columns=cols,turns=layers*cols,width_mm=cols*coated,height_mm=layers*coated,
                coil_wire_m=wire_length,total_wire_m=wire_length*count,copper_g=copper,moving_kg=mass,
                R_series_phase20_Ohm=rcoil*count/3,Br_T=br,start_mm=start,forces_N=forces,
                magnet_rod_mm=m['count']*m['length_mm']+(m['count']-1)*d['thickness_mm'])

def plan(g):
    out=[]
    for j in range(g['count']):
        if g['density']==3:phase='ABC'[j%3];sense=1
        else:
            group=j if g['density']==6 else j//2
            phase=['A','C','B'][group%3];sense=1 if group%2==0 else -1
        out.append(dict(coil=j+1,center_mm=(j-(g['count']-1)/2)*g['pitch_mm'],phase=phase,sense=sense))
    return out

def write_json(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def write_csv(path,rows):
    if not rows:return
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),delimiter=';');writer.writeheader();writer.writerows(rows)
def real(value):return float(complex(value).real)

def load_femm(c):
    folder=Path(c['femm']['program_directory']).expanduser()
    os.environ['FEMM_DIR']=str(folder)
    try:import femm
    except ImportError:
        candidates=[folder.parent/'pyfemm'/'femm.py',HERE.parent/'.venv'/'Lib'/'site-packages'/'femm.py']
        found=next((p for p in candidates if p.is_file()),None)
        if found is None:raise RuntimeError('FEMM Python binding missing. Install femm.py supplied with FEMM-Qt; see docs/INSTALLATION.md.')
        spec=importlib.util.spec_from_file_location('femm',found);femm=importlib.util.module_from_spec(spec);spec.loader.exec_module(femm)
    if not hasattr(femm,'FemmSession'):raise RuntimeError('This version requires FEMM-Qt with FemmSession. The classic COM binding is not compatible.')
    return femm

def build(f,c,g,path,shift,mesh=None,padding=None):
    m,d=c['magnets'],c['spacers'];mesh=c['femm']['mesh_mm'] if mesh is None else mesh
    padding=c['femm']['boundary_padding_mm'] if padding is None else padding
    f.newdocument(0);f.mi_probdef(0,'millimeters','axi',c['femm']['solver_tolerance'],0,c['femm']['min_triangle_angle_deg'],0)
    f.mi_addmaterial('Air',1,1,0,0,0,0,0,1,0,0,0,0,0)
    f.mi_addmaterial('PM_Recoil',m['mu_r'],m['mu_r'],g['Br_T']/(4e-7*math.pi*m['mu_r']),0,0,0,0,1,0,0,0,0,0)
    if d['thickness_mm']>0:
        try:f.mi_getmaterial(d['material'])
        except Exception as exc:raise RuntimeError(f'Spacer material "{d["material"]}" is missing from the FEMM library. No automatic substitution.') from exc
    f.mi_addmaterial('Winding_mu1',1,1,0,0,0,0,0,1,0,0,0,0,0)
    for phase in 'ABC':f.mi_addcircprop(phase,0,1)
    f.mi_addboundprop('A0',0,0,0,0,0,0,0,0,0,0,0)
    intervals=[];pitch=m['length_mm']+d['thickness_mm']
    for j in range(m['count']):
        z=-g['magnet_rod_mm']/2+j*pitch
        intervals.append((z,z+m['length_mm'],m['diameter_mm']/2,'PM_Recoil',90 if j%2==0 else -90))
        if j<m['count']-1 and d['thickness_mm']>0:intervals.append((z+m['length_mm'],z+pitch,d['diameter_mm']/2,d['material'],0))
    maxshift=max([abs(g['start_mm']),abs(g['start_mm']+g['period_mm']*c['simulation']['electrical_periods'])]+[abs(x) for x in c['simulation']['stroke_check_positions_mm']])
    zl=max(g['magnet_rod_mm']/2,maxshift+g['wire_span_mm']/2)+padding
    rl=max(m['diameter_mm']/2,d['diameter_mm']/2,g['outer_mm']/2)+padding
    nodes=set();edges=set()
    def segment(a,b):
        for point in [a,b]:
            if point not in nodes:f.mi_addnode(*point);nodes.add(point)
        key=tuple(sorted((a,b)))
        if key not in edges:f.mi_addsegment(*a,*b);edges.add(key)
    # Split shared horizontal faces, also when magnet and spacer diameters differ.
    horizontal={}
    for z0,z1,radius,material,direction in intervals:
        horizontal.setdefault(z0,{0.}).add(radius);horizontal.setdefault(z1,{0.}).add(radius)
        segment((radius,z0),(radius,z1))
        f.mi_addblocklabel(radius/2,(z0+z1)/2);f.mi_selectlabel(radius/2,(z0+z1)/2)
        f.mi_setblockprop(material,0,mesh,'<None>',direction,1 if material=='PM_Recoil' else 2,0);f.mi_clearselected()
    for z,radii in horizontal.items():
        ordered=sorted(radii)
        for a,b in zip(ordered,ordered[1:]):segment((a,z),(b,z))
    axis=sorted({-zl,zl}|set(horizontal))
    for a,b in zip(axis,axis[1:]):segment((0,a),(0,b))
    segment((0,-zl),(rl,-zl));segment((rl,-zl),(rl,zl));segment((rl,zl),(0,zl))
    for a,b in edges:
        if a[0]==b[0]==0 or a[0]==b[0]==rl or a[1]==b[1]==zl or a[1]==b[1]==-zl:
            f.mi_selectsegment((a[0]+b[0])/2,(a[1]+b[1])/2);f.mi_setsegmentprop('A0',0,1,0,0);f.mi_clearselected()
    f.mi_addblocklabel(rl-10,0);f.mi_selectlabel(rl-10,0)
    f.mi_setblockprop('Air',0,c['femm']['air_mesh_mm'],'<None>',0,0,0);f.mi_clearselected()
    coils=[];ri=g['inner_mm']/2;ro=g['outer_mm']/2
    for item in plan(g):
        z=item['center_mm']+shift;z0=z-g['width_mm']/2;z1=z+g['width_mm']/2
        corners=[(ri,z0),(ro,z0),(ro,z1),(ri,z1)]
        for point in corners:
            f.mi_addnode(*point);f.mi_selectnode(*point);f.mi_setnodeprop('<None>',10);f.mi_clearselected()
        for a,b in zip(corners,corners[1:]+corners[:1]):
            f.mi_addsegment(*a,*b);f.mi_selectsegment((a[0]+b[0])/2,(a[1]+b[1])/2)
            f.mi_setsegmentprop('<None>',mesh,0,0,10);f.mi_clearselected()
        f.mi_addblocklabel((ri+ro)/2,z);f.mi_selectlabel((ri+ro)/2,z)
        f.mi_setblockprop('Winding_mu1',0,mesh,item['phase'],0,10,item['sense']*g['turns']);f.mi_clearselected()
        coils.append(dict(item,z_mm=z,rmid_mm=(ri+ro)/2,area_m2=g['width_mm']*g['height_mm']*1e-6))
    f.mi_saveas(str(path));return coils

def set_currents(f,values):
    for p,v in zip('ABC',values):f.mi_modifycircprop(p,1,float(v))

class Run:
    def __init__(self,c,g,folder):self.c=c;self.g=g;self.folder=folder;self.f=None;self.input_open=False;self.output_open=False;self.solves=0;self.warnings=[]
    def log(self,message):
        line=f'[{datetime.now():%H:%M:%S}] {message}';print(line,flush=True)
        with (self.folder/'log.txt').open('a',encoding='utf-8') as stream:stream.write(line+'\n')
        write_json(self.folder/'progress.json',dict(message=message,solves=self.solves,time=datetime.now().isoformat()))
    def connect(self):
        module=load_femm(self.c)
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        self.f=module.FemmSession(port=port,headless=not self.c['display']['visible'])
        process=getattr(self.f,'_proc',None)
        write_json(self.folder/'session.json',dict(port=port,visible=self.c['display']['visible'],python_process_id=os.getpid(),femm_process_id=process.pid if process else None))
        if self.c['display']['visible']:
            try:self.f.callfemm(f'main_resize({self.c["display"].get("window_width_px",600)},{self.c["display"].get("window_height_px",950)})')
            except Exception as exc:self.log('Could not set window size: '+str(exc))
    def close_output(self):
        if self.output_open:self.f.mo_close();self.output_open=False
    def rebuild(self,x,path,mesh=None):
        self.close_output()
        if self.input_open:self.f.mi_close()
        coils=build(self.f,self.c,self.g,path,x,mesh);self.input_open=True
        return coils
    def solve(self,path):
        self.close_output();self.f.mi_saveas(str(path))
        try:self.f.mi_analyze()
        except Exception as exc:
            if 'meshing failed' not in str(exc):raise
            self.log('Retrying mesh generation once.');self.f.mi_purgemesh();self.f.mi_analyze()
        self.f.mi_loadsolution();self.output_open=True;self.solves+=1
        self.f.mo_groupselectblock(10);force=real(self.f.mo_blockintegral(12));self.f.mo_clearblock()
        flux=[real(self.f.mo_getcircuitproperties(p)[2]) for p in 'ABC']
        return force,flux
    def show(self,x,screenshot=None):
        if not self.c['display']['visible']:return
        f=self.f;a=self.c['display'];g=self.g
        f.mo_showdensityplot(1,0,a['max_field_t'],0,'bmag')
        f.mo_showcontourplot(-1) if a['show_flux_lines'] else f.mo_hidecontourplot()
        f.mo_showmesh() if a['show_mesh'] else f.mo_hidemesh()
        span=a.get('view_length_mm',42) or g['packet_mm']+20
        f.mo_zoom(0,x-span/2,g['outer_mm']/2+5,x+span/2);f.mo_refreshview()
        if screenshot:
            try:
                f.mo_savebitmap(str(screenshot))
                if not screenshot.exists():self.log('The GUI did not save a screenshot; the scientific PNG export is still available.')
            except Exception as exc:self.log('GUI image export unavailable: '+str(exc))
        if a['pause_s']:time.sleep(a['pause_s'])

def field_image(run,x,name):
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    f=run.f;g=run.g
    # A regular display grid avoids transferring the complete far-field mesh
    # (hundreds of thousands of entries) for every image. All samples are real
    # mo_getb results from the newly solved FE model, not a synthetic field.
    z=np.linspace(-g['packet_mm']/2-15,g['packet_mm']/2+15,241)
    radius=np.linspace(.001,g['outer_mm']/2+4,49)
    br=np.empty((len(radius),len(z)));bz=np.empty_like(br)
    for j,r in enumerate(radius):
        for i,dz in enumerate(z):
            value=f.mo_getb(float(r),float(x+dz));br[j,i]=real(value[0]);bz[j,i]=real(value[1])
    write_csv(run.folder/'Images'/(name+'.csv'),[dict(r_mm=float(r),z_absolute_mm=float(x+dz),Br_T=float(br[j,i]),Bz_T=float(bz[j,i])) for j,r in enumerate(radius) for i,dz in enumerate(z)])
    np.savez_compressed(run.folder/'Images'/(name+'.npz'),r_mm=radius,z_rel_mm=z,Br_T=br,Bz_T=bz)
    fig,ax=plt.subplots(figsize=(11,3.6),layout='constrained')
    colors=ax.pcolormesh(z,radius,np.hypot(br,bz),vmin=0,vmax=run.c['display']['max_field_t'],cmap='viridis',shading='auto',rasterized=True)
    fig.colorbar(colors,ax=ax,label='|B| [T]')
    for item in plan(g):ax.add_patch(Rectangle((item['center_mm']-g['width_mm']/2,g['inner_mm']/2),g['width_mm'],g['height_mm'],fill=False,edgecolor='white',lw=.6))
    ax.set(xlim=(-g['packet_mm']/2-15,g['packet_mm']/2+15),ylim=(0,g['outer_mm']/2+4),xlabel='Position relative to coil packet center [mm]',ylabel='Radius [mm]',title=f'FEMM loaded field · absolute packet position {x:.3f} mm')
    fig.savefig(run.folder/'Images'/(name+'.png'),dpi=160);plt.close(fig)

def snapshot(path,destination):
    for ext in ['.fem','.ans']:
        p=path.with_suffix(ext)
        if p.exists():shutil.copy2(p,destination.with_suffix(ext))

def driver_currents(values,c):
    p=c['winding']['parallel_branches_per_phase']
    if c['winding']['connection'].lower()=='star':return [p*x for x in values]
    return [p*(values[0]-values[2]),p*(values[1]-values[0]),p*(values[2]-values[1])]

def thermal_models(run,p20):
    import numpy as np
    c,g,f=run.c,run.g,run.f;w=c['thermal'];b=c['motion'];rows=[]
    if w['duty_cycle'].lower()=='auto':
        a=b['acceleration_mm_s2']/1000;v=b['speed_m_s'];distance=b['stroke_mm']/1000
        if a<=0 or v<=0 or distance<=0:duty=1.
        else:
            vmax=min(v,math.sqrt(a*distance));t_acc=2*vmax/a;t_all=t_acc+max(0,distance-vmax*vmax/a)/vmax;duty=t_acc/t_all
    else:duty=number(w['duty_cycle']);require(0<=duty<=1,'duty_cycle must be between 0 and 1.')
    run.close_output()
    if run.input_open:f.mi_close();run.input_open=False
    ri=g['inner_mm']/2;ro=g['outer_mm']/2;L=g['packet_mm'];volume=math.pi*((ro*.001)**2-(ri*.001)**2)*L*.001
    for k in w['effective_conductivities_w_mk']:
      for h in w['effective_heat_transfer_w_m2k']:
       for ambient in w['coolant_temperatures_c']:
        f.newdocument(2);f.hi_probdef('millimeters','axi',1e-9,0,20)
        f.hi_addmaterial('Effective_winding',k,k,1/volume);f.hi_addboundprop('Convection',2,0,0,ambient+273.15,h,0)
        points=[(ri,-L/2),(ro,-L/2),(ro,L/2),(ri,L/2)]
        for point in points:f.hi_addnode(*point)
        for a,bp in zip(points,points[1:]+points[:1]):f.hi_addsegment(*a,*bp)
        f.hi_addblocklabel((ri+ro)/2,0);f.hi_selectlabel((ri+ro)/2,0);f.hi_setblockprop('Effective_winding',0,c['femm']['mesh_mm'],1);f.hi_clearselected()
        f.hi_selectsegment(ro,0);f.hi_setsegmentprop('Convection',0,1,0,0,'<None>');f.hi_clearselected()
        path=run.folder/'Models'/f'Thermal_k{k:g}_h{h:g}_T{ambient:g}.feh'
        f.hi_saveas(str(path));f.hi_analyze();f.hi_loadsolution();run.solves+=1
        radius=np.linspace(ri,ro,101);temp=np.array([real(f.ho_getpointvalues(float(r),0)[0])-273.15 for r in radius])
        rmean=float(np.trapezoid(temp*radius,radius)/np.trapezoid(radius,radius))-ambient;rmax=float(temp.max())-ambient
        denominator=1-p20*duty*c['winding']['copper_coefficient_per_k']*rmean
        power=p20*duty*(1+c['winding']['copper_coefficient_per_k']*(ambient-20))/denominator if denominator>0 else None
        rows.append(dict(k_W_mK=k,h_W_m2K= h,ambient_C=ambient,duty=duty,Rmean_K_W=rmean,Rmax_K_W=rmax,
                         P_mean_equilibrium_W=power,mean_temperature_C=ambient+rmean*power if power is not None else None,
                         hotspot_temperature_C=ambient+rmax*power if power is not None else None))
        f.ho_close();f.hi_close();run.log(f'Thermal model k={k:g}, h={h:g}, coolant={ambient:g} C solved.')
    write_csv(run.folder/'thermal_scenarios.csv',rows);return rows

def report(run,rows,summary,inductance,checks,heat,calibration,correction_summary):
    import matplotlib.pyplot as plt
    import html
    g,c=run.g,run.c
    images_dir=run.folder/'Images'
    fig,axes=plt.subplots(2,1,figsize=(10,7),sharex=True,layout='constrained')
    for name in dict.fromkeys(r['case'] for r in rows):
        selected=[r for r in rows if r['case']==name]
        axes[0].plot([r['angle_deg'] for r in selected],[r['F_N'] for r in selected],'-o',ms=3,label=name)
        axes[1].plot([r['angle_deg'] for r in selected],[r['I_A_winding_A'] for r in selected],label=name+' / phase A')
    axes[0].set_ylabel('Axial force [N]');axes[0].legend(fontsize=9)
    axes[1].set(xlabel='Electrical angle [degrees]',ylabel='Winding current [A]');axes[1].legend(fontsize=9)
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle('Newly solved FEMM loaded fields');fig.savefig(images_dir/'force_and_current.png',dpi=160);plt.close(fig)
    images=sorted(p.name for p in images_dir.glob('Field_*.png'))
    def table(headers,data):
        return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in data)+'</table></div>'
    operating=table(['Operating point','Mean force N','Ripple pp %','Winding peak A','Line peak A','DC Cu loss W','Equivalent phase peak V'],[
        [s['case'],f'{s["F_mean_N"]:.3f}',f'{s["ripple_pp_percent"]:.3f}',f'{s["I_winding_peak_A"]:.3f}',f'{s["I_line_peak_A"]:.3f}',f'{s["P_Cu_W"]:.2f}',f'{s["V_phase_equiv_peak_V"]:.2f}'] for s in summary])
    thermal='Not calculated.'
    if heat:
        thermal=table(['k_eff W/mK','h_eff W/m2K','Coolant C','Duty cycle','Model hotspot C'],[
            [r['k_W_mK'],r['h_W_m2K'],r['ambient_C'],f'{r["duty"]:.3f}',
             'No stable equilibrium' if r['hotspot_temperature_C'] is None else ('>200: outside useful model range' if r['hotspot_temperature_C']>200 else f'{r["hotspot_temperature_C"]:.1f}')] for r in heat])
        fig,ax=plt.subplots(figsize=(9,4.3),layout='constrained')
        combinations=sorted(set((r['k_W_mK'],r['ambient_C']) for r in heat))
        for k,ambient in combinations:
            selected=sorted((r for r in heat if r['k_W_mK']==k and r['ambient_C']==ambient),key=lambda r:r['h_W_m2K'])
            ax.plot([r['h_W_m2K'] for r in selected],[r['Rmax_K_W'] for r in selected],'-o',label=f'k={k:g}, coolant={ambient:g} C')
        ax.set(xscale='log',xlabel='Assumed effective heat transfer coefficient [W/(m2 K)]',ylabel='FEMM hotspot thermal resistance [K/W]',title='Parametric thermal models / no cooling qualification')
        ax.grid(alpha=.2);ax.legend(fontsize=9);fig.savefig(images_dir/'thermal.png',dpi=160);plt.close(fig)
        thermal+='<img src="Images/thermal.png" alt="Parametric thermal analysis">'
    correction='Not calculated.'
    if correction_summary:
        correction=table(['Mode','Mean force N','Ripple pp %','Mean P20 W'],[
            [r['mode'],f'{r["F_mean_N"]:.3f}',f'{r["ripple_pp_percent"]:.3f}',f'{r["P20_mean_W"]:.3f}'] for r in correction_summary])
        with (run.folder/'current_correction_validation.csv').open(encoding='utf-8-sig') as stream:validation=list(csv.DictReader(stream,delimiter=';'))
        fig,ax=plt.subplots(figsize=(10,4.3),layout='constrained')
        for mode in ['uncorrected','corrected']:
            selected=[r for r in validation if r['mode']==mode]
            ax.plot([float(r['angle_deg']) for r in selected],[float(r['F_N']) for r in selected],'-o',ms=3,label=mode)
        ax.set(xlabel='Electrical angle [degrees]',ylabel='Newly solved FEMM force [N]',title='Current correction at independent positions')
        ax.grid(alpha=.2);ax.legend();fig.savefig(images_dir/'current_correction.png',dpi=160);plt.close(fig)
        correction+='<img src="Images/current_correction.png" alt="Independent validation of current correction">'
    links=['force_curves.csv','operating_points.csv','inductance.csv','checks.csv','counterfield.csv','current_correction_validation.csv','thermal_scenarios.csv','winding_plan.csv','results.json','input_parameters.ini','effective_parameters.json']
    text=f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FEMM Motor Simulation</title>
    <style>body{{font:16px system-ui;line-height:1.5;color:#19313d;max-width:1150px;margin:28px auto;padding:16px}}img{{max-width:100%}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:right}}.scroll{{overflow:auto}}.note{{background:#edf5f6;padding:16px}}a{{color:#08758a}}</style>
    <h1>FEMM Tubular Motor Simulation</h1><p>Version {VERSION} / {datetime.now():%Y-%m-%d %H:%M} / {run.solves} solved FEMM models</p>
    <p class="note">{g['count']} coils; packet {g['packet_mm']:.3f} mm; winding ID {g['inner_mm']:.3f} / OD {g['outer_mm']:.3f} mm; {g['layers']} layers x {g['columns']} turns = {g['turns']} turns per coil. Copper {g['copper_g']:.2f} g; moving mass {g['moving_kg']*1000:.2f} g. Model remanence {g['Br_T']:.4f} T at {c['magnets']['temperature_c']:g} C. Copper temperature for electrical losses {c['winding']['copper_temperature_c']:g} C.</p>
    <h2>Force and electrical results</h2>{operating}<img src="Images/force_and_current.png" alt="Force and winding current">
    <p>FEMM curves use physical winding currents. Driver line current accounts for parallel branches and star/delta connection. Delta is an ideal balanced fundamental-frequency conversion; internal circulating currents are not solved. Voltage uses a local dq approximation without real PWM or current-loop dynamics. Ideal available equivalent phase peak: {c['motion']['supply_v']/math.sqrt(3):.2f} V with suitable modulation.</p>
    <h2>FEMM field images</h2>{''.join(f'<img src="Images/{name}" alt="Newly computed FEMM field">' for name in images)}
    <h2>Inductance and numerical checks</h2><p>Differential inductance and independently solved checks are in the linked CSV files. Calibrated fundamental force constant: {calibration['Kf_N_A']:.6f} N/A winding peak. No-load and loaded fields are solved separately. Winding blocks are homogenized.</p>
    <h2>Optional current correction</h2>{correction}<p>The sixth-harmonic correction is fitted to the first loaded curve and tested at new intermediate positions. It is not presented as an independent validation of an exact inversion of the training curve. Real encoder and current-controller errors are not included.</p>
    <h2>Optional thermal scenarios</h2>{thermal}<p>Homogenized annular winding packet with insulated inner and end surfaces and effective external convection. Conductivity and heat transfer coefficients are assumptions, not verified cooling-system properties. Copper temperature feedback is computed algebraically from unit-power FEMM thermal resistances. Automatic duty cycle assumes continuous travel back and forth with the specified stroke, speed and acceleration, without pauses or friction.</p>
    <h2>Limitations and notes</h2><ul>{''.join('<li>'+html.escape(x)+'</li>' for x in run.warnings)}</ul>
    <p>The magnet recoil model does not solve irreversible demagnetization or use measured J-H curves for the actual magnets. Warm N35 operation and local opposing fields remain unverified. Spacer galvanizing is not modeled separately. Carbon fiber is statically mu_r=1; dynamic eddy-current losses are omitted. No 3D, eccentricity, cooling-hose, PWM or transient mechanical simulation; no continuous-load or temperature qualification.</p>
    <h2>Files</h2><p>{' / '.join(f'<a href="{x}">{x}</a>' for x in links if (run.folder/x).exists())}</p><p>Models and solutions: <a href="Models/">Models</a>. Images: <a href="Images/">Images</a>. CSV uses semicolons, decimal points and UTF-8 with BOM.</p></html>"""
    (run.folder/'report.html').write_text(text,encoding='utf-8')


def simulate(path,c,quick=False):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    if quick:
        c['simulation'].update(no_load_positions=12,positions_per_period=12,electrical_periods=1,mesh_check=False,stroke_check_positions_mm=[],validate_current_correction=False)
        c['thermal']['calculate']=False;c['operating_points']['forces_n']=c['operating_points']['forces_n'][:1]
    g=derive(c);root=Path(c['output']['directory']).expanduser()
    if not root.is_absolute():root=path.parent/root
    folder=root/('Run_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));folder.mkdir(parents=True)
    for name in ['Models','Images']:(folder/name).mkdir()
    shutil.copy2(path,folder/'input_parameters.ini')
    write_json(folder/'effective_parameters.json',dict(version=VERSION,parameters=c,geometry=g,quick_test=quick))
    write_csv(folder/'winding_plan.csv',plan(g))
    run=Run(c,g,folder);run.log(f'{g["count"]} coils, {g["turns"]} turns per coil, {g["copper_g"]:.2f} g copper. Output: {folder}')
    run.warnings=['Additional moving mass and thermal parameters are input assumptions, not verified construction data.',
                  'N35 characteristics and steel grade are not verified supplier data for the actual parts.']
    if quick:run.warnings.append('QUICK TEST: few positions; ripple is only a coarse functional check.')
    if g['wire_span_mm']+c['motion']['stroke_mm']>g['magnet_rod_mm']:run.warnings.append('Magnet rod is shorter than stroke plus winding packet; expect end-of-travel force loss.')
    rows=[];summary=[];induct=[];checks=[];heat=[];correction_summary=[];success=False
    model=folder/'Models'/'current.fem';final_model=folder/'Models'/'first_operating_point.fem'
    try:
        run.connect();basis=[];n0=c['simulation']['no_load_positions']
        for i in range(n0):
            x=g['start_mm']+g['period_mm']*i/n0;coils=run.rebuild(x,model)
            set_currents(run.f,[0,0,0]);run.solve(model);k={p:0. for p in 'ABC'}
            for item in coils:
                run.f.mo_selectblock(item['rmid_mm'],item['z_mm'])
                k[item['phase']]+=-item['sense']*g['turns']/item['area_m2']*real(run.f.mo_blockintegral(8));run.f.mo_clearblock()
            basis.append(k);run.show(x);run.log(f'No-load force calibration {i+1}/{n0}')
        co=2/n0*sum(k['A']*cmath.exp(-2j*math.pi*i/n0) for i,k in enumerate(basis));origin=cmath.phase(co)
        kf=sum(sum(k[p]*math.cos(2*math.pi*i/n0+origin+j*2*math.pi/3) for j,p in enumerate('ABC')) for i,k in enumerate(basis))/n0
        require(kf>0,'Calibrated force constant is not positive. Check geometry, materials and phases.')
        calibration=dict(Kf_N_A=kf,origin_rad=origin,positions=n0);write_json(folder/'calibration.json',calibration)
        raw_cases=[(f'{force:.3f} N',force/kf) for force in g['forces_N']]+[(f'{i:.3f} A winding',i) for i in c['operating_points']['winding_peak_currents_a']]
        cases=[(f'OP{i+1:02d}: '+name,amp) for i,(name,amp) in enumerate(raw_cases)]
        samples=c['simulation']['positions_per_period'];total=samples*c['simulation']['electrical_periods']
        alpha=c['winding']['copper_coefficient_per_k'];tempfactor=1+alpha*(c['winding']['copper_temperature_c']-20)
        for ci,(name,ipk) in enumerate(cases):
            local=[]
            for i in range(total):
                angle=2*math.pi*i/samples;x=g['start_mm']+g['period_mm']*i/samples
                run.rebuild(x,model);values=[ipk*math.cos(angle+origin+j*2*math.pi/3) for j in range(3)]
                set_currents(run.f,values);force,flux=run.solve(model);line=driver_currents(values,c)
                row=dict(case=name,index=i,angle_deg=360*i/samples,position_mm=x,I_winding_peak_A=ipk,
                         I_A_winding_A=values[0],I_B_winding_A=values[1],I_C_winding_A=values[2],
                         I_A_line_A=line[0],I_B_line_A=line[1],I_C_line_A=line[2],F_N=force,
                         Flux_A_Wb=flux[0],Flux_B_Wb=flux[1],Flux_C_Wb=flux[2],P20_W=1.5*g['R_series_phase20_Ohm']*ipk**2,
                         nodes=int(run.f.mo_numnodes()),elements=int(run.f.mo_numelements()))
                rows.append(row);local.append(row);write_csv(folder/'force_curves.csv',rows)
                stride=c['output']['field_image_every_n_positions'];export=i==0 or (stride>0 and i%stride==0)
                run.show(x,folder/'Images'/f'FEMM_view_{ci+1:02d}_{i:04d}.png' if export else None)
                if export:field_image(run,x,f'Field_{ci+1:02d}_{i:04d}')
                if i==0:
                    snapshot(model,folder/'Models'/f'Operating_point_{ci+1:02d}_start')
                    if ci==0:snapshot(model,final_model.with_suffix(''))
                if c['output']['keep_all_models']:snapshot(model,folder/'Models'/f'Point_{ci+1:02d}_{i:04d}')
                run.log(f'Operating point {ci+1}/{len(cases)}, Position {i+1}/{total}: F={force:.3f} N')
            forces=np.array([r['F_N'] for r in local]);p20=local[0]['P20_W'];branch=c['winding']['parallel_branches_per_phase'];delta=c['winding']['connection'].lower()=='delta'
            line_factor=branch*(math.sqrt(3) if delta else 1);v=(g['R_series_phase20_Ohm']*tempfactor*ipk+kf/1.5*c['motion']['speed_m_s'])/line_factor
            summary.append(dict(case=name,I_winding_peak_A=ipk,I_line_peak_A=ipk*line_factor,I_line_RMS_A=ipk*line_factor/math.sqrt(2),
                                F_mean_N=float(forces.mean()),F_min_N=float(forces.min()),F_max_N=float(forces.max()),
                                ripple_pp_percent=float(np.ptp(forces)/forces.mean()*100),P20_W=p20,P_Cu_W=p20*tempfactor,
                                Km_N_sqrtW=float(forces.mean())/math.sqrt(p20*tempfactor),V_phase_equiv_peak_V=v,
                                a_mm_s2=float(forces.mean())/g['moving_kg']*1000))
        first=summary[0];ipk=cases[0][1];baseangle=origin
        if c['simulation']['calculate_inductance']:
            run.rebuild(g['start_mm'],model);delta_i=c['simulation']['inductance_step_a']
            base=[ipk*math.cos(baseangle+j*2*math.pi/3) for j in range(3)]
            for axis in ['q','d']:
                direction=[math.cos(baseangle+j*2*math.pi/3+(0 if axis=='q' else math.pi/2)) for j in range(3)];proj=[]
                for sign in [-1,1]:
                    set_currents(run.f,[a+sign*delta_i*v for a,v in zip(base,direction)]);_,flux=run.solve(model)
                    proj.append(sum(v*p for v,p in zip(direction,flux))/1.5)
                induct.append(dict(axis=axis,L_series_H=(proj[1]-proj[0])/(2*delta_i)))
            write_csv(folder/'inductance.csv',induct)
            lq=next(x['L_series_H'] for x in induct if x['axis']=='q')
            for point in summary:
                factor=c['winding']['parallel_branches_per_phase']*(math.sqrt(3) if c['winding']['connection'].lower()=='delta' else 1)
                vd=2*math.pi*c['motion']['speed_m_s']/(g['period_mm']*.001)*lq*point['I_winding_peak_A']/factor
                point['V_phase_equiv_peak_V']=math.hypot(point['V_phase_equiv_peak_V'],vd)
        if c['simulation']['mesh_check']:
            for i in [0,samples//6,samples//3]:
                angle=2*math.pi*i/samples;x=g['start_mm']+g['period_mm']*i/samples
                run.rebuild(x,model,c['simulation']['check_mesh_mm']);set_currents(run.f,[ipk*math.cos(angle+origin+j*2*math.pi/3) for j in range(3)]);force,_=run.solve(model)
                old=next(r['F_N'] for r in rows if r['case']==cases[0][0] and r['index']==i)
                checks.append(dict(kind='Fine mesh',position_mm=x,F_N=force,change_percent=100*(force/old-1)))
                run.show(x);run.log(f'Fine-mesh check at {x:.3f} mm: {100*(force/old-1):+.3f}%')
        for x in c['simulation']['stroke_check_positions_mm']:
            angle=2*math.pi*(x-g['start_mm'])/g['period_mm'];run.rebuild(x,model)
            set_currents(run.f,[ipk*math.cos(angle+origin+j*2*math.pi/3) for j in range(3)]);force,_=run.solve(model)
            checks.append(dict(kind='Stroke point',position_mm=x,F_N=force,change_percent=None));run.show(x);run.log(f'Stroke sample {x:g} mm: {force:.3f} N')
        write_csv(folder/'checks.csv',checks)
        if c['simulation']['counterfield_check']:
            run.rebuild(g['start_mm'],model);set_currents(run.f,[ipk*math.cos(origin+j*2*math.pi/3) for j in range(3)]);run.solve(model)
            samples_h=[];m=c['magnets'];ref=m['hcj_20c_a_m']*(1+m['hcj_coefficient_per_k']*(m['temperature_c']-20))
            for j in range(m['count']):
                z0=-g['magnet_rod_mm']/2+j*(m['length_mm']+c['spacers']['thickness_mm']);sense=1 if j%2==0 else -1
                for radius in [.1*m['diameter_mm']/2,.5*m['diameter_mm']/2,.96*m['diameter_mm']/2]:
                    for fraction in [.01,.5,.99]:
                        z=z0+fraction*m['length_mm'];h=sense*real(run.f.mo_geth(radius,z)[1])
                        samples_h.append(dict(magnet=j+1,r_mm=radius,z_mm=z,H_parallel_A_m=h,reference_Hcj_A_m=ref,beyond_generic_reference=h < -ref))
            write_csv(folder/'counterfield.csv',samples_h)
            if any(x['beyond_generic_reference'] for x in samples_h):run.warnings.append('Counterfield samples exceed a generic Hcj reference. Irreversible demagnetization is not solved; this remains an unresolved material limit.')
        if c['simulation']['validate_current_correction']:
            training=[r for r in rows if r['case']==cases[0][0] and r['index']<samples]
            angles=np.array([r['angle_deg'] for r in training])*math.pi/180;force=np.array([r['F_N'] for r in training]);mean=float(force.mean())
            c6=2/samples*np.sum(force*np.exp(-6j*angles));factors=mean/(mean+np.real(c6*np.exp(6j*angles)));norm=mean/float(np.mean(force*factors))
            validate=[];nv=c['simulation']['correction_positions']
            for i in range(nv):
                # Shift away from the training grid: no reused training positions.
                angle=2*math.pi*i/nv+2*math.pi/samples*.37;x=g['start_mm']+g['period_mm']*angle/(2*math.pi)
                run.rebuild(x,model);factor=norm*mean/(mean+float(np.real(c6*np.exp(6j*angle))))
                for mode,fact in [('uncorrected',1.),('corrected',factor)]:
                    amp=ipk*fact;set_currents(run.f,[amp*math.cos(angle+origin+j*2*math.pi/3) for j in range(3)]);value,_=run.solve(model)
                    validate.append(dict(mode=mode,angle_deg=angle*180/math.pi,position_mm=x,factor=fact,F_N=value,P20_W=1.5*g['R_series_phase20_Ohm']*amp**2))
                run.show(x);write_csv(folder/'current_correction_validation.csv',validate);run.log(f'Current correction, new position {i+1}/{nv}')
            for mode in ['uncorrected','corrected']:
                chosen=[r for r in validate if r['mode']==mode];values=np.array([r['F_N'] for r in chosen])
                correction_summary.append(dict(mode=mode,F_mean_N=float(values.mean()),ripple_pp_percent=float(np.ptp(values)/values.mean()*100),P20_mean_W=float(np.mean([r['P20_W'] for r in chosen]))))
        if c['thermal']['calculate']:heat=thermal_models(run,first['P20_W'])
        for point in summary:
            if point['I_line_peak_A']>c['motion']['planning_peak_current_limit_a']:run.warnings.append(point['case']+': planning current limit exceeded.')
            if point['V_phase_equiv_peak_V']>c['motion']['supply_v']/math.sqrt(3):run.warnings.append(point['case']+': steady-state voltage requirement exceeds the ideal available voltage.')
        write_csv(folder/'operating_points.csv',summary)
        write_json(folder/'results.json',dict(version=VERSION,complete=True,geometry=g,calibration=calibration,operating_points=summary,
                   inductance=induct,checks=checks,thermal=heat,correction=correction_summary,solves=run.solves,warnings=run.warnings))
        report(run,rows,summary,induct,checks,heat,calibration,correction_summary)
        # Return the visible FEMM window to a magnetic field rather than the optional heat model.
        run.close_output()
        if run.input_open:run.f.mi_close();run.input_open=False
        run.f.opendocument(str(final_model));run.input_open=True;run.f.mi_loadsolution();run.output_open=True
        run.show(g['start_mm'],folder/'Images'/'FEMM_final_view.png')
        success=True;run.log(f'Finished: {run.solves} FEMM solutions. Report: {folder/"report.html"}')
        if c['output']['open_report']:
            try:webbrowser.open((folder/'report.html').as_uri())
            except Exception as exc:run.log('Please open the report manually: '+str(exc))
        return dict(folder=str(folder),summary=summary,geometry=g)
    except BaseException as exc:
        write_json(folder/'status.json',dict(complete=False,error=str(exc),solves=run.solves))
        (folder/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        if run.f is not None:
            if success and c['display']['visible'] and c['display']['keep_open']:
                # Keep the launcher alive too: some Windows launch environments
                # terminate child applications when their parent process exits.
                run.log('Calculation complete. FEMM remains open. Close its window or press Ctrl+C here to exit.')
                try:
                    process=getattr(run.f,'_proc',None)
                    if process is not None:process.wait()
                    else:input('Press Enter to close FEMM and exit. ')
                except (KeyboardInterrupt,EOFError):pass
            run.f.close()

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version=f'%(prog)s {VERSION} (GPL-3.0-only)')
    parser.add_argument('parameter',nargs='*',type=Path,help='One or more INI files; default: motor_parameters.ini next to this script.')
    view=parser.add_mutually_exclusive_group();view.add_argument('--visible',action='store_true');view.add_argument('--headless',action='store_true')
    parser.add_argument('--quick-test',action='store_true',help='Short functional test; not an accurate ripple analysis.')
    parser.add_argument('--check',action='store_true',help='Validate parameters and geometry without starting FEMM.')
    args=parser.parse_args(argv);paths=args.parameter or [default_parameters()];out=[]
    for source in paths:
        path=source.expanduser().resolve();cfg=read_parameters(path)
        if args.visible:cfg['display']['visible']=True
        if args.headless:cfg['display']['visible']=False
        geometry=derive(cfg)
        if args.check:print(json.dumps(dict(parameter=str(path),geometry=geometry),ensure_ascii=False,indent=2));continue
        # Keep just the final GUI open when running several parameter files in sequence.
        if len(paths)>1 and source!=paths[-1]:cfg['display']['keep_open']=False
        out.append(simulate(path,cfg,args.quick_test))
    if len(out)>1:
        target=Path(out[-1]['folder']).parent/('Comparison_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        write_json(target,out);print('Comparison summary:',target)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('\nCancelled. Previously written data remain in the results folder.');raise SystemExit(130)
    except (ValueError,RuntimeError,ImportError) as exc:
        print('\nERROR:',exc,file=sys.stderr);raise SystemExit(1)
