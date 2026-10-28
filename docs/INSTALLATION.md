# Installation on Windows

Requirements: Python 3.10 or newer, numpy, matplotlib and **FEMM 5 / FEMM-Qt with
`FemmSession`**. Python 3.14 on 64-bit Windows is the locally tested setup.
FEMM 4.2's classic COM binding is not compatible with this script.

## 1. Install Python and FEMM

Download a stable 64-bit Python 3.14 installer from
[python.org](https://www.python.org/downloads/windows/). Enable the PATH option if
offered. Use a normal installation, not the embeddable package.

Download the Windows installer from the official
[FEMM 5 download page](https://femm.info/doku/doku.php?id=download5&redirect=1).
This guide assumes installation in `C:\femm-qt`. Keep the complete installation,
including DLLs and material libraries. Check that these files exist:

```text
C:\femm-qt\bin\femm_gui.exe
C:\femm-qt\bin\femm_headlessw.exe
C:\femm-qt\bin\matlib.dat
C:\femm-qt\bin\heatlib.dat
C:\femm-qt\pyfemm\femm.py
```

Open `femm_gui.exe` once to check it starts, then close it.

## 2. Download and open this project

Download the repository ZIP and extract it completely, or clone it with Git.
Open PowerShell **in the folder containing `motor_simulator.py`**. Run all commands
below from that folder.

## 3. Create an environment and install packages

Run each command separately and resolve any errors before continuing:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install "C:\femm-qt\pyfemm"
```

If `py` is unavailable but `python --version` shows the intended Python version,
use `python` instead of `py -3.14` in the first command. A separate activation step
is unnecessary because the commands call the environment's interpreter directly.

Install the binding supplied with FEMM 5, as described in the official
[binding setup guide](https://www.femm.info/doku/doku.php?id=bindingsetup).
An arbitrary `pip install femm` or `pip install pyfemm` is not an equivalent setup.

## 4. Create and check your configuration

```powershell
.\.venv\Scripts\python.exe motor_simulator.py --check
```

On first start this copies `motor_parameters.example.ini` to
`motor_parameters.ini`. Existing local settings are never overwritten. Edit the
local file and check the installation path:

```ini
[femm]
program_directory = C:\femm-qt\bin
```

For a different FEMM installation, adjust this path and the binding installation
command above. Do not add quotes around the path in the INI file. Keep the other
settings and sections.

Verify the packages and binding:

```powershell
.\.venv\Scripts\python.exe -c "import numpy, matplotlib; print('Packages OK')"
.\.venv\Scripts\python.exe -c "import femm; print(femm.__file__); print('FemmSession:', hasattr(femm, 'FemmSession'))"
```

Expect `Packages OK` and `FemmSession: True`. The unchanged example produces twelve
coils with 72 turns each and a winding outer diameter of 19.816 mm.

## 5. Run the first simulation

Double-click `run_quick_test.bat`, or run:

```powershell
.\.venv\Scripts\python.exe motor_simulator.py --visible --quick-test
```

FEMM displays the field solutions. The quick test is a functional check with fewer
positions and disabled optional checks; use `start_simulation.bat` for a complete
run. Open `Results/Run_.../report.html` if it does not open automatically.

With `keep_open = yes`, Python waits after completion so you can examine the FEMM
view. Close the FEMM window or press Ctrl+C in the terminal to finish.

## Troubleshooting

| Problem | Check |
|---|---|
| Python command not found | Install Python and open a new terminal. |
| Missing numpy or matplotlib | Install requirements with the same `.venv` interpreter used to run the script. |
| `FemmSession: False` | A different FEMM binding is being imported. Use a separate environment and install `C:\femm-qt\pyfemm` into it. |
| FEMM executable not found | Check `program_directory` and the EXE files listed above. |
| DLL or material-library error | Use the complete FEMM installation. Check the exact spacer material name. |
| Window remains after completion | This is expected with `keep_open = yes`. |
| Environment fails after moving computers | Recreate `.venv` on the target computer instead of copying it. |

Solver failures write `error.txt` and `log.txt` in the results folder. Keep the
input parameters with a failure report, and remove personal paths before sharing.
See [User guide](USAGE.md) for configuration and model limitations.
