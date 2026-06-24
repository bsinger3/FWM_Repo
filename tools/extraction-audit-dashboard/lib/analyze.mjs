// Deterministic analysis of a review comment vs. the measurements we extracted.
//
// This module is the single source of truth for:
//   - which measurement TYPES we recognize (height, weight, waist, hips, bust,
//     bra band, cup, inseam, age, pregnancy weeks),
//   - how a comment is tokenized into colour-coded segments for the dashboard,
//   - a "suspicion" score that floats likely-bad extractions to the top.
//
// When the human flags rows whose extraction is wrong, the new deterministic
// regex tests we add should live alongside MEASUREMENT_KEYWORDS / the token
// patterns here so the dashboard highlighting and the extractor stay in lockstep.

// Measurement keyword phrases. Each maps to the canonical measurement type so we
// can tell the reviewer "the comment mentions a bra size but nothing was
// extracted for it". Order matters: longer / more specific phrases first.
export const MEASUREMENT_KEYWORDS = [
  { type: "pregnancy", re: /\b(?:weeks?|wks?)\s+(?:pregnant|along)\b/gi },
  { type: "pregnancy", re: /\b(?:months?\s+pregnant|postpartum|post[-\s]?partum|pre[-\s]?pregnancy)\b/gi },
  { type: "pregnancy", re: /\bpregnan(?:t|cy)\b/gi },
  { type: "braband", re: /\b(?:under\s*bust|underbust|under\s*band|band\s*size|rib\s*cage|ribcage)\b/gi },
  { type: "bust", re: /\b(?:bust|chest)\b/gi },
  { type: "cup", re: /\bcups?\b/gi },
  { type: "waist", re: /\bwaists?\b/gi },
  { type: "hips", re: /\b(?:hips?|hip\s*\/\s*butt)\b/gi },
  { type: "inseam", re: /\binseams?\b/gi },
  { type: "height", re: /\b(?:height|tall)\b/gi },
  { type: "weight", re: /\b(?:weigh(?:t|s|ed|ing)?)\b/gi },
  { type: "age", re: /\b(?:age|years?\s*old|yrs?\s*old|y\/o|yo)\b/gi },
  { type: "unit", re: /\b(?:lbs?|pounds?|kgs?|kilograms?|cm|centimet(?:er|re)s?)\b/gi },
];

// Numeric tokens, most-specific first so e.g. a bra size or a height pair is one
// token rather than two loose numbers.
const NUMERIC_PATTERNS = [
  // Bra size: 32B, 34DD, 36 DDD/F
  { kind: "bra", re: /\b(2[02468]|3[02468]|4[02468]|5[024])\s*(AAA|AA|DDD\/?[EF]?|DD\/?E?|[A-K])\b/g },
  // Height: 5'7", 5 ft 7 in, 5'7, 5’7”
  {
    kind: "height",
    re: /\b([3-7])\s*(?:ft|feet|foot|['’])\s*(\d{1,2}(?:\.\d+)?)?\s*(?:in|inch|inches|["”'’])?/g,
  },
  // Number + fraction (36 1/2) or decimal, optionally followed by a unit/inch mark
  { kind: "num", re: /\b(\d{1,3}(?:\.\d+)?)(?:\s+(\d)\/(\d))?\s*(?:["”]|in\b|inches\b|lbs?\b|kgs?\b|cm\b)?/g },
];

const round1 = (n) => Math.round(n * 10) / 10;

// Stable id derived from the comment TEXT, so the same review comment (which
// recurs across many image rows) is one auditable unit and one flag. Reviewer
// flags key off this, not the row.
export function commentId(comment) {
  const norm = String(comment || "").replace(/\s+/g, " ").trim().toLowerCase();
  if (!norm) return "";
  let h = 0x811c9dc5;
  for (let i = 0; i < norm.length; i += 1) {
    h ^= norm.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return "c_" + (h >>> 0).toString(16).padStart(8, "0");
}

// Build the set of numeric values we actually captured into structured fields,
// so a comment number can be classified captured vs. missed.
function buildCapturedValues(extracted) {
  const captured = new Set();
  const heightPairs = [];
  const add = (v) => {
    const n = Number(v);
    if (Number.isFinite(n) && n > 0) captured.add(round1(n));
  };
  // Extracted values can be ranges or carry units ("150-153 lb", "36 1/2 in").
  // Capture every number present so each one matches the comment.
  const addAll = (v) => {
    const s = String(v ?? "");
    for (const m of s.matchAll(/\d+(?:\.\d+)?/g)) add(m[0]);
  };
  addAll(extracted.weightLbs);
  addAll(extracted.waistIn);
  addAll(extracted.hipsIn);
  addAll(extracted.bustIn);
  addAll(extracted.braBandIn);
  addAll(extracted.inseamIn);
  addAll(extracted.ageYears);
  addAll(extracted.weeksPregnant);
  if (extracted.heightIn) {
    const h = Number(String(extracted.heightIn).match(/\d+(?:\.\d+)?/)?.[0]);
    if (Number.isFinite(h)) {
      add(h);
      const ft = Math.floor(h / 12);
      const inch = Math.round(h - ft * 12);
      heightPairs.push({ ft, inch, total: h });
    }
  }
  if (extracted.cupSize) {
    const band = String(extracted.cupSize).match(/\d{2}/);
    if (band) add(band[0]);
  }
  return { captured, heightPairs };
}

function valueCaptured(value, captured) {
  const v = round1(value);
  if (captured.has(v)) return true;
  for (const c of captured) {
    if (Math.abs(c - v) <= 0.6) return true;
  }
  return false;
}

// Returns ordered, non-overlapping segments describing the comment for rendering.
// Each segment: { text, type } where type is one of:
//   plain | num-captured | num-missed | kw-<measurementtype>
export function analyzeComment(comment, extracted) {
  const text = String(comment || "");
  if (!text) {
    return { segments: [], numbers: [], suspicion: 0, mentionedTypes: [] };
  }
  const { captured, heightPairs } = buildCapturedValues(extracted);
  const marks = []; // {start, end, type, value?}

  // Numeric tokens
  for (const { kind, re } of NUMERIC_PATTERNS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m[0].trim() === "") {
        re.lastIndex += 1;
        continue;
      }
      const start = m.index + (m[0].length - m[0].trimStart().length);
      const end = m.index + m[0].trimEnd().length;
      let isCaptured = false;
      let value = null;
      if (kind === "bra") {
        value = Number(m[1]);
        isCaptured = valueCaptured(value, captured);
      } else if (kind === "height") {
        const ft = Number(m[1]);
        const inch = m[2] != null ? Number(m[2]) : 0;
        value = ft * 12 + inch;
        isCaptured = heightPairs.some(
          (p) => Math.abs(p.total - value) <= 1.5 || (p.ft === ft && Math.abs(p.inch - inch) <= 1),
        );
      } else {
        let v = Number(m[1]);
        if (m[2] && m[3]) v += Number(m[2]) / Number(m[3]);
        value = v;
        isCaptured = valueCaptured(value, captured);
      }
      marks.push({ start, end, type: isCaptured ? "num-captured" : "num-missed", value });
    }
  }

  // Keyword phrases
  const mentionedTypes = new Set();
  for (const { type, re } of MEASUREMENT_KEYWORDS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      mentionedTypes.add(type);
      marks.push({ start: m.index, end: m.index + m[0].length, type: `kw-${type}` });
    }
  }

  // Resolve overlaps: numeric marks win over keyword marks; earlier/larger wins ties.
  marks.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
  const priority = (mark) => (mark.type.startsWith("num") ? 2 : 1);
  const kept = [];
  let lastEnd = 0;
  for (const mark of marks) {
    if (mark.start < lastEnd) {
      // overlaps a kept mark; keep the higher-priority / earlier one already placed
      const prev = kept[kept.length - 1];
      if (prev && priority(mark) > priority(prev) && mark.start <= prev.start) {
        kept[kept.length - 1] = mark;
        lastEnd = mark.end;
      }
      continue;
    }
    kept.push(mark);
    lastEnd = mark.end;
  }

  // Build segments
  const segments = [];
  let cursor = 0;
  for (const mark of kept) {
    if (mark.start > cursor) segments.push({ text: text.slice(cursor, mark.start), type: "plain" });
    segments.push({ text: text.slice(mark.start, mark.end), type: mark.type });
    cursor = mark.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), type: "plain" });

  const numbers = kept.filter((k) => k.type.startsWith("num"));
  const missed = numbers.filter((k) => k.type === "num-missed").length;
  const anyCaptured = numbers.some((k) => k.type === "num-captured");
  // Suspicion: missed numbers are the core signal. A comment that mentions a
  // measurement type with a number we never captured is the strongest case.
  let suspicion = missed * 2;
  if (missed > 0 && mentionedTypes.size > 0) suspicion += 3;
  if (missed > 0 && anyCaptured) suspicion += 1; // partial extraction
  return {
    segments,
    numbers: numbers.map((n) => ({ value: n.value, captured: n.type === "num-captured" })),
    suspicion,
    mentionedTypes: [...mentionedTypes],
  };
}

// A row is worth showing only if there's something to compare against.
export function isCheckable(analysis, extracted) {
  if (analysis.numbers.length > 0) return true;
  if (analysis.mentionedTypes.length > 0) return true;
  return Object.values(extracted || {}).some((v) => String(v ?? "").trim() !== "");
}
