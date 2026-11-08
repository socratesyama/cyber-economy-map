# サイバー経済マップ — 世界経済のWhat-ifエンジン

観測された企業間関係 + 財務状態 + 産業構造 + 外部環境から、任意のWhat-ifシナリオ
（台湾海峡封鎖・原油価格2倍・スエズ運河停止・大手銀行破綻・半導体工場停止・制裁・
大地震・港湾閉鎖・サイバー攻撃・パンデミック・原材料輸出禁止・特定企業の倒産…）を
与えたときの**損失伝播を確率分布として推定する**システム。

最終目標は「**何が起きたら、世界のどこが最初に揺れるのか**」を探索する道具。

## アーキテクチャ（v2）

- **Layer F（企業層）**: 日本の上場企業（約3,900社）を中心に個別企業ノードを収録。
  日本企業と直接つながる海外企業（親・子会社・主要取引先）のみ個別ノード化（境界ノード）
- **Layer A（集計層）**: 国×産業ノード（OECD ICIO）。海外側の伝播はここで表現
- **外部環境レイヤ**: 貿易統計・海運ルート・資源価格・国リスク・為替金利・災害地理（世界規模）
- **単一エンジン**: すべてのシナリオは共通の「ショックチャネル」に分解されて同じエンジンで走る

設計の詳細は [docs/00_DATABASE_DESIGN.md](docs/00_DATABASE_DESIGN.md) を参照。

## 現在の状態（Phase 1）

| データ | 状態 |
|---|---|
| 日本上場企業 3,893社（JPX） | ✅ ノード化済み |
| 時価総額 3,701社（Yahoo） | ✅ |
| 財務（売上・従業員等）1,421社 | ✅（残りはEDINET取得後に置換） |
| 資本関係エッジ（Wikidata） | ✅ 1,999本（tier 3・observed_binary） |
| EDINET有報XBRL（大株主・財務・関係会社） | ✅ **tier 1 取得済み**: 2,245社分の有報CSVを解析。大株主 21,528件（うち3,780本の資本エッジは持分比率observed_value）、連結財務 2,147社（IFRS/GAAP自動判別） |
| OECD ICIO 2023（Layer A・国×産業連関） | ✅ 2020年表: 3,465ノード、40万係数（`data/icio2020_coeff.npz`） |
| UN Comtrade・資源価格・運河・為替 | Phase 2（スキーマ実装済み） |

`db/cybermap.sqlite` に全データ格納（5,529社・23テーブル）。

## クイックスタート

```bash
# デモ: トヨタ自動車が倒産したらどこが揺れるか（エンジン動作確認用）
cd scripts
python3 simulate_demo.py --ticker 7203 --iterations 1000

# EDINET取得（要: 無料APIキー https://www.fsa.go.jp/opendata/）
export EDINET_KEY="..."
python3 fetch_edinet.py --start 2026-10-01 --end 2026-10-31 --download

# DB再構築
python3 build_db.py
```

## 科学性の原則

- 開示された関係と推定した関係を**必ず分離**（`dependency_status` カラム）
- 依存度が不明なら数値を補わない（`unknown` は計算から除外、`estimated` は別レポート）
- 代替供給・在庫による減衰を考慮
- フロー会計で二重計上を禁止（産業連関表との整合はエッジ置換で解決）
- 予測は必ず P50/P90/P99 の分布で、観測のみ/推定込みの両方を出す
- 過去の災害・供給停止でバックテスト、倒産確率は実績で較正

## ディレクトリ

```
docs/       設計書
raw/        生データ（不変）
data/       Stage1-2 産物 (CSV/JSONL)
db/         cybermap.sqlite
scripts/    取得・構築・シミュレーション
analysis/   デモ結果・バックテスト
viz/        Three.jsダッシュボード（Phase 4）
```

## データソースとライセンス

- JPX上場銘柄一覧（JPX公式、月次更新）
- Wikidata（CC0）
- Yahoo Finance（API経由、研究目的）
- EDINET API v2（金融庁、要無料登録）
- 今後: OECD ICIO / UN Comtrade / EIA / 世界銀行 Pink Sheet（オープンデータ）
