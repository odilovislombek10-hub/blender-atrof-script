# Bishkek 35 km context model - task list (kept by Claude)

Working file: D:\Bishkek_35km\Bishkek_35km.blend (single file, updated in place)
One-click rebuild: scripts\REBUILD_ZONE.bat
  06 partition -> 07 Blender assembly (+ 08 automatic ground repair) -> 10 terrain textures -> 12 geometric QA
  progress: logs\REBUILD_STATUS.txt (ends with ALLDONE), per-stage logs in logs\, QA report data\qa_geometry.json

## Rules from SHEF (hold for every delivery)
- [x] Parking only where seen on close satellite imagery (manual_edits.json); never invented
- [x] Playgrounds kept only where they clash with nothing; the 20 clashing ones were checked on imagery -> all 20 were not playgrounds (data\playground_decisions.json)
- [x] No overlapping / z-fighting surfaces (QA: overlap pairs = 0)
- [x] One working .blend file (old versions in _old_versions, delete manually)
- [x] Every surface category its own object (GROUND_*), every building its own object
- [x] Errors are found from the geometry itself (12_qa_geometry.py), not from screenshots
- [x] Automated, ordered pipeline (REBUILD_ZONE.bat), agents used for parallel work

## Done today (24 Sep 2026)
- [x] Geometric QA script: seams/open edges, wall ends, overlaps, slivers, logic (paths, entrances, crosswalks, parking access), trees, building bases, terrain seam
- [x] Fixes: tapered walls no longer deleted by Blender; near-duplicate vertices merged; triangulation fallback; sliver merge; trees only on soft ground (827 -> 0 on hard); building bases sunk (135 -> 5 floating); terrain seam blended 60 m; automatic hole repair stage
- [x] Imagery check (agent): 2 parking rows added, 2 wrong OSM parking polygons removed (garages / tree yard)
- [x] Web reference (agent): street_reference.md (2024-26 reconstructions, aryks, lighting, no kerb parking seen)

## Next
- [ ] Street profiles from street_reference.md: Toktonalieva asphalt sidewalks (2024), Akhunbaev rebuilt 2024 (kerbs+aryks), Aitmatov: no open aryks, 6 lanes + bike lanes south of Akhunbaev, bus lanes
- [ ] Zone edge ribbon (vertical strip where terrain and zone heights differ, e.g. river/canal crossing)
- [ ] Remaining QA items: entrances not reaching a building (30), crosswalks without sidewalk (3), playgrounds without path (31)
- [ ] Street widths: Akhunbaev, Aitmatov, Aini, Zhamanbaeva
- [ ] 300 m tile imagery pass for the rest of the 1 km zone, then extend to 35 km (automated per tile)
