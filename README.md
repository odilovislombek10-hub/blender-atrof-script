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
- `REBUILD_ALL.bat` — hammasi: 1 km zona + barcha shahar plitkalari (majburiy) + ulash + hisobot;
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

## 25 sentyabr o'zgarishlari
- **Hovli parkovkasi (SHEF qarori, a variant):** hovli ichidagi proezd bo'ylab (bloklardan 4–45 m), sentyabr Sentinel suratida yashil bo'lmagan joyga parkovka qatori qo'yiladi, daraxt tagiga qo'yilmaydi. Yanvar qor sharti o'lchanib, olib tashlandi: hovlilar qordan tozalanmaydi.
- **Plitkalar chegarasi:** o'simlik qatlami endi faqat mahalliy, deterministik amallar bilan olinadi (soddalashtirish olib tashlandi). Chekkadagi bo'laklar qo'shniga qo'shilmaydi. Yo'l chizig'i shtrixlari dunyo koordinatasiga bog'langan. Natija: ikki qo'shni plitkaning chegarasida qatlamlar bir xil.
- **Geometriya:** QA dagi "degenerate" endi haqiqiy nol yuza (< 1 mm²) degani. Mayda va ingichka yuzalar alohida ko'rsatiladi. Tekis T-birikmalar 08 da yopiladi.
- **Shahar chekkasidagi terrain** plitkaning haqiqiy yer chekkasidan 3 sm pastga qo'yiladi.
- **Muhim xato tuzatildi (06):** geometrik amallardan keyin "aralash to'plam" (poligon + chiziq) bo'lib qolgan qatlamning chegarasi bo'laklarga ajratishda yo'qolardi. Natijada katta bo'lak bitta nuqtaga qarab butunlay gazon yoki butunlay qattiq hovli bo'lib qolardi. Masalan, plitka (−1,1) da 47 000 m² hovli uchastkasi gazon bo'lib ketgan edi. Endi har bir qatlamdan faqat poligon qismi olinadi va chegarasi yo'qolgan qatlam haqida log yoziladi.
- **Asosiy faylda shahar plitkalari ulangan bo'lsa:** 07/07b/08/12 faqat lokal ma'lumot bilan ishlaydi. Zona qurilayotganda plitkalar ko'rinishdan chiqarib turiladi. Zona tikuvi (terrain) plitkalar zonani o'rab olgan bo'lsa tekshirilmaydi, uni 16 tekshiradi.
- `REBUILD_ZONE_QA.bat` — faqat zona QA (12 → 12b → 13).

**Holat (25 sentyabr, 17:35):** oxirgi to'liq qayta qurish yarmida to'xtatildi (~90 / 258 plitka yangi skript bilan). Oxiriga yetkazish uchun: `scripts\REBUILD_ALL.bat` (~1 soat, kompyuterni to'liq band qiladi).

## Ma'lumotlar
- `data/tiles/T_i_j.json` — yaqin sputnik suratidan qo'lda chizilgan 300 m plitkalar: parkovka, hovli, yo'lak, devor, yetishmayotgan binolar.
- `data/city/tile_list.json` — shahar plitkalari ro'yxati (258 ta, 1×1 km).
- `reports/CITY_REPORT.md` — oxirgi shahar hisoboti.
- `docs/TASKS.md` — vazifalar ro'yxati.
- `docs/street_reference.md` — ko'chalar bo'yicha ma'lumotnoma.
- `tools/tracing/` — Yandex sputnik ustida chizish uchun yordamchi skriptlar: koordinata to'ri, model overlay.

Katta ma'lumotlar (OSM extract, DEM, Sentinel, .blend fayllar) repoda yo'q. Ular `D:\Bishkek_35km` da qoladi.
