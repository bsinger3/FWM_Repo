# Step 4 Clothing Type Replacement Report

This report records the direct replacement of `clothing_type_id = other`
inside the Step 4 chunk files.

- total `other` rows before replacement: `6759`
- rows replaced with inferred clothing types: `3284`
- rows still left as `other`: `3475`
- replacement rate: `48.59%`

Replacement sources:

- `unresolved`: `3475`
- `keyword_only`: `1372`
- `product_majority_only`: `851`
- `product_small_sample_only`: `557`
- `product_majority_override`: `277`
- `product_small_sample_override`: `227`

Inferred clothing types written into `clothing_type_id`:

- `top`: `1169`
- `swimsuit`: `990`
- `overalls`: `269`
- `dress`: `143`
- `bra`: `128`
- `jeans`: `110`
- `bikini`: `101`
- `shorts`: `96`
- `pants`: `80`
- `coverup`: `67`
- `capris`: `43`
- `jacket`: `39`
- `skirt`: `20`
- `shirt`: `13`
- `tank`: `12`
- `bodysuit`: `4`

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
- `images_to_approve_part_001.csv` row `41`
  product: `https://www.amazon.com/dp/B07J3D9962/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Omg yes! I am 5’2 and 130ish pounds ! I ordered A size regular 2 so i could Cuff the bottoms. For shorter look i would Order short . They fit so well! They are `
- `images_to_approve_part_001.csv` row `42`
  product: `https://www.amazon.com/dp/B07J3D9962/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Omg yes! I am 5’2 and 130ish pounds ! I ordered A size regular 2 so i could Cuff the bottoms. For shorter look i would Order short . They fit so well! They are `
- `images_to_approve_part_001.csv` row `67`
  product: `https://www.amazon.com/dp/B09N5WG6NZ/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Obsessed Recommend sizing down one size, if you’re a tall girly like me (5’9) they definitely will be too short but stuff cute if cuffed.`
- `images_to_approve_part_001.csv` row `77`
  product: `https://www.amazon.com/dp/B09N5ZFSXF/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Very clearly 31” when description states 30” inseam. Please make sure you’re shipping the correct products as per the description. I own these in a few washes a`
- `images_to_approve_part_001.csv` row `98`
  product: `https://www.amazon.com/dp/B07B6GK4ZX/ref=cm_cr_arp_d_product_top?ie=UTF8`
  comment excerpt: `Good fit For reference I am almost 5’2”, almost 140 lbs and these are a size 6 SHORT and I’m wearing 3” heels. Definitely runs a bit long. If you are “between s`
