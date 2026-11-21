// Reference copy of the Gladewood Prospect Hub underwriting formulas (artifact BH7nsdF1LXHVEEfSqasFAz,
// version 1792590720-21af, read 2026-11-21). Copied verbatim so app/underwriting.py can be checked against
// the page that Paul already uses. Run: node tools/underwriting_reference.mjs > tests/fixtures/underwriting_golden.json
const S = { settings: {
market: "Chattanooga, TN", tourLink: "",
sharedMin: 550, sharedMax: 650, privateMin: 850, privateMax: 1100,
planShared: 600, planPrivate: 950, incomeMultiple: 2,
targetOcc: 90, utilitiesPerBed: 60, internet: 80, cleaning: 150, supplies: 50, furnishPerBed: 700, amortMonths: 12,
uwMinCoverage: 1.3, uwMaxBreakeven: 75, uwMinCash: 300, uwMinCoC: 15, uwMinDSCR: 1.25, uwMinCap: 6,
uwRepairsPct: 5, uwReservePerBed: 25, uwInsurance: 100, uwMarketing: 50, uwCreditLoss: 2, uwGrowth: 3, uwReserveMonths: 2,
} };
const num = v => { const n = parseFloat(String(v ?? "").replace(/[$,\s]/g, "")); return isFinite(n) ? n : null; };
const money = v => { const n = num(v); return n == null ? "—" : (n < 0 ? "-$" : "$") + Math.abs(Math.round(n)).toLocaleString("en-US"); };
function uwInputs(r, st = S.settings) {
  const u = r.uw || {};
  let priv = num(r.privateRooms), shared = num(r.sharedRooms);
  if (priv == null && shared == null) priv = num(r.bedrooms);
  priv = priv || 0; shared = shared || 0;
  const beds = priv + shared * 2;
  const g = (k, d) => (u[k] != null && u[k] !== "" && isFinite(+u[k])) ? +u[k] : d;
  const lease = num(r.leaseCost) ?? 0;
  return {
    mode: u.mode === "buy" ? "buy" : "lease", priv, shared, beds,
    privRent: g("privRent", st.planPrivate), sharedRent: g("sharedRent", st.planShared),
    occ: Math.max(0, Math.min(100, g("occ", st.targetOcc))), creditLoss: g("creditLoss", st.uwCreditLoss), otherIncome: g("otherIncome", 0),
    lease, leaseEsc: g("leaseEsc", 3), deposit: g("deposit", lease),
    util: num(r.utilities) ?? beds * st.utilitiesPerBed,
    internet: g("internet", st.internet), cleaning: g("cleaning", st.cleaning), supplies: g("supplies", st.supplies),
    insurance: g("insurance", st.uwInsurance), marketing: g("marketing", st.uwMarketing),
    repairsPct: g("repairsPct", st.uwRepairsPct), mgmtPct: g("mgmtPct", 0), reservePerBed: g("reservePerBed", st.uwReservePerBed),
    growth: g("growth", st.uwGrowth), expGrowth: g("expGrowth", 3),
    furnishPerBed: g("furnishPerBed", st.furnishPerBed), makeReady: g("makeReady", 0), setupCosts: g("setupCosts", 0), reserveMonths: g("reserveMonths", st.uwReserveMonths),
    price: g("price", num(r.salePrice) ?? 0), downPct: g("downPct", 25), rate: g("rate", 7), years: Math.max(1, g("years", 30)), closingPct: g("closingPct", 3),
    taxAnnual: g("taxAnnual", 0), insAnnual: g("insAnnual", 0)
  };
}
function uwReady(i) {
  const miss = [];
  if (i.beds === 0) miss.push("planned rooms or bedrooms");
  if (i.mode === "lease" && !i.lease) miss.push("monthly lease cost");
  if (i.mode === "buy" && !i.price) miss.push("purchase price");
  return miss;
}
function uwCalc(i, adj = {}) {
  const occ = Math.max(0, Math.min(100, adj.occ ?? i.occ)) / 100, rm = adj.rentMult ?? 1, buy = i.mode === "buy";
  const gpr = (i.priv * i.privRent + i.shared * 2 * i.sharedRent) * rm;
  const rented = gpr * occ, vacancy = gpr - rented, credit = rented * i.creditLoss / 100;
  const egi = rented - credit + i.otherIncome;
  const insurance = buy ? i.insAnnual / 12 : i.insurance, tax = buy ? i.taxAnnual / 12 : 0, reserve = i.reservePerBed * i.beds;
  const fixed = i.util + i.internet + i.cleaning + i.supplies + insurance + i.marketing + reserve + tax;
  const pct = (i.repairsPct + i.mgmtPct) / 100;
  const repairs = egi * i.repairsPct / 100, mgmt = egi * i.mgmtPct / 100;
  const opex = fixed + repairs + mgmt;
  const noi = egi - opex;
  const loan = buy ? i.price * (1 - i.downPct / 100) : 0, mr = i.rate / 1200, n = i.years * 12;
  const pmt = buy && loan > 0 ? (mr > 0 ? loan * mr / (1 - Math.pow(1 + mr, -n)) : loan / n) : 0;
  const fin = buy ? pmt : i.lease;
  const cash = noi - fin;
  const furnish = i.beds * i.furnishPerBed;
  const reserves = i.reserveMonths * (fixed + fin);
  const upfront = (buy ? i.price * i.downPct / 100 + i.price * i.closingPct / 100 : i.deposit) + furnish + i.makeReady + i.setupCosts + reserves;
  const coverage = fin > 0 ? noi / fin : null;
  const coc = upfront > 0 ? cash * 12 / upfront : null;
  const payback = cash > 0 && upfront > 0 ? upfront / cash : null;
  const cap = buy && i.price > 0 ? noi * 12 / i.price : null;
  const grm = buy && gpr > 0 ? i.price / (gpr * 12) : null;
  const egiStar = (fixed + fin) / (1 - pct);
  const breakeven = gpr > 0 ? ((egiStar - i.otherIncome) / (1 - i.creditLoss / 100)) / gpr : null;
  const beds = i.beds || 1;
  return { gpr, vacancy, credit, other: i.otherIncome, egi, util: i.util, internet: i.internet, cleaning: i.cleaning, supplies: i.supplies, insurance, marketing: i.marketing, repairs, mgmt, reserve, tax, fixed, opex, noi, loan, pmt, fin, cash, annual: cash * 12, furnish, reserves, upfront, coverage, coc, payback, cap, grm, breakeven, perBedRevenue: egi / beds, perBedCost: (opex + fin) / beds, perBedProfit: cash / beds, occ: occ * 100, buy };
}
function uwProject(i, years = 5) {
  const base = uwCalc(i), rows = []; let cum = -base.upfront;
  for (let y = 1; y <= years; y++) {
    const gf = Math.pow(1 + i.growth / 100, y - 1), ef = Math.pow(1 + i.expGrowth / 100, y - 1);
    const egi = base.egi * gf, fixed = base.fixed * ef, noi = egi - fixed - egi * (i.repairsPct + i.mgmtPct) / 100;
    const fin = i.mode === "buy" ? base.pmt : i.lease * Math.pow(1 + i.leaseEsc / 100, y - 1);
    const cf = (noi - fin) * 12; cum += cf; rows.push({ y, egi: egi * 12, noi: noi * 12, fin: fin * 12, cf, cum });
  }
  return rows;
}
function uwChecks(i, c, st = S.settings) {
  const list = [];
  const buy = i.mode === "buy";
  list.push({ label: buy ? "Debt service coverage" : "Rent coverage", value: c.coverage == null ? "—" : c.coverage.toFixed(2) + "×", target: "at least " + (buy ? st.uwMinDSCR : st.uwMinCoverage).toFixed(2) + "×", ok: c.coverage != null && c.coverage >= (buy ? st.uwMinDSCR : st.uwMinCoverage) });
  list.push({ label: "Break-even occupancy", value: c.breakeven == null ? "—" : Math.round(c.breakeven * 100) + "%", target: "at most " + st.uwMaxBreakeven + "%", ok: c.breakeven != null && c.breakeven * 100 <= st.uwMaxBreakeven });
  list.push({ label: "Cash flow per month", value: money(c.cash), target: "at least " + money(st.uwMinCash), ok: c.cash >= st.uwMinCash });
  list.push({ label: "Cash-on-cash return", value: c.coc == null ? "—" : Math.round(c.coc * 100) + "%", target: "at least " + st.uwMinCoC + "%", ok: c.coc != null && c.coc * 100 >= st.uwMinCoC });
  if (buy) list.push({ label: "Cap rate", value: c.cap == null ? "—" : (c.cap * 100).toFixed(1) + "%", target: "at least " + st.uwMinCap + "%", ok: c.cap != null && c.cap * 100 >= st.uwMinCap });
  return list;
}
const UW_SCEN = [
  { k: "cons", label: "Conservative", occ: -15, rent: 0.9 },
  { k: "base", label: "Base case", occ: 0, rent: 1 },
  { k: "up", label: "Upside", occ: 5, rent: 1.05 }
];
function uwScenario(i, s) { return uwCalc(i, { occ: Math.min(100, i.occ + s.occ), rentMult: s.rent }); }
export { S, num, uwInputs, uwReady, uwCalc, uwProject, uwChecks, UW_SCEN, uwScenario };
