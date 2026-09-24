@echo off
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
set BISHKEK_CITY_ONLY=-3,-5;0,-6;6,-1
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\14_run_city.py 3 > logs\14_run_city_add2.log 2>&1
set BISHKEK_CITY_ONLY=
call scripts\INTEGRATE_CITY.bat
