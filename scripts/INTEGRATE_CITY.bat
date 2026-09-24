@echo off
rem Link finished city tiles into Bishkek_35km.blend, cut terrain under them, remove v1 LOD1 buildings there, then city QA report
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
echo START %TIME% > logs\INTEGRATE_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b Bishkek_35km.blend --factory-startup --python-exit-code 1 --python scripts\15_integrate_city.py > logs\15_integrate_city.log 2>&1
if errorlevel 1 (echo FAILED 15 >> logs\INTEGRATE_STATUS.txt & exit /b 1)
echo OK 15 %TIME% >> logs\INTEGRATE_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\16_city_report.py > logs\16_city_report.log 2>&1
echo OK 16 %TIME% >> logs\INTEGRATE_STATUS.txt
echo ALLDONE >> logs\INTEGRATE_STATUS.txt
