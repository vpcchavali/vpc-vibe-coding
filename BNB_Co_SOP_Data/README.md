# BNB Co. S&OP Synthetic Data v1.0

**All records are fictional.**

- 120 finished-good saleable SKUs, 10 suppliers, 2 factories, 2 regional DCs, 6 country DCs, 24 local warehouses, plus maritime port/customs transit nodes.
- 24 months of demand/sales history (October 2024 - September 2026) and 12 months of future plans.
- Philippines and Vietnam carry Thai-made fruit yoghurts through Rayong RDC, sea transport, customs/bulk-break and direct local-warehouse distribution. No country DCs in these markets.
- Batch expiry modeled at 60 days; FEFO drawdowns and write-offs on local warehouse ledger.
- Refer to data_dictionary.csv for field names and validation_report.json for machine-checked tests.

**Known design limits:** The warehouse ledger is reconciled, but upstream inventory stock balances are not fully simulated. Future supply plan is illustrative and must not be treated as an optimized or capacity-approved plan. Historic manufacturing/transport events are linked by batch for demonstration, but the operational timestamps are simplified. There is no materials requirements planning in V1.

**Start here:** item_master.csv, location_master.csv, network_lane_master.csv, item_location_master.csv, item_warehouse_routes.csv. Then load demand_history.csv, sales_history.csv, inventory_movements.csv, inventory_opening.csv and demand_plan.csv.
