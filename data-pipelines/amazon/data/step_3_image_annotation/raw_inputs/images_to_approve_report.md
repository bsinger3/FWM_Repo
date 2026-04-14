# Images To Approve: Size And Measurement Coverage Report

Source: `images_to_approve.csv`

Assumptions:
- The dataset is image-centric, so multiple image rows can represent the same review. I include row counts, and also note the approximate unique review/product/size count.
- `size_display` is treated as the ordered size.
- Height/weight ratio coverage is evaluated two ways: a raw height-by-weight bin grid and BMI bands computed from height and weight.
- Measurement count uses structured fields, not raw helper fields.

## Summary

| Metric | Count |
|---|---:|
| Output image rows | 91,925 |
| Approx. unique product/comment/size rows | 53,704 |
| Rows with height | 83,618 (91.0%) |
| Rows with weight | 58,151 (63.3%) |
| Rows with both height and weight | 55,086 (59.9%) |
| Rows with BMI computable | 55,086 (59.9%) |

## Measurement Ranges

| Field | Rows | Min | P5 | P25 | Median | P75 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| height_in_display | 83,618 | 48 | 60 | 63 | 65 | 67 | 70 | 84 |
| weight_lbs_display | 58,151 | 70 | 112 | 130 | 148 | 170 | 220 | 400 |
| BMI | 55,086 | 10.3 | 19.1 | 21.9 | 24.8 | 28.8 | 37.2 | 94.6 |

## Clothing Type Coverage

| clothing_type_id | Rows | Share |
|---|---:|---:|
| pants | 32,670 | 35.5% |
| jeans | 24,617 | 26.8% |
| dress | 17,241 | 18.8% |
| other | 13,531 | 14.7% |
| top | 1,509 | 1.6% |
| overalls | 1,295 | 1.4% |
| jumpsuit | 568 | 0.6% |
| skirt | 350 | 0.4% |
| shirt | 116 | 0.1% |
| tank | 19 | 0.0% |
| romper | 9 | 0.0% |

## Size Family Coverage

| Size family | Rows | Share |
|---|---:|---:|
| medium | 19,416 | 21.1% |
| small | 15,048 | 16.4% |
| large | 14,816 | 16.1% |
| x-large | 9,673 | 10.5% |
| xx-large | 3,938 | 4.3% |
| x-small | 2,824 | 3.1% |
| numeric 8 | 2,815 | 3.1% |
| numeric 6 | 2,685 | 2.9% |
| numeric 12 | 2,401 | 2.6% |
| numeric 4 | 2,321 | 2.5% |
| numeric 10 | 2,190 | 2.4% |
| numeric 14 | 1,766 | 1.9% |
| numeric 16 | 1,683 | 1.8% |
| numeric 18 | 1,206 | 1.3% |
| 3x-large | 959 | 1.0% |
| numeric 2 | 937 | 1.0% |
| other size text | 933 | 1.0% |
| one size | 518 | 0.6% |
| numeric 20 | 476 | 0.5% |
| numeric 24 | 435 | 0.5% |
| numeric 9 | 416 | 0.5% |
| numeric 22 | 389 | 0.4% |
| numeric 28 | 346 | 0.4% |
| numeric 26 | 343 | 0.4% |
| numeric 7 | 334 | 0.4% |
| numeric 27 | 322 | 0.4% |
| numeric 0 | 313 | 0.3% |
| numeric 29 | 255 | 0.3% |
| numeric 30 | 255 | 0.3% |
| numeric 11 | 248 | 0.3% |

## Most Common Raw Ordered Sizes

| size_display | Rows |
|---|---:|
| medium | 17,995 |
| small | 14,033 |
| large | 13,954 |
| x-large | 8,757 |
| xx-large | 3,427 |
| x-small | 2,249 |
| 6 | 2,005 |
| 8 | 2,005 |
| 4 | 1,738 |
| 12 | 1,656 |
| 10 | 1,502 |
| 14 | 1,199 |
| 16 | 937 |
| 3x-large | 669 |
| 2 | 643 |
| 18 | 509 |
| 18 plus | 443 |
| one size | 405 |
| 16 plus | 338 |
| small-medium | 277 |
| 9 | 253 |
| 20 plus | 250 |
| 7 | 239 |
| 22 plus | 229 |
| medium petite | 216 |
| 8-10 | 213 |
| 12 long | 211 |
| 12 short | 209 |
| 4 short | 208 |
| large-x-large | 201 |
| 2x | 191 |
| 8 long | 189 |
| small petite | 187 |
| 6 short | 183 |
| 10 short | 183 |
| 11 | 175 |
| 1x | 172 |
| 8 short | 171 |
| 10 long | 168 |
| large petite | 168 |
| medium tall | 165 |
| 4-6 | 160 |
| small tall | 159 |
| 0 | 154 |
| 6 long | 152 |
| 3x | 152 |
| small short | 146 |
| 14 short | 145 |
| 26 | 145 |
| 14 long | 140 |

## Numeric Size Coverage

| Numeric size found in size_display | Rows |
|---:|---:|
| 0 | 313 |
| 1 | 118 |
| 2 | 953 |
| 3 | 246 |
| 4 | 2,326 |
| 5 | 249 |
| 6 | 2,691 |
| 7 | 336 |
| 8 | 2,817 |
| 9 | 416 |
| 10 | 2,190 |
| 11 | 248 |
| 12 | 2,409 |
| 13 | 202 |
| 14 | 1,766 |
| 15 | 135 |
| 16 | 1,683 |
| 17 | 21 |
| 18 | 1,206 |
| 19 | 3 |
| 20 | 478 |
| 22 | 389 |
| 23 | 19 |
| 24 | 468 |
| 25 | 182 |
| 26 | 360 |
| 27 | 429 |
| 28 | 390 |
| 29 | 359 |
| 30 | 354 |
| 31 | 300 |
| 32 | 221 |
| 33 | 172 |
| 34 | 223 |
| 35 | 89 |
| 36 | 75 |
| 37 | 43 |
| 38 | 38 |
| 39 | 19 |

## Height By Weight Coverage

Counts below use rows with both `height_in_display` and `weight_lbs_display`.

| Height bin \ Weight bin | <110 lb | 110-129 lb | 130-149 lb | 150-169 lb | 170-189 lb | 190-219 lb | 220+ lb |
|---|---:|---:|---:|---:|---:|---:|---:|
| <60 in | 172 | 488 | 413 | 221 | 153 | 86 | 39 |
| 60-61 in | 437 | 1,835 | 1,534 | 926 | 515 | 246 | 98 |
| 62-63 in | 550 | 3,391 | 3,712 | 2,355 | 1,300 | 820 | 420 |
| 64-65 in | 269 | 2,627 | 4,070 | 2,881 | 1,672 | 1,189 | 579 |
| 66-67 in | 62 | 1,561 | 3,938 | 3,119 | 1,927 | 1,196 | 797 |
| 68-69 in | 19 | 510 | 1,469 | 1,807 | 1,088 | 908 | 637 |
| 70+ in | 47 | 194 | 589 | 671 | 630 | 528 | 391 |

No overall height/weight cells are completely missing at this bin size.

Sparse overall height/weight cells, fewer than 25 rows:
- 68-69 in / <110 lb: 19

## BMI Band Coverage By Common Size Family

| Size family | Rows in approval set | <18.5 | 18.5-24.9 | 25-29.9 | 30-34.9 | 35-39.9 | 40+ |
|---|---:|---:|---:|---:|---:|---:|---:|
| medium | 19,416 | 172 | 7,844 | 3,969 | 520 | 56 | 135 |
| small | 15,048 | 641 | 8,037 | 779 | 94 | 100 | 29 |
| large | 14,816 | 24 | 2,527 | 4,514 | 1,555 | 199 | 110 |
| x-large | 9,673 | 13 | 413 | 1,982 | 2,111 | 704 | 206 |
| xx-large | 3,938 | 7 | 45 | 245 | 681 | 575 | 322 |
| x-small | 2,824 | 329 | 1,390 | 40 | 24 | 9 | 0 |
| numeric 8 | 2,815 | 7 | 1,028 | 570 | 40 | 6 | 18 |
| numeric 6 | 2,685 | 53 | 1,351 | 234 | 7 | 41 | 1 |
| numeric 12 | 2,401 | 11 | 245 | 816 | 279 | 23 | 3 |
| numeric 4 | 2,321 | 122 | 1,213 | 64 | 0 | 13 | 5 |
| numeric 10 | 2,190 | 3 | 431 | 667 | 110 | 2 | 9 |
| numeric 14 | 1,766 | 3 | 71 | 419 | 433 | 57 | 46 |
| numeric 16 | 1,683 | 2 | 12 | 183 | 390 | 169 | 30 |
| numeric 18 | 1,206 | 0 | 3 | 43 | 227 | 215 | 83 |
| 3x-large | 959 | 0 | 3 | 39 | 69 | 90 | 179 |
| numeric 2 | 937 | 37 | 526 | 29 | 5 | 0 | 0 |

Missing BMI bands among the most common size families:
- x-small (2,824 rows): missing BMI band(s) 40+
- numeric 4 (2,321 rows): missing BMI band(s) 30-34.9
- numeric 18 (1,206 rows): missing BMI band(s) <18.5
- 3x-large (959 rows): missing BMI band(s) <18.5
- numeric 2 (937 rows): missing BMI band(s) 35-39.9, 40+

## Height/Weight Grid Gaps By Common Alpha Size

| Size family | Rows with height+weight | Missing grid cells | First missing cells | Sparse cells under 5 rows |
|---|---:|---:|---|---|
| x-small | 1,792 | 19 | <60 in / 150-169 lb; <60 in / 170-189 lb; <60 in / 190-219 lb; <60 in / 220+ lb; 60-61 in / 150-169 lb; 60-61 in / 190-219 lb; 60-61 in / 220+ lb; 62-63 in / 150-169 lb; 62-63 in / 170-189 lb; 62-63 in / 220+ lb; 64-65 in / 170-189 lb; 64-65 in / 190-219 lb | <60 in / 130-149 lb (3); 60-61 in / 170-189 lb (3); 62-63 in / 190-219 lb (2); 64-65 in / 150-169 lb (1); 66-67 in / 150-169 lb (1); 66-67 in / 170-189 lb (4); 68-69 in / 150-169 lb (3); 68-69 in / 220+ lb (3); 70+ in / 150-169 lb (3); 70+ in / 190-219 lb (1); 70+ in / 220+ lb (2) |
| small | 9,680 | 10 | <60 in / 190-219 lb; <60 in / 220+ lb; 60-61 in / 170-189 lb; 60-61 in / 190-219 lb; 60-61 in / 220+ lb; 62-63 in / 190-219 lb; 64-65 in / 190-219 lb; 64-65 in / 220+ lb; 68-69 in / <110 lb; 68-69 in / 220+ lb | <60 in / 170-189 lb (1); 66-67 in / 190-219 lb (1); 66-67 in / 220+ lb (2); 68-69 in / 190-219 lb (1); 70+ in / 190-219 lb (3); 70+ in / 220+ lb (3) |
| medium | 12,696 | 4 | <60 in / 220+ lb; 60-61 in / 220+ lb; 62-63 in / 220+ lb; 68-69 in / 220+ lb | 60-61 in / 190-219 lb (1); 64-65 in / 220+ lb (1); 66-67 in / 220+ lb (2); 70+ in / <110 lb (2); 70+ in / 220+ lb (1) |
| large | 8,929 | 5 | <60 in / 220+ lb; 60-61 in / <110 lb; 62-63 in / <110 lb; 64-65 in / <110 lb; 66-67 in / <110 lb | <60 in / <110 lb (1); <60 in / 110-129 lb (1); 68-69 in / <110 lb (2); 70+ in / <110 lb (3); 70+ in / 110-129 lb (4) |
| x-large | 5,429 | 4 | <60 in / <110 lb; <60 in / 110-129 lb; 62-63 in / <110 lb; 64-65 in / <110 lb | 60-61 in / <110 lb (1); 64-65 in / 110-129 lb (3); 66-67 in / <110 lb (1); 66-67 in / 110-129 lb (3); 68-69 in / <110 lb (1); 68-69 in / 110-129 lb (1); 70+ in / <110 lb (2); 70+ in / 110-129 lb (1) |
| xx-large | 1,875 | 15 | <60 in / <110 lb; <60 in / 110-129 lb; <60 in / 130-149 lb; 60-61 in / <110 lb; 60-61 in / 110-129 lb; 62-63 in / 110-129 lb; 64-65 in / 110-129 lb; 66-67 in / <110 lb; 66-67 in / 110-129 lb; 66-67 in / 130-149 lb; 68-69 in / <110 lb; 68-69 in / 110-129 lb | <60 in / 150-169 lb (2); 60-61 in / 130-149 lb (3); 62-63 in / <110 lb (3); 62-63 in / 130-149 lb (3); 64-65 in / <110 lb (4); 64-65 in / 130-149 lb (3); 68-69 in / 130-149 lb (2) |
| 3x-large | 380 | 24 | <60 in / <110 lb; <60 in / 130-149 lb; 60-61 in / <110 lb; 60-61 in / 110-129 lb; 60-61 in / 130-149 lb; 60-61 in / 150-169 lb; 62-63 in / <110 lb; 62-63 in / 110-129 lb; 62-63 in / 130-149 lb; 62-63 in / 150-169 lb; 64-65 in / <110 lb; 64-65 in / 110-129 lb | <60 in / 110-129 lb (1); <60 in / 150-169 lb (1); <60 in / 170-189 lb (3); <60 in / 190-219 lb (2); <60 in / 220+ lb (3); 60-61 in / 170-189 lb (2); 64-65 in / 170-189 lb (4); 66-67 in / 130-149 lb (2); 70+ in / 130-149 lb (1) |

## Main Findings

- The approval set heavily covers alpha sizes `small`, `medium`, `large`, `x-large`, and `xx-large`, plus numeric sizes `4` through `16`.
- The thinnest coverage is at extreme numeric and plus sizes, especially raw sizes above `20`, and at uncommon raw labels like petite/long/short variants when considered individually.
- Overall height/weight coverage is broad, but sparse at the shortest/tallest and lightest/heaviest edges. These edge bins are the riskiest for fit approval because there are fewer comparable examples.
- BMI coverage exists across the major alpha size families, but the row counts skew strongly toward mid-range BMI bands. Very low BMI and very high BMI bands are present but comparatively sparse.
- Because this is image-centric, products/reviews with multiple images inflate counts. For modeling or final QA, consider deduping by product/comment/size before calculating training-set balance.
