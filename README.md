# RIPPLE — 世界経済 What-if エンジン

> **現行アプリについて（2026-11-09）:** `viz/` はコミット `9563fef` のThree.js 3D What-ifビューアへ戻しています。後続のReact/TypeScript 2Dワークベンチは現行画面ではありません。ライセンス、CI、データ系譜などの新しい資料は保持していますが、一部は後続プロトタイプの設計・仕様記録です。

このリポジトリは、世界経済のシナリオ分析を試す研究用prototypeです。旧シミュレーションの出力はバックテストで較正された予測ではなく、画面の「損失」「影響額」等も実現損失・会計上の損失・発生確率を意味しません。利用時はコード、入力データ、仮定の範囲を確認してください。

## アプリを使う

静的ビューアは `viz/index.html` です。企業グラフと事前計算シナリオを同じディレクトリの `viz/data/graph.json`、`viz/data/scenarios.json` から読み込みます。`fetch()` を使うため、ファイルを直接開かずHTTPサーバー経由で表示してください。

```bash
python3 -m http.server 8000 --directory viz
```

ブラウザーで `http://localhost:8000/` を開きます。リポジトリにあるグラフ・シナリオのスナップショットをそのまま表示できます。データを再生成する `python3 scripts/export_viz.py` はローカルSQLiteデータベースを必要とします。

CLIのシナリオ計算は `scripts/scenario_engine.py` です。SQLite/ICIO入力、NumPyとSciPyが利用できる環境で実行します。例えば `python3 scripts/scenario_engine.py --scenario oil_price --multiplier 2.0 --iterations 300` です。入力がない場合に値を補ったり、公開出力が検証済み精度になるわけではありません。

## 現行ビューアの範囲

現行の旧版ビューアは、日本上場企業のネットワークと事前計算したシナリオ結果を3D表示します。エンジンのシナリオ種別は原油価格、国・地域の封鎖、チョークポイント、企業破綻、港湾閉鎖などです。グラフ、エッジ、企業単位の結果、事前計算値は旧版の前提に依存します。企業間の調達関係・経路、事象確率、企業別の損失を観測したデータと誤認しないでください。

`viz/data/scenarios.json` の集計値（`total_impact_oku`等）は旧エンジンの条件付きシミュレーション出力です。経済損失額、倒産確率、実測値、予測精度として引用できる検証はされていません。`scripts/scenario_engine.py` は当時の試作計算経路で、利用には入力・仮定・コードの個別レビューが必要です。

## 保持している設計・データ資料

- [データ系譜・利用条件](docs/data-sources.md) は、このリポジトリのデータと後続分析prototypeを含む出典・再利用境界を記録します。列挙された全資料が現行ビューアで読み込まれるとは限りません。
- [Scenario Bundle仕様](docs/scenario-bundle.md) は後続React/TypeScript prototypeの `ripple-scenario/1.3` の歴史的仕様です。現行の旧版ビューアがこのJSON/CSV Bundleを出力するという意味ではありません。
- [データベース設計書](docs/00_DATABASE_DESIGN.md) と [Cloudflareデプロイガイド](docs/cloudflare_deploy.md) は歴史的な資料です。pushでWeb公開される構成ではありません。
- ライセンス、[貢献ガイド](CONTRIBUTING.md)、[セキュリティポリシー](SECURITY.md)、CIは残しています。CIはデータ整合性とPythonスクリプトの構文・静的ビューアのJSONを検査し、予測性能を検証するものではありません。

## データの出典・ライセンス

ソースコードは[`LICENSE`](LICENSE)に記載したApache License 2.0の対象です。企業一覧、統計値、SQLiteデータベース、生成スナップショット、地図境界、第三者資料に同じライセンスを一括適用しません。OECD、EDINET、JPX、Wikidata、UN Comtrade、World Bank、Natural Earth等の条件は[データ系譜・利用条件](docs/data-sources.md)で出典別に確認してください。とくにJPXの商用利用条件や第三者統計は、ソースコードのライセンスだけで自由に再利用できません。

データ取得・再生成時は、原資料の利用条件、取得時点、単位、加工内容、出典表示を確認してください。認められていないデータの再配布や、企業・港湾・工場・輸送経路の未観測リンクを観測済みとして追加しないでください。

## 検査

```bash
python3 -m pip install -r requirements-workbench.txt
python3 scripts/export_workbench.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/scenario_engine.py scripts/export_viz.py
```

`requirements-workbench.txt` はデータスナップショット用依存です。旧CLIシミュレーションにはNumPyとSciPyが必要です。CIはPythonのデータ系譜・スナップショット試験と、旧ビューアの読み込みJSONを確認します。テスト通過はモデルの実体経済予測の検証・的中率を意味しません。

## リポジトリ構成

```text
docs/        データ系譜、利用条件、歴史的な設計・仕様資料
scripts/     データ出力、取得スクリプト、旧シナリオエンジン
analysis/    実験結果・バックテスト資料
raw/         一次データ・地理ファイル
data/        産業連関用の中間データ
db/          SQLite研究データ
viz/         現行の静的Three.jsビューアとgraph/scenario JSON
archive/     過去の画面・データの記録
```

## コードライセンス

コードはApache License 2.0です。データ・第三者資料の権利は[データ源ドキュメント](docs/data-sources.md)を参照してください。
