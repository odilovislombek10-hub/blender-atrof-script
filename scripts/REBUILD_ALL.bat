@echo off
rem Full rebuild: 1 km zone (in parallel) + every city tile (forced) -> link tiles into Bishkek_35km.blend -> city report
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
echo START %DATE% %TIME% > logs\REBUILD_ALL_STATUS.txt
start "" /b cmd /c scripts\REBUILD_ZONE.bat
set BISHKEK_CITY_FORCE=1
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\14_run_city.py 14 > logs\14_run_city.log 2>&1
set BISHKEK_CITY_FORCE=
echo OK city %TIME% >> logs\REBUILD_ALL_STATUS.txt
:waitzone
findstr /c:"ALLDONE" logs\REBUILD_STATUS.txt >nul || (timeout /t 20 /nobreak >nul & goto waitzone)
echo OK zone %TIME% >> logs\REBUILD_ALL_STATUS.txt
call scripts\INTEGRATE_CITY.bat
echo ALLDONE %TIME% >> logs\REBUILD_ALL_STATUS.txt
