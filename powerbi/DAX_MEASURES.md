# DAX Measures

Paste into a `_Measures` table. All price measures use the **normalised** price (INR/kg, INR/l or
INR/unit) — never mix units in one visual: put `fact_price[normalized_unit]` in a slicer or filter.

```DAX
// ---------- core
Observations = COUNTROWS ( fact_price )
Avg Normalized Price = AVERAGE ( fact_price[normalized_price] )
Median Normalized Price = MEDIAN ( fact_price[normalized_price] )
Min Normalized Price = MIN ( fact_price[normalized_price] )
Max Normalized Price = MAX ( fact_price[normalized_price] )
Distinct Products = DISTINCTCOUNT ( fact_price[product_key] )

Commodities Tracked =
CALCULATE ( DISTINCTCOUNT ( fact_price[product_key] ), dim_source[source_code] = "DOCA_PMD" )
Branded Products Observed =
CALCULATE ( DISTINCTCOUNT ( fact_price[product_key] ), dim_source[source_code] = "OPEN_PRICES" )
Cities Covered =
CALCULATE ( DISTINCTCOUNT ( dim_location[city] ), dim_location[location_level] = "outlet" )
Latest Collection Date =
CALCULATE ( MAX ( dim_date[full_date] ), USERELATIONSHIP ( fact_price[collection_date_key], dim_date[date_key] ) )

// ---------- time comparisons (DoCA: latest observation vs look-back observation)
Latest Obs Date = CALCULATE ( MAX ( fact_price[date_key] ), REMOVEFILTERS ( dim_date ) )

Price Latest =
VAR d = [Latest Obs Date]
RETURN CALCULATE ( [Avg Normalized Price], REMOVEFILTERS ( dim_date ), fact_price[date_key] = d )

Price 1M Ago =
VAR d = DATEVALUE ( FORMAT ( [Latest Obs Date], "0000-00-00" ) )
VAR t = EDATE ( d, -1 )
RETURN CALCULATE ( [Avg Normalized Price], REMOVEFILTERS ( dim_date ),
        dim_date[full_date] >= t - 7, dim_date[full_date] <= t )

Price 1Y Ago =
VAR d = DATEVALUE ( FORMAT ( [Latest Obs Date], "0000-00-00" ) )
VAR t = EDATE ( d, -12 )
RETURN CALCULATE ( [Avg Normalized Price], REMOVEFILTERS ( dim_date ),
        dim_date[full_date] >= t - 7, dim_date[full_date] <= t )

MoM Change % = DIVIDE ( [Price Latest] - [Price 1M Ago], [Price 1M Ago] )
YoY Change % = DIVIDE ( [Price Latest] - [Price 1Y Ago], [Price 1Y Ago] )

Avg YoY Change % (DoCA) =
AVERAGEX ( CALCULATETABLE ( VALUES ( dim_product[product_key] ), dim_source[source_code] = "DOCA_PMD",
           fact_price[price_type] = "retail" ), [YoY Change %] )
Avg MoM Change % (DoCA) =
AVERAGEX ( CALCULATETABLE ( VALUES ( dim_product[product_key] ), dim_source[source_code] = "DOCA_PMD",
           fact_price[price_type] = "retail" ), [MoM Change %] )

// ---------- volatility (coefficient of variation of normalised price)
Price CV % = DIVIDE ( STDEVX.P ( fact_price, fact_price[normalized_price] ), [Avg Normalized Price] )

// ---------- brands
Brands in Selection = DISTINCTCOUNT ( fact_price[brand_key] )
Sample Flag = IF ( [Observations] >= 3, "ok", "low sample (<3 obs)" )

// ---------- locations
Cities for Product = DISTINCTCOUNT ( dim_location[city] )
Min Pack Price = MIN ( fact_price[price_paid] )
Max Pack Price = MAX ( fact_price[price_paid] )
Location Spread % = DIVIDE ( [Max Pack Price] - [Min Pack Price], [Min Pack Price] )

// product-matched city index: obs price / all-India average of the SAME product (x100)
City Price Index =
VAR t =
    ADDCOLUMNS (
        fact_price,
        "@ref", CALCULATE ( AVERAGE ( fact_price[normalized_price] ),
                    ALLEXCEPT ( fact_price, fact_price[product_key] ) ),
        "@cities", CALCULATE ( DISTINCTCOUNT ( dim_location[city] ),
                    ALLEXCEPT ( fact_price, fact_price[product_key] ) )
    )
RETURN 100 * AVERAGEX ( FILTER ( t, [@cities] >= 2 && NOT ISBLANK ( fact_price[normalized_price] ) ),
                         DIVIDE ( fact_price[normalized_price], [@ref] ) )

Retail Markup over Wholesale % =
VAR r = CALCULATE ( [Avg Normalized Price], fact_price[price_type] = "retail",
                    fact_price[date_key] = [Latest Obs Date] )
VAR w = CALCULATE ( [Avg Normalized Price], fact_price[price_type] = "wholesale" )
RETURN DIVIDE ( r - w, w )

// ---------- discounts (exclude implausible list prices)
% Observations Discounted =
DIVIDE ( CALCULATE ( COUNTROWS ( fact_price ), fact_price[is_discounted] = 1,
         NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" ) ),
         CALCULATE ( COUNTROWS ( fact_price ), NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" ) ) )
Avg Discount % (when discounted) =
CALCULATE ( AVERAGE ( fact_price[discount_pct] ) / 100, fact_price[is_discounted] = 1,
            fact_price[price_list] > fact_price[price_paid],
            NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" ) )
Total Savings INR =
CALCULATE ( SUMX ( fact_price, fact_price[price_list] - fact_price[price_paid] ), fact_price[is_discounted] = 1,
            NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" ) )
Avg Normalized List Price =
CALCULATE ( AVERAGE ( fact_price[normalized_list_price] ), fact_price[is_discounted] = 1,
            NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" ) )
Avg Normalized Effective Price =
CALCULATE ( AVERAGE ( fact_price[normalized_price] ), fact_price[is_discounted] = 1,
            NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" ) )

// ---------- availability (DoCA reporting status, NOT shelf stock)
Availability Status = SELECTEDVALUE ( fact_availability[availability_status] )
Not Reported Gap Rate % =
DIVIDE ( CALCULATE ( COUNTROWS ( fact_availability ), fact_availability[availability_status] = "not_reported" ),
         CALCULATE ( COUNTROWS ( fact_availability ), fact_availability[availability_status] <> "not_yet_tracked" ) )

// ---------- data quality (page 6 has no include_in_analysis filter)
Total Raw Records = COUNTROWS ( fact_price )
Records Excluded = CALCULATE ( COUNTROWS ( fact_price ), fact_price[include_in_analysis] = 0 )
Records Flagged = CALCULATE ( COUNTROWS ( fact_price ), NOT ISBLANK ( fact_price[dq_flags] ) )
% Usable = DIVIDE ( CALCULATE ( COUNTROWS ( fact_price ), fact_price[include_in_analysis] = 1 ), [Total Raw Records] )
```

Notes
- `Latest Obs Date` returns the yyyymmdd integer key; `FORMAT(...,"0000-00-00")` converts it to a date.
- `fact_price[dq_flags] & ""` turns blanks into empty text so CONTAINSSTRING works on unflagged rows.
- Format `%` measures as Percentage, 1 decimal.
