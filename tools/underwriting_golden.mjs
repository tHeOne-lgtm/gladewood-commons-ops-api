// Produces tests/fixtures/underwriting_golden.json from the Hub's own formulas (tools/underwriting_reference.mjs).
// Run: node tools/underwriting_golden.mjs > tests/fixtures/underwriting_golden.json
import { S, uwInputs, uwReady, uwCalc, uwProject, uwChecks, UW_SCEN, uwScenario } from "./underwriting_reference.mjs";

const CASES = {
  lease_defaults: { privateRooms: 3, sharedRooms: 1, leaseCost: 1800, uw: {} },
  lease_overrides: { privateRooms: 4, sharedRooms: 2, leaseCost: 2400, utilities: 480, uw: {
    privRent: 900, sharedRent: 575, occ: 85, creditLoss: 3, otherIncome: 100, leaseEsc: 2, deposit: 3600,
    internet: 90, cleaning: 200, supplies: 40, insurance: 120, marketing: 60, repairsPct: 6, mgmtPct: 8,
    reservePerBed: 30, growth: 2.5, expGrowth: 3.5, furnishPerBed: 800, makeReady: 2500, setupCosts: 1200, reserveMonths: 3 } },
  buy_loan: { bedrooms: 4, salePrice: "$285,000", uw: { mode: "buy", downPct: 20, rate: 6.5, years: 30, closingPct: 2.5, taxAnnual: 2400, insAnnual: 1800 } },
  buy_zero_rate: { privateRooms: 2, uw: { mode: "buy", price: 120000, rate: 0, years: 15 } },
  bad_override_falls_back: { privateRooms: 2, leaseCost: 1500, uw: { privRent: "abc", occ: "", internet: "95" } },
  not_ready_no_rooms: { leaseCost: 1500, uw: {} },
  not_ready_no_lease: { privateRooms: 2, uw: {} },
  not_ready_no_price: { privateRooms: 2, uw: { mode: "buy" } },
};
const out = { settings: S.settings, cases: {} };
for (const [name, r] of Object.entries(CASES)) {
  const i = uwInputs(r), miss = uwReady(i), c = miss.length ? null : uwCalc(i);
  out.cases[name] = { record: r, inputs: i, missing: miss, calc: c,
    checks: c ? uwChecks(i, c) : null, project: c ? uwProject(i) : null,
    scenarios: c ? Object.fromEntries(UW_SCEN.map(s => [s.k, uwScenario(i, s)])) : null };
}
process.stdout.write(JSON.stringify(out, null, 1));
