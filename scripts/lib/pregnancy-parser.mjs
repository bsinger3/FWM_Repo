export const PREGNANCY_PARSE_VERSION = "pregnancy_text_explicit_v1";

export function parseWeeksPregnant(comment) {
  const text = String(comment || "");
  if (/\bpostpartum\b|\bafter\s+baby\b|\bpre[-\s]?pregnancy\b/i.test(text)) {
    return { weeks_pregnant: null, pregnancy_evidence: null };
  }

  const weekMatch = text.match(/\b(\d{1,2})\s*(?:weeks?|wks?)\s+(?:pregnant|along)\b/i);
  if (weekMatch) {
    return { weeks_pregnant: Number(weekMatch[1]), pregnancy_evidence: weekMatch[0] };
  }

  const monthMatch = text.match(/\b(\d{1,2})\s*months?\s+pregnant\b/i);
  if (monthMatch) {
    return {
      weeks_pregnant: Math.floor(Number(monthMatch[1]) * 4.345 + 0.5),
      pregnancy_evidence: monthMatch[0],
    };
  }

  return { weeks_pregnant: null, pregnancy_evidence: null };
}
