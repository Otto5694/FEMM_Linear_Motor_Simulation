# User guide

## Configuration and commands

The default input is `motor_parameters.ini` next to the script. On first start
without a configuration argument it is created from `motor_parameters.example.ini`.
The local file is ignored by Git. Edit it in a normal text editor and preserve
the `.ini` extension. Unknown sections or parameters are rejected.

Numbers accept a decimal point or comma. Lists use **semicolons**, such as
`auto; 30; 40`. Boolean values accept `yes/no`, `true/false`, `on/off` or `1/0`.
Comments begin with `#`. These English parameter names replace the earlier German
configuration format; use the supplied example for this version.

Run from the script folder using your installed environment:

```powershell
# Create the local INI if needed and validate geometry; no FEMM calculation
.\.venv\Scripts\python.exe motor_simulator.py --check

# Short visible functional test
.\.venv\Scripts\python.exe motor_simulator.py --visible --quick-test

# Complete visible calculation
.\.venv\Scripts\python.exe motor_simulator.py --visible

# Complete calculation without the FEMM window
.\.venv\Scripts\python.exe motor_simulator.py --headless

# Two complete configurations, solved sequentially
.\.venv\Scripts\python.exe motor_simulator.py examples\six_coils.ini examples\nine_coils.ini --headless
```

For multiple inputs, a `Comparison_*.json` file beside the last run references
each result. It is an index with numerical summaries, not an automatic ranking
of the best motor. Relative output directories are relative to each input INI.
The Windows launchers always use the default local INI and request visible mode.

## Main settings

The commented example contains all available settings and their units.

| Section | Purpose |
|---|---|
| `[display]` | GUI visibility, viewing pause, mesh/flux lines and viewing area. |
| `[femm]` | Installation directory, mesh sizes, solver tolerance and outer boundary. |
| `[magnets]` | Count, dimensions, recoil permeability, remanence and temperature assumptions. |
| `[spacers]` | Dimensions and exact FEMM library material name. |
| `[tube]` | Tube outside diameter, checked against winding clearance. |
| `[winding]` | Coil layout, wire, packing, resistance, connection and copper temperature. |
| `[motion]` | Payload, extra moving hardware, acceleration, speed, stroke and supply. |
| `[operating_points]` | Target forces or physical winding peak currents. |
| `[simulation]` | Sampling, inductance, mesh/stroke checks and current correction. |
| `[thermal]` | Parametric conductivity, convection, coolant temperature and duty cycle. |
| `[output]` | Output directory, field-image frequency, saved models and report opening. |

### Magnet rod and coil layout

Magnets alternate their axial magnetization so like poles face each other at
successive spacers. One electrical period is twice the sum of magnet length and
spacer thickness: the example gives `2 * (19.5 + 1.5) = 42 mm`.

`coils_per_pole_pair` supports 3, 6 or 12. `pole_pairs` specifies the packet length
in electrical periods. Their product must be an integer divisible by three.
For six coils per pole pair:

| Pole pairs | Coils | Packet length with the example magnets |
|---:|---:|---:|
| 1 | 6 | 42 mm |
| 1.5 | 9 | 63 mm |
| 2 | 12 | 84 mm |

Magnet count determines rod length. The supplied count of 26 is an assumption
with end reserve, not a requirement or a statement about available hardware.
A finite rod can lose force near its ends; a few stroke samples do not validate
the full travel range.

### Wire and packing

`layers` and `turns_per_layer` can be fixed positive integers. Set
`turns_per_layer = 0` to fit turns automatically within coil pitch and axial
allowance. Set `layers = 0` and a positive `max_outer_diameter_mm` for automatic
radial packing. Square packing is assumed; radial/axial allowances are extra
geometric budgets, not a detailed winding or adhesive model.

When changing wire, update **all three** of `wire_copper_mm`, `wire_coated_mm` and
`wire_resistance_20c_ohm_per_m`. Copper diameter alone is insufficient. A thicker
wire generally needs fewer turns and more current; compare force and copper
losses at the same task rather than the same current.

`parallel_branches_per_phase` must divide the coil count per phase exactly.
`connection` accepts `star` or `delta`. FEMM always uses physical winding current;
line currents and equivalent voltage are converted for ideal balanced connections.
Internal delta or parallel circulating currents are not solved.

### Motion and operating points

`payload_g` and `additional_moving_mass_g` exclude winding copper. Calculated
copper mass is added automatically. `forces_n = auto; 40` first requests the
force needed for the entered total mass and acceleration, then a separate 40 N
point. Optional `winding_peak_currents_a` entries specify physical winding current
amplitudes, not RMS values or supply current.

The script calibrates the force constant from no-load FEMM fields, then solves
loaded fields at the corresponding currents. Nonlinearity means the resulting
mean force can differ slightly from the target. The planning current limit
produces a warning; it is not a protection circuit or a driver validation.

### Watching FEMM

```ini
[display]
visible = yes
pause_s = 0.3
keep_open = yes
show_mesh = no
show_flux_lines = yes
view_length_mm = 42
```

Edit existing values rather than adding duplicate sections. `pause_s` holds each
finished magnetic view for inspection. FEMM displays the axisymmetric motor
vertically; `view_length_mm = 0` shows the complete coil packet. Exported field
plots show it horizontally. The viewing area does not change the physical model.
Headless mode closes FEMM automatically at the end.

## Outputs

Each run creates `Results/Run_TIMESTAMP/` by default. Runs are never overwritten.
Start with `report.html`; the directory also contains:

| File or folder | Contents |
|---|---|
| `force_curves.csv` | Position, electrical angle, currents, force and flux linkage. |
| `operating_points.csv` | Mean force, peak-to-peak ripple, currents, losses and voltage estimate. |
| `results.json` | Overall results and model warnings. |
| `input_parameters.ini` | Exact input file. |
| `effective_parameters.json` | Effective settings, including quick-test overrides. |
| `winding_plan.csv` | Coil position, phase and connection sign. |
| `Images/` | English plots, sampled FEMM fields and optional native GUI screenshots. |
| `Models/` | Magnetic `.fem/.ans` and optional thermal `.feh/.anh` files. |
| `log.txt`, `progress.json` | Progress; `error.txt` and `status.json` on failures. |

Optional calculations add `inductance.csv`, `checks.csv`, `counterfield.csv`,
`current_correction_validation.csv` and `thermal_scenarios.csv`.
CSV uses semicolons, decimal points and UTF-8 with BOM. A field image also has a
sampled-field CSV and compressed NPZ file; samples come from the actual solved
FEMM field. `field_image_every_n_positions = 0` saves only the first field of each
operating point. A positive interval saves additional images. Keeping every model
can consume considerable disk space.

## Optional checks and interpretation

- **Mesh:** `mesh_check` recomputes three positions with `check_mesh_mm`. Inspect
  convergence after geometry changes. This is not a global error bound.
- **Current correction:** fits the sixth electrical harmonic of the first loaded
  curve and tests new intermediate positions. Use at least 24 samples per period;
  72 is the normal example. Encoder and current-controller errors are omitted.
- **Counterfield:** compares selected opposing-field samples with a generic,
  temperature-adjusted Hcj reference. It does not solve irreversible
  demagnetization or calculate a damaged volume fraction.
- **Thermal:** solves a homogenized annular packet with insulated inner/end
  surfaces and effective outer convection. Assumed `k` and `h` values are not
  measured properties of your winding or cooling system. Copper temperature
  feedback is calculated from unit-power thermal resistance. `duty_cycle = auto`
  assumes continuous travel back and forth with no dwell or friction. Very high
  predicted temperatures indicate overload beyond useful model assumptions.

The model omits 3D eccentricity, real PWM, current-loop dynamics, mechanical
transients and dynamic eddy-current losses. Verify actual magnet/steel data and
cooling performance experimentally before treating predictions as operating limits.
