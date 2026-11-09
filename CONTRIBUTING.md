# 貢献する

RIPPLEは、モデルの境界を明示して検討できる研究用ワークベンチです。モデル精度を裏付けるデータや過去検証が無い機能を、予測・確率・企業固有損失として追加しないでください。

## ローカル開発

1. Python 3.12以降とNode.js 22以降を準備します。
2. `python3 -m pip install -r requirements-workbench.txt` でスナップショット生成依存を入れます。
3. リポジトリにあるSQLite・ICIO係数・Natural Earthファイルから `python3 scripts/export_workbench.py` を実行します。生成物は `viz/public/data/` に作られ、`.gitignore` により追跡しません。配布条件の確認済み入力以外を取得・追加するときは、ライセンスと帰属を先にレビューしてください。
4. `cd viz && corepack enable && pnpm install` でロックされた依存を使い `pnpm dev`、`pnpm test`、`pnpm build` を実行します。プレビューは `http://localhost:3000` を使います。
5. Python出力整合性テストはリポジトリルートで `python3 -m unittest discover -s tests -p 'test_*.py'` です。

## 変更提案の原則

モデル変更では、shock channel、国×産業ノード、係数と分母、変換単位、ユーザー設定、未観測値の扱い、サイクルと重複フローへの対応、不確実性、出力の読み方を説明してください。コードを変える場合は、固定コード・データ・設定・seedで再現可能な小さなテストを付けてください。証拠データを取り込む際は、観測／推定、出典文書と箇所、公開日・取得日、基準日、単位、欠損、代替関係、ライセンスを同時に記録します。個社売上額や倒産確率を新たに表示する提案は、対応する実データと独立の履歴較正・バックテストを提示してください。

UIの変更では、色と文字の両方で根拠を区別し、キーボードと読み上げ、375pxの幅、`prefers-reduced-motion`、数値の単位と比較対象を確認してください。ユーザーがJSON Scenario Bundleから入力と結果を読み取れるように保ってください。

## ライセンス

コードは[`LICENSE`](LICENSE)に従います。コードの利用許諾は、リポジトリ由来の会社一覧・提出書類・行列・画像・第三者資料には及びません。出典個別の条件と採用データの対象範囲は[`docs/data-sources.md`](docs/data-sources.md)に従います。データを追加するPull Requestには、そのデータの利用条件と配布可能な根拠を記載してください。
