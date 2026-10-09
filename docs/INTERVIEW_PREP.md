# Interview prep — Consumer Price Intelligence

## 30-second pitch
> "I built a pipeline that answers one question: **which Indian essentials are getting expensive, and does
> the official CPI agree?** It collects official All-India commodity prices from the Department of Consumer
> Affairs and shop-level branded prices from Open Prices, converts everything to price per kg, litre or unit,
> runs 27 data-quality checks without deleting anything, and loads a SQLite star schema behind a 7-page Power BI
> dashboard. Onion is up 99% year-on-year, but that's a recovery to its 2-year-ago level; the steady rise is
> edible oils, up as much as 46% over two years. For 22 of 37 items my price changes match CPI within 3
> points; turmeric and tomato are the clear exceptions, and I can explain why."

---

## The four questions you will be asked

### 1. How did you turn pack sizes into price per kg / litre?
- **Pick a canonical unit:** kg for mass, litre for volume, unit for pieces (g ÷ 1000, ml ÷ 1000, dozen × 12).
- **`normalized_price = price paid ÷ pack size in that unit`.** 69 g for ₹40 → ₹580/kg.
- **Where the pack size comes from, in order:**
  1. structured `product_quantity` + unit from the API;
  2. regex on the quantity text (handles "2 x 200ml", "70gms");
  3. regex on the product name — **flagged** `pack_size_from_name`.
- **No pack size → normalised price left empty, never guessed** (78 rows, 19%). Those rows still count for discount analysis.
- **DoCA:** the reporting unit changes by commodity (butter per 100 g, eggs per dozen), so the unit column is parsed per row. Butter ₹60.55/100 g → ₹605.5/kg.
- **Comparisons only within one unit.** Never ₹/kg against ₹/l, and never pack price against pack price.
- **Real catch:** Nutella logged against a 15 g pack → ₹29,933/kg. The robust z-score outlier check flags it.

### 2. Why is CPI only a benchmark, never mixed into the price data?
- **CPI is an index (2012 = 100), not a price.** You can't average ₹/kg with an index number.
- **Different method:** CPI is a Laspeyres index with fixed basket weights and monthly averages over many markets; DoCA is one day's average price across reporting centres.
- **Built into the design:** separate table `fact_cpi_benchmark`, joined to commodities only through `bridge_commodity_cpi`. The comparison is side by side (change % vs inflation %), never on one axis.
- **Why it's still useful:** if my numbers disagreed with CPI everywhere, my pipeline would be wrong. They agree on 22 of 37 items, which validates the normalisation and date handling.
- **Explaining the disagreements:** turmeric (DoCA powder per 50 g vs a differently defined CPI item) and tomato (one day vs a monthly average of a very volatile vegetable).
- **So I never call this "inflation".**

### 3. Why not scrape BigBasket / Blinkit / Amazon?
- **Their terms of service forbid automated scraping.** They also sit behind login/location walls and anti-bot systems.
- **My rule: no CAPTCHA bypass, no login, no anti-bot workarounds.** That also excluded DoCA's own city-level reports, which are CAPTCHA-protected.
- **I chose sources open by design:**
  - a public government dashboard (plain GET request);
  - an ODbL-licensed open API (Open Prices);
  - the MoSPI public API.
- **The trade-off, stated openly:** weak city coverage. I'd rather have a smaller honest dataset than a bigger one I'm not allowed to use.

### 4. What does "availability" mean here?
- **It means the source reported a price for that commodity on that date — not that the product was on a shelf.** No legitimate open source here reports stock-outs.
- **Three states in `fact_availability`:**
  - `reported`;
  - `not_reported` (a gap in a live series);
  - `not_yet_tracked` (before the commodity was added to monitoring).
- **Why the third state matters:** Broken Rice, Ginger and Garlic show "--" in older columns only because DoCA started tracking them later. Calling that "unavailable" would be wrong.

---

## Likely follow-ups (one-line answers)

| Question | Answer |
|---|---|
| How is it incremental? | Each raw file's SHA-256 goes in `etl_raw_file`; already-loaded files are skipped; facts upsert on `(source, source_record_id)` |
| What if a raw file changes? | The pipeline stops. Raw files are immutable by design |
| What if DoCA revises a weekend price? | Same natural key → value updated, old value kept in `fact_price_revision` |
| Why two dates on the fact? | `date_key` = when the price applied, `collection_date_key` = when I captured it. DoCA look-backs differ by up to 2 years |
| What's the grain of `fact_price`? | One price × product × place × observation date × price type (retail/wholesale) |
| Biggest data-quality catches? | Duplicate crowd submissions, a "list price" of ₹99,99,999, ₹1 vs a ₹67 median (Tahi ayam), MoSPI API paging that repeated 85 rows and skipped 85 others (fixed with a sliced backfill) |
| Why not delete bad rows? | Deleting hides problems. Flags + `include_in_analysis` keep an audit trail and let the dashboard show data quality |
| How does the spike alert work? | z-score of a commodity's daily % change against its own mean and SD; z > 2 = spike. It needs 10+ daily steps, so it ignores the year-apart look-backs |
| Biggest limitation? | Short official history (6 points) and thin city data. The daily scheduler fixes the first; the second is a deliberate legal choice |
| What would you add next? | NHB city vegetable prices, the CPI base-2024 series for 2026, and price forecasting once there's 3+ months of daily data |

## Numbers to remember
**677** price rows · **647** usable · **27** DQ checks · **42** commodities · **99** cities · avg YoY **+7.8%** ·
avg MoM **+1.8%** · onion **+99%** (≈0% vs 2 yrs) · sugar **+20%** · edible oils **+8–19%** (sunflower **+46%** in 2 yrs) ·
**1 in 5** shop prices discounted, **~25%** off · CPI agreement **22 / 37** within 3 pp.
