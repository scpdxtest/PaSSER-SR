"""
Screening Criteria Constants
============================
Shared definitions for inclusion and exclusion criteria used across
the PaSSER-SR systematic review platform.

These criteria are used in:
- LLM Screening Backend (llm_screening_api.py)
- Human Screening Backend (screening_api.py)
- Import/Export utilities
- Results validation

Version: 1.0
Last Updated: February 2026
"""

from typing import Dict, List

# =============================================================================
# INCLUSION CRITERIA (IC1-IC5)
# Papers must meet these criteria to be included in the systematic review
# =============================================================================

INCLUSION_CRITERIA_TEXT: Dict[str, str] = {
    "IC1": "Proposes, describes, or evaluates a blockchain-based model, framework, or system",
    "IC2": "Addresses electoral process (voter authentication, registration, petition signing, voting, counting, auditing, dispute resolution) for public or institutional elections (national, regional, local, university, organization)",
    "IC3": "Includes empirical evaluation or experimental results",
    "IC4": "Contains security/privacy analysis",
    "IC5": "Describes implementation or prototype",
}

# =============================================================================
# EXCLUSION CRITERIA (EC1-EC6)
# Papers meeting any of these criteria are excluded from the systematic review
# =============================================================================

EXCLUSION_CRITERIA_TEXT: Dict[str, str] = {
    "EC1": "No blockchain technology discussed, or mentions blockchain without specific implementation",
    "EC2": "Focuses on non-electoral domain (e.g., finance, supply chain, healthcare, IoT, energy) or discusses decentralization/blockchain in general without electoral application",
    "EC3": "Opinion pieces, position papers, tutorials, or general overviews/surveys without systematic methodology or original contribution",
    "EC4": "DAO governance, corporate voting, or technical voting/election mechanisms (consensus protocols, node/notary/leader election, Byzantine voting)",
    "EC5": "Abstract missing, insufficient, unclear scope, or not in English",
    "EC6": "Only theoretical discussion, or general blockchain/smart contract concepts without concrete electoral application",
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_criterion_text(code: str) -> str:
    """
    Get criterion text by code.
    
    Args:
        code: Criterion code (e.g., 'IC1', 'EC3')
        
    Returns:
        Criterion text or empty string if not found
    """
    if code.startswith("IC"):
        return INCLUSION_CRITERIA_TEXT.get(code, "")
    elif code.startswith("EC"):
        return EXCLUSION_CRITERIA_TEXT.get(code, "")
    return ""


def format_reasoning_with_criteria(criteria_met: List[str], criteria_violated: List[str], original_reasoning: str) -> str:
    """
    Format reasoning to include criteria text descriptions.
    This creates a unified format compatible with Human Screening.
    
    Output format:
        Criteria met: IC1 (text); IC2 (text)
        Criteria violated: EC1 (text)
        Notes: original reasoning from LLM
        
    Args:
        criteria_met: List of inclusion criterion codes that were satisfied
        criteria_violated: List of exclusion criterion codes that were violated
        original_reasoning: Original reasoning text from LLM or screener
        
    Returns:
        Formatted reasoning string
    """
    parts = []
    
    if criteria_met:
        met_texts = []
        for code in criteria_met:
            text = INCLUSION_CRITERIA_TEXT.get(code, "")
            if text:
                met_texts.append(f"{code} ({text})")
            else:
                met_texts.append(code)
        parts.append(f"Criteria met: {'; '.join(met_texts)}")
    
    if criteria_violated:
        violated_texts = []
        for code in criteria_violated:
            text = EXCLUSION_CRITERIA_TEXT.get(code, "")
            if text:
                violated_texts.append(f"{code} ({text})")
            else:
                violated_texts.append(code)
        parts.append(f"Criteria violated: {'; '.join(violated_texts)}")
    
    if original_reasoning and original_reasoning.strip():
        parts.append(f"Notes: {original_reasoning.strip()}")
    
    return "\n".join(parts) if parts else original_reasoning


def generate_criteria_prompt_section() -> str:
    """
    Generate formatted criteria section for LLM prompts.
    
    Returns:
        Formatted string with all criteria for inclusion in prompts
    """
    lines = ["INCLUSION CRITERIA:"]
    for code in sorted(INCLUSION_CRITERIA_TEXT.keys()):
        lines.append(f"{code}: {INCLUSION_CRITERIA_TEXT[code]}")
    
    lines.append("\nEXCLUSION CRITERIA:")
    for code in sorted(EXCLUSION_CRITERIA_TEXT.keys()):
        lines.append(f"{code}: {EXCLUSION_CRITERIA_TEXT[code]}")
    
    return "\n".join(lines)
