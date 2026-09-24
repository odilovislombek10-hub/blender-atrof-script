# Bishkek 35 km — Blender atrof (kontekst) modeli skriptlari

Lanessa Studio uchun: Bishkek, Toktonalieva 77 (42.845424, 74.591755) atrofidagi shahar modeli. Blender'da quriladi, Unreal'ga eksport qilinadi.
Ishchi papka: `D:\Bishkek_35km`. Asosiy fayl: `Bishkek_35km.blend`. Shahar plitkalari: `city\tile_I_J.blend`.

## Tartib (skriptlar raqam bo'yicha ishlaydi)

| bosqich | skript | nima qiladi |
|---|---|---|
| 01–04 | `01_extract_osm.py` … `04_previews.py` | OSM ma'lumotlari, DEM, 35 km v1 LOD1 model, statistika |
| 05–05e | `05*_get_sentinel2*.py`, `05e_split_osm_city.py` | Sentinel-2 (iyul, mart, sentyabr, yanvar qor), OSM ni 1 km plitkalarga bo'lish |
| 06 | `06_zone_partition.py` | yer sirtining ustma-ust tushmaydigan bo'linishi (asfalt, bordyur, trotuar, ariq, gazon, hovli, parkovka…), devorlar, daraxtlar |
| 07 / 07b | `07_zone_blender.py`, `07b_zone_materials.py` | Blender'da yig'ish: har bir sirt turi alohida obyekt, har bir bino alohida obyekt, PBR materiallar |
| 08 | `08_repair_ground.py` | yerdagi teshiklarni avtomatik yopish |
| 09–10 | terrain teksturalari | 35 km relyefga Sentinel teksturasi |
| 12 / 12b / 13 | `12_qa_geometry.py`, `12b_qa_rules.py`, `13_qa_report.py` | geometriya QA (teshik, ustma-ust sirt, bino yo'lda, daraxt asfaltda…) + SHEF qoidalari + QA darvozalari |
| 14 | `14_run_city.py` | butun shahar: har bir 1 km plitka 06 → 07 → 12 → 12b → 13 dan o'tadi, 14 ta parallel jarayon |
| 15 | `15_integrate_city.py` | plitkalarni asosiy faylga ulash, ostidagi terrain va eski LOD1 binolarni olib tashlash, eski qatlamlarni tozalash |
| 16 | `16_city_report.py` | shahar bo'yicha QA hisoboti, plitkalar chegarasini tekshirish, hovlilar yashilligini Sentinel bilan solishtirish |
| — | `unthrottle.py` | Windows EcoQoS (orqa fon jarayonlarini sekinlashtirish) ni o'chiradi, taxminan 3 marta tez |

Bir tugma bilan ishga tushirish:
- `REBUILD_ZONE.bat` — 1 km zona;
- `RUN_CITY.bat` — shahar plitkalari;
- `INTEGRATE_CITY.bat` — ulash va hisobot.

`14_run_city.py` qo'shimcha sozlamalari:
- `BISHKEK_TILE=I,J` — bitta plitka;
- `BISHKEK_CITY_ONLY="3,2;4,2"` — faqat shu plitkalar;
- `BISHKEK_CITY_RERUN=qa_fail` — QA dan o'tmagan plitkalarni qayta qurish.

## Mijoz (SHEF) qoidalari
- Ustma-ust sirt yo'q. Har bir sirt turi alohida obyekt, har bir bino alohida obyekt. Bitta asosiy .blend.
- Parkovka faqat sputnikda ko'ringan joyda bo'ladi. O'yin maydonchasi faqat hech narsa bilan to'qnashmasa qoladi, aks holda sputnikda tekshiriladi.
- Daraxt ostida gazon (yashil) bo'ladi. Asfalt, bruschatka, beton va tuproqning teksturalari har xil.
- Yo'l chiziqlari uzluksiz. Devor hech qachon yo'l ustida bo'lmaydi.
- Xatolar geometriyadan topiladi. Har bir tuzatish skriptga, har bir tekshiruv QA ga yoziladi.

## Ma'lumotlar
- `data/tiles/T_i_j.json` — yaqin sputnik suratidan qo'lda chizilgan 300 m plitkalar: parkovka, hovli, yo'lak, devor, yetishmayotgan binolar.
- `data/city/tile_list.json` — shahar plitkalari ro'yxati (258 ta, 1×1 km).
- `reports/CITY_REPORT.md` — oxirgi shahar hisoboti.
- `docs/TASKS.md` — vazifalar ro'yxati.
- `docs/street_reference.md` — ko'chalar bo'yicha ma'lumotnoma.
- `tools/tracing/` — Yandex sputnik ustida chizish uchun yordamchi skriptlar: koordinata to'ri, model overlay.

Katta ma'lumotlar (OSM extract, DEM, Sentinel, .blend fayllar) repoda yo'q. Ular `D:\Bishkek_35km` da qoladi.
