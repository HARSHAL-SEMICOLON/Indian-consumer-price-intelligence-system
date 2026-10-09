# Findings — capture of 2026-10-01

All figures come from `data/processed/analysis/*.csv` (regenerated on every run). Prices are
**normalised** (INR/kg, INR/l, INR/unit). DoCA = official All-India average retail price; Open Prices =
crowd-sourced shop observations. **None of this is an inflation measure.**

### Q1. Which products have increased most in price?
DoCA, latest (30-Sep-2026) vs official value one year earlier (30-Sep-2025):

| Commodity | 1 yr ago | Latest | Change |
|---|---|---|---|
| Onion | ₹27.08/kg | ₹53.86/kg | **+98.9%** (but ≈ flat vs 2 yrs ago: +0.1%) |
| Sugar | ₹46.54 | ₹56.02 | +20.4% |
| Sunflower oil (packed) | ₹162.34 | ₹192.54 | +18.6% (+45.7% over 2 yrs) |
| Coriander (whole) | ₹150.68 | ₹175.32 | +16.4% |
| Palm oil (packed) | ₹132.66 | ₹153.72 | +15.9% |

Edible oils dominate the 2-year rise (soya +29%, mustard +32%, palm +34%, sunflower +46%); Tur dal is
the notable faller over 2 years (−23%). Branded products: only 11 barcodes were observed on two dates;
the largest move is Paper Boat Swing Coconut Water 1.2 l, ₹75 → ₹125/l in Bengaluru (Mar→Sep 2025) — anecdotal.

### Q2. Which brands have the lowest normalised price?
Ranked **within a category and unit only**. Examples with ≥3 observations: Beverages (INR/l) —
Campa ₹89.6/l < Paper Boat ₹115/l ≈ Coca-Cola ₹117/l; Biscuits/Bread (INR/kg) — Modern ₹137/kg vs
Britannia ₹311/kg (Britannia's mix includes premium biscuits). Most brands have 1–2 observations, so
rankings are indicative; the CSV carries a `sample_flag` column.

### Q3. Which locations have the highest prices?
Cannot be answered robustly with legitimate data available today (DoCA centre-wise = CAPTCHA). Product-
matched index (same barcode in 2+ cities) covers 7 cities with 1–2 observations each (Danapur 118, Bengaluru 102,
Hyderabad 96, Dholi 82). The category-relative index (indicative only) puts Pune and Kochi highest and
Hyderabad, Delhi, Mumbai lowest — but it mainly reflects *what* contributors bought, not *where*.

### Q4. Which categories show the highest price volatility?
Coefficient of variation across DoCA's 6 official points (2 yrs):
**Vegetables 16.2%** (onion 28.7%, potato 21.5%, tomato 19.1%) > Sugar & Gur 10.9% > Edible Oils 8.3% >
Spices/Tea/Salt 5.9% > Pulses 3.6% > Milk/Dairy/Eggs 2.4% > Cereals & Flours 1.9% > Fruits (banana) 1.1%.

### Q5. Which products frequently become unavailable?
No genuine gaps: every live DoCA series reported on every captured date. The only blanks are **before
series start** (Broken Rice — reported from Aug-2026; Ginger and Garlic — from Mar-2026). Shelf
availability is not measured by any legitimate source used here (stated limitation).

### Q6. How much does the same product vary between locations?
Only 6 barcodes seen in 2+ cities: Soan Papdi 400 g ₹125 vs ₹179 (+43%, Danapur vs Dholi, Bihar);
Modern whole-wheat bread 400 g ₹55 vs ₹60 (+9%); the other 4 (Maggi, Bingo Tedha Medha, Dark
Fantasy, Spot On biryani) had identical MRP-level prices. Supplementary: All-India retail markup over
wholesale on 30-Sep-2026 ranges from **+34.7% (potato)** and +27.1% (tomato) down to ~5% for packed edible oils.

### Q7. How do discounts affect effective price?
375 usable Open Prices rows (5 with implausible list prices excluded): **20.5% were discounted**, average
discount **25.5%** when discounted. Highest discount incidence: household (other) 73%, cleaning 63%,
staples 46%, edible oils 44%; lowest: sauces/spreads 0%, chocolates 3%, snacks 5%, dairy 4%.
Example: discounted staples' effective price averaged ₹409/kg vs ₹478/kg list.

### Q8. Month-over-month price change
DoCA 30-Aug-2026 → 30-Sep-2026: vegetables **+5.1% avg** (onion +11.5%, tomato +11.1%), pulses +2.1%,
spices/tea +2.0%, cereals +1.7%, oils +1.2%, dairy +1.1%; **sugar −12.8%**, gur −1.3%, ginger −4.3%.
CPI item-level MoM for 2024–2025 is available in `q8c_cpi_benchmark_mom.csv` as context.

### Benchmark: DoCA vs MoSPI CPI (Sep-2024 → Sep-2025)
For 37 mapped items, 22 are within 3 percentage points (onion −49.7% vs −49.9%; tur −29.8% vs −30.0%;
mustard oil +22.2% vs +21.0%). Clear disagreements: turmeric (DoCA −26% vs CPI +4%), tomato (−27% vs −6%),
black pepper (−3% vs +7%) — likely single-day price vs monthly average, and different item definitions.
They are different methodologies (average price vs. index) — shown side by side only.
