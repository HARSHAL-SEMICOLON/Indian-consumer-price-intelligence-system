"""Standardisation rules: units/pack sizes, product names, brands, categories, locations, dates.

All rules are explicit lookup tables or regexes so they can be explained in an interview
and extended when new raw values appear (unknown values are logged, not guessed).
"""
import re
import unicodedata

# ----------------------------------------------------------------------------- units
# canonical: mass -> kg, volume -> l, count -> unit
UNIT_MAP = {
    "g": ("kg", 0.001), "gm": ("kg", 0.001), "gms": ("kg", 0.001), "gram": ("kg", 0.001),
    "grams": ("kg", 0.001), "gr": ("kg", 0.001),
    "kg": ("kg", 1.0), "kgs": ("kg", 1.0), "kilo": ("kg", 1.0),
    "mg": ("kg", 0.000001),
    "ml": ("l", 0.001), "millilitre": ("l", 0.001), "milliliter": ("l", 0.001),
    "cl": ("l", 0.01), "l": ("l", 1.0), "ltr": ("l", 1.0), "litre": ("l", 1.0),
    "liter": ("l", 1.0), "lt": ("l", 1.0),
    "pc": ("unit", 1.0), "pcs": ("unit", 1.0), "piece": ("unit", 1.0), "pieces": ("unit", 1.0),
    "unit": ("unit", 1.0), "units": ("unit", 1.0), "n": ("unit", 1.0),
    "dozen": ("unit", 12.0),
}
QTY_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(kgs?|kilo|gms?|grams?|gr|g|mg|ml|millilit(?:re|er)|cl|ltr|litre|liter|lt|l|pcs?|pieces?|units?|dozen)(?![a-z])",
    re.I,
)
MULTIPACK_RE = re.compile(r"(\d+)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gm|ml|l)\b", re.I)


def unit_to_std(unit):
    if unit is None:
        return None, None
    return UNIT_MAP.get(str(unit).strip().lower().rstrip("."), (None, None))


def parse_quantity(text):
    """Return (qty_in_std_unit, std_unit, matched_text) from free text such as
    '500 g', '2 x 200ml', '1 Dozen', '70gms'. None if nothing parseable."""
    if not text:
        return None, None, None
    t = str(text)
    m = MULTIPACK_RE.search(t)
    if m:
        n, q, u = int(m.group(1)), float(m.group(2).replace(",", ".")), m.group(3)
        std, f = unit_to_std(u)
        if std:
            return n * q * f, std, m.group(0)
    m = QTY_RE.search(t)
    if m:
        q, u = float(m.group(1).replace(",", ".")), m.group(2)
        std, f = unit_to_std(u)
        if std and q > 0:
            return q * f, std, m.group(0)
    return None, None, None


def doca_unit(unit_text):
    """DoCA reporting unit e.g. '1 Kg', '100 gm', '1 Dozen', '1 Ltr', '1 kg'."""
    q, std, _ = parse_quantity(unit_text)
    return q, std


# ----------------------------------------------------------------------------- text
def clean_text(s):
    if s is None:
        return None
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = re.sub(r"\s+", " ", s)
    return s or None


def product_name_std(name):
    """Upper-case-insensitive display name: trim, collapse spaces, title-case only
    if the original was ALL CAPS or all lower (keeps brand stylings like 'Parle-G')."""
    n = clean_text(name)
    if not n:
        return None
    if n.isupper() or n.islower():
        n = n.title()
    return n


BRAND_ALIASES = {
    "brotannica": "Britannia", "brit": "Britannia", "britannia": "Britannia",
    "coca cola": "Coca-Cola", "coca-cola": "Coca-Cola", "coke": "Coca-Cola",
    "nestle": "Nestlé", "nestlé": "Nestlé", "maggi": "Nestlé (Maggi)",
    "amul": "Amul", "parle": "Parle", "parle agro": "Parle Agro",
    "balaji": "Balaji Wafers", "balaji wafers": "Balaji Wafers",
    "paper boat": "Paper Boat", "kurkure": "Kurkure (PepsiCo)", "lay's": "Lay's (PepsiCo)", "lays": "Lay's (PepsiCo)",
    "haldiram's": "Haldiram's", "haldirams": "Haldiram's", "haldiram": "Haldiram's",
    "oral-b is sold by procter & gamble": "Oral-B", "oral-b": "Oral-B", "oral b": "Oral-B",
    "dmart": "DMart (private label)", "dmart premia": "DMart (private label)",
    "mtr": "MTR", "itc": "ITC", "sunfeast": "ITC (Sunfeast)", "bingo": "ITC (Bingo)",
    "colgate": "Colgate", "colgate-palmolive": "Colgate", "dabur": "Dabur", "patanjali": "Patanjali",
    "tata": "Tata", "tata sampann": "Tata", "tata consumer products": "Tata",
    "mother dairy": "Mother Dairy", "coca-cola company": "Coca-Cola", "the coca-cola company": "Coca-Cola",
    "dabur india ltd.": "Dabur", "dabur india ltd": "Dabur", "dabur india limited": "Dabur",
    "hindustan unilever limited": "Hindustan Unilever", "hul": "Hindustan Unilever", "hindustan unilever": "Hindustan Unilever", "epigamia": "Epigamia", "vita": "Vita",
}


def brand_std(brands_field):
    """OFF `brands` is a comma-separated list; first listed brand is the primary brand."""
    b = clean_text(brands_field)
    if not b:
        return None, "missing"
    first = clean_text(b.split(",")[0])
    if not first:
        return None, "missing"
    key = first.lower()
    if key in BRAND_ALIASES:
        return BRAND_ALIASES[key], ("alias_mapped" if BRAND_ALIASES[key] != first else "as_is")
    std = first if not (first.isupper() or first.islower()) else first.title()
    return std, ("case_normalised" if std != first else "as_is")


# ----------------------------------------------------------------------------- categories
# (category_group, category) ; first matching rule wins (most specific first)
OFF_CATEGORY_RULES = [
    (("en:electronic-products", "en:usb-cables", "en:lamps"), ("Out of scope", "Electronics")),
    (("en:alcoholic-beverages", "en:beers", "en:wines"), ("Out of scope", "Alcohol")),
    (("en:toothpastes", "en:toothbrushes", "en:hygiene", "en:body", "en:soap", "en:shampoos",
      "en:open-beauty-facts", "en:deodorants", "en:skin-care", "en:hair"), ("Personal Care", "Personal Hygiene & Care")),
    (("en:baby-toddler", "en:diapers", "en:diapering"), ("Personal Care", "Baby Care")),
    (("en:household-chemicals", "en:liquid-detergent", "en:detergents", "en:cleaning"), ("Household", "Cleaning & Laundry")),
    (("en:pet-food", "en:dog-food", "en:cat-food"), ("Household", "Pet Food")),
    (("en:vegetable-oils", "en:animal-fats", "en:ghees", "en:vegetable-fats", "en:butters"), ("Groceries", "Edible Oils & Ghee")),
    (("en:rices", "en:flours", "en:wheat-flours", "en:cereal-grains", "en:legumes", "en:pulses",
      "en:legumes-and-their-products", "en:sugars", "en:salts", "en:spices", "en:teas", "en:coffees"),
     ("Groceries", "Staples, Spices & Hot Beverages")),
    (("en:milks", "en:milks-liquid-and-powder", "en:cheeses", "en:paneer", "en:yogurts",
      "en:fermented-milk-products", "en:dairy-drinks", "en:dairies"), ("Packaged Food", "Dairy")),
    (("en:biscuits", "en:biscuits-and-cakes", "en:biscuits-and-crackers", "en:breads", "en:cakes"),
     ("Packaged Food", "Biscuits, Bread & Bakery")),
    (("en:salty-snacks", "en:crisps", "en:chips-and-fries", "en:namkeen", "en:appetizers", "en:popcorn"),
     ("Packaged Food", "Salty Snacks & Namkeen")),
    (("en:confectioneries", "en:chocolates", "en:chocolate-candies", "en:sweet-snacks", "en:bars",
      "en:ice-creams", "en:frozen-desserts", "en:desserts"), ("Packaged Food", "Chocolates, Sweets & Desserts")),
    (("en:beverages", "en:sodas", "en:waters", "en:plant-based-beverages", "en:fruit-based-beverages",
      "en:beverages-and-beverages-preparations"), ("Packaged Food", "Beverages")),
    (("en:breakfast-cereals", "en:mueslis", "en:rolled-oats", "en:noodles", "en:instant-noodles",
      "en:pastas", "en:meals"), ("Packaged Food", "Breakfast, Noodles & Ready Meals")),
    (("en:sauces", "en:condiments", "en:ketchup", "en:spreads", "en:jams", "en:peanut-butters",
      "en:nut-butters"), ("Packaged Food", "Sauces, Spreads & Condiments")),
    (("en:nuts", "en:dried-fruits", "en:dates", "en:seeds", "en:nuts-and-their-products"),
     ("Packaged Food", "Nuts, Seeds & Dry Fruits")),
    (("en:dietary-supplements", "en:bodybuilding-supplements", "en:protein-bars"), ("Packaged Food", "Health & Supplements")),
]
SOURCE_DEFAULT_CATEGORY = {
    "obf": ("Personal Care", "Personal Hygiene & Care"),
    "opff": ("Household", "Pet Food"),
    "opf": ("Household", "Other Household"),
}


def off_category(categories_tags, product_source):
    tags = set(categories_tags or [])
    for keys, cat in OFF_CATEGORY_RULES:
        if tags.intersection(keys):
            return cat, "tag_rule"
    if product_source in SOURCE_DEFAULT_CATEGORY:
        return SOURCE_DEFAULT_CATEGORY[product_source], "source_default"
    if tags:
        return ("Packaged Food", "Other Packaged Food"), "tag_unmatched"
    return ("Unclassified", "Unclassified"), "no_tags"


# DoCA commodity -> (std name, category_group, category, commodity_code)
DOCA_COMMODITIES = {
    "rice": ("Rice", "Groceries", "Cereals & Flours"),
    "broken rice": ("Broken Rice", "Groceries", "Cereals & Flours"),
    "wheat": ("Wheat", "Groceries", "Cereals & Flours"),
    "atta (wheat)": ("Atta (Wheat)", "Groceries", "Cereals & Flours"),
    "maida (wheat)": ("Maida (Wheat)", "Groceries", "Cereals & Flours"),
    "suji (whole)": ("Suji", "Groceries", "Cereals & Flours"),
    "bajra (whole)": ("Bajra", "Groceries", "Cereals & Flours"),
    "jowar (whole)": ("Jowar", "Groceries", "Cereals & Flours"),
    "ragi (whole)": ("Ragi", "Groceries", "Cereals & Flours"),
    "gram dal": ("Gram Dal", "Groceries", "Pulses"),
    "gram dal(bharat dal adjusted)": ("Gram Dal (Bharat Dal adjusted)", "Groceries", "Pulses"),
    "tur/arhar dal": ("Tur/Arhar Dal", "Groceries", "Pulses"),
    "urad dal": ("Urad Dal", "Groceries", "Pulses"),
    "moong dal": ("Moong Dal", "Groceries", "Pulses"),
    "masoor dal": ("Masoor Dal", "Groceries", "Pulses"),
    "besan": ("Besan", "Groceries", "Pulses"),
    "groundnut oil (packed)": ("Groundnut Oil (Packed)", "Groceries", "Edible Oils & Ghee"),
    "mustard oil (packed)": ("Mustard Oil (Packed)", "Groceries", "Edible Oils & Ghee"),
    "vanaspati (packed)": ("Vanaspati (Packed)", "Groceries", "Edible Oils & Ghee"),
    "soya oil (packed)": ("Soya Oil (Packed)", "Groceries", "Edible Oils & Ghee"),
    "sunflower oil (packed)": ("Sunflower Oil (Packed)", "Groceries", "Edible Oils & Ghee"),
    "palm oil (packed)": ("Palm Oil (Packed)", "Groceries", "Edible Oils & Ghee"),
    "desi ghee": ("Desi Ghee", "Groceries", "Edible Oils & Ghee"),
    "potato": ("Potato", "Groceries", "Vegetables"),
    "onion": ("Onion", "Groceries", "Vegetables"),
    "tomato": ("Tomato", "Groceries", "Vegetables"),
    "brinjal": ("Brinjal", "Groceries", "Vegetables"),
    "ginger": ("Ginger", "Groceries", "Vegetables"),
    "garlic": ("Garlic", "Groceries", "Vegetables"),
    "banana": ("Banana", "Groceries", "Fruits"),
    "sugar": ("Sugar", "Groceries", "Sugar & Gur"),
    "gur": ("Gur", "Groceries", "Sugar & Gur"),
    "milk": ("Milk", "Groceries", "Milk, Dairy & Eggs"),
    "milk (₹/ltr)": ("Milk", "Groceries", "Milk, Dairy & Eggs"),
    "milk @": ("Milk", "Groceries", "Milk, Dairy & Eggs"),
    "butter (pasteurised)": ("Butter (Pasteurised)", "Groceries", "Milk, Dairy & Eggs"),
    "eggs": ("Eggs", "Groceries", "Milk, Dairy & Eggs"),
    "tea loose": ("Tea (Loose)", "Groceries", "Tea, Salt & Spices"),
    "salt pack (iodised)": ("Salt (Iodised, Packed)", "Groceries", "Tea, Salt & Spices"),
    "black pepper (whole)": ("Black Pepper", "Groceries", "Tea, Salt & Spices"),
    "coriander (whole)": ("Coriander (Whole)", "Groceries", "Tea, Salt & Spices"),
    "cummin seed (whole)": ("Cumin Seed", "Groceries", "Tea, Salt & Spices"),
    "red chillies (whole)": ("Red Chillies (Whole)", "Groceries", "Tea, Salt & Spices"),
    "turmeric (powder)": ("Turmeric (Powder)", "Groceries", "Tea, Salt & Spices"),
}


def doca_commodity(raw):
    key = clean_text(raw).lower()
    key = re.sub(r"\s+", " ", key)
    if key in DOCA_COMMODITIES:
        return DOCA_COMMODITIES[key]
    return None


def commodity_code(std_name):
    return "DOCA-" + re.sub(r"[^A-Z0-9]+", "_", std_name.upper()).strip("_")


# ----------------------------------------------------------------------------- locations
CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru urban": "Bengaluru", "bangalore south": "Bengaluru",
    "bangalore east": "Bengaluru", "pune city": "Pune", "pimpri-chinchwad": "Pune (Pimpri-Chinchwad)",
    "mumbai city": "Mumbai", "mumbai suburban": "Mumbai", "nagpur city": "Nagpur",
    "new delhi": "Delhi", "west delhi": "Delhi", "kochi": "Kochi (Ernakulam)", "ernakulam": "Kochi (Ernakulam)",
    "thiruvananthapuram": "Thiruvananthapuram", "gurugram": "Gurugram", "gurgaon": "Gurugram",
    "sahibzada ajit singh nagar": "Mohali",
}
STATE_REGION = {
    "Delhi": "North", "Haryana": "North", "Punjab": "North", "Uttar Pradesh": "North", "Uttarakhand": "North",
    "Himachal Pradesh": "North", "Jammu and Kashmir": "North", "Chandigarh": "North", "Rajasthan": "North",
    "Gujarat": "West", "Maharashtra": "West", "Goa": "West",
    "Madhya Pradesh": "Central", "Chhattisgarh": "Central",
    "Karnataka": "South", "Tamil Nadu": "South", "Kerala": "South", "Telangana": "South",
    "Andhra Pradesh": "South", "Puducherry": "South",
    "West Bengal": "East", "Odisha": "East", "Bihar": "East", "Jharkhand": "East",
    "Assam": "North-East", "Meghalaya": "North-East", "Manipur": "North-East", "Tripura": "North-East",
    "Nagaland": "North-East", "Mizoram": "North-East", "Arunachal Pradesh": "North-East", "Sikkim": "North-East",
}
STATES = set(STATE_REGION)


def parse_osm_location(loc):
    """Return dict(city, state, region, outlet_type, outlet_name, lat, lon, city_source)."""
    loc = loc or {}
    disp = [clean_text(x) for x in (loc.get("osm_display_name") or "").split(",")]
    disp = [x for x in disp if x]
    state = next((p for p in reversed(disp) if p in STATES), None)
    city_raw = clean_text(loc.get("osm_address_city"))
    city_source = "osm_address_city"
    if not city_raw and state:
        i = disp.index(state)
        city_raw = disp[i - 1] if i >= 1 else None
        city_source = "parsed_display_name"
    if not city_raw and state == "Delhi":
        city_raw, city_source = "Delhi", "state_is_city"
    city = CITY_ALIASES.get((city_raw or "").lower(), city_raw)
    if city and city.lower().endswith(" district"):
        city = city[: -len(" district")]
    return {
        "city": city, "city_raw": city_raw, "city_source": city_source if city else "missing",
        "state": state, "region": STATE_REGION.get(state),
        "country": loc.get("osm_address_country_code"),
        "outlet_type": clean_text(loc.get("osm_tag_value")),
        "outlet_name": clean_text(loc.get("osm_name")),
        "lat": loc.get("osm_lat"), "lon": loc.get("osm_lon"),
    }
