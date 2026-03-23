/**
 * sraudit Smart Contract (v2.1 with Audit Export Support)
 * ======================================================
 * PaSSER-SR: Systematic Review Audit Contract
 *
 * This contract logs screening decisions and resolutions
 * for the Human Screening Module of PaSSER-SR.
 * Now includes project_id for multi-project support.
 *
 * Tables:
 *   - decisions: Stores screening decisions (with project_id)
 *   - resolutions: Stores disagreement resolutions (with project_id)
 *   - imports: Stores import/export events (with project_id)
 *   - audits: Stores audit export records (Merkle root + file hash)
 *
 * Actions:
 *   - logdecision: Log a screening decision (manual human screening)
 *   - logresolution: Log a resolution
 *   - logimport: Log data import event
 *   - logexport: Log data export event
 *   - logllmdec: Log an individual LLM screening decision
 *   - logllmjob: Log an LLM screening job
 *   - logaudit: Log an audit export event (Merkle root + file hash)
 *   - cleardata: Clear all data (admin only)
 *   - clearproject: Clear data for specific project (admin only)
 * 
 * Compile with:
 *   cdt-cpp -abigen -o sraudit.wasm sraudit.cpp
 *   eosio-cpp -abigen -o sraudit.wasm sraudit.cpp
 *   cleos -u http://<BLOCKCHAIN_ENDPOINT> set contract sraudit ./ sraudit.wasm sraudit.abi
 * 
 * Deploy with:
 *   cleos set contract sraudit /path/to/contract -p sraudit@active
 * 
 * Author: PaSSER-SR Team
 * Date: January 2026
 * Version: 2.1
 */

#include <eosio/eosio.hpp>
#include <eosio/system.hpp>
#include <eosio/time.hpp>

using namespace eosio;

class [[eosio::contract("sraudit")]] sraudit : public contract {
public:
    using contract::contract;

    /**
     * Log a screening decision
     * 
     * @param screener - The Antelope account of the screener
     * @param projectid - Project ID (max 16 chars)
     * @param gsid - Gold Standard paper ID (e.g., "GS-001")
     * @param decision - Decision: INCLUDE, EXCLUDE, or UNCERTAIN
     * @param confidence - Confidence: HIGH, MEDIUM, or LOW
     * @param datahash - Hash of the full decision data (for verification)
     */
    [[eosio::action]]
    void logdecision(
        name screener,
        std::string projectid,
        std::string gsid,
        std::string decision,
        std::string confidence,
        std::string datahash
    ) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(gsid.length() > 0 && gsid.length() <= 16, "Invalid gsid length (max 16)");
        check(decision == "INCLUDE" || decision == "EXCLUDE" || decision == "UNCERTAIN", 
              "Invalid decision. Must be INCLUDE, EXCLUDE, or UNCERTAIN");
        check(confidence == "HIGH" || confidence == "MEDIUM" || confidence == "LOW",
              "Invalid confidence. Must be HIGH, MEDIUM, or LOW");
        check(datahash.length() > 0 && datahash.length() <= 64, "Invalid datahash length");
        
        // Get current time
        time_point_sec now = current_time_point();
        
        // Store in decisions table
        decisions_table decisions(get_self(), get_self().value);
        
        decisions.emplace(get_self(), [&](auto& row) {
            row.id = decisions.available_primary_key();
            row.screener = screener;
            row.projectid = projectid;
            row.gsid = gsid;
            row.decision = decision;
            row.confidence = confidence;
            row.datahash = datahash;
            row.created_at = now;
        });
        
        // Print confirmation
        print("Decision logged: ", screener, " [", projectid, "] ", gsid, " = ", decision);
    }

    /**
     * Log a resolution for a disagreement
     * 
     * @param resolver - The Antelope account of the resolver
     * @param projectid - Project ID
     * @param gsid - Gold Standard paper ID
     * @param decision - Final decision: INCLUDE or EXCLUDE
     * @param datahash - Hash of the full resolution data
     */
    [[eosio::action]]
    void logres(
        name resolver,
        std::string projectid,
        std::string gsid,
        std::string decision,
        std::string datahash
    ) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(gsid.length() > 0 && gsid.length() <= 16, "Invalid gsid length (max 16)");
        check(decision == "INCLUDE" || decision == "EXCLUDE", 
              "Invalid decision. Must be INCLUDE or EXCLUDE");
        check(datahash.length() > 0 && datahash.length() <= 64, "Invalid datahash length");
        
        // Get current time
        time_point_sec now = current_time_point();
        
        // Store in resolutions table
        resolutions_table resolutions(get_self(), get_self().value);
        
        resolutions.emplace(get_self(), [&](auto& row) {
            row.id = resolutions.available_primary_key();
            row.resolver = resolver;
            row.projectid = projectid;
            row.gsid = gsid;
            row.decision = decision;
            row.datahash = datahash;
            row.resolved_at = now;
        });
        
        // Print confirmation
        print("Resolution logged: ", resolver, " [", projectid, "] ", gsid, " = ", decision);
    }

    /**
     * Log a data import event
     * 
     * @param admin - The admin who performed the import
     * @param projectid - Project ID
     * @param source - Source file name
     * @param count - Number of records imported
     * @param datahash - Hash of the imported data
     */
    [[eosio::action]]
    void logimport(
        name admin,
        std::string projectid,
        std::string source,
        uint32_t count,
        std::string datahash
    ) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(source.length() > 0 && source.length() <= 128, "Invalid source length");
        check(count > 0, "Count must be greater than 0");
        check(datahash.length() > 0 && datahash.length() <= 64, "Invalid datahash length");
        
        // Get current time
        time_point_sec now = current_time_point();
        
        // Store in imports table
        imports_table imports(get_self(), get_self().value);
        
        imports.emplace(get_self(), [&](auto& row) {
            row.id = imports.available_primary_key();
            row.admin = admin;
            row.projectid = projectid;
            row.event_type = "import";
            row.source = source;
            row.count = count;
            row.datahash = datahash;
            row.created_at = now;
        });
        
        // Print confirmation
        print("Import logged: ", admin, " [", projectid, "] ", count, " records from ", source);
    }

    /**
     * Log a data export event (Merkle root for verification)
     * 
     * @param admin - The admin who performed the export
     * @param projectid - Project ID
     * @param destination - Destination description
     * @param count - Number of records exported
     * @param datahash - Hash of the exported data (Merkle root)
     */
    [[eosio::action]]
    void logexport(
        name admin,
        std::string projectid,
        std::string destination,
        uint32_t count,
        std::string datahash
    ) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(destination.length() > 0 && destination.length() <= 128, "Invalid destination length");
        check(count > 0, "Count must be greater than 0");
        check(datahash.length() > 0 && datahash.length() <= 64, "Invalid datahash length");
        
        // Get current time
        time_point_sec now = current_time_point();
        
        // Store in imports table (reuse for exports)
        imports_table imports(get_self(), get_self().value);
        
        imports.emplace(get_self(), [&](auto& row) {
            row.id = imports.available_primary_key();
            row.admin = admin;
            row.projectid = projectid;
            row.event_type = "export";
            row.source = destination;
            row.count = count;
            row.datahash = datahash;
            row.created_at = now;
        });
        
        // Print confirmation
        print("Export logged: ", admin, " [", projectid, "] ", count, " records, Merkle: ", datahash);
    }

    /**
     * Log an individual LLM screening decision
     * 
     * @param screener - The Antelope account who ran the LLM screening
     * @param projectid - Project ID (max 32 chars)
     * @param gsid - Gold Standard paper ID (e.g., "GS-001")
     * @param decision - Decision: INCLUDE, EXCLUDE, or UNCERTAIN
     * @param confidence - Confidence: HIGH, MEDIUM, or LOW
     * @param model - LLM model used (e.g., "mistral-7b") (max 32 chars)
     * @param strategy - Strategy used (e.g., "S1_SINGLE") (max 16 chars)
     * @param jobid - Job identifier (links to logllmjob) (max 32 chars)
     * @param datahash - Hash of the decision data (for verification)
     */
    [[eosio::action]]
    void logllmdec(
        name screener,
        std::string projectid,
        std::string gsid,
        std::string decision,
        std::string confidence,
        std::string model,
        std::string strategy,
        std::string jobid,
        std::string datahash
    ) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(gsid.length() > 0 && gsid.length() <= 16, "Invalid gsid length (max 16)");
        check(decision == "INCLUDE" || decision == "EXCLUDE" || decision == "UNCERTAIN", 
              "Invalid decision. Must be INCLUDE, EXCLUDE, or UNCERTAIN");
        check(confidence == "HIGH" || confidence == "MEDIUM" || confidence == "LOW",
              "Invalid confidence. Must be HIGH, MEDIUM, or LOW");
        check(model.length() > 0 && model.length() <= 32, "Invalid model length (max 32)");
        check(strategy.length() > 0 && strategy.length() <= 16, "Invalid strategy length (max 16)");
        check(jobid.length() > 0 && jobid.length() <= 32, "Invalid jobid length (max 32)");
        check(datahash.length() > 0 && datahash.length() <= 64, "Invalid datahash length");
        
        // Get current time
        time_point_sec now = current_time_point();
        
        // Store in llmdecisions table
        llmdecisions_table llmdecisions(get_self(), get_self().value);
        
        llmdecisions.emplace(get_self(), [&](auto& row) {
            row.id = llmdecisions.available_primary_key();
            row.screener = screener;
            row.projectid = projectid;
            row.gsid = gsid;
            row.decision = decision;
            row.confidence = confidence;
            row.model = model;
            row.strategy = strategy;
            row.jobid = jobid;
            row.datahash = datahash;
            row.created_at = now;
        });
        
        // Print confirmation
        print("LLM decision logged: ", screener, " [", projectid, "] ", gsid, " = ", decision, " (", model, ")");
    }

    /**
     * Log an LLM screening job
     * 
     * @param username - The Antelope account of the user who initiated the job
     * @param projectid - Project ID (max 32 chars)
     * @param jobid - Unique job identifier (max 32 chars)
     * @param strategy - Screening strategy used (e.g., "S1", "S5") (max 16 chars)
     * @param models - Comma-separated list of models used (max 128 chars)
     * @param promptmode - Prompt mode (e.g., "zero_shot", "multi_agent") (max 32 chars)
     * @param papercount - Number of papers screened
     * @param datahash - Hash of the job data (for verification)
     */
    [[eosio::action]]
    void logllmjob(
        name username,
        std::string projectid,
        std::string jobid,
        std::string strategy,
        std::string models,
        std::string promptmode,
        uint32_t papercount,
        std::string datahash
    ) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(jobid.length() > 0 && jobid.length() <= 32, "Invalid jobid length (max 32)");
        check(strategy.length() > 0 && strategy.length() <= 16, "Invalid strategy length (max 16)");
        check(models.length() > 0 && models.length() <= 128, "Invalid models length (max 128)");
        check(promptmode.length() > 0 && promptmode.length() <= 32, "Invalid promptmode length (max 32)");
        check(papercount > 0, "Paper count must be greater than 0");
        check(datahash.length() > 0 && datahash.length() <= 64, "Invalid datahash length");
        
        // Get current time
        time_point_sec now = current_time_point();
        
        // Store in llmjobs table
        llmjobs_table llmjobs(get_self(), get_self().value);
        
        llmjobs.emplace(get_self(), [&](auto& row) {
            row.id = llmjobs.available_primary_key();
            row.username = username;
            row.projectid = projectid;
            row.jobid = jobid;
            row.strategy = strategy;
            row.models = models;
            row.promptmode = promptmode;
            row.papercount = papercount;
            row.datahash = datahash;
            row.created_at = now;
        });
        
        // Print confirmation
        print("LLM job logged: ", username, " [", projectid, "] ", jobid, " - ", strategy, " with ", papercount, " papers");
    }

    /**
     * Log an audit export event with Merkle root and file hash
     *
     * @param admin - The admin who performed the export
     * @param projectid - Project ID (max 32 chars)
     * @param milestone - Export milestone (e.g., "final_corpus") (max 32 chars)
     * @param merkleroot - Merkle root hash of all records (64 hex chars)
     * @param filehash - SHA-256 hash of the export JSON file (64 hex chars)
     * @param leafcount - Number of Merkle tree leaves
     */
    [[eosio::action]]
    void logaudit(
        name admin,
        std::string projectid,
        std::string milestone,
        std::string merkleroot,
        std::string filehash,
        uint32_t leafcount
    ) {
        // Require authorization from the contract account
        require_auth(get_self());

        // Validate inputs
        check(projectid.length() > 0 && projectid.length() <= 32, "Invalid projectid length (max 32)");
        check(milestone.length() > 0 && milestone.length() <= 32, "Invalid milestone length (max 32)");
        check(merkleroot.length() == 64, "Merkle root must be 64 hex characters");
        check(filehash.length() == 64, "File hash must be 64 hex characters");
        check(leafcount > 0, "Leaf count must be greater than 0");

        // Get current time
        time_point_sec now = current_time_point();

        // Store in audits table
        audits_table audits(get_self(), get_self().value);

        audits.emplace(get_self(), [&](auto& row) {
            row.id = audits.available_primary_key();
            row.admin = admin;
            row.projectid = projectid;
            row.milestone = milestone;
            row.merkleroot = merkleroot;
            row.filehash = filehash;
            row.leafcount = leafcount;
            row.created_at = now;
        });

        // Print confirmation
        print("Audit logged: ", admin, " [", projectid, "] ", milestone,
              " merkle:", merkleroot.substr(0, 16), "... file:", filehash.substr(0, 16),
              "... leaves:", leafcount);
    }

    /**
     * Clear all data from tables (admin only, for testing)
     * 
     * @param confirm - Must be "CONFIRM" to proceed
     */
    [[eosio::action]]
    void cleardata(std::string confirm) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Safety check
        check(confirm == "CONFIRM", "Must pass 'CONFIRM' to clear data");
        
        // Clear decisions table
        decisions_table decisions(get_self(), get_self().value);
        auto dec_itr = decisions.begin();
        while (dec_itr != decisions.end()) {
            dec_itr = decisions.erase(dec_itr);
        }
        
        // Clear resolutions table
        resolutions_table resolutions(get_self(), get_self().value);
        auto res_itr = resolutions.begin();
        while (res_itr != resolutions.end()) {
            res_itr = resolutions.erase(res_itr);
        }
        
        // Clear imports table
        imports_table imports(get_self(), get_self().value);
        auto imp_itr = imports.begin();
        while (imp_itr != imports.end()) {
            imp_itr = imports.erase(imp_itr);
        }
        
        // Clear llmjobs table
        llmjobs_table llmjobs(get_self(), get_self().value);
        auto llm_itr = llmjobs.begin();
        while (llm_itr != llmjobs.end()) {
            llm_itr = llmjobs.erase(llm_itr);
        }
        
        // Clear llmdecisions table
        llmdecisions_table llmdecisions(get_self(), get_self().value);
        auto llmd_itr = llmdecisions.begin();
        while (llmd_itr != llmdecisions.end()) {
            llmd_itr = llmdecisions.erase(llmd_itr);
        }

        // Clear audits table
        audits_table audits(get_self(), get_self().value);
        auto aud_itr = audits.begin();
        while (aud_itr != audits.end()) {
            aud_itr = audits.erase(aud_itr);
        }

        print("All data cleared");
    }

    /**
     * Clear data for a specific project (admin only)
     * 
     * @param projectid - Project ID to clear
     * @param confirm - Must be "CONFIRM" to proceed
     */
    [[eosio::action]]
    void clearproject(std::string projectid, std::string confirm) {
        // Require authorization from the contract account
        require_auth(get_self());
        
        // Safety check
        check(confirm == "CONFIRM", "Must pass 'CONFIRM' to clear project data");
        check(projectid.length() > 0, "Project ID required");
        
        uint32_t deleted_decisions = 0;
        uint32_t deleted_resolutions = 0;
        uint32_t deleted_imports = 0;
        uint32_t deleted_llmjobs = 0;
        uint32_t deleted_llmdecisions = 0;
        
        // Clear decisions for project
        decisions_table decisions(get_self(), get_self().value);
        auto dec_itr = decisions.begin();
        while (dec_itr != decisions.end()) {
            if (dec_itr->projectid == projectid) {
                dec_itr = decisions.erase(dec_itr);
                deleted_decisions++;
            } else {
                dec_itr++;
            }
        }
        
        // Clear resolutions for project
        resolutions_table resolutions(get_self(), get_self().value);
        auto res_itr = resolutions.begin();
        while (res_itr != resolutions.end()) {
            if (res_itr->projectid == projectid) {
                res_itr = resolutions.erase(res_itr);
                deleted_resolutions++;
            } else {
                res_itr++;
            }
        }
        
        // Clear imports for project
        imports_table imports(get_self(), get_self().value);
        auto imp_itr = imports.begin();
        while (imp_itr != imports.end()) {
            if (imp_itr->projectid == projectid) {
                imp_itr = imports.erase(imp_itr);
                deleted_imports++;
            } else {
                imp_itr++;
            }
        }
        
        // Clear llmjobs for project
        llmjobs_table llmjobs(get_self(), get_self().value);
        auto llm_itr = llmjobs.begin();
        while (llm_itr != llmjobs.end()) {
            if (llm_itr->projectid == projectid) {
                llm_itr = llmjobs.erase(llm_itr);
                deleted_llmjobs++;
            } else {
                llm_itr++;
            }
        }
        
        // Clear llmdecisions for project
        llmdecisions_table llmdecisions(get_self(), get_self().value);
        auto llmd_itr = llmdecisions.begin();
        while (llmd_itr != llmdecisions.end()) {
            if (llmd_itr->projectid == projectid) {
                llmd_itr = llmdecisions.erase(llmd_itr);
                deleted_llmdecisions++;
            } else {
                llmd_itr++;
            }
        }

        uint32_t deleted_audits = 0;

        // Clear audits for project
        audits_table audits(get_self(), get_self().value);
        auto aud_itr = audits.begin();
        while (aud_itr != audits.end()) {
            if (aud_itr->projectid == projectid) {
                aud_itr = audits.erase(aud_itr);
                deleted_audits++;
            } else {
                aud_itr++;
            }
        }

        print("Project ", projectid, " cleared: ",
              deleted_decisions, " decisions, ",
              deleted_resolutions, " resolutions, ",
              deleted_imports, " imports, ",
              deleted_llmjobs, " llm jobs, ",
              deleted_llmdecisions, " llm decisions, ",
              deleted_audits, " audits");
    }

private:
    /**
     * Table: decisions
     * Stores all screening decisions with project isolation
     */
    struct [[eosio::table]] decision_row {
        uint64_t id;
        name screener;
        std::string projectid;
        std::string gsid;
        std::string decision;
        std::string confidence;
        std::string datahash;
        time_point_sec created_at;

        uint64_t primary_key() const { return id; }
        uint64_t by_screener() const { return screener.value; }
    };

    typedef multi_index<"decisions"_n, decision_row,
        indexed_by<"byscreener"_n, const_mem_fun<decision_row, uint64_t, &decision_row::by_screener>>
    > decisions_table;

    /**
     * Table: resolutions
     * Stores all disagreement resolutions with project isolation
     */
    struct [[eosio::table]] resolution_row {
        uint64_t id;
        name resolver;
        std::string projectid;
        std::string gsid;
        std::string decision;
        std::string datahash;
        time_point_sec resolved_at;

        uint64_t primary_key() const { return id; }
        uint64_t by_resolver() const { return resolver.value; }
    };

    typedef multi_index<"resolutions"_n, resolution_row,
        indexed_by<"byresolver"_n, const_mem_fun<resolution_row, uint64_t, &resolution_row::by_resolver>>
    > resolutions_table;

    /**
     * Table: imports
     * Stores import/export events with project isolation
     */
    struct [[eosio::table]] import_row {
        uint64_t id;
        name admin;
        std::string projectid;
        std::string event_type;  // "import" or "export"
        std::string source;      // filename or destination
        uint32_t count;
        std::string datahash;    // Merkle root for exports
        time_point_sec created_at;

        uint64_t primary_key() const { return id; }
        uint64_t by_admin() const { return admin.value; }
    };

    typedef multi_index<"imports"_n, import_row,
        indexed_by<"byadmin"_n, const_mem_fun<import_row, uint64_t, &import_row::by_admin>>
    > imports_table;

    /**
     * Table: llmjobs
     * Stores LLM screening job records with project isolation
     */
    struct [[eosio::table]] llmjob_row {
        uint64_t id;
        name username;
        std::string projectid;
        std::string jobid;
        std::string strategy;
        std::string models;
        std::string promptmode;
        uint32_t papercount;
        std::string datahash;
        time_point_sec created_at;

        uint64_t primary_key() const { return id; }
        uint64_t by_username() const { return username.value; }
    };

    typedef multi_index<"llmjobs"_n, llmjob_row,
        indexed_by<"byusername"_n, const_mem_fun<llmjob_row, uint64_t, &llmjob_row::by_username>>
    > llmjobs_table;

    /**
     * Table: llmdecisions
     * Stores individual LLM screening decisions with project isolation
     */
    struct [[eosio::table]] llmdecision_row {
        uint64_t id;
        name screener;
        std::string projectid;
        std::string gsid;
        std::string decision;
        std::string confidence;
        std::string model;
        std::string strategy;
        std::string jobid;
        std::string datahash;
        time_point_sec created_at;

        uint64_t primary_key() const { return id; }
        uint64_t by_screener() const { return screener.value; }
    };

    typedef multi_index<"llmdecisions"_n, llmdecision_row,
        indexed_by<"byscreener"_n, const_mem_fun<llmdecision_row, uint64_t, &llmdecision_row::by_screener>>
    > llmdecisions_table;

    /**
     * Table: audits
     * Stores audit export records with Merkle root and file hash
     */
    struct [[eosio::table]] audit_row {
        uint64_t id;
        name admin;
        std::string projectid;
        std::string milestone;
        std::string merkleroot;
        std::string filehash;
        uint32_t leafcount;
        time_point_sec created_at;

        uint64_t primary_key() const { return id; }
        uint64_t by_admin() const { return admin.value; }
    };

    typedef multi_index<"audits"_n, audit_row,
        indexed_by<"byadmin"_n, const_mem_fun<audit_row, uint64_t, &audit_row::by_admin>>
    > audits_table;
};
