# Graph Report - Streamlit  (2026-05-13)

## Corpus Check
- 48 files · ~927,562 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 756 nodes · 1314 edges · 27 communities (25 shown, 2 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 84 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `358a8ae8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]

## God Nodes (most connected - your core abstractions)
1. `PriceTagPage` - 37 edges
2. `render()` - 34 edges
3. `OdooConnectionManager` - 29 edges
4. `IndexedDBPriceSyncService` - 25 edges
5. `IndexedDBBridge` - 24 edges
6. `PriceTagService` - 22 edges
7. `ESCPOSLabelPrinter` - 19 edges
8. `main()` - 18 edges
9. `process_sales_workbook()` - 18 edges
10. `StockCardPage` - 18 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `AuthManager`  [INFERRED]
  app.py → logic/auth.py
- `main()` --calls--> `AuthComponents`  [INFERRED]
  app.py → ui/components/auth_components.py
- `main()` --calls--> `has_saved_barcodes()`  [INFERRED]
  app.py → utils/persistence.py
- `main()` --calls--> `restore_active_tab()`  [INFERRED]
  app.py → utils/persistence.py
- `main()` --calls--> `save_active_tab()`  [INFERRED]
  app.py → utils/persistence.py

## Communities (27 total, 2 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (44): Stock card generation logic module., BASalesReportPage, BA Sales Report page UI, BA Sales Report page UI component, Render download section, Initialize session state variables, Render the complete BA Sales Report page, Function to render BA Sales Report page (for backward compatibility) (+36 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (58): apply_excel_formatting(), create_detailed_report(), create_grouped_detailed_report(), create_pivot_by_barcode(), create_workbook_for_parent_brand(), create_zip_file(), Excel utilities and formatting functions, Create detailed report with all original columns, formatting Order Date as long (+50 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (34): IndexedDBPriceSyncService, PriceChange, IndexedDB-based Price Sync Service - Per-device price tracking., Fetch active goods from Odoo with pricelist discounts., Resolve pricelist external ID to database ID., Load baseline from Excel file (fallback for first-time users)., Compare Odoo prices against IndexedDB baseline (with Excel fallback)., Represents a price change for a product. (+26 more)

### Community 3 - "Community 3"
Cohesion: 0.05
Nodes (31): AuthComponents, Authentication UI components, Render the login page, Render logout button in sidebar, Check if user is authenticated, UI components for authentication, UI components package, AuthManager (+23 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (22): _format_price_input(), get_price_tag_service(), _now_key(), _parse_price(), PriceTagPage, Price Tag Generator Streamlit Page, Lightweight hash of current filled items., Check if lookup should be performed (debounce guard). (+14 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (42): CandidateLocationQty, get_candidate_internal_locations_for_product(), get_candidate_locations_for_products(), get_employee_partner_id(), get_employee_partner_id_by_name(), get_internal_picking_type_id(), get_location_by_complete_name(), get_products_category_names() (+34 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (24): get_odoo_settings(), OdooSettings, Centralized configuration management for Odoo connectivity., Container for Odoo connection settings sourced from the environment., Return cached settings instance to avoid repeated env parsing., connection(), OdooConnectionManager, OdooIntegrationError (+16 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (23): ESCPOSLabelPrinter, find_printer_devices(), ESC/POS Label Printer for Xprinter thermal printers.  Generates raw ESC/POS co, Feed paper by N lines., Write text with formatting., Print Code 128 barcode.                  Args:             data: Barcode data, Cut paper (for label mode, this may eject or mark cut position)., Initialize printer for label printing mode.                  Sets up continuou (+15 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (17): format_price(), _format_price_cached(), _hex_to_rgb(), _load_excel_cached(), PriceTagService, Price Tag Generator Service — optimized for performance., Load Parquet into memory dicts for O(1) lookups.          Key optimisations ov, Stat the parquet file at most once every _RELOAD_CHECK_INTERVAL seconds. (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.11
Nodes (22): Tests for IndexedDB bridge, Test upserting and retrieving products., Test getting product count., Test clearing all products., Test sync history operations., Test bridge can be initialized., test_bridge_initialization(), test_clear_all() (+14 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (29): 1. Web Workers for Background Processing, 2. Incremental Loading with Lazy Evaluation, 3. Browser Storage Integration, 4. WebSocket Barcode Scanners, 5. Print-Direct Integration, 6. Product Image Integration, 7. Real-time Inventory Sync, Cloud Deployment Considerations (+21 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (24): code:html (<!DOCTYPE html>), code:html (<!-- Add Streamlit communication library -->), code:python (from logic.indexeddb_price_sync import IndexedDBPriceSyncSer), code:bash (git add components/indexeddb_manager.html utils/indexeddb_br), code:python (import streamlit as st), code:bash (git add components/indexeddb_manager.html), code:python (import pytest), code:python ("""Bridge between Python and browser IndexedDB via Streamlit) (+16 more)

### Community 12 - "Community 12"
Cohesion: 0.08
Nodes (23): 1. Separation of Concerns, 2. Modularity, 3. Maintainability, 4. Testability, After (Separated), Before (Monolithic), Benefits Achieved, Code Organization (+15 more)

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (21): API Design, code:block1 (┌─────────────┐     ┌─────────────┐     ┌─────────────┐), code:python (class IndexedDBPriceSync:), code:python (# JavaScript-side (via st.components.v1)), Data Flow, Files to Modify, IndexedDB-Based Price Sync Design, IndexedDB Schema (+13 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (20): _build_change_lookup(), _build_dataframe(), _clear_sync_cache(), _filter_changes(), _generate_price_tags_pdf(), _get_price_tag_service(), _get_sync_service(), Instantiate the IndexedDB sync service once per session. (+12 more)

### Community 15 - "Community 15"
Cohesion: 0.14
Nodes (17): check_odoo_health(), get_recent_pos_orders(), get_recent_sales_orders(), get_sales_metrics(), Higher-level service helpers for querying Odoo objects., Retrieve recent (non-cancelled) sale orders ordered by date desc., Retrieve POS orders within the given window ordered by most recent., Aggregate key sales metrics from Odoo. (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.14
Nodes (19): clear_session(), _get_session_id(), _get_user_file(), has_saved_barcodes(), has_saved_session(), Server-side file persistence for session data (reliable alternative to localStor, Clear persisted session data from server-side file., Check if there's a saved session in server-side file. (+11 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): Architecture, Authentication, Changelog (recent), code:ini (# Odoo Connection Configuration), code:bash (pip install -r requirements.txt), code:bash (streamlit run app.py), code:bash (cd scripts), Dashboard Details (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.11
Nodes (18): code:python (def get_sync_history(self, limit: int = 5) -> List[Dict[str,), code:bash (git add logic/indexeddb_price_sync.py), code:python (def add_sync_to_history(self, result: SyncResult) -> None:), code:bash (git add logic/indexeddb_price_sync.py), code:python (if st.button("Update Harga", type="primary", use_container_w), code:bash (git add ui/pages/price_sync.py), code:python (with col2:), code:bash (git add ui/pages/price_sync.py) (+10 more)

### Community 19 - "Community 19"
Cohesion: 0.17
Nodes (8): Main processing function for stock cards., Generates stock cards grouped by parent brand with print settings., Load dataframe from any supported excel source., Apply border to all cells in a range., Group data by Parent Brand with Hebe and Paragon exceptions., Get all dates for a given month., Create stock card sheet with proper formatting and print settings., StockCardGenerator

### Community 20 - "Community 20"
Cohesion: 0.29
Nodes (5): code:bash (git add logic/price_tag_service.py), File Structure, Mini Tag Layout Redesign Implementation Plan, Spec Coverage Check, Task 1: Rewrite `_draw_mini_tag` Method

### Community 21 - "Community 21"
Cohesion: 0.5
Nodes (3): convert_excel_to_duckdb(), Convert Excel products to DuckDB for faster lookups, Convert Excel to DuckDB with index for fast lookups.

## Knowledge Gaps
- **291 isolated node(s):** `Main Streamlit application with separated UI and logic`, `Main application with separated UI and logic`, `Dashboard page content`, `Sanitize filename by removing invalid characters`, `Sort data by Parent Brand (alphabetically) then Order Date (earliest date, then` (+286 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OdooConnectionManager` connect `Community 6` to `Community 1`, `Community 2`, `Community 3`, `Community 7`, `Community 8`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `PriceTagPage` connect `Community 4` to `Community 8`, `Community 9`, `Community 0`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Why does `render()` connect `Community 0` to `Community 4`, `Community 14`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `PriceTagPage` (e.g. with `PriceTagService` and `IndexedDBBridge`) actually correct?**
  _`PriceTagPage` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `OdooConnectionManager` (e.g. with `PriceChange` and `SyncResult`) actually correct?**
  _`OdooConnectionManager` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `IndexedDBPriceSyncService` (e.g. with `OdooConnectionManager` and `IndexedDBBridge`) actually correct?**
  _`IndexedDBPriceSyncService` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `IndexedDBBridge` (e.g. with `PriceChange` and `SyncResult`) actually correct?**
  _`IndexedDBBridge` has 11 INFERRED edges - model-reasoned connections that need verification._