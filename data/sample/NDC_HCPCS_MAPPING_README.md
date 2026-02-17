# NDC-HCPCS Mapping File Documentation

> **File:** `ndc_hcpcs_mapping.csv`
> **Created:** January 24, 2026
> **Source:** CMS ASP NDC-HCPCS Crosswalk (Q1 2025)

---

## Purpose

This file provides a clean, normalized mapping between 11-digit NDC codes and HCPCS billing codes. It is essential for:

1. **Medicare Part B margin calculations** - Determining which drugs can be billed through medical benefit
2. **Billing unit conversion** - Converting NDC package quantities to HCPCS billing units
3. **ASP pricing lookup** - Joining to ASP pricing file via HCPCS code

---

## Source Data

The mapping is derived from the CMS ASP NDC-HCPCS Crosswalk file:

- **Source File:** `asp_crosswalk.csv`
- **Original Source:** [CMS ASP Pricing Files](https://www.cms.gov/medicare/payment/part-b-drugs/asp-pricing-files)
- **Header Rows to Skip:** 8 (CMS metadata)
- **Key Columns Used:**
  - `NDC2` → NDC code (with dashes)
  - `_2025_CODE` → HCPCS code (column name varies by quarter)
  - `Short Description` → HCPCS description
  - `Drug Name` → Product name
  - `LABELER NAME` → Manufacturer
  - `HCPCS dosage` → Billing unit description
  - `PKG SIZE` → Amount per item
  - `PKG QTY` → Items per NDC package
  - `BILLUNITS` → Billing units per item
  - `BILLUNITSPKG` → Total billing units per NDC

---

## Reconstruction Steps

### Step 1: Load the CMS Crosswalk File

```python
import pandas as pd

# Load crosswalk, skipping 8 header rows
crosswalk = pd.read_csv(
    'data/sample/asp_crosswalk.csv',
    skiprows=8,
    encoding='latin-1'
)
```

### Step 2: Normalize NDC to 11-Digit Format

```python
# Remove dashes, strip whitespace, pad to 11 digits
crosswalk['NDC11'] = (
    crosswalk['NDC2']
    .astype(str)
    .str.replace('-', '')
    .str.strip()
    .str.zfill(11)
    .str[-11:]  # Take last 11 chars in case of overflow
)
```

### Step 3: Normalize HCPCS Code

```python
# Clean and uppercase HCPCS
crosswalk['HCPCS'] = (
    crosswalk['_2025_CODE']  # Column name varies by quarter
    .astype(str)
    .str.strip()
    .str.upper()
)
```

### Step 4: Filter Invalid Data

```python
# Keep only valid NDC11 (exactly 11 characters)
crosswalk = crosswalk[crosswalk['NDC11'].str.len() == 11]

# Remove empty/null HCPCS
crosswalk = crosswalk[crosswalk['HCPCS'].str.len() > 0]
crosswalk = crosswalk[crosswalk['HCPCS'] != 'NAN']
```

### Step 5: Identify NDCs with Multiple HCPCS Codes

Some NDCs legitimately map to multiple HCPCS codes (e.g., ESRD vs non-ESRD billing codes). Flag these:

```python
# Count unique HCPCS per NDC
ndc_hcpcs_count = crosswalk.groupby('NDC11')['HCPCS'].nunique()

# Identify NDCs with multiple codes
multi_hcpcs_ndcs = set(ndc_hcpcs_count[ndc_hcpcs_count > 1].index)
```

### Step 6: Create One-Row-Per-NDC Mapping

Take the first HCPCS code for each NDC (deterministic ordering):

```python
# Group by NDC, take first row
mapping = crosswalk.groupby('NDC11').first().reset_index()

# Add flag for multiple HCPCS
mapping['has_multiple_hcpcs'] = mapping['NDC11'].isin(multi_hcpcs_ndcs)

# Add all HCPCS codes for flagged NDCs
def get_all_hcpcs(ndc):
    if ndc in multi_hcpcs_ndcs:
        codes = crosswalk[crosswalk['NDC11'] == ndc]['HCPCS'].unique()
        return '|'.join(sorted(codes))
    return ''

mapping['all_hcpcs_codes'] = mapping['NDC11'].apply(get_all_hcpcs)
```

### Step 7: Select and Rename Columns

```python
# Rename to standard column names
mapping_output = mapping.rename(columns={
    'NDC11': 'ndc11',
    'HCPCS': 'hcpcs_code',
    'Short Description': 'hcpcs_description',
    'Drug Name': 'drug_name',
    'LABELER NAME': 'manufacturer',
    'HCPCS dosage': 'hcpcs_dosage',
    'PKG SIZE': 'pkg_size',
    'PKG QTY': 'pkg_qty',
    'BILLUNITS': 'bill_units_per_item',
    'BILLUNITSPKG': 'bill_units_per_pkg',
    'has_multiple_hcpcs': 'has_multiple_hcpcs',
    'all_hcpcs_codes': 'all_hcpcs_codes'
})
```

### Step 8: Save to CSV

```python
mapping_output.to_csv('data/sample/ndc_hcpcs_mapping.csv', index=False)
```

---

## Output File Schema

| Column | Type | Description |
|--------|------|-------------|
| `ndc11` | string | 11-digit NDC code (primary key) |
| `hcpcs_code` | string | Primary HCPCS billing code (J-code, Q-code, etc.) |
| `hcpcs_description` | string | Short description of HCPCS code |
| `drug_name` | string | Drug product name |
| `manufacturer` | string | Labeler/manufacturer name |
| `hcpcs_dosage` | string | Billing unit description (e.g., "5 mg", "1 ml") |
| `pkg_size` | float | Amount per item (e.g., 0.5 mL per vial) |
| `pkg_qty` | float | Number of items per NDC package |
| `bill_units_per_item` | float | HCPCS billing units per item |
| `bill_units_per_pkg` | float | **Total billing units per NDC** (key for margin calc) |
| `has_multiple_hcpcs` | boolean | True if NDC maps to multiple HCPCS codes |
| `all_hcpcs_codes` | string | All HCPCS codes (pipe-separated) if multiple |

---

## Mapping Relationship Analysis

### NDC → HCPCS (One-to-One with Exceptions)

- **7,928 NDCs** (98.3%) map to exactly 1 HCPCS code
- **139 NDCs** (1.7%) map to multiple HCPCS codes

### Why Multiple HCPCS Codes?

| Pattern | Example | Reason |
|---------|---------|--------|
| ESRD vs Non-ESRD | J0881/J0882, Q5105/Q5106 | Different codes for dialysis patients |
| Volume-based | J7030/J7040/J7050 | Different codes for IV fluid volumes |
| Vaccine vs Therapeutic | 90586/J9030 | BCG can be vaccine or cancer treatment |
| Skin substitutes | Q4252/Q4279 | Different product configurations |

### HCPCS → NDC (One-to-Many)

- Each HCPCS code maps to **multiple NDCs** (average: 8.5)
- This is expected: same drug from different manufacturers share billing code
- Example: J7512 (Prednisone) has 175 different NDCs

---

## Usage in Margin Calculations

### Medicare Margin Formula

```
Medicare Revenue = ASP × 1.06 × Bill Units Per Package
Medicare Margin = Revenue - Contract Cost

Where:
- ASP = Payment Limit from asp_pricing.csv ÷ 1.06
- Bill Units Per Package = bill_units_per_pkg from this mapping
- Contract Cost = Unit Price (Current Catalog) from product_catalog.xlsx
```

### Join Chain

```
Product Catalog (NDC, Contract Cost, AWP)
       ↓ JOIN ON ndc11
NDC-HCPCS Mapping (ndc11 → hcpcs_code, bill_units_per_pkg)
       ↓ JOIN ON hcpcs_code
ASP Pricing (HCPCS Code → Payment Limit)
```

---

## Coverage Statistics

| Metric | Count |
|--------|-------|
| Total NDCs in mapping | 8,067 |
| Unique HCPCS codes | 961 |
| NDCs with multiple HCPCS | 139 |
| Product Catalog NDCs with mapping | 3,962 (13.1%) |
| Product Catalog NDCs without mapping | 26,250 (86.9%) |

**Note:** Most drugs in the Product Catalog are retail-only (oral medications, OTC products) and do not have Medicare Part B medical billing codes.

---

## Updating the Mapping

CMS releases updated ASP crosswalk files quarterly. To update:

1. Download new crosswalk from [CMS ASP Pricing Files](https://www.cms.gov/medicare/payment/part-b-drugs/asp-pricing-files)
2. Note the HCPCS code column name (e.g., `_2026_CODE` for 2026)
3. Run the reconstruction steps above with the new file
4. Verify row counts are similar (±10%)
5. Check for new drugs added or removed

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-24 | 1.0 | Initial creation from Q1 2025 CMS crosswalk |
