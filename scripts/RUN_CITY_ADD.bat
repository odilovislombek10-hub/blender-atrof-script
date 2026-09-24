@echo off
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\05e_split_osm_city.py > logs\05e_run.out 2>&1
set BISHKEK_CITY_ONLY=0,-3;-5,-2;-3,-5;0,-6;1,-6;2,-5;3,-5;6,-1
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\14_run_city.py 8 > logs\14_run_city_add.log 2>&1
