# developer-cashflow-survival

[![CI](https://github.com/islamelsabahy/developer-cashflow-survival/actions/workflows/ci.yml/badge.svg)](https://github.com/islamelsabahy/developer-cashflow-survival/actions/workflows/ci.yml)

**EN** — *Will an off-plan developer reach delivery before the cash runs out?* The simulator runs thousands of Monte Carlo paths over construction-cost inflation, sales pace and installment collections, and answers: the probability of breaching the credit line before delivery, a cash **fan chart**, a **tornado** of the drivers that matter most, a **risk map** of down payment × installment term, the **longest term you can afford** for a risk limit you choose, and a **payment-plan x-ray** that shows the hidden discount (present value) of each plan. Python engine (no dependencies) plus a bilingual browser page in [`docs/`](docs/index.html) with a PDF report.

**AR** — *هل المطوّر العقاري هيوصل للتسليم قبل ما الكاش يخلص؟* بتشغّل آلاف السيناريوهات (مونت كارلو) على تضخم التشطيب وسرعة البيع ونسبة التحصيل، وتطلعلك: احتمال كسر حد الائتمان قبل التسليم، ومروحة الكاش، وأكتر العوامل تأثيرا، وخريطة مخاطر (المقدم × مدة التقسيط)، وأطول مدة تقسيط تقدر تقدمها لحد مخاطرة تحدده، وأشعة على خطط السداد بتبين الخصم المخفي (القيمة الحالية). محرك بايثون بدون مكتبات وصفحة ويب بالعربي والإنجليزي مع تقرير PDF.

> **Educational, not advice.** All numbers are fictional samples. The model is deliberately simple: no taxes, no detailed loan terms, no contract cancellations, installments not collected are delayed (not lost). Money is in millions of any currency. It is a planning aid for asking "what if", not a forecast.
>
> **أداة تعليمية وليست استشارة.** كل الأرقام وهمية. النموذج مبسّط عمدا (بدون ضرائب أو تفاصيل قروض أو إلغاء عقود).

## Use / الاستخدام

```python
from survival import simulate, tornado, max_term, plan_xray

r = simulate({"opening_cash": 190, "term": 48}, paths=2000, seed=7)
print(r["default_prob"])            # share of paths breaching the credit line before delivery
print(r["final_cash"])              # 5/25/50/75/95th percentile cash at delivery
print(tornado({}, paths=1000)["rows"][0])             # the driver that moves risk most
print(max_term({}, target=0.10)["best_term"])         # longest term with risk <= 10%
print(plan_xray(6.0, 0.27, [{"name": "10/90 x60", "down_pct": 0.1, "term": 60}]))
```

Open `docs/index.html` in a browser (works offline) or serve the `docs/` folder with GitHub Pages.

## Model in one paragraph

Per path: one persistent sales-pace shock, then each month a cost-inflation shock, a sales count (normal approximation around the expected pace), and a collection-efficiency shock. Down payments arrive at contract; the rest comes in equal installments (monthly to annual). Construction spend follows an S-curve scaled by cumulative inflation. Negative cash pays overdraft interest; the path **breaches** when cash falls below minus the credit line. Delivery is the horizon.

## Egyptian pricing and payment options (0.2)

Price by m² × area or by fixed unit price; optional annual price escalation; delivery payment, extra yearly payments, cash buyers with discount, and a maintenance deposit (escrow or counted as cash). Conflicting options are rejected by the engine and switched off in the UI (e.g. yearly payments with annual installments). All options default to off.

## Reproducible by design

* Seeded PRNG (mulberry32) and an Irwin–Hall normal (sum of 12 uniforms − 6), so a seed always gives the same answer.
* Only `+ − × ÷` and `sqrt` touch the numbers, so the Python reference and the JS port give identical results; `tests/vectors.json` is generated from Python and replayed in Node (`node tests/test_survival.js`). CI fails if either side drifts.

```bash
python -m unittest discover -s tests -v
python scripts/build_vectors.py          # regenerate vectors after changing the engine
node tests/test_survival.js
```

## License

MIT
