#!/usr/bin/env node

import assert from "node:assert/strict";
import { parseWeeksPregnant, PREGNANCY_PARSE_VERSION } from "./lib/pregnancy-parser.mjs";

const cases = [
  ["I am 20 weeks pregnant and ordered a medium.", 20, "20 weeks pregnant"],
  ["Currently 20 wks pregnant.", 20, "20 wks pregnant"],
  ["I was 20 weeks along here.", 20, "20 weeks along"],
  ["1 month pregnant and this fit.", 4, "1 month pregnant"],
  ["2 months pregnant and this fit.", 9, "2 months pregnant"],
  ["3 months pregnant and this fit.", 13, "3 months pregnant"],
  ["7 months pregnant and this fit.", 30, "7 months pregnant"],
  ["I am 22 weeks pregnant, basically 5 months pregnant.", 22, "22 weeks pregnant"],
  ["20 weeks postpartum and still wearing it.", null, null],
  ["I bought my pre-pregnancy size.", null, null],
  ["This is bump friendly but no timing given.", null, null],
];

for (const [text, expectedWeeks, expectedEvidence] of cases) {
  const actual = parseWeeksPregnant(text);
  assert.equal(actual.weeks_pregnant, expectedWeeks, text);
  assert.equal(actual.pregnancy_evidence, expectedEvidence, text);
}

console.log(`Pregnancy parser tests passed (${cases.length} cases, ${PREGNANCY_PARSE_VERSION}).`);
