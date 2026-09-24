@echo off
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\05e_split_osm_city.py > logs\05e_run.out 2>&1
