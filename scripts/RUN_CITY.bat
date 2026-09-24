@echo off
rem Whole-city run: every 1 km tile through 06-07-08-12-12b-13, 14 in parallel. Progress: logs\CITY_STATUS.txt
rem tiles already DONE are skipped; tiles whose QA failed are rebuilt (BISHKEK_CITY_RERUN=qa_fail)
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
set BISHKEK_CITY_RERUN=qa_fail
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\14_run_city.py 14 > logs\14_run_city.log 2>&1
