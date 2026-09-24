@echo off
rem Rebuild the 1 km detail zone inside the single working file Bishkek_35km.blend, then geometric QA
cd /d D:\Bishkek_35km
set BISHKEK_ROOT=D:\Bishkek_35km
echo START %DATE% %TIME% > logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\06_zone_partition.py > logs\06_zone_partition.log 2>&1
if errorlevel 1 (echo FAILED 06 >> logs\REBUILD_STATUS.txt & exit /b 1)
echo OK 06 %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python scripts\07_zone_blender.py > logs\07_zone_blender.log 2>&1
if errorlevel 1 (echo FAILED 07 >> logs\REBUILD_STATUS.txt & exit /b 1)
echo OK 07+08 %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python scripts\10_apply_terrain_textures.py > logs\10_apply_textures.log 2>&1
if errorlevel 1 (echo FAILED 10 >> logs\REBUILD_STATUS.txt & exit /b 1)
echo OK 10 %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b Bishkek_35km.blend --factory-startup --python-exit-code 1 --python scripts\12_qa_geometry.py > logs\12_qa_geometry.log 2>&1
if errorlevel 1 (echo FAILED 12 >> logs\REBUILD_STATUS.txt & exit /b 1)
echo OK 12 %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\12b_qa_rules.py > logs\12b_qa_rules.log 2>&1
if errorlevel 1 (echo FAILED 12b >> logs\REBUILD_STATUS.txt)
echo OK 12b %TIME% >> logs\REBUILD_STATUS.txt
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -u scripts\13_qa_report.py > logs\13_qa_report.log 2>&1
if errorlevel 1 (echo QA GATES FAILED - see logs\13_qa_report.log >> logs\REBUILD_STATUS.txt) else (echo QA GATES PASS >> logs\REBUILD_STATUS.txt)
echo ALLDONE >> logs\REBUILD_STATUS.txt
