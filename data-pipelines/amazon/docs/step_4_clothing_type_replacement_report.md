# Step 4 Clothing Type Replacement Report

This report records the direct replacement of `clothing_type_id = other`
inside the Step 4 chunk files.

- total `other` rows before replacement: `13531`
- rows replaced with inferred clothing types: `6772`
- rows still left as `other`: `6759`
- replacement rate: `50.05%`

Replacement sources:

- `unresolved`: `6759`
- `product_majority_only`: `3617`
- `keyword_only`: `2529`
- `product_majority_override`: `572`
- `product+keyword_agree`: `54`

Inferred clothing types written into `clothing_type_id`:

- `top`: `2179`
- `jeans`: `2048`
- `pants`: `910`
- `dress`: `739`
- `overalls`: `520`
- `shorts`: `333`
- `skirt`: `22`
- `shirt`: `15`
- `sweater`: `6`

Sample unresolved rows left as `other`:

- `images_to_approve_part_001.csv` row `3`
  product: `https://www.amazon.com/dp/B07J3F6TV3/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Went with reviews, but too small!! I am 5"3" and 135 lbs. I bought the size 6 in white after reading reviews of women similar to my size. I couldn't even come c`
- `images_to_approve_part_001.csv` row `19`
  product: `https://www.amazon.com/dp/B07RK25YP5/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `I’m 5’5”, 115 and I got my normal size, 0, and these are so huge and baggy. The butt is baggy and I have a butt and the legs are baggy and don’t fit skinny. Dis`
- `images_to_approve_part_001.csv` row `20`
  product: `https://www.amazon.com/dp/B07RK25YP5/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `I’m 5’5”, 115 and I got my normal size, 0, and these are so huge and baggy. The butt is baggy and I have a butt and the legs are baggy and don’t fit skinny. Dis`
- `images_to_approve_part_001.csv` row `35`
  product: `https://www.amazon.com/dp/B07J3F6TRH/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `They feel and look great on me (run small). As other reviews state, they do run small. I typically wear a 0/2 so I went ahead and ordered a size 4 short. I'm 5'`
- `images_to_approve_part_001.csv` row `36`
  product: `https://www.amazon.com/dp/B07J3F6TRH/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `They feel and look great on me (run small). As other reviews state, they do run small. I typically wear a 0/2 so I went ahead and ordered a size 4 short. I'm 5'`
- `images_to_approve_part_001.csv` row `38`
  product: `https://www.amazon.com/dp/B07RL5Z31H/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Not long enough for long legs I like the shape and the color, but I'm 5'10, 130 lbs and the 2 long looks like a pair of capris on me.`
- `images_to_approve_part_001.csv` row `41`
  product: `https://www.amazon.com/dp/B07J3D9962/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Omg yes! I am 5’2 and 130ish pounds ! I ordered A size regular 2 so i could Cuff the bottoms. For shorter look i would Order short . They fit so well! They are `
- `images_to_approve_part_001.csv` row `42`
  product: `https://www.amazon.com/dp/B07J3D9962/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Omg yes! I am 5’2 and 130ish pounds ! I ordered A size regular 2 so i could Cuff the bottoms. For shorter look i would Order short . They fit so well! They are `
- `images_to_approve_part_001.csv` row `45`
  product: `https://www.amazon.com/dp/B07J31WFNB/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Love these! So happy I purchased! I’m 5’6 and 145 lbs - I ordered a size 10 reg. These things fit wonderful!!!! High waste my mommy tummy and super stretchy. Th`
- `images_to_approve_part_001.csv` row `46`
  product: `https://www.amazon.com/dp/B07J31WFNB/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Love these! So happy I purchased! I’m 5’6 and 145 lbs - I ordered a size 10 reg. These things fit wonderful!!!! High waste my mommy tummy and super stretchy. Th`
