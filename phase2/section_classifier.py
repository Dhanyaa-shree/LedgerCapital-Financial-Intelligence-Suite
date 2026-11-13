"""
Section Classification: Classify sections into 12 canonical types
"""

import re
from typing import Dict, List
from rapidfuzz import fuzz
from config import SECTION_TYPES


def classify_section(section: Dict, page_num: int = None) -> str:
    """
    Classify a section into one of 12 canonical types.

    Reads 'page' or 'page_start' (Phase 1 uses 'page', Phase 2 spec used 'page_start').
    """
    text = section.get('text', '').lower()
    level = section.get('level', 0)
    # Accept either field name
    page_start = (
        section.get('page_start')
        or section.get('page')
        or page_num
        or 0
    )

    # Short sections are likely headers
    if len(text) < 50:
        return "header"

    # Special-case: actual cover page = page 1-3 AND has 2+ cover-page keywords
    if page_start <= 3:
        cover_hits = sum(1 for kw in SECTION_TYPES['cover_page'].get('keywords', [])
                         if kw in text[:500])
        if cover_hits >= 2:
            return "cover_page"

    # Risk detection — often pages say "RISK FACTORS" without "Item 1A"
    risk_hits = sum(1 for kw in [
        "risk factor", "risks related", "risk related",
        "material adverse", "may adversely affect",
        "principal risks", "we face risks",
    ] if kw in text)
    if risk_hits >= 1 and "item 1a" not in text[:200]:
        # Only apply if we're not already on page 1
        if page_start > 3:
            return "risk_factors"

    # Check each section type in priority order
    for section_type, config in sorted(SECTION_TYPES.items(), key=lambda x: x[1]['priority']):
        # Never let cover_page match beyond page 3
        if section_type == 'cover_page':
            continue

        # Check max pages constraint (only if the field exists)
        if 'max_pages' in config and page_start > config['max_pages']:
            continue

        keywords = config.get('keywords', [])
        exclude_keywords = config.get('exclude_keywords', [])

        # Check for exclude keywords first
        if any(kw in text for kw in exclude_keywords):
            continue

        # Check for include keywords
        if keywords:
            # For section types, check first 400 chars for better accuracy
            text_start = text[:400]

            if any(kw in text_start for kw in keywords):
                return section_type

    return "other"


def classify_section_enhanced(section: Dict, context: Dict = None) -> str:
    """Enhanced classification using context."""
    section_type = classify_section(section)

    # If "other", try to infer from context
    if section_type == "other" and context:
        previous_sections = context.get('previous_sections', [])
        text = section.get('text', '').lower()

        if previous_sections:
            last = previous_sections[-1]
            # Continuation of a section (no "item" keyword near start)
            if last in ('business_overview', 'risk_factors', 'mda') \
               and 'item' not in text[:100] and len(text) > 200:
                return last

    return section_type


def classify_all_sections(sections: List[Dict], doc_metadata: Dict = None) -> List[Dict]:
    """Classify all sections in a document with context awareness."""
    classified_sections = []
    previous_types = []

    for i, section in enumerate(sections):
        context = {
            'previous_sections': previous_types[-5:],
            'doc_metadata': doc_metadata,
            'section_index': i,
        }

        section_type = classify_section_enhanced(section, context)

        # Add classification to section
        section['section_type'] = section_type
        classified_sections.append(section)

        previous_types.append(section_type)

    return classified_sections


def get_section_statistics(classified_sections: List[Dict]) -> Dict:
    """Get statistics on section classification."""
    from collections import Counter

    section_types = [s['section_type'] for s in classified_sections]
    counts = Counter(section_types)
    total = len(section_types)

    stats = {
        'total_sections': total,
        'counts': dict(counts),
        'percentages': {k: (v / total) * 100 for k, v in counts.items()},
    }

    return stats


def validate_classification(classified_sections: List[Dict]) -> Dict:
    """Validate that classification makes sense."""
    stats = get_section_statistics(classified_sections)
    counts = stats['counts']
    percentages = stats['percentages']

    warnings = []

    if percentages.get('other', 0) > 50:
        warnings.append(f"⚠️  {percentages['other']:.1f}% sections classified as 'other' (>50%)")

    critical_sections = ['business_overview', 'risk_factors', 'mda', 'financial_statements']
    for section_type in critical_sections:
        if counts.get(section_type, 0) == 0:
            warnings.append(f"⚠️  No '{section_type}' sections found")
        elif counts.get(section_type, 0) < 3:
            warnings.append(f"⚠️  Only {counts[section_type]} '{section_type}' sections found (seems low)")

    return {
        'valid': len(warnings) == 0,
        'warnings': warnings,
        'stats': stats,
    }


if __name__ == "__main__":
    test_sections = [
        {"text": "ITEM 1. BUSINESS", "level": 1, "page": 5},
        {"text": "ITEM 1A. RISK FACTORS", "level": 1, "page": 15},
        {"text": "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS", "level": 1, "page": 30},
        {"text": "Our company operates in three segments...", "level": 2, "page": 6},
        {"text": "We face significant risks related to...", "level": 2, "page": 16},
    ]

    classified = classify_all_sections(test_sections)

    print("Classification Results:")
    for sec in classified:
        print(f"  {sec['section_type']:20s}: {sec['text'][:60]}...")

    validation = validate_classification(classified)
    print(f"\nValidation: {'✅ Valid' if validation['valid'] else '⚠️  Issues found'}")
    for warning in validation['warnings']:
        print(f"  {warning}")