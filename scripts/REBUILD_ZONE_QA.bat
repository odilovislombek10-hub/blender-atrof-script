@echo off
rem Zone QA only (12 -> 12b -> 13) on the saved working file; appends to logs\REBUILD_STATUS.txt and ends with ALLDONE
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b Bishkek_35km.blend --factory-startup --python-exit-code 1 --python scripts\12_qa_geometry.py > logs\12_qa_geometry.log 2>&1
if errorlevel 1 (echo FAILED 12 >> logs\REBUILD_STATUS.txt & echo ALLDONE >> logs\REBUILD_STATUS.txt & exit /b 1)
echo OK 12 %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\12b_qa_rules.py > logs\12b_qa_rules.log 2>&1
echo OK 12b %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\13_qa_report.py > logs\13_qa_report.log 2>&1
if errorlevel 1 (echo QA GATES FAILED - see logs\13_qa_report.log >> logs\REBUILD_STATUS.txt) else (echo QA GATES PASS >> logs\REBUILD_STATUS.txt)
echo ALLDONE >> logs\REBUILD_STATUS.txt
