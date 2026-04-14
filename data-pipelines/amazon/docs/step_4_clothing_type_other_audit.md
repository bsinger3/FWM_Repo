# Step 4 Clothing Type `other` Audit

This report audits how many Step 4 rows currently have `clothing_type_id = other`
and estimates how many can be recovered with deterministic Python logic
without mutating the Step 4 chunk files.

## Current Counts

- total Step 4 rows: `91925`
- rows with `clothing_type_id = other`: `13531`
- percentage of Step 4 rows in `other`: `14.72%`

Current overall clothing type counts:

- `pants`: `32670`
- `jeans`: `24617`
- `dress`: `17241`
- `other`: `13531`
- `top`: `1509`
- `overalls`: `1295`
- `jumpsuit`: `568`
- `skirt`: `350`
- `shirt`: `116`
- `tank`: `19`
- `romper`: `9`

## Proposed Inference Logic

- keep any non-`other` `clothing_type_id` unchanged
- use product-majority when a product has at least `3` known rows and the dominant type is at least `70%`
- otherwise fall back to keyword matching on comments, search text, and product URLs
- if product-majority and keywords disagree, let product-majority win only when it is at least `85%`
- otherwise leave the row unresolved for review

## First-Pass Results

- rows recoverable in the first pass: `6772`
- percentage of `other` recoverable in the first pass: `50.05%`
- rows still unresolved after the first pass: `6759`

Inference source counts:

- `unresolved`: `6759`
- `product_majority_only`: `3617`
- `keyword_only`: `2529`
- `product_majority_override`: `572`
- `product+keyword_agree`: `54`

Recovered clothing types:

- `top`: `2179`
- `jeans`: `2048`
- `pants`: `910`
- `dress`: `739`
- `overalls`: `520`
- `shorts`: `333`
- `skirt`: `22`
- `shirt`: `15`
- `sweater`: `6`

Keyword signal counts for `other` rows:

- `no_match`: `9996`
- `top`: `2587`
- `shorts`: `715`
- `pants`: `111`
- `ambiguous`: `110`
- `sweater`: `8`
- `shirt`: `4`

## Preview Output

- detailed per-row preview CSV:
  `step_4_clothing_type_other_inference_preview.csv`
- this CSV includes helper columns showing the inferred type, the source of the inference,
  the product-majority evidence, and the keyword evidence

## Examples: `product+keyword_agree`

- file: `images_to_approve_part_004.csv` row `376`
  product: `https://www.amazon.com/dp/B0CW8TZJLR/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `pants`
  product-majority: `pants` at `100.00%`
  keyword signal: `pants`
  comment excerpt: `Decent Nice for the price. I wish I would've sized down (I'm a pant size 10-12 and got waist 37-45 as I'm about ~38 but I'm already basically on the last notch so it has a super lo`

- file: `images_to_approve_part_004.csv` row `377`
  product: `https://www.amazon.com/dp/B0CW8TZJLR/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `pants`
  product-majority: `pants` at `100.00%`
  keyword signal: `pants`
  comment excerpt: `Decent Nice for the price. I wish I would've sized down (I'm a pant size 10-12 and got waist 37-45 as I'm about ~38 but I'm already basically on the last notch so it has a super lo`

- file: `images_to_approve_part_004.csv` row `878`
  product: `https://www.amazon.com/dp/B07GDZGDYN/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `pants`
  product-majority: `pants` at `89.34%`
  keyword signal: `pants`
  comment excerpt: `Very short Didn't measure inseam, but I'm 5'8" and the black L and XL are ankle length. Not a full lenght pant.`

- file: `images_to_approve_part_004.csv` row `2594`
  product: `https://www.amazon.com/dp/B07H9HP6VT/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `pants`
  product-majority: `pants` at `100.00%`
  keyword signal: `pants`
  comment excerpt: `Perfect color and fit I ordered this for my husband and it was true royal blue. He is about 5’11 and wears a 30 pant I think and we went with a small.`

- file: `images_to_approve_part_005.csv` row `93`
  product: `https://www.amazon.com/dp/B08JDNY7J9/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `pants`
  product-majority: `pants` at `87.18%`
  keyword signal: `pants`
  comment excerpt: `Nice casual pant. Just received these today. I’m 5’1’ and weigh 105. These are a size 2. They fit great. Being a small person these fit at my waist rather than below my waist. I lo`

## Examples: `product_majority_override`

- file: `images_to_approve_part_001.csv` row `209`
  product: `https://www.amazon.com/dp/B0CPNMDJYN/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `87.50%`
  keyword signal: `shorts`
  note: `product-majority and keyword disagree; strong product-majority wins`
  comment excerpt: `Obsessed! Love these shorts! I’m 5ft & 130lbs, my waist is 28” & my hips are 41” so I followed the size guide & ordered a size 27, the fit is almost perfect. I’m an hour glass shap`

- file: `images_to_approve_part_001.csv` row `210`
  product: `https://www.amazon.com/dp/B0CPNMDJYN/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `87.50%`
  keyword signal: `shorts`
  note: `product-majority and keyword disagree; strong product-majority wins`
  comment excerpt: `Obsessed! Love these shorts! I’m 5ft & 130lbs, my waist is 28” & my hips are 41” so I followed the size guide & ordered a size 27, the fit is almost perfect. I’m an hour glass shap`

- file: `images_to_approve_part_001.csv` row `211`
  product: `https://www.amazon.com/dp/B0CPNMDJYN/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `87.50%`
  keyword signal: `shorts`
  note: `product-majority and keyword disagree; strong product-majority wins`
  comment excerpt: `LOVE these shorts! Love these shorts and LOVE the length. I’m a new mama and was looking for some shorts that had coverage but still cute and these exceeded my expectations! I am 5`

- file: `images_to_approve_part_001.csv` row `215`
  product: `https://www.amazon.com/dp/B0CPNMDJYN/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `87.50%`
  keyword signal: `shorts`
  note: `product-majority and keyword disagree; strong product-majority wins`
  comment excerpt: `Great longer shorts Love the longer length for daily wear. There is no stretch so size up. I did a 31 and I usually wear a 30 (150lb). I wish the white pocket was black though as i`

- file: `images_to_approve_part_001.csv` row `216`
  product: `https://www.amazon.com/dp/B0CPNMDJYN/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `87.50%`
  keyword signal: `shorts`
  note: `product-majority and keyword disagree; strong product-majority wins`
  comment excerpt: `Great longer shorts Love the longer length for daily wear. There is no stretch so size up. I did a 31 and I usually wear a 30 (150lb). I wish the white pocket was black though as i`

## Examples: `product_majority_only`

- file: `images_to_approve_part_001.csv` row `37`
  product: `https://www.amazon.com/dp/B07J3GQ91R/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `100.00%`
  keyword signal: `no_match`
  comment excerpt: `Camel Toe City I ordered a size 10 short, 5’4 and 180lbs and they fit exactly how they are supposed to. However, they gave me the world’s biggest camel toe. I think any other color`

- file: `images_to_approve_part_001.csv` row `51`
  product: `https://www.amazon.com/dp/B09N5MKSV7/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `100.00%`
  keyword signal: `no_match`
  comment excerpt: `They fit- true to size- a little short but good I like how they stretch, I wish they had a long options, but that’s okay. I’m 5’8, almost 5’9 and I weigh 138IBS.`

- file: `images_to_approve_part_001.csv` row `52`
  product: `https://www.amazon.com/dp/B09N5MKSV7/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `100.00%`
  keyword signal: `no_match`
  comment excerpt: `They fit- true to size- a little short but good I like how they stretch, I wish they had a long options, but that’s okay. I’m 5’8, almost 5’9 and I weigh 138IBS.`

- file: `images_to_approve_part_001.csv` row `123`
  product: `https://www.amazon.com/dp/B07Q4PVPZW/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `100.00%`
  keyword signal: `no_match`
  comment excerpt: `Same kind different size but still worth finding the right size, never find a better fit I absolutely love this kut and brand depending on the color you might have to play with the`

- file: `images_to_approve_part_001.csv` row `124`
  product: `https://www.amazon.com/dp/B07Q4PVPZW/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `jeans`
  product-majority: `jeans` at `100.00%`
  keyword signal: `no_match`
  comment excerpt: `Same kind different size but still worth finding the right size, never find a better fit I absolutely love this kut and brand depending on the color you might have to play with the`

## Examples: `keyword_only`

- file: `images_to_approve_part_001.csv` row `60`
  product: `https://www.amazon.com/dp/B09N5HPJHV/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `top`
  product-majority: `` at ``
  keyword signal: `top`
  comment excerpt: `GET THEMMMM COME ON SPOIL URSELF BESTIE I am a 5'1 190lb meatball! look I have mom pooch and c section pooch. I followed the size guide and they fit well!! I LOVE them. I was afrai`

- file: `images_to_approve_part_001.csv` row `61`
  product: `https://www.amazon.com/dp/B09N5HPJHV/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `top`
  product-majority: `` at ``
  keyword signal: `top`
  comment excerpt: `GET THEMMMM COME ON SPOIL URSELF BESTIE I am a 5'1 190lb meatball! look I have mom pooch and c section pooch. I followed the size guide and they fit well!! I LOVE them. I was afrai`

- file: `images_to_approve_part_001.csv` row `236`
  product: `https://www.amazon.com/dp/B091SXL6D4/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `top`
  product-majority: `` at `69.05%`
  keyword signal: `top`
  comment excerpt: `Order 2-3 sizes up I’m usually a 1-2x and after reading the reviews I ordered a 5x. On no planet but this one am I a 5x. I’m 5’4” and 250 lbs with a curvy backside and these fit pe`

- file: `images_to_approve_part_001.csv` row `237`
  product: `https://www.amazon.com/dp/B091SXL6D4/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `top`
  product-majority: `` at `69.05%`
  keyword signal: `top`
  comment excerpt: `Order 2-3 sizes up I’m usually a 1-2x and after reading the reviews I ordered a 5x. On no planet but this one am I a 5x. I’m 5’4” and 250 lbs with a curvy backside and these fit pe`

- file: `images_to_approve_part_001.csv` row `358`
  product: `https://www.amazon.com/dp/B0BYCG2BV9/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: `shorts`
  product-majority: `` at ``
  keyword signal: `shorts`
  comment excerpt: `Very cute shorts with a LOT of stretch!! Cute shorts and they cover up nicely which I really like!! They are VERY stretchy though! Almost too much cause I would have preferred a li`

## Examples: `unresolved`

- file: `images_to_approve_part_001.csv` row `3`
  product: `https://www.amazon.com/dp/B07J3F6TV3/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: ``
  product-majority: `` at ``
  keyword signal: `no_match`
  note: `no_match`
  comment excerpt: `Went with reviews, but too small!! I am 5"3" and 135 lbs. I bought the size 6 in white after reading reviews of women similar to my size. I couldn't even come close to zipping up o`

- file: `images_to_approve_part_001.csv` row `19`
  product: `https://www.amazon.com/dp/B07RK25YP5/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: ``
  product-majority: `` at ``
  keyword signal: `no_match`
  note: `no_match`
  comment excerpt: `I’m 5’5”, 115 and I got my normal size, 0, and these are so huge and baggy. The butt is baggy and I have a butt and the legs are baggy and don’t fit skinny. Disappointed because I `

- file: `images_to_approve_part_001.csv` row `20`
  product: `https://www.amazon.com/dp/B07RK25YP5/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: ``
  product-majority: `` at ``
  keyword signal: `no_match`
  note: `no_match`
  comment excerpt: `I’m 5’5”, 115 and I got my normal size, 0, and these are so huge and baggy. The butt is baggy and I have a butt and the legs are baggy and don’t fit skinny. Disappointed because I `

- file: `images_to_approve_part_001.csv` row `35`
  product: `https://www.amazon.com/dp/B07J3F6TRH/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: ``
  product-majority: `` at ``
  keyword signal: `no_match`
  note: `no_match`
  comment excerpt: `They feel and look great on me (run small). As other reviews state, they do run small. I typically wear a 0/2 so I went ahead and ordered a size 4 short. I'm 5'1 and 125 lbs with a`

- file: `images_to_approve_part_001.csv` row `36`
  product: `https://www.amazon.com/dp/B07J3F6TRH/ref=cm_cr_arp_d_product_top?ie=UTF8`
  existing type: `other`
  inferred type: ``
  product-majority: `` at ``
  keyword signal: `no_match`
  note: `no_match`
  comment excerpt: `They feel and look great on me (run small). As other reviews state, they do run small. I typically wear a 0/2 so I went ahead and ordered a size 4 short. I'm 5'1 and 125 lbs with a`

