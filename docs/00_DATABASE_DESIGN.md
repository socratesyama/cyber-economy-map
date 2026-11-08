# サイバー経済マップ — データベース精密設計書 v2

**目標**: 観測された企業間関係 + 財務状態 + 産業構造 + 外部環境から、任意のWhat-ifシナリオを与えたときの損失伝播を**確率分布として**推定する「世界経済のWhat-ifエンジン」。

**完成形の定義（v2で確定）**:
- 企業ノードは**日本の上場企業を中心**に収録する
- ただし**外部環境モデル（貿易・物流・資源・エネルギー・為替・地政学・災害）は世界規模**で持つ
- 海外側の伝播は「国×産業」集計で表現し、日本企業と直接つながる海外企業だけ個別ノード化する
- この構成だけで「台湾海峡封鎖・原油2倍・スエズ停止・銀行破綻・半導体工場停止・制裁・大地震・港湾閉鎖・サイバー攻撃・パンデミック・輸出禁止」が**同じ1個のエンジン**で走る

設計思想（不変の3原則）:
1. **すべての事実は「出典・時点・信頼度・観測/推定フラグ」付き**で保存する
2. **関係は「方向・種類・強度」を持つ有向重み付きグラフ**として統一する
3. **計算は完全に再現可能**（シナリオ・パラメータ・乱数シード・モデル版をDBに残す）

科学性の原則（妥協しない）:
- 開示された関係と推定した関係を**必ず分離**する
- 売上依存度が不明なら**勝手に数値を補わない**（推定フラグ＋幅として別扱い）
- 代替供給先と在庫を考慮する
- 同じ損失を複数経路で**二重計上しない**（フロー会計、後述）
- 予測値には必ず**不確実性の幅**を付ける
- 過去の災害・供給停止・価格変動で**バックテスト検証**する
- 倒産確率は実際の倒産履歴で**別途較正**する
- 産業連関表の波及と企業間取引の波及の**重複を防ぐ会計整合**を取る

---

## 1. 全体アーキテクチャ — 2層グラフ + 外部環境

```
                ┌─────────────────────────────────────────────┐
                │  外部環境レイヤ（世界規模・時系列）            │
                │  貿易統計 / 海運ルート / 資源価格 / 国リスク    │
                │  為替・金利 / 災害地理 / 産業連関表            │
                └──────────────────────┬──────────────────────┘
                                       │ シナリオ→ショック変換
        ┌──────────────────────────────┴───────────────────────┐
        │              What-if エンジン（単一）                 │
        │  Layer A: 国×産業ノード（集計・世界）                  │
        │  Layer F: 企業ノード（日本上場中心 + 境界海外企業）     │
        └──────────────────────────────┬───────────────────────┘
                                       │ モンテカルロ
                              損失率の確率分布
                    「何が起きたら、どこが最初に揺れるか」
```

### 1.1 Layer F（企業層）
- **日本上場企業（約3,900社）**: 全ノード。観測された関係（EDINET有報・Wikidata・報道）で結ぶ。
- **境界海外企業**: 日本企業の親会社・子会社・主要取引先・主要顧客である海外企業のみ、必要に応じて個別ノード化（`resolution_level='firm'`）。
- それ以外の海外経済は Layer A で表現。

### 1.2 Layer A（集計層）
- ノード = (国 × 産業)。OECD ICIO（Inter-Country Input-Output）を標準とする。
- エッジ = 投入産出係数（buying sector の総投入に占める selling 国×産業からの投入比率）。
- **会計整合**: 日本企業の間に観測エッジがある部分は、Layer A の該当セルを**上書き（置換）**し、残りをIO残差で埋める。足し合わせない（§5.6 参照）。

---

## 2. ストレージ構成

```
cyber-economy-map/
├── docs/        設計書（本書・データソース登録簿・計算仕様）
├── raw/         生データ（取得日入り・不変）
├── data/        Stage1-2 産物（CSV/Parquet）
├── db/          cybermap.sqlite（本体）/ analytics.duckdb（集計用）
├── scripts/     取得・名前解決・グラフ構築・シミュレーション
├── analysis/    バックテスト・較正
└── viz/         Three.js ダッシュボード
```

- `cybermap.sqlite`: 100万ノードまで単一ファイルで扱える。GitHubでそのまま配布可能。
- `raw/` は日付ごとに不変保存。大ファイルは Parquet + gzip。

---

## 3. ID体系とエンティティ解決

### 3.1 会社ID
- `company_id` = ULID（内部主キー）
- 外部IDは `id_map` で統一: `wikidata_qid / edinet_code / isin / lei / ticker+exchange / jp_corporate_number（日本の全法人に付く13桁）`
- **日本の未上場社は法人番号で一意に決まる**（国税庁データは全法人約500万件分公開）。100万社スケールの土台はこれ。

### 3.2 名前解決パイプライン
```
正規化: 全角→半角 / 大文字統一 / 法人形態除去（(株)・株式会社・Inc.・GmbH…）
        / 記号除去 → normal_key
照合:   normal_key + 国 → 別名テーブル → トークンJaccard ≥ 閾値
未解決: company_unresolved に入れ、LLM/手動判定キューへ
```
- 誤マージは伝播計算を汚染するため、**precision優先の保守的閾値**。解決履歴は `resolution_log` に全件残し取り消し可能に。

---

## 4. テーブル定義（DDL）

### 4.1 企業層

```sql
CREATE TABLE company (
  company_id   TEXT PRIMARY KEY,            -- ULID
  legal_name   TEXT NOT NULL,
  name_ja      TEXT, name_en TEXT, short_name TEXT,
  country      TEXT,                        -- ISO-3166 alpha-2
  region       TEXT, city TEXT,
  entity_type  TEXT NOT NULL DEFAULT 'company',
    -- company | holding | subsidiary | bank | fund | government_entity
  listing_status TEXT NOT NULL DEFAULT 'unlisted',  -- listed | delisted | unlisted
  status       TEXT NOT NULL DEFAULT 'active',      -- active | bankrupt | dissolved | acquired
  layer        TEXT NOT NULL DEFAULT 'F_jp',        -- F_jp(日本上場) | F_border(境界海外企業) | A(集計ノード)
  founded_year INTEGER, employees INTEGER,
  sector_gics TEXT, sector_j33 TEXT,        -- 業種コード（マッピングテーブルで相互変換）
  homepage TEXT,
  created_at TEXT, updated_at TEXT,
  data_quality REAL DEFAULT 0.0             -- 0-1
);

CREATE TABLE company_alias (
  alias TEXT NOT NULL, lang TEXT,
  alias_type TEXT,                          -- legal | trade | brand | abbrev | romanized
  company_id TEXT NOT NULL REFERENCES company,
  source TEXT, confidence REAL,
  PRIMARY KEY (alias, lang, company_id)
);

CREATE TABLE id_map (
  id_type TEXT NOT NULL,                    -- wikidata | edinet | isin | lei | ticker | jp_corporate_number
  id_value TEXT NOT NULL, company_id TEXT NOT NULL,
  exchange TEXT, valid_from TEXT, valid_to TEXT, source TEXT,
  PRIMARY KEY (id_type, id_value)
);
```

### 4.2 `relation` — 企業間関係エッジ（Layer F 内部）

```sql
CREATE TABLE relation (
  edge_id     TEXT PRIMARY KEY,
  src_id TEXT NOT NULL, dst_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
    -- ownership_parent_of : src が dst の親 (share_pct)
    -- supply_seller_to    : src が dst に販売 (revenue_share)
    -- supply_buyer_of     : src が dst から仕入 (cost_share)
    -- financing_lender_to : src が dst に融資 (amount)
    -- joint_venture | alliance | director_overlap
  share_pct REAL, revenue_share REAL, cost_share REAL,
  amount REAL, currency TEXT,
  dependency_status TEXT NOT NULL,          -- ★観測/推定の分離
    -- observed_value  : 依存度の数値を出典が直接与える（例: 有報の相手先別売上）
    -- observed_binary : 関係の存在のみ観測、数値は不明
    -- estimated       : 業種・規模からの統計的推定（幅付き）
    -- unknown         : 数値不明（計算には使わない。存在フラグのみ）
  as_of TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
  source_tier INTEGER NOT NULL,             -- 1-5（§7）
  source_ref TEXT,                          -- 文書URL / XBRL要素 / 記事URL
  extraction TEXT,                          -- api | registry | structured_wiki | nlp_news | co_mention | manual
  confidence REAL NOT NULL                  -- 0-1
);
CREATE INDEX ix_rel_src ON relation(src_id, relation_type);
CREATE INDEX ix_rel_dst ON relation(dst_id, relation_type);
```

**ルール**:
- `dependency_status='unknown'` のエッジは**平均損失の計算から除外**し、感度分析にのみ使う。
- `estimated` のエッジは結果レポートで「観測のみ」「推定込み」の2種類を**必ず両方出す**。
- 同一 (src, dst, type, as_of月) の重複は出典優先度で解決: `EDINET有報(1) > 登記・公的DB(2) > Wikidata/構造化Wiki(3) > ニュースNLP(4) > 共起(5)`。不採用分は `relation_archive` に保管。

### 4.3 財務・暴露（時系列）

```sql
CREATE TABLE financials (
  company_id TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
  period TEXT NOT NULL,                     -- FY | H1
  currency TEXT NOT NULL,
  revenue REAL, operating_income REAL, net_income REAL,
  total_assets REAL, equity REAL, cash REAL, interest_debt REAL,
  current_assets REAL, current_liabilities REAL,
  inventory REAL, receivables REAL, payables REAL, cogs REAL,
  employees INTEGER, capex REAL, rd_expense REAL,
  consolidation TEXT,                       -- consolidated | standalone
  source_tier INTEGER, source TEXT, as_of TEXT,
  PRIMARY KEY (company_id, fiscal_year, period, consolidation)
);

CREATE TABLE geo_exposure (                 -- 地理別の売上・仕入構成（戦争・制裁の要）
  company_id TEXT NOT NULL, country TEXT NOT NULL,
  kind TEXT NOT NULL,                       -- revenue | procurement
  share REAL NOT NULL,                      -- 0-1
  dependency_status TEXT NOT NULL,          -- observed_value | estimated（有報セグメント=observed）
  as_of TEXT, source_tier INTEGER, source TEXT,
  PRIMARY KEY (company_id, country, kind, as_of)
);

CREATE TABLE segment (                      -- 事業セグメント（業種マッピング経由でLayer Aと接続）
  company_id TEXT NOT NULL, segment_name TEXT NOT NULL,
  sector_code TEXT, revenue_share REAL,
  as_of TEXT, source TEXT,
  PRIMARY KEY (company_id, segment_name, as_of)
);

CREATE TABLE shareholding (                 -- 大株主（EDINET「大株主の状況」）
  company_id TEXT NOT NULL, holder_name_raw TEXT NOT NULL,
  holder_id TEXT REFERENCES company,        -- 解決済みなら
  holder_type TEXT,                         -- parent | financial_institution | founder | foreign | other_corp | individual
  share_pct REAL, rank INTEGER,
  as_of TEXT NOT NULL, source_tier INTEGER, source_ref TEXT,
  PRIMARY KEY (company_id, holder_name_raw, as_of)
);

CREATE TABLE facility (                     -- 工場・拠点（地震・サイバーの物理被害用）
  facility_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
  name TEXT, country TEXT, lat REAL, lon REAL,
  facility_type TEXT,                       -- fab | plant | warehouse | port_terminal | dc | hq
  capacity_share REAL,                      -- 会社内生産能力に占める比率（既知なら）
  as_of TEXT, source_tier INTEGER, source TEXT
);
```

### 4.4 外部環境レイヤ（世界規模）

```sql
CREATE TABLE country_industry (             -- Layer A ノード定義
  ci_id TEXT PRIMARY KEY,                   -- 例: "TW-semis"（国×産業）
  country TEXT NOT NULL, industry TEXT NOT NULL,   -- ICIO 36業種 or 拡張分類
  industry_code_standard TEXT               -- isic_rev4 | icio_36
);

CREATE TABLE sector_io (                    -- 国×産業 → 国×産業 の投入産出係数
  year INTEGER NOT NULL,
  buyer_ci TEXT NOT NULL, seller_ci TEXT NOT NULL,
  io_coeff REAL NOT NULL,                   -- buyer総投入に占めるsellerからの投入比率
  source TEXT,                              -- oecd_icio
  PRIMARY KEY (year, buyer_ci, seller_ci)
);

CREATE TABLE trade_flows (                  -- 国際貿易統計（二国間・品目）
  year INTEGER NOT NULL, exporter TEXT NOT NULL, importer TEXT NOT NULL,
  hs_section TEXT,                          -- HS 2桁章（エネルギー・半導体等の選別用）
  value_usd REAL, source TEXT,              -- un_comtrade
  PRIMARY KEY (year, exporter, importer, hs_section)
);

CREATE TABLE shipping_route (               -- 海運ルート・チョークポイント
  route_id TEXT PRIMARY KEY,                -- suez | hormuz | malacca | taiwan_strait | panama ...
  name TEXT, chokepoint INTEGER,            -- 1 = 閉塞で代替不可
  world_capacity_share REAL,                -- 世界海上輸送量に占める比率
  alt_route_cost_mult REAL,                 -- 迂回時のコスト倍率
  alt_route_days_add REAL,                  -- 迂回による追加日数
  source TEXT
);

CREATE TABLE port (                         -- 港湾（閉鎖シナリオ）
  port_id TEXT PRIMARY KEY, name TEXT, country TEXT,
  lat REAL, lon REAL,
  teu_annual REAL,                          -- 年間取扱コンテナ量
  country_container_share REAL,             -- 国の輸出入コンテナに占める比率
  source TEXT
);

CREATE TABLE commodity_price (              -- 資源・原材料価格（時系列）
  commodity_id TEXT NOT NULL,               -- brent | lng_jkm | wheat | dram | lithium ...
  price_date TEXT NOT NULL, price REAL, unit TEXT, currency TEXT,
  source TEXT,                              -- eia | world_bank_pink_sheet
  PRIMARY KEY (commodity_id, price_date)
);

CREATE TABLE country_risk (                 -- 国別リスク（制裁・紛争・政治）
  country TEXT NOT NULL, as_of TEXT NOT NULL,
  conflict_intensity REAL,                  -- 0-1（ACLED/UCDPイベント由来）
  sanctions_intensity REAL,                 -- 0-1
  governance REAL,                          -- WGI等
  source TEXT,
  PRIMARY KEY (country, as_of)
);

CREATE TABLE macro_series (                 -- 為替・金利（金融波及）
  series_id TEXT NOT NULL,                  -- usdjpy | jpy10y | ted_spread | vix ...
  obs_date TEXT NOT NULL, value REAL,
  source TEXT,
  PRIMARY KEY (series_id, obs_date)
);

CREATE TABLE geo_hazard (                   -- 災害・地理リスク
  hazard_id TEXT PRIMARY KEY,
  hazard_type TEXT,                         -- earthquake | typhoon | flood | volcano
  geometry TEXT,                            -- GeoJSON（震度帯・浸水想定）
  probability_1y REAL,                      -- 年発生確率
  source TEXT                               -- jemafdm（政府想定）| jma | global_quake_model
);
```

### 4.5 シナリオとシミュレーション

```sql
CREATE TABLE scenario (
  scenario_id TEXT PRIMARY KEY, name TEXT NOT NULL,
  scenario_type TEXT NOT NULL,
    -- company_bankruptcy | war_blockade | commodity_price | chokepoint_disruption
    -- bank_failure | facility_shutdown | sanctions | earthquake | port_closure
    -- cyberattack | pandemic | export_ban | tariff
  params_json TEXT NOT NULL, description TEXT,
  created_at TEXT, created_by TEXT
);

CREATE TABLE simulation_run (
  run_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenario,
  model_version TEXT NOT NULL,              -- "v1.2-hybrid-cascade"
  params_json TEXT NOT NULL,                -- iterations, seed, θ, β...
  started_at TEXT, finished_at TEXT, status TEXT
);

CREATE TABLE simulation_result (            -- ★結果は必ず分布で持つ
  run_id TEXT NOT NULL, company_id TEXT NOT NULL,
  direct_loss_pct REAL,                     -- 初期ショックのみ
  total_loss_mean REAL,
  total_loss_p50 REAL, total_loss_p90 REAL, total_loss_p99 REAL,
  default_prob REAL,
  basis TEXT NOT NULL,                      -- observed_only | with_estimates（両方出す）
  top_paths_json TEXT,                      -- 頻出伝播経路
  PRIMARY KEY (run_id, company_id, basis)
);

CREATE TABLE backtest (                     -- 検証結果（§6）
  test_id TEXT PRIMARY KEY, event TEXT,     -- 2011_tohoku | 2021_chip_shortage | 2022_ukraine ...
  run_id TEXT NOT NULL,
  predicted_json TEXT, realized_json TEXT,  -- 予測分布 vs 実際の業績下方修正・株価
  metrics_json TEXT,                        -- 相関・Brier score・分位点被覆率
  created_at TEXT
);
```

---

## 5. What-if エンジン — 統一計算規格

### 5.1 シナリオ = チャネルの活性化リスト

すべてのシナリオは共通の「ショックチャネル」の組合せに分解される。**エンジンはチャネルしか知らない**（シナリオ固有ロジックは変換器だけが持つ）。

| チャネル | 例 | 作用先 |
|---|---|---|
| `transport_disruption` | 台湾海峡封鎖・スエズ停止・港湾閉鎖 | shipping_route / port → その経路を使う貿易フロー |
| `price_shock` | 原油2倍・LNG高騰・DRAM急騰 | commodity_price → 当該品目の輸入依存企業 |
| `facility_shutdown` | 半導体工場停止・自社工場被災 | facility → 所属企業 |
| `financial_failure` | 大手銀行破綻 | company(bank) → 融資先 |
| `trade_restriction` | 制裁・輸出禁止・関税 | country × hs_section → 該当貿易フロー |
| `demand_shock` | パンデミック・特定国需要崩落 | country×industry の最終需要 |
| `entity_failure` | 特定企業倒産 | company → 全エッジ |

**変換例（台湾海峡封鎖）**:
```
route: taiwan_strait (capacity_share=0.2, chokepoint=0.7)
→ 日本の対台輸出入 + 台湾経由の第三国貿易が停止率×閉塞率で削減
→ 日本企業: geo_exposure(TW) × 停止率 + 海上輸送の迂回コスト(alt_route_cost_mult)
→ 台湾の産業ノード(A層)に需要・供給ショック → ICIO経由で全世界に伝播 → 日本に還流
```

### 5.2 エッジ伝播係数（全関係型で統一）

エッジ (i → j)（i が被災し j へ影響）について:

**伝播確率**
```
p_ij = confidence × min(1, dependency_ij / θ_p)      θ_p = 0.05（較正対象）
```

**損失強度**
```
s_ij = min(1, dependency_ij × β_type × (1 - substitutability_j) × inventory_relief_ij)
```
- `dependency` の取り方: 仕入側なら `cost_share`（j の総仕入に占める i の比率）、販売側なら `revenue_share`、資本なら `share_pct/100`
- `β_type`: supply=1.0, ownership=0.5, financing=0.7
- `substitutability_j`: 代替調達可能性 = `1/log(1+競合ノード数)`（グラフから計算）× 業種別の代替時間テーブル
- `inventory_relief_ij`: **在庫による減衰**。`inventory_days_j = inventory_j / cogs_j × 365`。停止期間 t < inventory_days なら損失を `t/inventory_days` に線形縮小

### 5.3 バッファ・倒産判定・カスケード

```
buffer_j = (equity_j + cash_j) / revenue_j
L_j^(t+1) = min(1, L_j^(t) + Σ_i s_ij × L_i^(t) × p_ij × (1 - L_j^(t)))
default_j: L_j × revenue_j > equity_j + cash_j  → 全エッジに二次ショック
```

倒産確率は損失率→デフォルトの写像を**ロジスティック関数**で別途較正（§6.2）:
```
PD_j = σ(a + b × L_j + c × buffer_j + 業種ダミー)
```

### 5.4 確率分布化（モンテカルロ）
- `p_ij ~ Beta(confidence×κ, (1-confidence)×κ)`
- `dependency ~ N(obs, 0.3×obs)`（obsが無いエッジは使わない）
- `dependency_status='estimated'` → 業種事前分布からサンプル（幅が広い）
- R = 1,000回 → P50/P90/P99, default_prob
- 出力は basis（observed_only / with_estimates）別に**両方**

### 5.5 二重計上の禁止（フロー会計）
損失は「経路」ではなく「フロー」に割り当てる。各企業 j の損失は:
```
L_j × revenue_j = Σ_フロー f ∈ j の売上/仕入フロー  loss_f
```
- 1つのフロー（例: j の台湾向け売上）に乗る損失は1回だけ。複数の親経路から届く「同じ原因」の損失はフロー単位でmaxを取る（加算しない）
- 飽和項 `(1 - L_j)` が社内の重複を防ぐ

### 5.6 産業連関表と企業取引の会計整合（最重要）
IO波及と企業エッジの重複を防ぐ規則:
1. 日本企業 j の仕入について `Σ(観測エッジの cost_share) + IO残差 = 1` を**恒等式として強制**
2. 観測エッジが存在する (j, seller国×産業) セルは、Layer A の該当係数を**置換**する（足し合わせない）
3. 観測されていないセルのみ IO 事前分布で埋め、`dependency_status='estimated'` を付ける
4. 集計チェック: 全企業の仕入合計 ≒ 国の産業連関表の該当行。ズレは「統合残差」として明示的に公表

### 5.7 探索モード（最終目標）
- **Forward**: シナリオ → 世界のどこが最初に揺れるか（伝播の時間順位）
- **Reverse**: 「トヨタに10%以上の損失を与える最小ショック集合」を探索（エッジのcriticality = 除去時のシステム損失増分）
- Critical link / critical node ランキングを `analysis/` に定常出力

---

## 6. 科学的成立条件（検証と較正）

### 6.1 バックテスト
| イベント | 検証対象 |
|---|---|
| 2011 東日本大震災 | 部品供給停止→完成品減産（自動車・電機）の伝播 |
| 2020-21 コロナ/半導体不足 | 需要ショック→供給制約→完成品減産 |
| 2022 ウクライナ戦争 | エネルギー価格→輸入企業の利益率低下 |
| 2024 能登半島地震 | 地理的近接性と在庫の効果 |
| 過去の主要銀行経営破綻 | 融資チャネルの伝播 |

指標: 損失率予測分布 vs 実際の業績下方修正率・株価ドローダウンの相関、P90の被覆率（実績がP90内に収まる率 ≒ 90%が理想）。

### 6.2 倒産確率の較正
- 東証上場企業の過去30年の倒産・上場廃止履歴（業種×規模×時点）で、損失率→デフォルト写像のロジスティック回帰をフィット。
- 理論倒産確率と実績倒産率の較正曲線を `analysis/calibration/` に保存。

### 6.3 不確実性の報告規格
すべての公開数値は `point estimate ± (P10, P90)` セットで出す。推定エッジを使った結果は「観測のみ」の結果と必ず並記する。

---

## 7. 出典優先度

| tier | 出典 | 既定confidence |
|---|---|---|
| 1 | 法定開示: EDINET有報XBRL・法人番号・UN Comtrade・OECD ICIO・政府統計 | 0.98 |
| 2 | 公的DB: LEI, OpenCorporates, EIA/世界銀行価格 | 0.90 |
| 3 | 構造化Wiki: Wikidata, Wikipedia基礎情報 | 0.75 |
| 4 | ニュースNLP: 提携・取引報道 | 0.55 |
| 5 | 共起統計: GDELT GKG | 0.35 |

tier 5 は単独では関係と認めず、tier 1-4 の補強または業種集計にのみ使用。

---

## 8. 現在のデータ取得状況と次の一手

| ソース | 対象 | 状態 |
|---|---|---|
| JPX 上場銘柄一覧 | 3,893社（内国株式） | ✅ 取得済み |
| Yahoo Finance | 時価総額・売上・財務 | ✅ スクリーンAPIで一括取得中 |
| Wikidata SPARQL | 資本関係 2,875エッジ（日本上場＋子会社） | ✅ 取得済み |
| EDINET API v2 | 大株主・関係会社・主要販売仕入先・地域別売上 | ⏳ 無料APIキー登録が必要（ユーザー作業）。パイプラインは scripts/ に実装 |
| OECD ICIO | 国×産業連関表 | 次の取得対象 |
| UN Comtrade | 二国間貿易 | 次の取得対象 |
| EIA / 世界銀行 Pink Sheet | エネルギー・資源価格 | 次の取得対象 |
| 運河・チョークポイント統計 | 海運ルート | 次の取得対象（公表値を手動テーブル化） |
| 国税庁法人番号 | 未上場社の土台 | 第2フェーズ |

---

## 9. 視覚化仕様（Three.js）

- **ノード**: 球。半径 ∝ √時価総額、色 = 国/業種切替、Y軸 = 業種、XZ = 力指向配置
- **エッジ**: 発光ライン（AdditiveBlending）。太さ = dependency、色 = relation_type、**観測=実線 / 推定=点線**（科学性の可視化）
- **Layer A** は背景に半透明の国×産業プレーンとして描き、Layer F がその上に浮かぶ
- **シミュレーション再生**: ショック源からラウンドごとにパルスが走る。倒産nodeは赤黒く崩壊
- **分布パネル**: クリックで損失ヒストグラム（P50/P90/P99）＋倒産確率
- 出力: `viz/graph_{version}.json`（座標はPythonで事前計算）

---

## 10. ロードマップ

- **Phase 1（現在）**: 日本上場3,900社のノード＋資本関係＋財務でDB構築。EDINETキー取得後に観測エッジを大量投入
- **Phase 2**: 外部環境レイヤ（ICIO・Comtrade・価格・運河）を取り込み、チャネル変換器を実装
- **Phase 3**: モンテカルロ伝播＋バックテスト較正
- **Phase 4**: 未上場社（法人番号ベース）拡張、Three.jsダッシュボード
