@echo off
REM ============================================================
REM  run_bridge.bat  -  launch the openEMS bridge on THIS Windows PC
REM
REM  This is the machine-specific launcher. The .py / .m / .html
REM  source stays OS-portable (env-var-with-macOS-default); all the
REM  Windows-specific paths live HERE, not in the code.
REM
REM  Just double-click this file (or run it from a terminal) to start
REM  the server, then open  http://localhost:8731  in a browser.
REM  To share with one remote tester, see share_funnel.bat / WINDOWS_SETUP.md.
REM ============================================================
setlocal

REM --- tool locations on this machine (edit if you move/upgrade a tool) ---
set "OPENEMS_INSTALL_PATH=C:\opt\openEMS"
set "OPENEMS_OCTAVE=C:\Program Files\GNU Octave\Octave-11.3.0\mingw64\bin\octave-cli.exe"
set "OPENEMS_MATLAB_PATH=C:\opt\openEMS\matlab"
set "CSXCAD_MATLAB_PATH=C:\opt\openEMS\matlab"
set "OPENEMS_SCRATCH=C:\openems_scratch"

REM --- Mesa software OpenGL (llvmpipe): lets the pyvista field/lobe renderers work
REM     in a headless / RDP-disconnected session, where the system GPU OpenGL has no
REM     usable pixel format and VTK off-screen rendering would otherwise CRASH. The
REM     renderers preload %OPENEMS_MESA_GL%\opengl32.dll before importing vtk. ---
set "OPENEMS_MESA_GL=C:\opt\mesa"
set "GALLIUM_DRIVER=llvmpipe"

REM --- the Python that has flask + pyvista (the openems_py314 venv) ---
set "BRIDGE_PYTHON=C:\Users\Huzaifa\openems_py314\Scripts\python.exe"

REM --- make openEMS.exe and its DLLs discoverable to Octave's shell-outs ---
set "PATH=%OPENEMS_INSTALL_PATH%;%PATH%"

if not exist "%OPENEMS_SCRATCH%" mkdir "%OPENEMS_SCRATCH%"

echo(
echo Starting openEMS bridge with:
echo   octave  = %OPENEMS_OCTAVE%
echo   python  = %BRIDGE_PYTHON%
echo   scratch = %OPENEMS_SCRATCH%
echo   openEMS = %OPENEMS_INSTALL_PATH%
echo(

"%BRIDGE_PYTHON%" "%~dp0openEMS\openems_server.py"

endlocal
