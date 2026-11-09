# 貢献する

このリポジトリは研究用prototypeです。モデル精度を裏付けるデータや過去検証が無い機能を、予測・確率・企業固有損失として追加しないでください。現行の有効画面は `viz/index.html` の旧Three.jsビューアです。後続React/TypeScript 2DワークベンチとScenario Bundleの資料は設計記録であり、現在の画面の機能を示すものではありません。

## ローカル実行と検査

1. 静的ビューアはリポジトリrootで `python3 -m http.server 8000 --directory viz` を実行し、`http://localhost:8000/` を開きます。`viz/data/graph.json` と `viz/data/scenarios.json` はコミット済みスナップショットです。
2. グラフデータを再生成する `python3 scripts/export_viz.py` はローカルSQLiteデータベースを必要とします。CLIシミュレーション `scripts/scenario_engine.py` はSQLite/ICIO入力、NumPyおよびSciPyを必要とします。出力は検証済み予測や実測損失ではありません。
3. 後続のデータスナップショットと整合性試験は `python3 -m pip install -r requirements-workbench.txt`、`python3 scripts/export_workbench.py`、`python3 -m unittest discover -s tests -p 'test_*.py'` で確認します。
4. 旧エンジン・データ出力スクリプトの構文は `python3 -m py_compile scripts/scenario_engine.py scripts/export_viz.py` で確認します。CIはこのPython試験と静的ビューアJSONを検査します。以前のReact/Viteの型検査・モデル試験は、現行`viz/`には含まれません。

## 変更提案の原則

モデル変更では、shock channel、国×産業ノード、係数と分母、変換単位、ユーザー設定、未観測値の扱い、サイクルと重複フローへの対応、不確実性、出力の読み方を説明してください。コードを変える場合は、固定コード・データ・設定・seedで再現可能な小さなテストを付けてください。証拠データを取り込む際は、観測／推定、出典文書と箇所、公開日・取得日、基準日、単位、欠損、代替関係、ライセンスを同時に記録します。個社売上額や倒産確率を表示する提案には、対応する実データと独立の履歴較正・バックテストが必要です。

UIの変更では、色と文字の両方で根拠を区別し、キーボードと読み上げ、375pxの幅、`prefers-reduced-motion`、数値の単位と比較対象を確認してください。保存形式や画面で、モデル出力をイベント発生確率・実測損失・企業固有の実績として扱わないでください。

## ライセンス

コードは[`LICENSE`](LICENSE)に従います。コードの利用許諾は、リポジトリ由来の会社一覧・提出書類・行列・画像・第三者資料には及びません。出典個別の条件と採用データの対象範囲は[`docs/data-sources.md`](docs/data-sources.md)に従います。データを追加するPull Requestには、そのデータの利用条件と配布可能な根拠を記載してください。
