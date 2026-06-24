#!/usr/bin/env python3
"""Deterministic regex tests for extract_measurements().

Seeded from real review comments the human flagged in the extraction-audit
dashboard (FWM_Data/_reports/extraction_audit/flagged_extractions*.json). Each
case pins the measurement(s) that were previously missed, wrong, or a false
positive. Run: python3 test_extract_measurements.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from step1_intake_utils import extract_measurements

# (label, comment, {field: expected_value}). A field mapped to "" must be empty.
CASES = [
    # --- Age: "yr old" / "year old" / "age of" / "age N" / "N years old" ------
    ("age_yr_old", "For ref, I’m 5’0”, 150-153 lbs ... My 42 yr old mom bod", {"age_years_display": "42"}),
    ("age_year_old", "I am a 30 year old toddler mom and these are cute.", {"age_years_display": "30"}),
    ("age_of_plus", "I dared to order them at my age of 60+, lol.", {"age_years_display": "60"}),
    ("age_bare_55", "regular sizes 10-12 Large, age 55, w/ extra saggy arms", {"age_years_display": "55"}),
    ("age_years_old_81", "I am 81 years old and I have bad scoliosis.", {"age_years_display": "81"}),
    ("age_years_old_58", "I am 5'4\", 138lbs (typical 58 years old who had children)", {"age_years_display": "58"}),

    # --- Bust-waist-hips triples: commas and inch marks --------------------
    ("triple_comma", "Classy & elegant 32,29,45 are my approximate measurements",
     {"bust_in_display": "32", "waist_in": "29", "hips_in_display": "45"}),
    ("triple_comma_2", "they fit like a glove. measurements 38,37,46 and they fit",
     {"bust_in_display": "38", "waist_in": "37", "hips_in_display": "46"}),
    ("triple_inch", "measurements about 40\"-30\"-40\" (bust-waist-hip)",
     {"bust_in_display": "40", "waist_in": "30", "hips_in_display": "40"}),

    # --- en-dash + cm: must convert, not read cm as inches -----------------
    ("endash_cm", "My measurements: Bust – 93 cm, Waist – 68 cm, Hips – 94 cm.",
     {"bust_in_display": "36.61", "waist_in": "26.77", "hips_in_display": "37.01"}),
    ("waist_cm_colon", "Bra: 32A/B. Waist: 65cm, Hips 92cm.",
     {"waist_in": "25.59", "hips_in_display": "36.22"}),

    # --- verbs / number-before-label / parens / "of" / "currently" ---------
    ("verb_measures", "waist measures 27”, hips/butt measure 39”",
     {"waist_in": "27", "hips_in_display": "39"}),
    ("num_before", "34\" bust, 29\" waist, & 40.5\" hip, 30\" inseam",
     {"bust_in_display": "34", "waist_in": "29", "hips_in_display": "40.5", "inseam_inches_display": "30"}),
    ("paren", "I have hips (40\") and a smaller waist (33\")",
     {"hips_in_display": "40", "waist_in": "33"}),
    ("waist_of", "I am 5'7\" 200lbs with a waist of 43\"", {"waist_in": "43"}),
    ("ish", "5'4\" tall, 33-ish waist, 44\" hips and 182 lbs",
     {"waist_in": "33", "hips_in_display": "44"}),
    ("currently_slash", "My waist is currently 36/37” and per the size guide", {"waist_in": "36"}),
    ("are_currently", "My waist is currently 37”, my hips are 45”, I am 5'7\"",
     {"waist_in": "37", "hips_in_display": "45"}),

    # --- False positives the fixes must NOT produce ------------------------
    ("bra_pronoun_I", "Dirty 30 I recently purchased this item and I love it.",
     {"cupsize_display": "", "bra_band_in_display": "", "bust_in_display": ""}),
    ("cup_not_bust", "I have a short torso and am a D cup. This is a crop top on me.",
     {"cupsize_display": "D", "bust_in_display": ""}),
    ("height_apostrophe_s", "good for temps in the upper 70's. For reference: I'm 5' 4\" tall",
     {"height_in_display": "64"}),
    ("height_inches_not_bust", "Perfect if petite. Height: 4'11” Bust: 34B Waist: 23-24 in",
     {"height_in_display": "59", "bust_in_display": "", "bra_band_in_display": "34", "cupsize_display": "B"}),
    ("inseam_not_neighbor", "Waistband =35.5” Hips = 41” Inseam 30” The waist sits",
     {"inseam_inches_display": "30", "hips_in_display": "41"}),

    # --- height written with a double-quote ("5\"4" == 5'4") ---------------
    ("height_dquote", "If you are 5”4 5”5 or 5”7 do not buy this outfit", {"height_in_display": "64"}),
    ("height_dquote_11", "Tall woman here, I'm 5\"11 and it fits.", {"height_in_display": "71"}),
    ("height_dquote_not_inches", "These run long. My waist is 34\" and hips 40\".",
     {"height_in_display": "", "waist_in": "34", "hips_in_display": "40"}),

    # --- weight range with '#' --------------------------------------------
    ("weight_hash_range", "I’m 5’8” and around 175-180#. A large fit me nicely.",
     {"weight_display_display": "175-180 lb"}),

    # --- pregnancy: bare "N weeks" only with current-pregnancy context -----
    ("pregnancy_soft", "smaller bump- 32 weeks but measuring at 29 weeks. maternity shoot soon",
     {"weeks_pregnant": "32"}),

    # --- Regressions: these must stay correct ------------------------------
    ("reg_canonical", "I'm 5'5\", 130 lbs, 34C, my waist is 28 and hips are 38.",
     {"height_in_display": "65", "weight_lbs_display": "130", "waist_in": "28",
      "hips_in_display": "38", "bra_band_in_display": "34", "cupsize_display": "C"}),
    ("reg_postpartum", "20 weeks postpartum and still wearing it.", {"weeks_pregnant": ""}),
    ("reg_prepregnancy", "I bought my pre-pregnancy size.", {"weeks_pregnant": ""}),
    ("reg_pregnant", "I'm 20 weeks pregnant and love it.", {"weeks_pregnant": "20"}),

    # === Height/weight outlier fixes (2026-06-24 dot-plot audit) ===========
    # Reversed feet/inch marks: 5"4' means 5'4", not 4 feet. Was -> 48/84/36.
    ("height_reversed_54", "Im 5”4’ and 155lbs with square shape, looks good.",
     {"height_in_display": "64", "weight_lbs_display": "155"}),
    ("height_reversed_57", "I am 5\"7' and weigh 160 lbs.",
     {"height_in_display": "67", "weight_lbs_display": "160"}),
    ("height_reversed_53", "I’m 5”3’ around 135lbs and the short size is perfect.",
     {"height_in_display": "63", "weight_lbs_display": "135"}),
    ("height_reversed_noweight", "My height is 5”4’ and it is perfect for me.",
     {"height_in_display": "64"}),
    # A genuine inch mark after the inches ("5' 4"") must NOT be read as feet.
    ("height_real_inch_mark", "Size 14, 5' 4\" 1 1/2\" heel, no hemming needed.",
     {"height_in_display": "64"}),
    ("height_plain_dquote_11", "Tall woman here, I'm 5\"11 and it fits.",
     {"height_in_display": "71"}),

    # Feet only + adjacent number: inches must NOT come from the weight. -> 79/91/88.
    ("height_feet_adjacent_5ft195", "Lightweight and elegant. I'm 5' 195 I got a 2xl.",
     {"height_in_display": "60"}),
    ("height_feet_adjacent_6feet198", "I'm 6feet 198lbs and ordered an X-Large.",
     {"height_in_display": "72", "weight_lbs_display": "198"}),
    ("height_feet_adjacent_6ft160", "I'm 6ft 160 pounds and a medium 37inch inseam is perfect!",
     {"height_in_display": "72", "weight_lbs_display": "160"}),
    ("height_feet_adjacent_5ft230", "I’m 5ft 230lbs and it fit well.",
     {"height_in_display": "60", "weight_lbs_display": "230"}),
    ("height_feet_adjacent_5foot190", "I am about 170 lbs... I'm 5 foot 190lbs and got an XL.",
     {"height_in_display": "60"}),

    # Inches >= 12 are not real inches: keep feet, drop the bogus inches. -> 90/95.
    ("height_inches_ge12_ft30", "I am 5 ft 30 23 34 and got xxs. Height: 5'0\". Weight: 100 lbs.",
     {"height_in_display": "60", "weight_lbs_display": "100"}),
    ("height_inches_ge12_535", "I’m 5’35”, 121.25lbs, with 37.40” hips.",
     {"height_in_display": "60"}),

    # Fractional inches written tight: 5'61/2" = 5'6.5" (66.5). Was -> 121.
    ("height_fraction_612", "I’m 5’61/2” and 132lbs and it’s tight in my arms.",
     {"height_in_display": "66.5", "weight_lbs_display": "132"}),
    ("height_fraction_612_nomark", "Height 5’61/2 weight 130 lbs, size 6 Long.",
     {"height_in_display": "66.5", "weight_lbs_display": "130"}),

    # Decimal feet used as feet+inches: 5.4ft = 5'4" (64). Was -> 48/24.
    ("height_decimal_54ft", "I am 5.4’ , 126 pounds, 36C.",
     {"height_in_display": "64", "weight_lbs_display": "126"}),
    ("height_decimal_52ft", "I’m a UK 10-12 and 5.2ft. I got a medium.",
     {"height_in_display": "62"}),
    ("height_decimal_54ft_lbsfirst", "I'm 146.5 lb ,5.4ft and it fit.",
     {"height_in_display": "64", "weight_lbs_display": "146.5"}),

    # Space between feet and inch digit before the mark: 5 3' = 5'3" (63). -> 36.
    ("height_space_53", "I am 5 3’ and 135 pounds I ordered a size 4.",
     {"height_in_display": "63", "weight_lbs_display": "135"}),

    # ft. with a period before inches: 4 ft. 9 in = 57. Was -> 48.
    ("height_ft_period", "She is 4 ft. 9 in, 70 lbs with a 22 in waist.",
     {"height_in_display": "57", "weight_lbs_display": "70"}),

    # A trailing-apostrophe inch measurement must not be read as feet. -> 48/84.
    ("height_waist_apostrophe", "my waist is like 24’ and hips 34.",
     {"height_in_display": ""}),
    ("height_jeans_size_apostrophe", "I originally got the 27’s, then the 28’s.",
     {"height_in_display": ""}),

    # Weight change with a hedge word between the verb and the number. -> 50/60.
    ("weight_lost_over", "I recently lost over 50 pounds. I needed new suits. I am 5'4\".",
     {"weight_lbs_display": "", "height_in_display": "64"}),
    ("weight_gained_parens", "I'm 5'10\" and 195 lbs. I’ve gained so much weight (60lbs).",
     {"weight_lbs_display": "195", "height_in_display": "70"}),
    ("weight_gained_over", "I gained over 50lbs during pregnancy (started around 110lbs).",
     {"weight_lbs_display": "110"}),

    # Non-body lifting context is not a body weight. -> 400.
    ("weight_leg_press", "thighs that can leg press 400lbs but still look not great. I'm 5'0\".",
     {"weight_lbs_display": "", "height_in_display": "60"}),

    # --- Must stay correct: real heavy adults / children / normal forms ----
    ("preserve_355", "I am 5’3” and weigh 355 pounds. I bought a 6x.",
     {"height_in_display": "63", "weight_lbs_display": "355"}),
    ("preserve_child_45", "Height: 4'5\". Weight: 100 lbs. Size purchased: xxs.",
     {"height_in_display": "53", "weight_lbs_display": "100"}),
    ("preserve_6ft360", "I'm 360 pounds and I'm 6 ft tall.",
     {"height_in_display": "72", "weight_lbs_display": "360"}),
    ("preserve_normal_57", "I'm 5'7\" and 145 lbs, medium fit me well.",
     {"height_in_display": "67", "weight_lbs_display": "145"}),
    ("preserve_normal_511", "I'm 5'11\" 170 lbs and the large was perfect.",
     {"height_in_display": "71", "weight_lbs_display": "170"}),
    ("preserve_normal_6ft", "I'm 6 ft, 200 lbs and got an XL.",
     {"height_in_display": "72", "weight_lbs_display": "200"}),
    ("preserve_normal_5foot5", "I am 5 foot 5 and 130 pounds.",
     {"height_in_display": "65", "weight_lbs_display": "130"}),
]


def main() -> int:
    failures = []
    for label, comment, expected in CASES:
        result = extract_measurements(comment)
        for field, want in expected.items():
            got = result.get(field, "")
            if got != want:
                failures.append(f"  [{label}] {field}: expected {want!r}, got {got!r}")
    if failures:
        print(f"FAILED {len(failures)} assertion(s):")
        print("\n".join(failures))
        return 1
    print(f"All extract_measurements tests passed ({len(CASES)} cases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
