-- Analysis queries for the 8 business questions.
-- Every query uses include_in_analysis = 1 (flagged-out rows stay in the DB, see dq_issue_log)
-- and compares NORMALISED prices (INR/kg, INR/l, INR/unit) - never raw pack prices of different sizes.
-- Blocks are separated by "-- name: <id>" so src/analysis.py can run them one by one.

-- name: v_price
DROP VIEW IF EXISTS v_price;
CREATE VIEW v_price AS
SELECT f.price_id, s.source_code, f.price_type, d.full_date AS obs_date, d.year_month,
       cd.full_date AS collection_date, f.lookback_label,
       p.product_key, p.product_code, p.product_name, p.pack_size_label, p.product_type,
       b.brand_name, b.is_branded, c.category_group, c.category,
       l.city, l.state, l.region, l.location_level, l.outlet_type,
       f.price_paid, f.price_list, f.discount_pct, f.is_discounted,
       f.normalized_price, f.normalized_list_price, f.normalized_unit,
       f.is_provisional, f.dq_flags
FROM fact_price f
JOIN dim_source s   ON s.source_key = f.source_key
JOIN dim_date d     ON d.date_key = f.date_key
JOIN dim_date cd    ON cd.date_key = f.collection_date_key
JOIN dim_product p  ON p.product_key = f.product_key
JOIN dim_brand b    ON b.brand_key = f.brand_key
JOIN dim_category c ON c.category_key = f.category_key
JOIN dim_location l ON l.location_key = f.location_key
WHERE f.include_in_analysis = 1;

-- name: q1a_commodity_price_change
-- Q1. Which products have increased most in price? (official DoCA All-India retail averages)
-- Look-back value = the observation closest before each target date (within 7 days), so the
-- query keeps working as daily captures accumulate.
WITH r AS (SELECT * FROM v_price WHERE source_code='DOCA_PMD' AND price_type='retail'),
latest AS (SELECT product_key, product_name, category, normalized_unit, MAX(obs_date) AS d FROM r GROUP BY product_key),
w AS (
  SELECT l.*,
    (SELECT normalized_price FROM r WHERE r.product_key=l.product_key AND r.obs_date=l.d) AS p_latest,
    (SELECT normalized_price FROM r WHERE r.product_key=l.product_key AND r.obs_date BETWEEN date(l.d,'-1 month','-7 days') AND date(l.d,'-1 month') ORDER BY obs_date DESC LIMIT 1) AS p_1m,
    (SELECT normalized_price FROM r WHERE r.product_key=l.product_key AND r.obs_date BETWEEN date(l.d,'-6 months','-7 days') AND date(l.d,'-6 months') ORDER BY obs_date DESC LIMIT 1) AS p_6m,
    (SELECT normalized_price FROM r WHERE r.product_key=l.product_key AND r.obs_date BETWEEN date(l.d,'-1 year','-7 days') AND date(l.d,'-1 year') ORDER BY obs_date DESC LIMIT 1) AS p_1y,
    (SELECT normalized_price FROM r WHERE r.product_key=l.product_key AND r.obs_date BETWEEN date(l.d,'-2 years','-7 days') AND date(l.d,'-2 years') ORDER BY obs_date DESC LIMIT 1) AS p_2y
  FROM latest l)
SELECT product_name, category, normalized_unit, d AS latest_date,
       ROUND(p_latest,2) AS price_latest, ROUND(p_1m,2) AS price_1m_ago, ROUND(p_6m,2) AS price_6m_ago,
       ROUND(p_1y,2) AS price_1y_ago, ROUND(p_2y,2) AS price_2y_ago,
       ROUND(100.0*(p_latest/p_1y - 1),2) AS pct_change_1y,
       ROUND(100.0*(p_latest/p_2y - 1),2) AS pct_change_2y
FROM w ORDER BY pct_change_1y IS NULL, pct_change_1y DESC;

-- name: q1b_product_repeat_observations
-- Q1 (branded products). Same barcode observed on 2+ dates - anecdotal, crowd-sourced, any outlet.
WITH x AS (
  SELECT product_code, product_name, brand_name, pack_size_label, normalized_unit, obs_date, city, normalized_price,
         ROW_NUMBER() OVER (PARTITION BY product_code ORDER BY obs_date, price_id) AS rn_first,
         ROW_NUMBER() OVER (PARTITION BY product_code ORDER BY obs_date DESC, price_id DESC) AS rn_last,
         nd.n_dates
  FROM v_price
  JOIN (SELECT product_code AS pc, COUNT(DISTINCT obs_date) AS n_dates FROM v_price
        WHERE source_code='OPEN_PRICES' AND normalized_price IS NOT NULL GROUP BY product_code) nd ON nd.pc = product_code
  WHERE source_code='OPEN_PRICES' AND normalized_price IS NOT NULL)
SELECT f.product_name, f.brand_name, f.pack_size_label, f.normalized_unit,
       f.obs_date AS first_date, f.city AS first_city, ROUND(f.normalized_price,2) AS first_norm_price,
       l.obs_date AS last_date, l.city AS last_city, ROUND(l.normalized_price,2) AS last_norm_price,
       ROUND(100.0*(l.normalized_price/f.normalized_price - 1),2) AS pct_change,
       CAST(julianday(l.obs_date) - julianday(f.obs_date) AS INT) AS days_apart,
       CASE WHEN f.city = l.city THEN 'same city' ELSE 'different city' END AS comparability
FROM x f JOIN x l ON l.product_code = f.product_code AND l.rn_last = 1
WHERE f.rn_first = 1 AND f.n_dates >= 2
ORDER BY pct_change DESC;

-- name: q2_brand_normalized_price
-- Q2. Which brands have the lowest normalised price? Ranked WITHIN category and unit only.
WITH b AS (
  SELECT category, normalized_unit, brand_name, COUNT(*) AS n_obs,
         COUNT(DISTINCT product_code) AS n_products,
         AVG(normalized_price) AS avg_norm_price,
         MIN(normalized_price) AS min_norm_price, MAX(normalized_price) AS max_norm_price
  FROM v_price
  WHERE source_code='OPEN_PRICES' AND normalized_price IS NOT NULL AND brand_name <> 'Unknown brand'
    AND COALESCE(dq_flags,'') NOT LIKE '%normalized_price_outlier%'
  GROUP BY category, normalized_unit, brand_name),
c AS (SELECT category, normalized_unit, COUNT(*) AS brands_in_cat FROM b GROUP BY 1,2)
SELECT b.category, b.normalized_unit, b.brand_name, b.n_obs, b.n_products,
       ROUND(b.avg_norm_price,2) AS avg_norm_price, ROUND(b.min_norm_price,2) AS min_norm_price,
       ROUND(b.max_norm_price,2) AS max_norm_price,
       RANK() OVER (PARTITION BY b.category, b.normalized_unit ORDER BY b.avg_norm_price) AS rank_cheapest,
       c.brands_in_cat,
       CASE WHEN b.n_obs >= 3 THEN 'ok' ELSE 'low sample (<3 obs)' END AS sample_flag
FROM b JOIN c USING(category, normalized_unit)
WHERE c.brands_in_cat >= 3
ORDER BY b.category, b.normalized_unit, rank_cheapest;

-- name: q3_location_price_index
-- Q3. Which locations have the highest prices?
-- Method A (strict): product-matched index. For barcodes seen in 2+ cities, each observation's
--   normalised price / that barcode's all-India median. City index = average ratio x 100.
-- Method B (indicative): category-relative index (obs / category median) - mixes products, weak.
WITH obs AS (
  SELECT price_id, product_code, category, normalized_unit, city, state, region, normalized_price
  FROM v_price WHERE source_code='OPEN_PRICES' AND normalized_price IS NOT NULL AND city IS NOT NULL
    AND COALESCE(dq_flags,'') NOT LIKE '%normalized_price_outlier%'),
multi AS (SELECT product_code FROM obs GROUP BY product_code HAVING COUNT(DISTINCT city) >= 2),
prod_med AS (
  SELECT product_code, AVG(normalized_price) AS ref FROM obs WHERE product_code IN (SELECT product_code FROM multi)
  GROUP BY product_code),
cat_ref AS (SELECT category, normalized_unit, AVG(normalized_price) AS ref, COUNT(*) n FROM obs GROUP BY 1,2)
SELECT 'A_product_matched' AS method, o.city, o.state, o.region, COUNT(*) AS n_obs,
       COUNT(DISTINCT o.product_code) AS n_products, ROUND(100*AVG(o.normalized_price/pm.ref),1) AS price_index
FROM obs o JOIN prod_med pm USING(product_code) GROUP BY o.city, o.state, o.region
UNION ALL
SELECT 'B_category_relative', o.city, o.state, o.region, COUNT(*), COUNT(DISTINCT o.product_code),
       ROUND(100*AVG(o.normalized_price/cr.ref),1)
FROM obs o JOIN cat_ref cr USING(category, normalized_unit) WHERE cr.n >= 5
GROUP BY o.city, o.state, o.region HAVING COUNT(*) >= 5
ORDER BY method, price_index DESC;

-- name: q4_category_volatility
-- Q4. Which categories show the highest price volatility? (DoCA, 6 official points per commodity:
--   2y, 1y, 6m, 1m, 1w back and latest; unevenly spaced -> CV across points + max abs step change)
WITH pts AS (
  SELECT product_name, category, obs_date, normalized_price,
         LAG(normalized_price) OVER (PARTITION BY product_key ORDER BY obs_date) AS prev
  FROM v_price WHERE source_code='DOCA_PMD' AND price_type='retail'),
per_commodity AS (
  SELECT product_name, category, COUNT(*) AS n_points,
         AVG(normalized_price) AS mean_p,
         SQRT(AVG(normalized_price*normalized_price) - AVG(normalized_price)*AVG(normalized_price)) AS sd_p,
         MAX(ABS(100.0*(normalized_price/prev - 1))) AS max_abs_step_pct,
         MIN(normalized_price) AS min_p, MAX(normalized_price) AS max_p
  FROM pts GROUP BY product_name, category)
SELECT category, COUNT(*) AS n_commodities,
       ROUND(AVG(100.0*sd_p/mean_p),2) AS avg_cv_pct,
       ROUND(MAX(100.0*sd_p/mean_p),2) AS max_cv_pct,
       (SELECT product_name FROM per_commodity p2 WHERE p2.category = p.category ORDER BY sd_p/mean_p DESC LIMIT 1) AS most_volatile_commodity,
       ROUND(AVG(100.0*(max_p/min_p - 1)),1) AS avg_high_low_range_pct,
       ROUND(AVG(max_abs_step_pct),1) AS avg_max_step_change_pct
FROM per_commodity p WHERE n_points >= 4
GROUP BY category ORDER BY avg_cv_pct DESC;

-- name: q4b_commodity_volatility
SELECT v.product_name, v.category, COUNT(*) AS n_points, ROUND(MIN(v.normalized_price),2) AS min_price,
       ROUND(MAX(v.normalized_price),2) AS max_price, v.normalized_unit,
       ROUND(100.0*SQRT(AVG(v.normalized_price*v.normalized_price)-AVG(v.normalized_price)*AVG(v.normalized_price))/AVG(v.normalized_price),2) AS cv_pct
FROM v_price v WHERE source_code='DOCA_PMD' AND price_type='retail'
GROUP BY v.product_key HAVING COUNT(*) >= 4 ORDER BY cv_pct DESC;

-- name: q5_unavailability
-- Q5. Which products frequently become unavailable?
-- Only DoCA has an explicit "no value" marker ('--'). This is NOT a shelf stock-out measure:
-- 'not_yet_tracked' = before the commodity was added to monitoring; 'not_reported' = gap in a live series.
SELECT p.product_name, c.category, a.price_type,
       COUNT(*) AS points_checked,
       SUM(a.availability_status='reported') AS reported,
       SUM(a.availability_status='not_reported') AS not_reported_gaps,
       SUM(a.availability_status='not_yet_tracked') AS before_series_start,
       ROUND(100.0*SUM(a.availability_status='not_reported')/COUNT(*),1) AS gap_rate_pct,
       MIN(CASE WHEN a.is_available=1 THEN d.full_date END) AS first_reported_date
FROM fact_availability a JOIN dim_product p USING(product_key) JOIN dim_category c ON c.category_key=p.category_key
JOIN dim_date d ON d.date_key=a.date_key
GROUP BY p.product_key, a.price_type
ORDER BY not_reported_gaps DESC, before_series_start DESC, p.product_name;

-- name: q6_same_product_across_locations
-- Q6. How much does the same product (same barcode = same pack) vary between locations?
SELECT product_code, product_name, brand_name, pack_size_label, normalized_unit,
       COUNT(*) AS n_obs, COUNT(DISTINCT city) AS n_cities, GROUP_CONCAT(DISTINCT city) AS cities,
       ROUND(MIN(price_paid),2) AS min_pack_price, ROUND(MAX(price_paid),2) AS max_pack_price,
       ROUND(100.0*(MAX(price_paid)/MIN(price_paid) - 1),1) AS max_vs_min_pct,
       MIN(obs_date) AS first_date, MAX(obs_date) AS last_date
FROM v_price WHERE source_code='OPEN_PRICES' AND city IS NOT NULL
GROUP BY product_code HAVING COUNT(DISTINCT city) >= 2
ORDER BY max_vs_min_pct DESC;

-- name: q6b_wholesale_to_retail_spread
-- Q6 (supplementary): All-India wholesale vs retail on the same date, same commodity, per kg/l.
SELECT r.product_name, r.category, r.obs_date, r.normalized_unit,
       ROUND(w.normalized_price,2) AS wholesale_per_unit, ROUND(r.normalized_price,2) AS retail_per_unit,
       ROUND(100.0*(r.normalized_price/w.normalized_price - 1),1) AS retail_markup_over_wholesale_pct
FROM v_price r JOIN v_price w ON w.product_key=r.product_key AND w.obs_date=r.obs_date AND w.price_type='wholesale'
WHERE r.source_code='DOCA_PMD' AND r.price_type='retail' AND r.normalized_unit = w.normalized_unit
ORDER BY retail_markup_over_wholesale_pct DESC;

-- name: q7_discount_effect
-- Q7. How do discounts affect effective price? (Open Prices: price_paid vs pre-discount price)
SELECT category_group, category, COUNT(*) AS n_obs, SUM(is_discounted) AS n_discounted,
       ROUND(100.0*SUM(is_discounted)/COUNT(*),1) AS pct_obs_discounted,
       ROUND(AVG(CASE WHEN is_discounted=1 AND price_list>price_paid THEN discount_pct END),1) AS avg_discount_pct_when_discounted,
       ROUND(SUM(CASE WHEN is_discounted=1 THEN price_list - price_paid ELSE 0 END),2) AS total_rupees_saved,
       ROUND(AVG(CASE WHEN is_discounted=1 AND price_list>price_paid THEN normalized_list_price END),2) AS avg_norm_list_price_disc_items,
       ROUND(AVG(CASE WHEN is_discounted=1 AND price_list>price_paid THEN normalized_price END),2) AS avg_norm_effective_price_disc_items
FROM v_price WHERE source_code='OPEN_PRICES' AND COALESCE(dq_flags,'') NOT LIKE '%implausible_list_price%'
GROUP BY category_group, category
UNION ALL
SELECT 'ALL','ALL', COUNT(*), SUM(is_discounted), ROUND(100.0*SUM(is_discounted)/COUNT(*),1),
       ROUND(AVG(CASE WHEN is_discounted=1 AND price_list>price_paid THEN discount_pct END),1),
       ROUND(SUM(CASE WHEN is_discounted=1 THEN price_list - price_paid ELSE 0 END),2), NULL, NULL
FROM v_price WHERE source_code='OPEN_PRICES' AND COALESCE(dq_flags,'') NOT LIKE '%implausible_list_price%'
ORDER BY n_obs DESC;

-- name: q8_mom_change
-- Q8. Month-over-month price change. DoCA: latest vs official '1 Month back' value.
WITH l AS (SELECT product_key, MAX(obs_date) d FROM v_price WHERE source_code='DOCA_PMD' AND price_type='retail' GROUP BY 1)
SELECT v.product_name, v.category, v.normalized_unit,
       m.obs_date AS month_ago_date, ROUND(m.normalized_price,2) AS month_ago_price,
       v.obs_date AS latest_date, ROUND(v.normalized_price,2) AS latest_price,
       ROUND(100.0*(v.normalized_price/m.normalized_price - 1),2) AS mom_pct
FROM v_price v JOIN l ON l.product_key=v.product_key AND l.d=v.obs_date
JOIN v_price m ON m.product_key=v.product_key AND m.source_code='DOCA_PMD' AND m.price_type='retail'
              AND m.lookback_label='1 Month back'
WHERE v.source_code='DOCA_PMD' AND v.price_type='retail'
ORDER BY mom_pct DESC;

-- name: q8b_mom_category
WITH l AS (SELECT product_key, MAX(obs_date) d FROM v_price WHERE source_code='DOCA_PMD' AND price_type='retail' GROUP BY 1),
x AS (
  SELECT v.category, 100.0*(v.normalized_price/m.normalized_price - 1) AS mom
  FROM v_price v JOIN l ON l.product_key=v.product_key AND l.d=v.obs_date
  JOIN v_price m ON m.product_key=v.product_key AND m.source_code='DOCA_PMD' AND m.price_type='retail' AND m.lookback_label='1 Month back'
  WHERE v.source_code='DOCA_PMD' AND v.price_type='retail')
SELECT category, COUNT(*) AS n_commodities, ROUND(AVG(mom),2) AS avg_mom_pct, ROUND(MIN(mom),2) AS min_mom_pct, ROUND(MAX(mom),2) AS max_mom_pct
FROM x GROUP BY category ORDER BY avg_mom_pct DESC;

-- name: q8c_cpi_benchmark_mom
-- Q8 benchmark (separate dataset, index not price): CPI item MoM % from MoSPI, for DoCA-mapped items.
WITH c AS (
  SELECT p.product_name AS doca_commodity, i.cpi_item, d.full_date AS month, f.index_value,
         LAG(f.index_value) OVER (PARTITION BY f.cpi_item_key ORDER BY f.date_key) AS prev_index,
         f.yoy_inflation_pct
  FROM fact_cpi_benchmark f JOIN dim_cpi_item i USING(cpi_item_key) JOIN dim_date d ON d.date_key=f.date_key
  JOIN bridge_commodity_cpi b ON b.cpi_item_key=f.cpi_item_key JOIN dim_product p ON p.product_key=b.product_key)
SELECT doca_commodity, cpi_item, month, index_value,
       ROUND(100.0*(index_value/prev_index - 1),2) AS cpi_mom_pct, yoy_inflation_pct AS cpi_yoy_pct
FROM c ORDER BY doca_commodity, month;

-- name: bench_doca_vs_cpi_yoy
-- Benchmark: DoCA price change Sep-2024 -> Sep-2025 vs MoSPI CPI item YoY inflation for Sep-2025.
-- Different methodologies (average price vs Laspeyres index) - shown side by side, not merged.
SELECT p.product_name AS doca_commodity, i.cpi_item, b.match_quality,
       ROUND(100.0*(f25.normalized_price/f24.normalized_price - 1),2) AS doca_price_change_pct,
       cpi.yoy_inflation_pct AS cpi_item_yoy_pct_sep2025,
       ROUND(100.0*(f25.normalized_price/f24.normalized_price - 1) - cpi.yoy_inflation_pct,2) AS gap_pp
FROM bridge_commodity_cpi b
JOIN dim_product p ON p.product_key=b.product_key
JOIN dim_cpi_item i ON i.cpi_item_key=b.cpi_item_key
JOIN fact_cpi_benchmark cpi ON cpi.cpi_item_key=b.cpi_item_key AND cpi.date_key=20250901
JOIN fact_price f25 ON f25.product_key=p.product_key AND f25.date_key=20250930 AND f25.price_type='retail' AND f25.include_in_analysis=1
JOIN fact_price f24 ON f24.product_key=p.product_key AND f24.date_key=20240930 AND f24.price_type='retail' AND f24.include_in_analysis=1
ORDER BY gap_pp DESC;

-- name: dq_summary
SELECT q.check_name, q.source_code, q.rows_checked, q.rows_flagged,
       ROUND(100.0*q.rows_flagged/q.rows_checked,1) AS pct_flagged, q.action, q.description
FROM dq_check_summary q WHERE q.run_id = (SELECT MAX(run_id) FROM dq_check_summary) AND q.rows_flagged > 0
ORDER BY q.rows_flagged DESC;

-- name: q9_history_depth
-- How much day-to-day history each DoCA commodity has. Spike detection needs >= 10 daily steps.
WITH s AS (
  SELECT product_key, product_name, obs_date,
         LAG(obs_date) OVER (PARTITION BY product_key ORDER BY obs_date) AS prev_date
  FROM v_price WHERE source_code='DOCA_PMD' AND price_type='retail')
SELECT product_name,
       COUNT(*) AS dated_points,
       SUM(julianday(obs_date) - julianday(prev_date) BETWEEN 1 AND 4) AS daily_steps,
       MIN(obs_date) AS first_date, MAX(obs_date) AS last_date,
       CASE WHEN SUM(julianday(obs_date) - julianday(prev_date) BETWEEN 1 AND 4) >= 10
            THEN 'ready' ELSE 'collecting' END AS spike_detection_status
FROM s GROUP BY product_key ORDER BY daily_steps DESC, product_name;

-- name: q9_price_spikes
-- Price-spike monitor. A step counts as "daily" if the previous point is 1-4 days earlier
-- (weekends/holidays). z = (step change - commodity's mean step change) / its standard deviation.
-- Spike up: z > 2 ; sharp drop: z < -2. Needs at least 10 daily steps per commodity.
WITH s AS (
  SELECT product_key, product_name, category, obs_date, normalized_price, normalized_unit,
         LAG(obs_date) OVER w AS prev_date, LAG(normalized_price) OVER w AS prev_price
  FROM v_price WHERE source_code='DOCA_PMD' AND price_type='retail'
  WINDOW w AS (PARTITION BY product_key ORDER BY obs_date)),
steps AS (
  SELECT *, 100.0*(normalized_price/prev_price - 1) AS pct_step
  FROM s WHERE prev_price IS NOT NULL AND julianday(obs_date) - julianday(prev_date) BETWEEN 1 AND 4),
stats AS (
  SELECT product_key, COUNT(*) AS n_steps, AVG(pct_step) AS mean_step,
         SQRT(MAX(AVG(pct_step*pct_step) - AVG(pct_step)*AVG(pct_step), 0)) AS sd_step
  FROM steps GROUP BY product_key),
latest AS (SELECT MAX(obs_date) AS d FROM steps)
SELECT st.product_name, st.category, st.obs_date, st.prev_date,
       ROUND(st.prev_price,2) AS prev_price, ROUND(st.normalized_price,2) AS price, st.normalized_unit,
       ROUND(st.pct_step,2) AS pct_change, ROUND(x.mean_step,2) AS normal_change,
       ROUND(x.sd_step,2) AS sd_change, ROUND((st.pct_step - x.mean_step)/x.sd_step,2) AS z_score,
       CASE WHEN (st.pct_step - x.mean_step)/x.sd_step > 2 THEN 'spike up' ELSE 'sharp drop' END AS spike_type,
       CASE WHEN st.obs_date >= date((SELECT d FROM latest),'-6 days') THEN 1 ELSE 0 END AS is_this_week,
       x.n_steps
FROM steps st JOIN stats x USING(product_key)
WHERE x.n_steps >= 10 AND x.sd_step > 0 AND ABS((st.pct_step - x.mean_step)/x.sd_step) > 2
ORDER BY st.obs_date DESC, z_score DESC;
