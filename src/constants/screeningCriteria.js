/**
 * Screening Criteria Constants
 * ============================
 * Shared definitions for inclusion and exclusion criteria used across
 * the PaSSER-SR systematic review platform.
 * 
 * These criteria are used in:
 * - Human Screening Module (Screening.js)
 * - LLM Screening Module (for reference and validation)
 * - Decision formatting and display
 * 
 * Version: 1.0
 * Last Updated: February 2026
 */

/**
 * Inclusion Criteria (IC1-IC5)
 * Papers must meet these criteria to be included in the systematic review
 */
export const INCLUSION_CRITERIA = [
    { code: 'IC1', text: 'Proposes, describes, or evaluates a blockchain-based model, framework, or system' },
    { code: 'IC2', text: 'Addresses electoral process (voter authentication, registration, petition signing, voting, counting, auditing, dispute resolution) for public or institutional elections (national, regional, local, university, organization)' },
    { code: 'IC3', text: 'Includes empirical evaluation or experimental results' },
    { code: 'IC4', text: 'Contains security/privacy analysis' },
    { code: 'IC5', text: 'Describes implementation or prototype' }
];

/**
 * Exclusion Criteria (EC1-EC6)
 * Papers meeting any of these criteria are excluded from the systematic review
 */
export const EXCLUSION_CRITERIA = [
    { code: 'EC1', text: 'No blockchain technology discussed, or mentions blockchain without specific implementation' },
    { code: 'EC2', text: 'Focuses on non-electoral domain (e.g., finance, supply chain, healthcare, IoT, energy) or discusses decentralization/blockchain in general without electoral application' },
    { code: 'EC3', text: 'Opinion pieces, position papers, tutorials, or general overviews/surveys without systematic methodology or original contribution' },
    { code: 'EC4', text: 'DAO governance, corporate voting, or technical voting/election mechanisms (consensus protocols, node/notary/leader election, Byzantine voting)' },
    { code: 'EC5', text: 'Abstract missing, insufficient, unclear scope, or not in English' },
    { code: 'EC6', text: 'Only theoretical discussion, or general blockchain/smart contract concepts without concrete electoral application' }
];

/**
 * Helper function to get criterion by code
 * @param {string} code - Criterion code (e.g., 'IC1', 'EC3')
 * @returns {Object|null} Criterion object or null if not found
 */
export const getCriterionByCode = (code) => {
    if (code.startsWith('IC')) {
        return INCLUSION_CRITERIA.find(c => c.code === code);
    } else if (code.startsWith('EC')) {
        return EXCLUSION_CRITERIA.find(c => c.code === code);
    }
    return null;
};

/**
 * Helper function to format criteria for display in reason field
 * Unified format compatible with LLM screening output
 * Includes full criterion text for complete documentation
 * @param {Array<string>} criteriaMet - Array of inclusion criterion codes
 * @param {Array<string>} criteriaViolated - Array of exclusion criterion codes
 * @param {string} notes - Additional notes
 * @returns {string} Formatted reason text
 */
export const formatReasonFromCriteria = (criteriaMet, criteriaViolated, notes) => {
    const parts = [];
    
    if (criteriaMet.length > 0) {
        const metTexts = criteriaMet.map(code => {
            const ic = INCLUSION_CRITERIA.find(c => c.code === code);
            return ic ? `${code} (${ic.text})` : code;
        });
        parts.push(`Criteria met: ${metTexts.join('; ')}`);
    }
    
    if (criteriaViolated.length > 0) {
        const violatedTexts = criteriaViolated.map(code => {
            const ec = EXCLUSION_CRITERIA.find(c => c.code === code);
            return ec ? `${code} (${ec.text})` : code;
        });
        parts.push(`Criteria violated: ${violatedTexts.join('; ')}`);
    }
    
    if (notes && notes.trim()) {
        parts.push(`Notes: ${notes.trim()}`);
    }
    
    return parts.join('\n');
};
