import csv
import html
import random
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
RAW_INPUT_DIR = PIPELINE_ROOT / "data" / "step_1_raw_scraping_data"
DOCS_DIR = PIPELINE_ROOT / "docs"
OUTPUT_DIR = (
    PIPELINE_ROOT
    / "data"
    / "step_2_standardization_and_text_extraction"
    / "pre_approval_normalized_outputs"
)
FULL_OUT = OUTPUT_DIR / "normalized_amazon_data.csv"
PREVIEW_OUT = OUTPUT_DIR / "normalized_amazon_data_preview_1000.csv"
VIGLINK_KEY = "2aba39b05bc3c8c85f46f6f98c7c728d"
META_COLUMNS_TO_SKIP = {"content_type", "bytes", "width", "height", "hash_md5"}


def load_target_columns():
    with (DOCS_DIR / "images_intake_sample - contraints.csv").open(
        newline="", encoding="utf-8-sig"
    ) as f:
        return [
            row["column_name"]
            for row in csv.DictReader(f)
            if row["column_name"] not in META_COLUMNS_TO_SKIP
        ]


TARGET_COLUMNS = load_target_columns()


def load_clothing_labels():
    with (DOCS_DIR / "clothingtypes.csv").open(newline="", encoding="utf-8-sig") as f:
        labels = [r["Unique clothing_types.label values"].strip().lower() for r in csv.DictReader(f)]
    return set(labels)


ALLOWED_CLOTHING = load_clothing_labels()


def load_measurement_patterns():
    rows = []
    with (DOCS_DIR / "measurement_regex_patterns.csv").open(
        newline="", encoding="utf-8-sig"
    ) as f:
        for row in csv.DictReader(f):
            field = row["measurement_field"].strip()
            if "," in field:
                raise ValueError(f"multi-field regex row remains: {row}")
            row["_compiled"] = re.compile(row["regex_expression"])
            rows.append(row)
    order = {
        "height_fractional_inches_without_space": 0,
        "height_doubled_quote_escape_feet_marker": 1,
        "height_double_quote_feet_marker": 2,
        "height_comma_between_feet_inches": 3,
        "height_decimal_feet_inches_near_weight": 4,
        "height_ft_dot_in": 5,
        "height_compact_two_digit_after_im": 6,
        "height_inches_explicit": 7,
        "height_word_five": 8,
        "height_feet_inches_numeric": 20,
        "weight_loss_exclusion": -10,
        "weight_weigh_no_unit": 0,
        "waist_labeled_fraction": 0,
        "waist_high_before_low_hips": 1,
        "waist_measurement_of": 2,
        "waist_labeled": 20,
        "hips_low_after_high_waist": 0,
        "hips_labeled": 20,
        "bust_number_before_label_bare": 0,
        "bust_labeled_about": 1,
        "cup_letter_after_cup_word_before_bra": 0,
        "cup_before_band_bra": 1,
        "band_after_cup_bra": 0,
    }
    rows.sort(key=lambda r: (r["measurement_field"], order.get(r["pattern_name"], 10)))
    return rows


MEASUREMENT_PATTERNS = load_measurement_patterns()


IMAGE_RE = re.compile(r"https?://[^\s\"'<>]+?(?:\.jpg|\.jpeg|\.png|\.webp)(?:\?[^\s\"'<>]*)?", re.I)
AMAZON_URL_RE = re.compile(r"https?://(?:www\.)?amazon\.com/[^\s\"'<>]+", re.I)
ASIN_PATTERNS = [
    re.compile(r"/dp/([A-Z0-9]{10})(?:[/?#]|$)", re.I),
    re.compile(r"/product-reviews/([A-Z0-9]{10})(?:[/?#]|$)", re.I),
    re.compile(r"[?&]ASIN=([A-Z0-9]{10})(?:[&#]|$)", re.I),
]
PROFILE_RE = re.compile(r"https?://(?:www\.)?amazon\.com/gp/profile/[^\s\"'<>]+", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
JS_JUNK_RE = re.compile(
    r"\b(?:data-action|a-popover|a-modal|popover|javascript|function\s*\(|var\s+|const\s+|if\s*\(\s*window\.ue|clickstreamNexusMetricsConfig|clientPrefix)\b",
    re.I,
)
HELPFUL_RE = re.compile(r"\b(?:\d+\s+people?\s+found\s+this\s+helpful|one\s+person\s+found\s+this\s+helpful|helpful|report|verified purchase)\b", re.I)
DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
    re.I,
)


def values_from_row(row):
    return [str(v or "") for v in row.values()]


def compact_space(text):
    text = html.unescape(str(text or ""))
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_measurements(text):
    text = html.unescape(str(text or ""))
    return (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
        .replace("”", '"')
        .replace("“", '"')
        .replace("″", '"')
        .replace("′", "'")
    )


def clean_comment_piece(text):
    text = html.unescape(str(text or ""))
    if JS_JUNK_RE.search(text):
        return ""
    text = HTML_TAG_RE.sub(" ", text)
    text = AMAZON_URL_RE.sub(" ", text)
    text = IMAGE_RE.sub(" ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"&nbsp;?", " ", text, flags=re.I)
    text = re.sub(r"\b(?:read more|show less|customer image|customer review)\b", " ", text, flags=re.I)
    text = HELPFUL_RE.sub(" ", text)
    text = strip_structured_variant_tail(text)
    return compact_space(text)


def strip_structured_variant_tail(text):
    text = str(text or "")
    # Remove scraped variant metadata when it is appended to otherwise useful text.
    marker = re.search(r"\b(?:special\s+size(?:\s+type)?|fit\s+type|color|size)\s*:", text, re.I)
    if not marker:
        return text
    tail = text[marker.start() :]
    tail_low = tail.lower()
    if (
        ("color:" in tail_low and "size:" in tail_low)
        or "special size" in tail_low
        or "fit waist size" in tail_low
        or "fit type:" in tail_low
    ) and len(tail) <= 220:
        return text[: marker.start()]
    return text


def is_junk_comment(text):
    if not text:
        return True
    low = text.lower()
    if len(text) < 3:
        return True
    if HTML_TAG_RE.search(text) or JS_JUNK_RE.search(text):
        return True
    if "amazon.com" in low or "m.media-amazon.com" in low or "images-na.ssl-images-amazon.com" in low:
        return True
    if low.startswith("amazon.com: customer reviews"):
        return True
    if re.fullmatch(r"(?:special\s+size(?:\s+type)?|fit\s+type|color|size)\s*:.*", low):
        return True
    if (("color:" in low and "size:" in low) or "special size" in low or "fit type:" in low) and len(text) < 140:
        return True
    if low in {"verified purchase", "read more", "helpful"}:
        return True
    return False


def dedupe_repeated_comment(text):
    text = compact_space(text)
    if not text:
        return ""
    half = len(text) // 2
    if len(text) > 80 and text[:half].strip() == text[half:].strip():
        return text[:half].strip()
    # Remove adjacent duplicated sentences/fragments conservatively.
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for part in parts:
        if not out or part.strip().lower() != out[-1].strip().lower():
            out.append(part)
    return " ".join(out).strip()


def choose_comment(row):
    title = clean_comment_piece(row.get("title") or row.get("Title") or "")
    body_candidates = []
    for key in ("body", "View1", "review_body", "Body"):
        v = clean_comment_piece(row.get(key) or "")
        if v and not is_junk_comment(v):
            body_candidates.append(v)
    if not body_candidates:
        for k, v in row.items():
            k_low = str(k).lower()
            if any(skip in k_low for skip in ("url", "avatar", "html", "image", "page_title", "aiconalt")):
                continue
            cleaned = clean_comment_piece(v)
            if len(cleaned) >= 60 and not is_junk_comment(cleaned):
                body_candidates.append(cleaned)
    body = max(body_candidates, key=len) if body_candidates else ""
    parts = []
    if title and not is_junk_comment(title) and not is_probable_product_title(title) and len(title) < 180 and title.lower() not in body.lower():
        parts.append(title)
    if body:
        parts.append(body)
    return dedupe_repeated_comment(" ".join(parts))


def is_probable_product_title(text):
    text = compact_space(text)
    low = text.lower()
    if len(text) < 75:
        return False
    clothing_terms = (
        "women",
        "womens",
        "women's",
        "jeans",
        "pants",
        "dress",
        "tankini",
        "swimsuit",
        "leggings",
        "joggers",
        "denim",
        "stretch",
        "waisted",
        "sleeve",
        "pockets",
    )
    product_phrases = (
        " for women",
        " women's ",
        " womens ",
        " high waisted",
        " wide leg",
        " bootcut",
        " straight leg",
        " tummy control",
        " cocktail dress",
        " yoga pants",
    )
    return any(t in low for t in clothing_terms) and any(p in low for p in product_phrases)


def image_urls_from_row(row):
    urls = []
    for value in values_from_row(row):
        for url in IMAGE_RE.findall(value):
            low = url.lower()
            if any(bad in low for bad in ("amazon-avatars", "grey-pixel", "_sx48", "sprite", "transparent-pixel")):
                continue
            if "/images/i/" not in low and "m.media-amazon.com/images/" not in low and "images-na.ssl-images-amazon.com/images/i/" not in low:
                continue
            urls.append(normalize_image_url(url))
    return unique_keep_order(urls)


def normalize_image_url(url):
    url = html.unescape(url).strip().rstrip(".,);]")
    # Convert small Amazon thumbnails to their base image where the URL follows the usual pattern.
    url = re.sub(r"\._[A-Z0-9_,]+_\.(jpg|jpeg|png|webp)$", r".\1", url, flags=re.I)
    url = re.sub(r"\._[A-Z0-9_,]+(?=\.(jpg|jpeg|png|webp)$)", "", url, flags=re.I)
    return url


def unique_keep_order(seq):
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def asin_from_text(text):
    for pat in ASIN_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(1).upper()
    return ""


def product_url_from_row(row):
    values = values_from_row(row)
    # Prefer explicit product URL columns.
    for key in ("product_url", "URL", "Original_URL", "asizemini_URL", "Title_URL"):
        v = row.get(key) or ""
        asin = asin_from_text(v)
        if asin:
            return f"https://www.amazon.com/dp/{asin}/ref=cm_cr_arp_d_product_top?ie=UTF8"
    for value in values:
        for url in AMAZON_URL_RE.findall(value):
            asin = asin_from_text(url)
            if asin:
                return f"https://www.amazon.com/dp/{asin}/ref=cm_cr_arp_d_product_top?ie=UTF8"
    return ""


def monetize(product_url):
    if not product_url:
        return ""
    return f"http://redirect.viglink.com?key={VIGLINK_KEY}&u={quote(product_url, safe='')}"


def parse_review_date(row):
    candidates = [
        row.get("DateReviewed(Generated)") or "",
        row.get("View") or "",
        row.get("date_review_submitted_raw") or "",
    ]
    for candidate in candidates + values_from_row(row):
        m = DATE_RE.search(candidate or "")
        if not m:
            continue
        raw = m.group(0)
        try:
            iso = datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            iso = ""
        return raw, iso
    return "", ""


def clean_size_color_value(value):
    value = compact_space(value)
    value = re.sub(r"^(?:size|color)\s*:\s*", "", value, flags=re.I).strip()
    value = value.strip(" -|,:;")
    if not value:
        return ""
    low = value.lower()
    bad = ("verified purchase", "amazon vine", "customer review", "reviewed in", "http", "<", "helpful", "i am ", "i'm ")
    if any(x in low for x in bad):
        return ""
    if len(value) > 55:
        return ""
    return low


def parse_size_color(row):
    texts = []
    for key in ("size_color", "asizemini", "SizeOrdered(generated)", "ColorOrdered(Generated)"):
        v = row.get(key) or ""
        if v:
            texts.append(v)
    for v in values_from_row(row):
        if "Size:" in v or "Color:" in v or "size:" in v or "color:" in v:
            texts.append(v)

    size = ""
    color = ""
    for text in texts:
        t = compact_space(text)
        if not size:
            m = re.search(r"size\s*:\s*(.*?)(?=\s*color\s*:|$)", t, re.I)
            if m:
                size = clean_size_color_value(m.group(1))
        if not color:
            m = re.search(r"color\s*:\s*(.*?)(?=\s*size\s*:|$)", t, re.I)
            if m:
                color = clean_size_color_value(m.group(1))
        if size and color:
            break
    return size, color


def clean_reviewer_name(name, title):
    name = compact_space(name)
    title = compact_space(title)
    if not name or len(name) > 80:
        return ""
    low = name.lower()
    if title and low == title.lower():
        return ""
    if any(x in low for x in ("http", "verified purchase", "reviewed in", "stars", "<", "amazon.com")):
        return ""
    if len(name.split()) > 6:
        return ""
    return name


def reviewer_profile(row):
    for key in ("aprofile_URL", "reviewer_profile_url"):
        v = row.get(key) or ""
        m = PROFILE_RE.search(v)
        if m:
            return m.group(0)
    for value in values_from_row(row):
        m = PROFILE_RE.search(value)
        if m:
            return m.group(0)
    return ""


def infer_clothing_type(filename, row):
    text = " ".join([filename] + values_from_row(row)).lower()
    rules = [
        ("jeans", ("jean", "denim")),
        ("pants", ("pants", "jogger", "trouser", "legging", "sweatpant")),
        ("leggings", ("legging",)),
        ("dress", ("dress", "cocktail", "gown")),
        ("gown", ("gown",)),
        ("skirt", ("skirt",)),
        ("jumpsuit", ("jumpsuit",)),
        ("romper", ("romper",)),
        ("overalls", ("overall",)),
        ("top", ("tankini", "tank top", "blouse", "shirt", "sweater", "tunic", "cami", "bralette", "bustier", "vest")),
        ("shirt", ("shirt", "t-shirt", "tee")),
        ("tank", ("tank",)),
        ("blouse", ("blouse",)),
        ("sweater", ("sweater",)),
        ("vest", ("vest",)),
        ("culottes", ("culottes",)),
    ]
    for label, words in rules:
        if label in ALLOWED_CLOTHING and any(w in text for w in words):
            return label
    return "other" if "other" in ALLOWED_CLOTHING else ""


def first_number(groups):
    for g in groups:
        if g not in (None, ""):
            return g
    return ""


def fmt_number(n):
    if n is None:
        return ""
    if abs(n - round(n)) < 0.001:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def valid_range(field, value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return False
    if field == "height_in_display":
        return 48 <= n <= 84
    if field in {"weight_lbs_display", "weight_display_display"}:
        return 70 <= n <= 400
    if field in {"waist_in", "hips_in_display", "bust_in_number_display"}:
        return 20 <= n <= 70
    if field == "inseam_inches_display":
        return 20 <= n <= 40
    if field == "age_years_display":
        return 13 <= n <= 100
    return True


def excluded_weight_spans(text):
    spans = []
    manual = re.compile(
        r"(?i)\b(?:lost|loss|down|gained|gain(?:ed)?|dropped|shed)\b.{0,25}?\b\d{1,3}(?:\.\d+)?\s*(?:lbs?|pounds?|#)\b"
    )
    for m in manual.finditer(text):
        spans.append(m.span())
    range_manual = re.compile(r"(?i)\b(?:about|around|approx\.?|approximately)?\s*\d{2,3}(?:\.\d+)?\s*(?:-|/|\bto\b)\s*\d{2,3}(?:\.\d+)?\b")
    for m in range_manual.finditer(text):
        spans.append(m.span())
    for row in MEASUREMENT_PATTERNS:
        if row["pattern_name"] == "weight_loss_exclusion":
            for m in row["_compiled"].finditer(text):
                spans.append(m.span())
    return spans


def overlaps(span, spans, pad=5):
    return any(span[0] < b + pad and span[1] > a - pad for a, b in spans)


def extract_height_value(pattern_name, m):
    groups = m.groups()
    try:
        if pattern_name == "height_inches_explicit":
            value = float(groups[0])
        elif pattern_name == "height_word_five":
            value = 60 + float(groups[0])
        elif pattern_name == "height_fractional_inches_without_space":
            feet = float(groups[0])
            whole = float(groups[1])
            numerator = float(groups[2])
            denominator = float(groups[3])
            if denominator == 0:
                return ""
            value = feet * 12 + whole + numerator / denominator
        else:
            feet = float(groups[0])
            inches = float(groups[1] or 0)
            if inches >= 12:
                return ""
            value = feet * 12 + inches
    except (TypeError, ValueError, IndexError):
        return ""
    if not valid_range("height_in_display", value):
        return ""
    return fmt_number(value)


def extract_measurements(comment):
    out = {}
    raw_out = {}
    text = normalize_for_measurements(comment)
    weight_exclusions = excluded_weight_spans(text)

    for row in MEASUREMENT_PATTERNS:
        field = row["measurement_field"]
        name = row["pattern_name"]
        if name == "weight_loss_exclusion":
            continue
        if field in out:
            continue
        for m in row["_compiled"].finditer(text):
            if field == "weight_lbs_display" and overlaps(m.span(), weight_exclusions, pad=12):
                continue
            if field == "weight_lbs_display" and is_weight_range_match(text, m):
                out.setdefault("weight_lbs_raw_issue", compact_space(expand_weight_range_raw(text, m)))
                continue
            if field == "weight_lbs_display" and third_person_measurement_context(text, m):
                continue
            if field == "height_in_display":
                value = extract_height_value(name, m)
            elif field == "cupsize_display":
                value = first_number(m.groups()).upper()
            elif name == "waist_labeled_fraction":
                value = fraction_value(m.groups())
            else:
                value = first_number(m.groups())
            value = (value or "").strip()
            if not value:
                continue
            if field != "cupsize_display" and field != "waist_raw_display" and not valid_range(field, value):
                continue
            out[field] = value
            raw_out[field] = compact_space(m.group(0))
            break

    if "height_in_display" in out:
        out["height_raw"] = raw_out.get("height_in_display", "")
    if "weight_lbs_display" in out:
        out["weight_display_display"] = out["weight_lbs_display"]
        out["weight_raw"] = raw_out.get("weight_lbs_display", "")
    if "waist_in" in out:
        out["waist_raw_display"] = raw_out.get("waist_in", out.get("waist_raw_display", ""))
    elif "waist_raw_display" in out:
        pass
    if "hips_in_display" in out:
        out["hips_raw"] = raw_out.get("hips_in_display", "")
    if "age_years_display" in out:
        out["age_raw"] = raw_out.get("age_years_display", "")
    return out


def fraction_value(groups):
    try:
        whole = float(groups[0])
        numerator = float(groups[1])
        denominator = float(groups[2])
        if denominator == 0:
            return ""
        return fmt_number(whole + numerator / denominator)
    except (TypeError, ValueError, IndexError):
        return ""


def is_weight_range_match(text, match):
    tail = text[match.end() : match.end() + 20]
    return bool(re.match(r"\s*(?:-|/|\bto\b)\s*\d{2,3}(?:\.\d+)?\b", tail, re.I))


def expand_weight_range_raw(text, match):
    tail = text[match.end() : match.end() + 20]
    m = re.match(r"\s*(?:-|/|\bto\b)\s*\d{2,3}(?:\.\d+)?\b", tail, re.I)
    if not m:
        return match.group(0)
    return match.group(0) + tail[: m.end()]


def third_person_measurement_context(text, match):
    prefix = text[max(0, match.start() - 40) : match.start()].lower()
    return bool(
        re.search(
            r"(?:\bshe\s+is\b|\bhe\s+is\b|\bmy\s+daughter\b|\bmy\s+sister\b|\bsister\s+in\s+law\b|\bsister-in-law\b).{0,35}$",
            prefix,
        )
    )


def empty_output_row():
    return {col: "" for col in TARGET_COLUMNS}


def normalize_source_file(path):
    produced = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            images = image_urls_from_row(row)
            if not images:
                continue
            product_url = product_url_from_row(row)
            if not product_url:
                continue
            review_date_raw, review_date = parse_review_date(row)
            user_comment = choose_comment(row)
            size, color = parse_size_color(row)
            reviewer_name = clean_reviewer_name(row.get("Name") or row.get("Author") or "", row.get("Title") or row.get("title") or "")
            profile_url = reviewer_profile(row)
            clothing_type = infer_clothing_type(path.name, row)
            measurements = extract_measurements(user_comment) if user_comment else {}
            for image_url in images:
                out = empty_output_row()
                out.update(
                    {
                        "original_url_display": image_url,
                        "product_page_url_display": product_url,
                        "monetized_product_url_display": monetize(product_url),
                        "user_comment": user_comment,
                        "date_review_submitted_raw": review_date_raw,
                        "review_date": review_date,
                        "source_site_display": "https://www.amazon.com/",
                        "reviewer_profile_url": profile_url,
                        "reviewer_name_raw": reviewer_name,
                        "size_display": size,
                        "color_display": color,
                        "color_canonical": "",
                        "clothing_type_id": clothing_type if clothing_type in ALLOWED_CLOTHING else "",
                    }
                )
                out.update(measurements)
                produced.append(out)
    return produced


def source_files():
    return [
        p
        for p in sorted(RAW_INPUT_DIR.glob("*.csv"))
        if "amazon" in p.name.lower() and not p.name.lower().startswith("normalized_")
    ]


def validate_rows(rows):
    bad_product = 0
    bad_monetized = 0
    bad_original = 0
    junk_comments = 0
    bad_clothing = 0
    for row in rows:
        image = row["original_url_display"].lower()
        product = row["product_page_url_display"].lower()
        if not ("/images/i/" in image or "m.media-amazon.com/images/" in image):
            bad_original += 1
        if product and ("/dp/" not in product or "/product-reviews/" in product or "m.media-amazon.com" in product or "/gp/customer-reviews/" in product):
            bad_product += 1
        if row["monetized_product_url_display"] != monetize(row["product_page_url_display"]):
            bad_monetized += 1
        if row["user_comment"] and is_junk_comment(row["user_comment"]):
            junk_comments += 1
        if row["clothing_type_id"] and row["clothing_type_id"] not in ALLOWED_CLOTHING:
            bad_clothing += 1
    return {
        "bad_original": bad_original,
        "bad_product": bad_product,
        "bad_monetized": bad_monetized,
        "junk_comments": junk_comments,
        "bad_clothing": bad_clothing,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = source_files()
    print("source_files")
    for p in files:
        print(" -", p.name)

    all_rows = []
    counts = {}
    for path in files:
        rows = normalize_source_file(path)
        counts[path.name] = len(rows)
        all_rows.extend(rows)
        print(path.name, len(rows))

    # De-dupe exact repeated image/product/comment rows while preserving separate images from the same review.
    deduped = []
    seen = set()
    for row in all_rows:
        key = (row["original_url_display"], row["product_page_url_display"], row["user_comment"], row["reviewer_profile_url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    checks = validate_rows(deduped)
    print("total_before_dedupe", len(all_rows))
    print("total_after_dedupe", len(deduped))
    print("checks", checks)
    if any(checks.values()):
        raise SystemExit(f"validation failed: {checks}")

    tmp_full = FULL_OUT.with_suffix(".csv.tmp")
    with tmp_full.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows(deduped)
    tmp_full.replace(FULL_OUT)

    rng = random.Random(20260407)
    preview_rows = rng.sample(deduped, min(1000, len(deduped)))
    tmp_preview = PREVIEW_OUT.with_suffix(".csv.tmp")
    with tmp_preview.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows(preview_rows)
    tmp_preview.replace(PREVIEW_OUT)

    filled = {}
    for col in TARGET_COLUMNS:
        filled[col] = sum(1 for r in deduped if r.get(col))
    for col in [
        "product_page_url_display",
        "monetized_product_url_display",
        "user_comment",
        "size_display",
        "color_display",
        "height_in_display",
        "weight_lbs_display",
        "waist_in",
        "hips_in_display",
        "inseam_inches_display",
        "age_years_display",
        "bust_in_number_display",
        "cupsize_display",
        "clothing_type_id",
    ]:
        print("filled", col, filled.get(col, 0))


if __name__ == "__main__":
    main()
