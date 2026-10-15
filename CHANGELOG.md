# Changelog

## 0.3.0
- CSV export of results (summary, fan chart, tornado, risk map) and a printed "report assumptions" block in the PDF report.
- Import from Land Deal Lab through the URL (`?from=ldl&...`), with an "imported" banner and a "land paid up front" field deducted from opening cash.

## 0.2.0
- Egyptian-market pricing: average unit area, price per m² or fixed unit price (radio: choose one), optional annual price escalation.
- Payment plans: installment frequency (monthly/quarterly/semi-annual/annual), delivery payment, extra yearly payments, cash buyers with discount, maintenance deposit (escrow or counted as cash).
- Conflicts are enforced in the engine (validation errors, `null` cells in the risk map) and in the UI (conflicting options switch off with a hint).
- Derived unit economics (price/m², total area, GDV, cost and margin per m², break-even price per m²).
- Every input has a (?) help tip and an explicit unit (months vs years, % of what, EGP million).
- Payment-plan x-ray supports frequency and delivery payments. All new options default to off, so 0.1.0 results are unchanged.

## 0.1.0
- Monte Carlo survival engine (Python, stdlib only) with seeded mulberry32 PRNG.
- Tornado sensitivity, down-payment × term risk map, longest affordable term, payment-plan PV x-ray.
- Bilingual (Arabic RTL / English) browser page with fan chart and print-to-PDF report.
- JS port verified against Python vectors (bit-identical arithmetic: only + - * / sqrt).
