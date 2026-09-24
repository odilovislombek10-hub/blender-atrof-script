@echo off
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\05d_get_sentinel2_city.py > logs\05d_run.out 2>&1
