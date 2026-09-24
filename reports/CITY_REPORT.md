# City run report  2026-09-25 00:24

tiles: done 258
QA gates failed (tiles): none
totals: hole 0, open_chain_long 0, building_overlap 0, wall_on_street 0, house_without_wall 6201, path_dead_end 20, marking_gap_main 0, playground_no_path 349, parking_no_access 0, buildings 131481, apartment_blocks 10024, yard_parking_m2 240885, yard_playground_m2 431523, ground_m2 232514521

## Apartment yards: model green share minus Sentinel-2 September green share
tiles 239; mean -3.3 pp; median -2.6 pp; tiles with > 20 pp: 0

| tile | yard m2 | model green | S2 green | excess pp | parking m2 | playground m2 |
|---|---|---|---|---|---|---|
| T_2_-4 | 11210 | 16% | 5% | 11.6 | 0 | 439 |
| T_-11_4 | 5005 | 40% | 31% | 8.8 | 0 | 179 |
| T_-3_-4 | 10856 | 14% | 8% | 6.4 | 0 | 0 |
| T_-7_0 | 20046 | 10% | 4% | 6.2 | 0 | 0 |
| T_-4_-2 | 19207 | 19% | 14% | 5.0 | 894 | 408 |
| T_-2_-3 | 36817 | 34% | 29% | 4.9 | 0 | 531 |
| T_14_4 | 218019 | 47% | 43% | 4.8 | 0 | 2831 |
| T_-8_-3 | 25912 | 21% | 16% | 4.6 | 0 | 750 |
| T_-3_-3 | 21526 | 11% | 7% | 4.4 | 0 | 161 |
| T_-5_-4 | 15740 | 15% | 11% | 4.4 | 0 | 377 |
| T_-8_1 | 12918 | 11% | 6% | 4.4 | 0 | 0 |
| T_-9_0 | 6512 | 6% | 2% | 4.3 | 0 | 64 |
| T_5_1 | 62458 | 14% | 10% | 4.2 | 0 | 1170 |
| T_11_2 | 83864 | 54% | 50% | 4.0 | 0 | 1357 |
| T_-3_-2 | 56358 | 23% | 19% | 3.9 | 0 | 623 |
| T_-4_-1 | 49268 | 12% | 8% | 3.9 | 0 | 465 |
| T_5_-4 | 48563 | 30% | 26% | 3.9 | 0 | 1149 |
| T_5_6 | 25537 | 31% | 27% | 3.8 | 0 | 378 |
| T_-8_2 | 18072 | 13% | 10% | 3.6 | 0 | 247 |
| T_7_6 | 16240 | 66% | 62% | 3.6 | 0 | 220 |
| T_-12_4 | 120849 | 28% | 25% | 3.4 | 0 | 2016 |
| T_-7_-1 | 36706 | 7% | 4% | 3.4 | 0 | 582 |
| T_6_3 | 351509 | 9% | 6% | 3.4 | 671 | 3089 |
| T_-7_1 | 65849 | 23% | 20% | 3.3 | 0 | 328 |
| T_5_2 | 11235 | 3% | 0% | 3.3 | 0 | 232 |

## Tile seams (shared 1 km edges: surface class and height must match on both sides)
edges 455; class mismatch mean 1.7 % (max 12.8 %); height step > 5 cm mean 0.5 % (max 7.5 %)

- T_-3_1 | T_-2_1: class mismatch 11.8 %, dz>5cm 6.0 %, dz max 0.6 m, gap 9.4 %
- T_3_3 | T_4_3: class mismatch 12.8 %, dz>5cm 0.1 %, dz max 0.15 m, gap 23.6 %
- T_0_6 | T_1_6: class mismatch 8.4 %, dz>5cm 3.9 %, dz max 0.6 m, gap 0.0 %
- T_-1_-1 | T_0_-1: class mismatch 10.1 %, dz>5cm 1.1 %, dz max 0.6 m, gap 36.6 %
- T_6_4 | T_7_4: class mismatch 6.9 %, dz>5cm 3.6 %, dz max 0.6 m, gap 8.9 %
- T_-5_0 | T_-5_1: class mismatch 9.6 %, dz>5cm 0.7 %, dz max 0.6 m, gap 6.2 %
- T_2_0 | T_2_1: class mismatch 4.3 %, dz>5cm 5.3 %, dz max 0.6 m, gap 13.0 %
- T_8_4 | T_8_5: class mismatch 6.7 %, dz>5cm 2.3 %, dz max 0.6 m, gap 6.3 %
- T_-5_-1 | T_-4_-1: class mismatch 5.7 %, dz>5cm 3.1 %, dz max 0.61 m, gap 1.1 %
- T_6_3 | T_6_4: class mismatch 1.2 %, dz>5cm 7.5 %, dz max 0.2 m, gap 0.0 %
