"""
Reference/Bibliography chunk detection and filtering.

Detects chunks that are part of reference/bibliography sections in academic
documents and provides strategies for handling them at import time and retrieval
time.

Detection approach:
1. Scan for reference section headers (English + Chinese)
2. Within detected boundaries, use regex patterns to identify reference lines
3. Ratio-based thresholding with confidence scoring

Supported citation formats: APA, MLA, IEEE, GB/T 7714, numbered, and common
journal-name patterns.
"""

import re
from typing import List, Set, Tuple

# ---------------------------------------------------------------------------
# Reference line detection patterns
# ---------------------------------------------------------------------------

# APA style: "Author, A.B., 2024."
APA_AUTHOR = r"^[A-Z][a-z\u00C0-\u024F]+,\s+[A-Z]\.\s*[A-Z]?\.?,?\s*\d{4}[a-z]?\."

# APA with "et al": "Author, A.B. et al., 2024."
APA_ETAL = (
    r"^[A-Z][a-z\u00C0-\u024F]+,\s+[A-Z]\.\s*[A-Z]?\.?\s+"
    r"et\s+al\.?,?\s*\d{4}[a-z]?\."
)

# Year-leading style: "2024. Author... Journal, 10(2): 123-145."
# Tightened: requires a journal-like structure with volume/pages
YEAR_FIRST = (
    r"^\d{4}[a-z]?\.\s+[A-Z][a-z\u00C0-\u024F]+"
    r".*?\.\s+\w[\w\s]*?[\.,]\s+\d{1,3}\([\d\-]+\)[:,\s]*\d+"
)

# Common journal name prefixes (English academic journals)
JOURNAL_NAMES = (
    r"^(Applied and Environmental Microbiology|Journal of|Veterinary|Animal\s"
    r"|Research in|PLoS|Asian|FEMS|Livestock|Archives of|British|"
    r"International Journal|Science|Nature|Cell|Lancet|BMJ|"
    r"Proceed(ings|ing)s? of the|IEEE|ACM|Springer|Elsevier)"
)

# Numbered reference: "[1]", "[12]", etc.
NUMBERED_BRACKET = r"^\[\d+\]\s"

# Numbered author-list: "1. Author, A. ..."
NUMBERED_DOT_AUTHOR = r"^\d+\.\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+,\s+[A-Z]"

# GB/T 7714 (Chinese academic standard): "[1] 张三, 李四. 标题[J]. 期刊, 2024, 10(2): 123."
GBT_7714 = (
    r"^\[\d+\]\s+[\u4e00-\u9fff\u3400-\u4dbf][\u4e00-\u9fff\u3400-\u4dbf\s,;，；]+\."
    r"\s*.+?\[[JMCNDP]\].*?\d{4}"
)

# IEEE style: "[1] A. Author et al., "Title," Journal, vol. X, no. Y, pp. Z, Year."
IEEE = (
    r"^\[\d+\]\s+[A-Z]\.\s+[A-Z][a-z\u00C0-\u024F]+"
    r".*?[\",]"
    r".*?"
    r"(?:[Jj]ournal|Conf\.|[Pp]roc\.|IEEE|ACM|Trans\.|vol\.|no\.|pp\.)"
)

# Generic "et al." line (lower priority, requires additional structural cues)
ETAL_GENERIC = (
    r"^.*?\bet\s+al\.?,?\s*\d{4}[a-z]?\.[\s,;]"
)

# DOI/URL reference
DOI_URL = r"\b(10\.\d{4,}/[^\s]+|https?://doi\.org/[^\s]+)"

# Volume/issue/page pattern (reinforcement, lower weight)
VOLUME_PAGES = r"\b\d{1,3}\([\d\-]+\)\s*:\s*\d+[\d\-]*\b"


REFERENCE_PATTERNS = [
    APA_AUTHOR,
    APA_ETAL,
    YEAR_FIRST,
    JOURNAL_NAMES,
    NUMBERED_BRACKET,
    NUMBERED_DOT_AUTHOR,
    GBT_7714,
    IEEE,
    ETAL_GENERIC,
]

# Patterns that are strong signals even with fewer matches
STRONG_REFERENCE_PATTERNS = [
    APA_AUTHOR,
    APA_ETAL,
    GBT_7714,
    IEEE,
    NUMBERED_BRACKET,
]


# ---------------------------------------------------------------------------
# Section header patterns (lines that are NOT references but section titles)
# ---------------------------------------------------------------------------

SECTION_PATTERNS = [
    r"^#+\s",              # Markdown headers
    r"^\d+\.\d+\s",        # Numbered sections like "1.2 Title"
    r"^Chapter\s+\d+",     # Chapter titles
    r"^(Abstract|摘要|Introduction|引言|Method|方法|Result|结果|Discussion|讨论|"
    r"Conclusion|结论|Appendix|附录)\b",
]


# ---------------------------------------------------------------------------
# Reference section header patterns
# ---------------------------------------------------------------------------

REF_HEADER_PATTERNS = [
    # English headers
    r"(?i)^#*\s*(references?|bibliography|literature\s*cited|works\s*cited)\s*$",
    # Chinese headers
    r"^#*\s*(参考|文献|参考资料|引用文献|参考文献|参考书目)\s*$",
    # Bracketed Chinese
    r"^#*\s*[\[【](参考|文献|参考资料|引用文献|参考文献|参考书目)[】\]]\s*$",
    # English with colon
    r"(?i)^#*\s*(references?|bibliography)\s*:\s*$",
]


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def is_reference_chunk(
    text: str,
    strong_ratio: float = 0.5,
    moderate_ratio: float = 0.3,
    weak_ratio: float = 0.4,
    moderate_min_matches: int = 5,
    weak_min_matches: int = 3,
    weak_min_strong: int = 2,
) -> Tuple[bool, float]:
    """Check if a text chunk is likely a reference/bibliography section.

    Uses ratio-based thresholding: if enough lines match reference patterns,
    the chunk is flagged as a reference.

    Args:
        text: The chunk text content
        strong_ratio: Threshold for strong signal (default 0.5)
        moderate_ratio: Threshold for moderate signal (default 0.3)
        weak_ratio: Threshold for weak signal (default 0.4)
        moderate_min_matches: Minimum matches for moderate signal (default 5)
        weak_min_matches: Minimum matches for weak signal (default 3)
        weak_min_strong: Minimum strong matches for weak signal (default 2)

    Returns:
        Tuple of (is_reference, confidence) where confidence is 0.0-1.0
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3:
        return False, 0.0

    ref_matches = 0
    strong_matches = 0
    total_lines = len(lines)

    for line in lines:
        # Skip lines that look like section headers
        if any(re.match(p, line) for p in SECTION_PATTERNS):
            continue

        if any(re.match(p, line) for p in REFERENCE_PATTERNS):
            ref_matches += 1
            if any(re.match(p, line) for p in STRONG_REFERENCE_PATTERNS):
                strong_matches += 1

    ratio = ref_matches / total_lines
    confidence = min(ratio, 1.0)

    # Strong signal: >= N% of lines match
    if ratio >= strong_ratio:
        return True, confidence

    # Moderate signal: >= N matches, >= N% ratio, with strong patterns present
    if ref_matches >= moderate_min_matches and ratio >= moderate_ratio:
        # Bonus for strong matches, capped at 1.0
        strong_bonus = min(strong_matches / ref_matches * 0.3, 0.3)
        confidence = min(ratio + strong_bonus, 1.0)
        return True, confidence

    # Weak signal: >= N matches, >= N% ratio but only strong patterns
    if ref_matches >= weak_min_matches and ratio >= weak_ratio and strong_matches >= weak_min_strong:
        return True, min(ratio, 0.8)

    return False, 0.0


def detect_reference_boundary(
    nodes: list,
    strong_ratio: float = 0.5,
    moderate_ratio: float = 0.3,
    weak_ratio: float = 0.4,
    moderate_min_matches: int = 5,
    weak_min_matches: int = 3,
    weak_min_strong: int = 2,
) -> Set[int]:
    """Detect the boundary where reference/bibliography section starts.

    Scans nodes sequentially. Once a reference section header or a high-confidence
    reference chunk is found, all subsequent nodes within the same section are
    marked as reference nodes. Stops when a new non-reference section header is
    encountered (e.g., Appendix).

    Args:
        nodes: List of nodes (each with get_content() or str)
        strong_ratio: Threshold for strong signal (default 0.5)
        moderate_ratio: Threshold for moderate signal (default 0.3)
        weak_ratio: Threshold for weak signal (default 0.4)
        moderate_min_matches: Minimum matches for moderate signal (default 5)
        weak_min_matches: Minimum matches for weak signal (default 3)
        weak_min_strong: Minimum strong matches for weak signal (default 2)

    Returns:
        Set of indices identifying reference nodes
    """
    ref_boundary_found = False
    ref_indices: Set[int] = set()

    for i, node in enumerate(nodes):
        text = node.get_content() if hasattr(node, "get_content") else str(node)

        # Check first non-empty line for reference section headers
        first_non_empty = text.strip().split("\n")[0] if text.strip() else ""
        if any(re.match(p, first_non_empty, re.MULTILINE) for p in REF_HEADER_PATTERNS):
            ref_boundary_found = True
            ref_indices.add(i)
            continue

        # If reference section is active, check if we've hit a new non-reference section
        if ref_boundary_found:
            if any(re.match(p, first_non_empty, re.MULTILINE) for p in SECTION_PATTERNS):
                ref_boundary_found = False
                continue

        # If no header found yet, check for high-confidence reference chunks as boundary
        is_ref, confidence = is_reference_chunk(
            text,
            strong_ratio=strong_ratio,
            moderate_ratio=moderate_ratio,
            weak_ratio=weak_ratio,
            moderate_min_matches=moderate_min_matches,
            weak_min_matches=weak_min_matches,
            weak_min_strong=weak_min_strong,
        )
        if not ref_boundary_found and is_ref and confidence >= 0.8:
            ref_boundary_found = True
            ref_indices.add(i)
            continue

        # Once boundary found, all subsequent nodes are references
        if ref_boundary_found:
            ref_indices.add(i)

    return ref_indices


# ---------------------------------------------------------------------------
# Strategy application
# ---------------------------------------------------------------------------

def flag_reference_nodes(
    nodes: list,
    strategy: str = "flag",
    strong_ratio: float = 0.5,
    moderate_ratio: float = 0.3,
    weak_ratio: float = 0.4,
    moderate_min_matches: int = 5,
    weak_min_matches: int = 3,
    weak_min_strong: int = 2,
) -> list:
    """Apply reference detection strategy to a list of nodes.

    Strategies:
        - "flag": Mark reference nodes with metadata but keep them (for retrieval downranking)
        - "skip": Remove reference nodes from the list entirely (exclude at import)
        - "none": No detection or filtering

    Args:
        nodes: List of nodes to process
        strategy: One of "flag", "skip", "none"
        strong_ratio: Threshold for strong signal (default 0.5)
        moderate_ratio: Threshold for moderate signal (default 0.3)
        weak_ratio: Threshold for weak signal (default 0.4)
        moderate_min_matches: Minimum matches for moderate signal (default 5)
        weak_min_matches: Minimum matches for weak signal (default 3)
        weak_min_strong: Minimum strong matches for weak signal (default 2)

    Returns:
        Filtered list of nodes (for "skip", reference nodes are removed)
    """
    if strategy == "none":
        return nodes

    ref_indices = detect_reference_boundary(
        nodes,
        strong_ratio=strong_ratio,
        moderate_ratio=moderate_ratio,
        weak_ratio=weak_ratio,
        moderate_min_matches=moderate_min_matches,
        weak_min_matches=weak_min_matches,
        weak_min_strong=weak_min_strong,
    )

    if strategy == "skip":
        return [node for i, node in enumerate(nodes) if i not in ref_indices]

    for i in ref_indices:
        node = nodes[i]
        if not hasattr(node, "metadata") or node.metadata is None:
            node.metadata = {}
        node.metadata["is_reference"] = True
        node.metadata["ref_confidence"] = 0.9

    return nodes


def apply_reference_strategy(nodes: list, strategy: str = None) -> list:
    """Canonical entry point for applying the configured reference strategy.

    Reads reference_strategy from settings if no per-import strategy is provided.
    Per-import overrides take precedence over global settings.

    Use this function in all import pipelines (generic, Obsidian, Zotero)
    instead of duplicating the logic.

    Args:
        nodes: List of nodes to process
        strategy: Optional per-import override ("flag", "skip", "none").
                  If None, reads from global settings.

    Returns:
        Filtered/marked list of nodes
    """
    if strategy is None:
        from rag.config import get_settings
        s = get_settings()
        strategy = s.reference_strategy
        strong_ratio = s.reference_strong_ratio
        moderate_ratio = s.reference_moderate_ratio
        weak_ratio = s.reference_weak_ratio
        moderate_min_matches = s.reference_moderate_min_matches
        weak_min_matches = s.reference_weak_min_matches
        weak_min_strong = s.reference_weak_min_strong
    else:
        strong_ratio = 0.5
        moderate_ratio = 0.3
        weak_ratio = 0.4
        moderate_min_matches = 5
        weak_min_matches = 3
        weak_min_strong = 2

    if strategy not in ("flag", "skip", "none"):
        strategy = "flag"

    return flag_reference_nodes(
        nodes,
        strategy=strategy,
        strong_ratio=strong_ratio,
        moderate_ratio=moderate_ratio,
        weak_ratio=weak_ratio,
        moderate_min_matches=moderate_min_matches,
        weak_min_matches=weak_min_matches,
        weak_min_strong=weak_min_strong,
    )
