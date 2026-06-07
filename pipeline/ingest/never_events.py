"""
TrustPulse -- pipeline/ingest/never_events.py
Ingests NHS Never Events data from StEIS system.

Output:
    data/processed/never_events_clean.csv

Metrics per trust per year:
    ne_count          : total never events reported
    ne_provisional    : 1 if provisional data, 0 if final

Source:
    NHS England Never Events publications. Table 3 from each annual report.
    Data stored by organisation name and resolved to org_code at runtime
    using fuzzy matching against the TrustPulse spine.
    
    2022-23: Final update (published December 2025). 401 confirmed events.
    2023-24: Provisional (published May 2024). 370 events.
    2024-25: Provisional (published July 2025). 403 events.
    2025-26: Provisional (published May 2026). 403 events.

Notes:
    - All StEIS Never Events data is provisional by design
    - Private provider incidents excluded (only NHS trust org codes in scope)
    - National total ~400 per year; most trusts report 0-3
    - 6+ per year = significant governance signal
"""

import os
import re
import pandas as pd
import numpy as np

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED   = os.path.join(BASE_DIR, "data", "processed")
MASTER_PATH = os.path.join(PROCESSED, "trust_master.csv")
OUTPUT_FILE = os.path.join(PROCESSED, "never_events_clean.csv")

PERIOD_MAP = {
    "2022-23": pd.Timestamp("2023-03-31"),
    "2023-24": pd.Timestamp("2024-03-31"),
    "2024-25": pd.Timestamp("2025-03-31"),
    "2025-26": pd.Timestamp("2026-03-31"),
}

# Table 3 data stored as (organisation_name, count) tuples
# Private providers included in source but excluded at matching stage
NE_BY_YEAR = {
    "2022-23": {"provisional": 0, "data": [
        ("Airedale NHS Foundation Trust", 1),
        ("Alder Hey Children's NHS Foundation Trust", 1),
        ("Ashford and St Peter's Hospitals NHS Foundation Trust", 5),
        ("Barking, Havering and Redbridge University Hospitals NHS Trust", 7),
        ("Barts Health NHS Trust", 4),
        ("Basildon and Thurrock University Hospitals NHS Foundation Trust", 1),
        ("Bedfordshire Hospitals NHS Foundation Trust", 3),
        ("Birmingham Women's and Children's NHS Foundation Trust", 7),
        ("Bradford Teaching Hospitals NHS Foundation Trust", 1),
        ("Brighton and Sussex University Hospitals NHS Trust", 1),
        ("Buckinghamshire Healthcare NHS Trust", 1),
        ("Calderdale and Huddersfield NHS Foundation Trust", 4),
        ("Cambridge University Hospitals NHS Foundation Trust", 2),
        ("Chelsea and Westminster Hospital NHS Foundation Trust", 1),
        ("Countess of Chester Hospital NHS Foundation Trust", 4),
        ("Dartford and Gravesham NHS Trust", 2),
        ("Doncaster and Bassetlaw Teaching Hospitals NHS Foundation Trust", 2),
        ("Dorset County Hospital NHS Foundation Trust", 1),
        ("East and North Hertfordshire Teaching NHS Trust", 2),
        ("East Cheshire NHS Trust", 1),
        ("East Kent Hospitals University NHS Foundation Trust", 6),
        ("East Lancashire Hospitals NHS Trust", 1),
        ("East Suffolk and North Essex NHS Foundation Trust", 3),
        ("East Sussex Healthcare NHS Trust", 1),
        ("Epsom and St Helier University Hospitals NHS Trust", 3),
        ("Frimley Health NHS Foundation Trust", 4),
        ("George Eliot Hospital NHS Trust", 2),
        ("Gloucestershire Hospitals NHS Foundation Trust", 2),
        ("Great Ormond Street Hospital for Children NHS Foundation Trust", 2),
        ("Great Western Hospitals NHS Foundation Trust", 2),
        ("Guy's and St Thomas' NHS Foundation Trust", 5),
        ("Hampshire Hospitals NHS Foundation Trust", 3),
        ("Harrogate and District NHS Foundation Trust", 2),
        ("Herefordshire and Worcestershire Health and Care NHS Trust", 1),
        ("Homerton Healthcare NHS Foundation Trust", 3),
        ("Hull University Teaching Hospitals NHS Trust", 6),
        ("Imperial College Healthcare NHS Trust", 2),
        ("James Paget University Hospitals NHS Foundation Trust", 2),
        ("King's College Hospital NHS Foundation Trust", 4),
        ("Kingston and Richmond NHS Foundation Trust", 3),
        ("Lancashire Teaching Hospitals NHS Foundation Trust", 2),
        ("Leeds Teaching Hospitals NHS Trust", 4),
        ("Lewisham and Greenwich NHS Trust", 5),
        ("Liverpool University Hospitals NHS Foundation Trust", 3),
        ("Liverpool Women's NHS Foundation Trust", 1),
        ("London North West University Healthcare NHS Trust", 2),
        ("Maidstone and Tunbridge Wells NHS Trust", 3),
        ("Manchester University NHS Foundation Trust", 11),
        ("Medway NHS Foundation Trust", 4),
        ("Mersey and West Lancashire Teaching Hospitals NHS Trust", 2),
        ("Mid Cheshire Hospitals NHS Foundation Trust", 1),
        ("Mid Essex Hospital Services NHS Trust", 1),
        ("Mid Yorkshire Teaching NHS Trust", 1),
        ("Milton Keynes University Hospital NHS Foundation Trust", 1),
        ("Moorfields Eye Hospital NHS Foundation Trust", 4),
        ("Newcastle Upon Tyne Hospitals NHS Foundation Trust", 7),
        ("Norfolk and Norwich University Hospitals NHS Foundation Trust", 5),
        ("North Bristol NHS Trust", 5),
        ("North Middlesex University Hospital NHS Trust", 4),
        ("North Tees and Hartlepool NHS Foundation Trust", 4),
        ("North West Anglia NHS Foundation Trust", 5),
        ("Northampton General Hospital NHS Trust", 3),
        ("Northern Care Alliance NHS Foundation Trust", 4),
        ("Northern Devon Healthcare NHS Trust", 4),
        ("Northumbria Healthcare NHS Foundation Trust", 4),
        ("Nottingham University Hospitals NHS Trust", 6),
        ("Oxford University Hospitals NHS Foundation Trust", 7),
        ("Poole Hospital NHS Foundation Trust", 4),
        ("Portsmouth Hospitals University NHS Trust", 4),
        ("Queen Victoria Hospital NHS Foundation Trust", 1),
        ("Robert Jones Agnes Hunt Orthopaedic Hospital NHS Foundation Trust", 3),
        ("Royal Berkshire NHS Foundation Trust", 3),
        ("Royal Cornwall Hospitals NHS Trust", 1),
        ("Royal Devon University Healthcare NHS Foundation Trust", 6),
        ("Royal Free London NHS Foundation Trust", 8),
        ("Royal National Orthopaedic Hospital NHS Trust", 1),
        ("Royal Surrey NHS Foundation Trust", 3),
        ("Royal United Hospitals Bath NHS Foundation Trust", 3),
        ("Sandwell and West Birmingham Hospitals NHS Trust", 4),
        ("Sheffield Children's NHS Foundation Trust", 2),
        ("Sheffield Teaching Hospitals NHS Foundation Trust", 5),
        ("Sherwood Forest Hospitals NHS Foundation Trust", 1),
        ("Shropshire and Telford Hospitals NHS Trust", 3),
        ("Somerset NHS Foundation Trust", 5),
        ("South Tees Hospitals NHS Foundation Trust", 7),
        ("South Tyneside and Sunderland NHS Foundation Trust", 2),
        ("South Warwickshire University NHS Foundation Trust", 2),
        ("Southport and Ormskirk Hospital NHS Trust", 3),
        ("St George's University Hospitals NHS Foundation Trust", 4),
        ("Surrey and Sussex Healthcare NHS Trust", 1),
        ("Tameside and Glossop Integrated Care NHS Foundation Trust", 1),
        ("The Dudley Group NHS Foundation Trust", 1),
        ("The Princess Alexandra Hospital NHS Trust", 3),
        ("The Royal Marsden NHS Foundation Trust", 2),
        ("Torbay and South Devon NHS Foundation Trust", 3),
        ("United Lincolnshire Teaching Hospitals NHS Trust", 6),
        ("University College London Hospitals NHS Foundation Trust", 3),
        ("University Hospital Southampton NHS Foundation Trust", 5),
        ("University Hospitals Birmingham NHS Foundation Trust", 11),
        ("University Hospitals Bristol and Weston NHS Foundation Trust", 4),
        ("University Hospitals Coventry and Warwickshire NHS Trust", 5),
        ("University Hospitals of Derby and Burton NHS Foundation Trust", 3),
        ("University Hospitals of Leicester NHS Trust", 8),
        ("University Hospitals of Morecambe Bay NHS Foundation Trust", 2),
        ("University Hospitals of North Midlands NHS Trust", 3),
        ("University Hospitals Plymouth NHS Trust", 4),
        ("Walsall Healthcare NHS Trust", 2),
        ("Warrington and Halton Teaching Hospitals NHS Foundation Trust", 3),
        ("West Hertfordshire Teaching Hospitals NHS Trust", 3),
        ("West Suffolk NHS Foundation Trust", 2),
        ("Whittington Health NHS Trust", 1),
        ("Wirral University Teaching Hospital NHS Foundation Trust", 2),
        ("Worcestershire Acute Hospitals NHS Trust", 4),
        ("Wrightington, Wigan and Leigh NHS Foundation Trust", 3),
        ("Wye Valley NHS Trust", 1),
        ("Yeovil District Hospital NHS Foundation Trust", 1),
        ("York and Scarborough Teaching Hospitals NHS Foundation Trust", 5),
    ]},
    "2023-24": {"provisional": 1, "data": [
        ("Alder Hey Children's NHS Foundation Trust", 1),
        ("Ashford and St Peter's Hospitals NHS Foundation Trust", 2),
        ("Barking, Havering and Redbridge University Hospitals NHS Trust", 6),
        ("Barnsley Hospital NHS Foundation Trust", 1),
        ("Barts Health NHS Trust", 8),
        ("Basildon and Thurrock University Hospitals NHS Foundation Trust", 2),
        ("Bedfordshire Hospitals NHS Foundation Trust", 1),
        ("Blackpool Teaching Hospitals NHS Foundation Trust", 1),
        ("Bolton NHS Foundation Trust", 2),
        ("Bradford Teaching Hospitals NHS Foundation Trust", 2),
        ("Brighton and Sussex University Hospitals NHS Trust", 4),
        ("Buckinghamshire Healthcare NHS Trust", 4),
        ("Calderdale and Huddersfield NHS Foundation Trust", 7),
        ("Cambridge University Hospitals NHS Foundation Trust", 2),
        ("Chelsea and Westminster Hospital NHS Foundation Trust", 5),
        ("Chesterfield Royal Hospital NHS Foundation Trust", 2),
        ("County Durham and Darlington NHS Foundation Trust", 1),
        ("Derbyshire Community Health Services NHS Foundation Trust", 1),
        ("Dorset County Hospital NHS Foundation Trust", 1),
        ("East and North Hertfordshire NHS Trust", 2),
        ("East Cheshire NHS Trust", 2),
        ("East Kent Hospitals University NHS Foundation Trust", 7),
        ("East Lancashire Hospitals NHS Trust", 4),
        ("East Suffolk and North Essex NHS Foundation Trust", 5),
        ("East Sussex Healthcare NHS Trust", 1),
        ("Epsom and St Helier University Hospitals NHS Trust", 4),
        ("Frimley Health NHS Foundation Trust", 3),
        ("Gateshead Health NHS Foundation Trust", 1),
        ("George Eliot Hospital NHS Trust", 2),
        ("Gloucestershire Hospitals NHS Foundation Trust", 3),
        ("Great Ormond Street Hospital for Children NHS Foundation Trust", 1),
        ("Great Western Hospitals NHS Foundation Trust", 4),
        ("Guy's and St Thomas' NHS Foundation Trust", 4),
        ("Hampshire Hospitals NHS Foundation Trust", 4),
        ("Harrogate and District NHS Foundation Trust", 1),
        ("Hull University Teaching Hospitals NHS Trust", 1),
        ("Imperial College Healthcare NHS Trust", 4),
        ("Isle of Wight NHS Trust", 1),
        ("James Paget University Hospitals NHS Foundation Trust", 2),
        ("King's College Hospital NHS Foundation Trust", 4),
        ("Kingston Hospital NHS Foundation Trust", 7),
        ("Lancashire Teaching Hospitals NHS Foundation Trust", 3),
        ("Leeds Teaching Hospitals NHS Trust", 6),
        ("Lewisham and Greenwich NHS Trust", 4),
        ("Liverpool University Hospitals NHS Foundation Trust", 3),
        ("Liverpool Women's NHS Foundation Trust", 2),
        ("London North West University Healthcare NHS Trust", 3),
        ("Manchester University NHS Foundation Trust", 4),
        ("Mid and South Essex NHS Foundation Trust", 2),
        ("Mid Cheshire Hospitals NHS Foundation Trust", 1),
        ("Mid Essex Hospital Services NHS Trust", 2),
        ("Mid Yorkshire Hospitals NHS Trust", 3),
        ("Milton Keynes University Hospital NHS Foundation Trust", 1),
        ("Moorfields Eye Hospital NHS Foundation Trust", 2),
        ("Norfolk and Norwich University Hospitals NHS Foundation Trust", 3),
        ("North Bristol NHS Trust", 2),
        ("North West Anglia NHS Foundation Trust", 3),
        ("Northampton General Hospital NHS Trust", 2),
        ("Northern Care Alliance NHS Foundation Trust", 5),
        ("Northumbria Healthcare NHS Foundation Trust", 1),
        ("Nottingham University Hospitals NHS Trust", 4),
        ("Poole Hospital NHS Foundation Trust", 2),
        ("Portsmouth Hospitals University NHS Trust", 1),
        ("Royal Berkshire NHS Foundation Trust", 6),
        ("Royal Cornwall Hospitals NHS Trust", 4),
        ("Royal Devon University Healthcare NHS Foundation Trust", 5),
        ("Royal Free London NHS Foundation Trust", 2),
        ("Royal National Orthopaedic Hospital NHS Trust", 2),
        ("Royal Papworth Hospital NHS Foundation Trust", 1),
        ("Royal Surrey NHS Foundation Trust", 2),
        ("Royal United Hospitals Bath NHS Foundation Trust", 3),
        ("Salisbury NHS Foundation Trust", 4),
        ("Sheffield Children's NHS Foundation Trust", 3),
        ("Sheffield Teaching Hospitals NHS Foundation Trust", 3),
        ("Sherwood Forest Hospitals NHS Foundation Trust", 2),
        ("Somerset NHS Foundation Trust", 2),
        ("South Tees Hospitals NHS Foundation Trust", 3),
        ("South Tyneside and Sunderland NHS Foundation Trust", 1),
        ("South Warwickshire University NHS Foundation Trust", 2),
        ("St George's University Hospitals NHS Foundation Trust", 10),
        ("St Helens and Knowsley Teaching Hospitals NHS Trust", 1),
        ("Stockport NHS Foundation Trust", 1),
        ("Surrey and Sussex Healthcare NHS Trust", 1),
        ("Tameside and Glossop Integrated Care NHS Foundation Trust", 1),
        ("The Dudley Group NHS Foundation Trust", 1),
        ("The Hillingdon Hospital NHS Foundation Trust", 1),
        ("The Newcastle Upon Tyne Hospitals NHS Foundation Trust", 10),
        ("The Princess Alexandra Hospital NHS Trust", 4),
        ("The Queen Elizabeth Hospital, King's Lynn, NHS Foundation Trust", 2),
        ("The Robert Jones and Agnes Hunt Orthopaedic Hospital NHS Foundation Trust", 1),
        ("The Royal Wolverhampton NHS Trust", 1),
        ("The Shrewsbury and Telford Hospital NHS Trust", 1),
        ("The Walton Centre NHS Foundation Trust", 1),
        ("United Lincolnshire Hospitals NHS Trust", 2),
        ("University College London Hospitals NHS Foundation Trust", 4),
        ("University Hospital Southampton NHS Foundation Trust", 10),
        ("University Hospitals Birmingham NHS Foundation Trust", 11),
        ("University Hospitals Bristol and Weston NHS Foundation Trust", 1),
        ("University Hospitals Coventry and Warwickshire NHS Trust", 7),
        ("University Hospitals of Derby and Burton NHS Foundation Trust", 5),
        ("University Hospitals of Leicester NHS Trust", 4),
        ("University Hospitals of Morecambe Bay NHS Foundation Trust", 5),
        ("University Hospitals of North Midlands NHS Trust", 6),
        ("University Hospitals Plymouth NHS Trust", 4),
        ("Warrington and Halton Teaching Hospitals NHS Foundation Trust", 5),
        ("West Hertfordshire Teaching Hospitals NHS Trust", 1),
        ("West Suffolk NHS Foundation Trust", 2),
        ("Whittington Health NHS Trust", 1),
        ("Wirral University Teaching Hospital NHS Foundation Trust", 2),
        ("Worcestershire Acute Hospitals NHS Trust", 4),
        ("Wrightington, Wigan and Leigh NHS Foundation Trust", 4),
        ("Wye Valley NHS Trust", 2),
        ("York and Scarborough Teaching Hospitals NHS Foundation Trust", 4),
    ]},
    "2024-25": {"provisional": 1, "data": [
        ("Airedale NHS Foundation Trust", 1),
        ("Alder Hey Children's NHS Foundation Trust", 3),
        ("Ashford and St Peter's Hospitals NHS Foundation Trust", 2),
        ("Barking, Havering and Redbridge University Hospitals NHS Trust", 4),
        ("Barnsley Hospital NHS Foundation Trust", 1),
        ("Barts Health NHS Trust", 5),
        ("Basildon and Thurrock University Hospitals NHS Foundation Trust", 2),
        ("Bedfordshire Hospitals NHS Foundation Trust", 2),
        ("Birmingham Women's and Children's NHS Foundation Trust", 3),
        ("Blackpool Teaching Hospitals NHS Foundation Trust", 6),
        ("Bradford Teaching Hospitals NHS Foundation Trust", 1),
        ("Brighton and Sussex University Hospitals NHS Trust", 2),
        ("Buckinghamshire Healthcare NHS Trust", 2),
        ("Calderdale and Huddersfield NHS Foundation Trust", 1),
        ("Chelsea and Westminster Hospital NHS Foundation Trust", 3),
        ("Chesterfield Royal Hospital NHS Foundation Trust", 4),
        ("Countess of Chester Hospital NHS Foundation Trust", 2),
        ("County Durham and Darlington NHS Foundation Trust", 2),
        ("Croydon Health Services NHS Trust", 1),
        ("Dartford and Gravesham NHS Trust", 2),
        ("Doncaster and Bassetlaw Teaching Hospitals NHS Foundation Trust", 4),
        ("East and North Hertfordshire NHS Trust", 4),
        ("East Kent Hospitals University NHS Foundation Trust", 6),
        ("East Lancashire Hospitals NHS Trust", 2),
        ("East Suffolk and North Essex NHS Foundation Trust", 4),
        ("East Sussex Healthcare NHS Trust", 3),
        ("Epsom and St Helier University Hospitals NHS Trust", 5),
        ("Frimley Health NHS Foundation Trust", 5),
        ("Gateshead Health NHS Foundation Trust", 1),
        ("Gloucestershire Hospitals NHS Foundation Trust", 1),
        ("Great Ormond Street Hospital for Children NHS Foundation Trust", 1),
        ("Great Western Hospitals NHS Foundation Trust", 7),
        ("Guy's and St Thomas' NHS Foundation Trust", 8),
        ("Hampshire Hospitals NHS Foundation Trust", 6),
        ("Harrogate and District NHS Foundation Trust", 3),
        ("Homerton Healthcare NHS Foundation Trust", 3),
        ("Hull University Teaching Hospitals NHS Trust", 5),
        ("Imperial College Healthcare NHS Trust", 3),
        ("Isle of Wight NHS Trust", 1),
        ("Kettering General Hospital NHS Foundation Trust", 3),
        ("Kingston Hospital NHS Foundation Trust", 1),
        ("Lancashire Teaching Hospitals NHS Foundation Trust", 4),
        ("Leeds Teaching Hospitals NHS Trust", 7),
        ("Lewisham and Greenwich NHS Trust", 4),
        ("Liverpool Heart and Chest Hospital NHS Foundation Trust", 1),
        ("Liverpool University Hospitals NHS Foundation Trust", 2),
        ("Liverpool Women's NHS Foundation Trust", 2),
        ("London North West University Healthcare NHS Trust", 2),
        ("Maidstone and Tunbridge Wells NHS Trust", 3),
        ("Manchester University NHS Foundation Trust", 3),
        ("Medway NHS Foundation Trust", 1),
        ("Mersey and West Lancashire Teaching Hospitals NHS Trust", 3),
        ("Mid Yorkshire Teaching NHS Trust", 2),
        ("Milton Keynes University Hospital NHS Foundation Trust", 2),
        ("Moorfields Eye Hospital NHS Foundation Trust", 1),
        ("Norfolk and Norwich University Hospitals NHS Foundation Trust", 4),
        ("North Bristol NHS Trust", 2),
        ("North Cumbria Integrated Care NHS Foundation Trust", 2),
        ("North Tees and Hartlepool NHS Foundation Trust", 1),
        ("North West Anglia NHS Foundation Trust", 7),
        ("Northampton General Hospital NHS Trust", 2),
        ("Northern Care Alliance NHS Foundation Trust", 8),
        ("Northern Lincolnshire and Goole NHS Foundation Trust", 1),
        ("Northumbria Healthcare NHS Foundation Trust", 3),
        ("Nottingham University Hospitals NHS Trust", 5),
        ("Oxford University Hospitals NHS Foundation Trust", 1),
        ("Plymouth Hospitals NHS Trust", 2),
        ("Poole Hospital NHS Foundation Trust", 4),
        ("Portsmouth Hospitals University NHS Trust", 4),
        ("Queen Victoria Hospital NHS Foundation Trust", 1),
        ("Robert Jones and Agnes Hunt Orthopaedic Hospital NHS Foundation Trust", 2),
        ("Royal Berkshire NHS Foundation Trust", 2),
        ("Royal Cornwall Hospitals NHS Trust", 1),
        ("Royal Devon University Healthcare NHS Foundation Trust", 2),
        ("Royal Free London NHS Foundation Trust", 10),
        ("Royal National Orthopaedic Hospital NHS Trust", 1),
        ("Royal Surrey County Hospital NHS Foundation Trust", 1),
        ("Royal United Hospitals Bath NHS Foundation Trust", 4),
        ("Salisbury NHS Foundation Trust", 2),
        ("Sandwell and West Birmingham Hospitals NHS Trust", 2),
        ("Sheffield Teaching Hospitals NHS Foundation Trust", 3),
        ("Sherwood Forest Hospitals NHS Foundation Trust", 1),
        ("Shrewsbury and Telford Hospital NHS Trust", 1),
        ("Somerset NHS Foundation Trust", 2),
        ("South Central Ambulance Service NHS Foundation Trust", 1),
        ("South Tees Hospitals NHS Foundation Trust", 5),
        ("South Tyneside and Sunderland NHS Foundation Trust", 4),
        ("South Warwickshire NHS Foundation Trust", 1),
        ("Southport and Ormskirk Hospital NHS Trust", 2),
        ("St George's University Hospitals NHS Foundation Trust", 4),
        ("Stockport NHS Foundation Trust", 1),
        ("Surrey and Sussex Healthcare NHS Trust", 1),
        ("Tameside and Glossop Integrated Care NHS Foundation Trust", 3),
        ("The Christie NHS Foundation Trust", 2),
        ("The Hillingdon Hospitals NHS Foundation Trust", 3),
        ("The Newcastle Upon Tyne Hospitals NHS Foundation Trust", 2),
        ("The Princess Alexandra Hospital NHS Trust", 3),
        ("The Queen Elizabeth Hospital, King's Lynn, NHS Foundation Trust", 2),
        ("The Robert Jones and Agnes Hunt Orthopaedic Hospital NHS Foundation Trust", 1),
        ("The Rotherham NHS Foundation Trust", 1),
        ("The Royal Orthopaedic Hospital NHS Foundation Trust", 2),
        ("The Royal Wolverhampton NHS Trust", 1),
        ("The Walton Centre NHS Foundation Trust", 3),
        ("Torbay and South Devon NHS Foundation Trust", 5),
        ("United Lincolnshire Hospitals NHS Trust", 3),
        ("United Lincolnshire Teaching Hospitals NHS Trust", 1),
        ("University College London Hospitals NHS Foundation Trust", 2),
        ("University Hospital Southampton NHS Foundation Trust", 11),
        ("University Hospitals Birmingham NHS Foundation Trust", 13),
        ("University Hospitals Bristol and Weston NHS Foundation Trust", 2),
        ("University Hospitals Coventry and Warwickshire NHS Trust", 2),
        ("University Hospitals of Derby and Burton NHS Foundation Trust", 9),
        ("University Hospitals of Leicester NHS Trust", 6),
        ("University Hospitals of Morecambe Bay NHS Foundation Trust", 2),
        ("University Hospitals of North Midlands NHS Trust", 9),
        ("University Hospitals Plymouth NHS Trust", 5),
        ("University Hospitals Sussex NHS Foundation Trust", 3),
        ("Walsall Healthcare NHS Trust", 1),
        ("Warrington and Halton Teaching Hospitals NHS Foundation Trust", 3),
        ("West Hertfordshire Teaching Hospitals NHS Trust", 2),
        ("West Suffolk NHS Foundation Trust", 1),
        ("Whittington Health NHS Trust", 2),
        ("Worcestershire Acute Hospitals NHS Trust", 4),
        ("Wrightington, Wigan and Leigh NHS Foundation Trust", 5),
        ("Wye Valley NHS Trust", 1),
        ("York and Scarborough Teaching Hospitals NHS Foundation Trust", 2),
    ]},
    "2025-26": {"provisional": 1, "data": [
        ("Airedale NHS Foundation Trust", 1),
        ("Alder Hey Children's NHS Foundation Trust", 2),
        ("Ashford and St Peter's Hospitals NHS Foundation Trust", 2),
        ("Barking, Havering and Redbridge University Hospitals NHS Trust", 3),
        ("Barnsley Hospital NHS Foundation Trust", 1),
        ("Barts Health NHS Trust", 9),
        ("Basildon and Thurrock University Hospitals NHS Foundation Trust", 2),
        ("Bedfordshire Hospitals NHS Foundation Trust", 3),
        ("Birmingham Women's and Children's NHS Foundation Trust", 1),
        ("Bolton NHS Foundation Trust", 1),
        ("Bradford Teaching Hospitals NHS Foundation Trust", 2),
        ("Brighton and Sussex University Hospitals NHS Trust", 2),
        ("Buckinghamshire Healthcare NHS Trust", 5),
        ("Calderdale and Huddersfield NHS Foundation Trust", 6),
        ("Cambridge University Hospitals NHS Foundation Trust", 6),
        ("Cambridgeshire and Peterborough NHS Foundation Trust", 1),
        ("Cheshire and Wirral Partnership NHS Foundation Trust", 1),
        ("Chesterfield Royal Hospital NHS Foundation Trust", 1),
        ("Countess of Chester Hospital NHS Foundation Trust", 4),
        ("County Durham and Darlington NHS Foundation Trust", 1),
        ("Croydon Health Services NHS Trust", 2),
        ("Dartford and Gravesham NHS Trust", 1),
        ("Doncaster and Bassetlaw Teaching Hospitals NHS Foundation Trust", 2),
        ("Dorset County Hospital NHS Foundation Trust", 1),
        ("East Cheshire NHS Trust", 1),
        ("East Kent Hospitals University NHS Foundation Trust", 8),
        ("East Lancashire Hospitals NHS Trust", 3),
        ("East Suffolk and North Essex NHS Foundation Trust", 5),
        ("East Sussex Healthcare NHS Trust", 4),
        ("Epsom and St Helier University Hospitals NHS Trust", 5),
        ("Frimley Health NHS Foundation Trust", 4),
        ("Gateshead Health NHS Foundation Trust", 1),
        ("Gloucestershire Hospitals NHS Foundation Trust", 6),
        ("Great Ormond Street Hospital for Children NHS Foundation Trust", 1),
        ("Great Western Hospitals NHS Foundation Trust", 1),
        ("Guy's and St Thomas' NHS Foundation Trust", 8),
        ("Hampshire and Isle of Wight Healthcare NHS Foundation Trust", 2),
        ("Hampshire Hospitals NHS Foundation Trust", 2),
        ("Harrogate and District NHS Foundation Trust", 2),
        ("Homerton Healthcare NHS Foundation Trust", 1),
        ("Hull University Teaching Hospitals NHS Trust", 6),
        ("Imperial College Healthcare NHS Trust", 5),
        ("Isle of Wight NHS Trust", 3),
        ("James Paget University Hospitals NHS Foundation Trust", 3),
        ("Kettering General Hospital NHS Foundation Trust", 2),
        ("Kingston and Richmond NHS Foundation Trust", 1),
        ("Lancashire Teaching Hospitals NHS Foundation Trust", 2),
        ("Leeds Teaching Hospitals NHS Trust", 3),
        ("Lewisham and Greenwich NHS Trust", 2),
        ("Liverpool University Hospitals NHS Foundation Trust", 3),
        ("London North West University Healthcare NHS Trust", 3),
        ("Maidstone and Tunbridge Wells NHS Trust", 4),
        ("Manchester University NHS Foundation Trust", 12),
        ("Medway NHS Foundation Trust", 2),
        ("Mersey and West Lancashire Teaching Hospitals NHS Trust", 2),
        ("Mid and South Essex NHS Foundation Trust", 1),
        ("Mid Cheshire Hospitals NHS Foundation Trust", 3),
        ("Mid Essex Hospital Services NHS Trust", 3),
        ("Mid Yorkshire Teaching NHS Trust", 1),
        ("Milton Keynes University Hospital NHS Foundation Trust", 2),
        ("Moorfields Eye Hospital NHS Foundation Trust", 1),
        ("Norfolk and Norwich University Hospitals NHS Foundation Trust", 1),
        ("North Bristol NHS Trust", 2),
        ("North Cumbria Integrated Care NHS Foundation Trust", 2),
        ("North Staffordshire Combined Healthcare NHS Trust", 1),
        ("North Tees and Hartlepool NHS Foundation Trust", 1),
        ("North West Anglia NHS Foundation Trust", 6),
        ("Northern Care Alliance NHS Foundation Trust", 9),
        ("Northern Lincolnshire and Goole NHS Foundation Trust", 6),
        ("Northumbria Healthcare NHS Foundation Trust", 4),
        ("Nottingham University Hospitals NHS Trust", 1),
        ("Oxford University Hospitals NHS Foundation Trust", 7),
        ("Poole Hospital NHS Foundation Trust", 6),
        ("Portsmouth Hospitals University NHS Trust", 8),
        ("Queen Victoria Hospital NHS Foundation Trust", 2),
        ("Royal Berkshire NHS Foundation Trust", 5),
        ("Royal Cornwall Hospitals NHS Trust", 2),
        ("Royal Devon University Healthcare NHS Foundation Trust", 8),
        ("Royal Free London NHS Foundation Trust", 3),
        ("Royal United Hospitals Bath NHS Foundation Trust", 3),
        ("Salisbury NHS Foundation Trust", 4),
        ("Sandwell and West Birmingham Hospitals NHS Trust", 3),
        ("Sheffield Children's NHS Foundation Trust", 2),
        ("Sheffield Teaching Hospitals NHS Foundation Trust", 5),
        ("Sherwood Forest Hospitals NHS Foundation Trust", 1),
        ("Somerset NHS Foundation Trust", 4),
        ("South Tees Hospitals NHS Foundation Trust", 5),
        ("South Tyneside and Sunderland NHS Foundation Trust", 2),
        ("South Warwickshire University NHS Foundation Trust", 3),
        ("Southport and Ormskirk Hospital NHS Trust", 2),
        ("St George's University Hospitals NHS Foundation Trust", 6),
        ("Stockport NHS Foundation Trust", 2),
        ("Tameside and Glossop Integrated Care NHS Foundation Trust", 2),
        ("The Dudley Group NHS Foundation Trust", 2),
        ("The Newcastle Upon Tyne Hospitals NHS Foundation Trust", 8),
        ("The Princess Alexandra Hospital NHS Trust", 2),
        ("The Queen Elizabeth Hospital, King's Lynn, NHS Foundation Trust", 1),
        ("The Robert Jones and Agnes Hunt Orthopaedic Hospital NHS Foundation Trust", 2),
        ("The Rotherham NHS Foundation Trust", 3),
        ("The Royal Orthopaedic Hospital NHS Foundation Trust", 2),
        ("The Shrewsbury and Telford Hospital NHS Trust", 3),
        ("Torbay and South Devon NHS Foundation Trust", 1),
        ("United Lincolnshire Teaching Hospitals NHS Trust", 1),
        ("University College London Hospitals NHS Foundation Trust", 4),
        ("University Hospital Southampton NHS Foundation Trust", 7),
        ("University Hospitals Birmingham NHS Foundation Trust", 10),
        ("University Hospitals Bristol and Weston NHS Foundation Trust", 3),
        ("University Hospitals Coventry and Warwickshire NHS Trust", 2),
        ("University Hospitals of Derby and Burton NHS Foundation Trust", 5),
        ("University Hospitals of Leicester NHS Trust", 2),
        ("University Hospitals of Morecambe Bay NHS Foundation Trust", 2),
        ("University Hospitals of North Midlands NHS Trust", 4),
        ("University Hospitals Plymouth NHS Trust", 2),
        ("University Hospitals Sussex NHS Foundation Trust", 2),
        ("Warrington and Halton Teaching Hospitals NHS Foundation Trust", 4),
        ("West Hertfordshire Teaching Hospitals NHS Trust", 3),
        ("West Suffolk NHS Foundation Trust", 1),
        ("Whittington Health NHS Trust", 1),
        ("Wirral University Teaching Hospital NHS Foundation Trust", 4),
        ("Worcestershire Acute Hospitals NHS Trust", 2),
        ("Wrightington, Wigan and Leigh Teaching Hospitals NHS Foundation Trust", 1),
        ("Wye Valley NHS Trust", 3),
    ]},
}


def build_name_lookup():
    """Build lookup from trust name variants to org_code using spine."""
    if not os.path.exists(MASTER_PATH):
        return {}
    master = pd.read_csv(MASTER_PATH, usecols=["org_code", "org_name"], dtype=str)
    master = master.drop_duplicates(subset=["org_code"])
    lookup = {}
    for _, row in master.iterrows():
        name = str(row["org_name"]).strip().upper()
        lookup[name] = row["org_code"]
    return lookup


def fuzzy_match(ne_name, lookup):
    """Match never events org name to org_code using normalised string matching."""
    # Direct match (normalised)
    norm = ne_name.strip().upper()
    if norm in lookup:
        return lookup[norm]
    # Remove common suffixes and try again
    for suffix in [" NHS FOUNDATION TRUST", " NHS TRUST", " FOUNDATION TRUST",
                   " NHS TEACHING HOSPITALS", " TEACHING HOSPITALS NHS TRUST"]:
        short = norm.replace(suffix, "").strip()
        for spine_name, code in lookup.items():
            spine_short = spine_name
            for s in [" NHS FOUNDATION TRUST", " NHS TRUST", " FOUNDATION TRUST"]:
                spine_short = spine_short.replace(s, "").strip()
            if short == spine_short:
                return code
    # Partial: ne_name words mostly in spine name
    ne_words = set(norm.split()) - {"NHS", "AND", "THE", "OF", "TRUST", "FOUNDATION"}
    best_code = None
    best_score = 0
    for spine_name, code in lookup.items():
        spine_words = set(spine_name.split()) - {"NHS", "AND", "THE", "OF", "TRUST", "FOUNDATION"}
        if not ne_words:
            continue
        score = len(ne_words & spine_words) / len(ne_words)
        if score > best_score and score >= 0.75:
            best_score = score
            best_code = code
    return best_code


def ingest_never_events():
    print("=" * 60)
    print("TrustPulse | NHS Never Events Ingestion")
    print("=" * 60)

    lookup = build_name_lookup()
    print(f"Spine lookup: {len(lookup)} trust names")

    rows = []
    unmatched_total = 0

    for year, info in sorted(NE_BY_YEAR.items()):
        period_date = PERIOD_MAP[year]
        provisional = info["provisional"]
        unmatched = []

        for name, count in info["data"]:
            code = fuzzy_match(name, lookup)
            if code:
                rows.append({
                    "org_code": code,
                    "org_name_source": name,
                    "period_date": period_date,
                    "financial_year": year,
                    "ne_count": count,
                    "ne_provisional": provisional,
                })
            else:
                unmatched.append((name, count))

        matched = len(info["data"]) - len(unmatched)
        unmatched_total += len(unmatched)
        print(f"\n  {year}: {matched}/{len(info['data'])} matched | "
              f"{sum(c for _,c in info['data'])} total events")
        if unmatched:
            print(f"  Unmatched ({len(unmatched)}):")
            for n, c in unmatched:
                # Skip private providers
                private_indicators = ["reported by", "circle health", "spire", "ramsay",
                                      "bpas", "practice plus", "spamedc", "optegra",
                                      "newmedica", "isight", "horder", "sulis hospital",
                                      "fairfield", "pioneer", "tyneside surgical",
                                      "west london regional", "epsomedical", "spa medica"]
                if not any(p in n.lower() for p in private_indicators):
                    print(f"    NHS: {n} ({c})")

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["org_code", "period_date"])
    df = df.sort_values(["org_code", "period_date"]).reset_index(drop=True)

    os.makedirs(PROCESSED, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE}")
    print(f"\n-- Summary --")
    print(f"  Rows          : {len(df):,}")
    print(f"  Unique trusts : {df['org_code'].nunique()}")
    print(f"  Years         : {sorted(df['financial_year'].unique())}")

    for year in sorted(df["financial_year"].unique()):
        yr = df[df["financial_year"] == year]
        total = yr["ne_count"].sum()
        prov = "provisional" if yr["ne_provisional"].iloc[0] else "final"
        print(f"  {year} ({prov}): {total} events | {(yr['ne_count']>0).sum()} trusts")

    print("\nNever events ingestion complete.")


if __name__ == "__main__":
    ingest_never_events()
