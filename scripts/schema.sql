-- cybermap.sqlite schema v2 (see docs/00_DATABASE_DESIGN.md)
CREATE TABLE company (
  company_id TEXT PRIMARY KEY,
  legal_name TEXT NOT NULL,
  name_ja TEXT, name_en TEXT, short_name TEXT,
  country TEXT, region TEXT, city TEXT,
  entity_type TEXT NOT NULL DEFAULT 'company',
  listing_status TEXT NOT NULL DEFAULT 'unlisted',
  status TEXT NOT NULL DEFAULT 'active',
  layer TEXT NOT NULL DEFAULT 'F_jp',
  founded_year INTEGER, employees INTEGER,
  sector_gics TEXT, sector_j33 TEXT, sector_sic TEXT,
  homepage TEXT,
  created_at TEXT, updated_at TEXT,
  data_quality REAL DEFAULT 0.0
);

CREATE TABLE company_alias (
  alias TEXT NOT NULL, lang TEXT, alias_type TEXT,
  company_id TEXT NOT NULL REFERENCES company,
  source TEXT, confidence REAL,
  PRIMARY KEY (alias, lang, company_id)
);

CREATE TABLE id_map (
  id_type TEXT NOT NULL, id_value TEXT NOT NULL,
  company_id TEXT NOT NULL REFERENCES company,
  exchange TEXT, valid_from TEXT, valid_to TEXT, source TEXT,
  PRIMARY KEY (id_type, id_value)
);

CREATE TABLE relation (
  edge_id TEXT PRIMARY KEY,
  src_id TEXT NOT NULL, dst_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  share_pct REAL, revenue_share REAL, cost_share REAL,
  amount REAL, currency TEXT,
  dependency_status TEXT NOT NULL,
  as_of TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
  source_tier INTEGER NOT NULL, source_ref TEXT,
  extraction TEXT, confidence REAL NOT NULL
);
CREATE INDEX ix_rel_src ON relation(src_id, relation_type);
CREATE INDEX ix_rel_dst ON relation(dst_id, relation_type);

CREATE TABLE financials (
  company_id TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
  period TEXT NOT NULL, currency TEXT NOT NULL,
  revenue REAL, operating_income REAL, net_income REAL,
  total_assets REAL, equity REAL, cash REAL, interest_debt REAL,
  current_assets REAL, current_liabilities REAL,
  inventory REAL, receivables REAL, payables REAL, cogs REAL,
  employees INTEGER, capex REAL, rd_expense REAL,
  consolidation TEXT,
  source_tier INTEGER, source TEXT, as_of TEXT,
  PRIMARY KEY (company_id, fiscal_year, period, consolidation)
);

CREATE TABLE market_snapshot (
  company_id TEXT NOT NULL, snap_date TEXT NOT NULL,
  market_cap_jpy REAL, price REAL, currency TEXT, source TEXT,
  PRIMARY KEY (company_id, snap_date)
);

CREATE TABLE geo_exposure (
  company_id TEXT NOT NULL, country TEXT NOT NULL,
  kind TEXT NOT NULL, share REAL NOT NULL,
  dependency_status TEXT NOT NULL,
  as_of TEXT, source_tier INTEGER, source TEXT,
  PRIMARY KEY (company_id, country, kind, as_of)
);

CREATE TABLE segment (
  company_id TEXT NOT NULL, segment_name TEXT NOT NULL,
  sector_code TEXT, revenue_share REAL,
  as_of TEXT, source TEXT,
  PRIMARY KEY (company_id, segment_name, as_of)
);

CREATE TABLE shareholding (
  company_id TEXT NOT NULL, holder_name_raw TEXT NOT NULL,
  holder_id TEXT, holder_type TEXT,
  share_pct REAL, rank INTEGER,
  as_of TEXT NOT NULL, source_tier INTEGER, source_ref TEXT,
  PRIMARY KEY (company_id, holder_name_raw, as_of)
);

CREATE TABLE facility (
  facility_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
  name TEXT, country TEXT, lat REAL, lon REAL,
  facility_type TEXT, capacity_share REAL,
  as_of TEXT, source_tier INTEGER, source TEXT
);

CREATE TABLE country_industry (
  ci_id TEXT PRIMARY KEY,
  country TEXT NOT NULL, industry TEXT NOT NULL,
  industry_code_standard TEXT
);

CREATE TABLE sector_io (
  year INTEGER NOT NULL, buyer_ci TEXT NOT NULL, seller_ci TEXT NOT NULL,
  io_coeff REAL NOT NULL, source TEXT,
  PRIMARY KEY (year, buyer_ci, seller_ci)
);

CREATE TABLE trade_flows (
  year INTEGER NOT NULL, exporter TEXT NOT NULL, importer TEXT NOT NULL,
  hs_section TEXT, value_usd REAL, source TEXT,
  PRIMARY KEY (year, exporter, importer, hs_section)
);

CREATE TABLE shipping_route (
  route_id TEXT PRIMARY KEY, name TEXT, chokepoint INTEGER,
  world_capacity_share REAL, alt_route_cost_mult REAL, alt_route_days_add REAL,
  source TEXT
);

CREATE TABLE port (
  port_id TEXT PRIMARY KEY, name TEXT, country TEXT,
  lat REAL, lon REAL, teu_annual REAL, country_container_share REAL, source TEXT
);

CREATE TABLE commodity_price (
  commodity_id TEXT NOT NULL, price_date TEXT NOT NULL,
  price REAL, unit TEXT, currency TEXT, source TEXT,
  PRIMARY KEY (commodity_id, price_date)
);

CREATE TABLE country_risk (
  country TEXT NOT NULL, as_of TEXT NOT NULL,
  conflict_intensity REAL, sanctions_intensity REAL, governance REAL,
  source TEXT, PRIMARY KEY (country, as_of)
);

CREATE TABLE macro_series (
  series_id TEXT NOT NULL, obs_date TEXT NOT NULL, value REAL, source TEXT,
  PRIMARY KEY (series_id, obs_date)
);

CREATE TABLE geo_hazard (
  hazard_id TEXT PRIMARY KEY, hazard_type TEXT, geometry TEXT,
  probability_1y REAL, source TEXT
);

CREATE TABLE scenario (
  scenario_id TEXT PRIMARY KEY, name TEXT NOT NULL, scenario_type TEXT NOT NULL,
  params_json TEXT NOT NULL, description TEXT, created_at TEXT, created_by TEXT
);

CREATE TABLE simulation_run (
  run_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL,
  model_version TEXT NOT NULL, params_json TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, status TEXT
);

CREATE TABLE simulation_result (
  run_id TEXT NOT NULL, company_id TEXT NOT NULL,
  direct_loss_pct REAL, total_loss_mean REAL,
  total_loss_p50 REAL, total_loss_p90 REAL, total_loss_p99 REAL,
  default_prob REAL, basis TEXT NOT NULL, top_paths_json TEXT,
  PRIMARY KEY (run_id, company_id, basis)
);

CREATE TABLE backtest (
  test_id TEXT PRIMARY KEY, event TEXT, run_id TEXT NOT NULL,
  predicted_json TEXT, realized_json TEXT, metrics_json TEXT, created_at TEXT
);
