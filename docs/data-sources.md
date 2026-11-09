# RIPPLEのデータ系譜・帰属表示・再利用境界

> **適用範囲:** この資料はリポジトリ内データと後続分析prototypeの出典・再利用方針を保持する参照文書です。現行の`viz/`は`9563fef`状態の旧版ビューアであり、一覧にある全データ源・後続2D UI機能を読み込むことを意味しません。

RIPPLEのプログラムコードはApache-2.0です。このライセンスは、SQLiteデータベース、生成したデータスナップショット、各社の会社名・銘柄・セクター、提出書類の値、地図境界やその他の第三者データまで一括して許諾するものではありません。データは原資料固有の条件に従います。権利・再配布条件を確認できていないデータを、オープンなデータと表示しないでください。

## リポジトリと過去prototypeのデータ

|データ|アプリ上の用途・粒度|取得時点・注意点|利用条件・帰属|
|---|---|---|---|
|OECD Inter-Country Input-Output (ICIO)|国×産業のbuyer-seller投入係数から作る国産業ストレスproxy|元リポジトリのSQLiteが使う2020年の行列。会社別調達、会社固有売上、海峡通過、二国間貿易の実測ではない|OECDの利用条件は、追加制限がなければデータのダウンロード・加工・共有を許す一方、第三者権利・データセット固有条件の確認とOECDの該当データ引用を要求。採用ファイルのエディション・DOI・元ファイルを確認してから更新する|
|日本上場企業の名称・銘柄・業種|企業検索、名称確認、広い分類コードを表示する会社名鑑。会社別の調達率・損失・順位には利用しない|SQLite内のJapan-listed company masterのスナップショット。会社分類と業種写像は不完全。個社リンク無し|JPXの利用規約はサイト情報の権利をJPXに留保し、商用目的の情報収集・二次利用を許可なく行うことを禁止。会社データにApache-2.0は適用しない。RIPPLEから商用配布・商用収集へ転用するには、JPXの許諾又は適用される契約を要確認|
|EDINET由来の提出・関係情報|利用できる一部の持株・資本関係リンクを、開示値・関係観測・出典時点・信頼度と共に表示。財務金額はエンジンに接続しない|年次有価証券報告書の記録やEDINET由来の関係。機械抽出、誤り訂正、個々の出典差に注意|EDINET利用規約はデジタル庁公共データ利用規約（PDL1.0）を採用。編集・加工した場合、出典に加え編集主体と編集内容を表示し、国が未加工で作成したように表示しない。APIでの取得時は最新API仕様・API利用条件に従う|
|Wikidata|一部の親子・持株関係を識別。資本関係を仕入・貸付・売上へ読み替えない|source_tierとdependency_statusを保持。二値の関係と比率がある関係は区別|Wikidataの構造化データはCC0。各レコードのsource_refと関係種別を確認|
|既存企業メッシュの2D表示座標|会社IDとx/yの描画位置のみ。既存3D表示のx/y/z配置から決定論的なPCAで二次元投影する。地理座標や経済量ではなく、従属先を示す新しい取引データでもない|3,893社の配置。資本関係は5,836件の根拠記録・5,573組の一意ペア。双方が配置対象に含まれる2,002組のみ描画し、配置外端点を持つ3,571組には座標を捏造しない。時系列観測値ではなく、古いノード市場値・サイズ・色・エッジ値は再出力しない|元データの出典・利用条件は引き続き適用。導出座標をソースコードApache-2.0で再許諾しない。新しい資本関係または第三者データ権を作るものではない|
|Natural Earth Admin 0|後続prototypeの世界地図背景、国境・地域名と対象ノード国の照合|Natural Earth 1:110m。de facto境界の可視化であり、政治的境界を公式判断する用途ではない|Natural Earthは地図データをpublic domainとして扱い、`Made with Natural Earth` のクレジットを推奨。現行の旧版ビューアでは使用しない|
|6件の日本港湾座標|地図上の港湾位置だけを表示|日本の6港。港湾位置は資本・仕入・貿易ルートと結びついていない。位置以外をショック伝播へ使用しない|レコード別に東京都・横浜市・名古屋港管理組合・神戸市・大阪市・福岡市を出典として表示する。港湾統計や特定の航路使用者データとみなさない|

## 後続React prototypeでウェブ配布しなかったDB項目

- 以下は後続React prototype用のスナップショット範囲の記録であり、旧版ビューアにコミットされたgraph/scenario JSONの全フィールドを説明するものではありません。
- 国連Comtradeの二国間貿易行は後続prototypeの静的公開スナップショットへ含めませんでした。UN Comtradeの配布方針は再配布やアプリでの利用形態を定めています。現デモの758行は計算にも会社にも結びついていないため、そのprototypeの公開アプリには不要でした。
- World Bank Pink Sheetの1,835件の価格観測は、後続prototypeでは値上げ・会社損失へ接続せず利用しませんでした。適用されるデータ条件のレビューまでブラウザー用バンドルから除外しました。
- 航路の6件の集計記録は、位置の航跡、港・品目・船荷・会社・産業の露出を含みません。出典・許諾条件をデータセット単位で確認するまでは、後続prototypeの静的Webアプリへ再出力しない方針でした。
- 後続prototypeの公開スナップショットには、市場価値、個社財務額、会社間の調達額、取引先・工場・港湾経路、FX・金利、国別リスク、災害設備露出を含めない方針でした。未収録とゼロは区別します。

元リポジトリに既に置かれていたSQLiteやその他の原資料にはこの説明で新しい利用権が生じません。各行の元出典・時点・観測/推定区分が上流で変わる場合は、アプリのmanifest・帰属・UI表示も更新してください。

## 公式利用条件・一次資料

- OECD, [Terms & Conditions](https://www.oecd.org/en/about/terms-conditions.html) and [Inter-Country Input-Output tables](https://www.oecd.org/en/data/datasets/inter-country-input-output-tables.html).
- JPX, [Disclaimer / Terms of Use](https://www.jpx.co.jp/english/term-of-use/index.html), page updated 29 July 2026. If English and Japanese differ, JPX states the Japanese version prevails.
- EDINET, [Terms of Use](https://disclosure2dl.edinet-fsa.go.jp/guide/static/submit/WZEK0030.html) and [API materials](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html). The Terms of Use require the EDINET attribution and a note that EDINET-derived contents have been edited/processed; they also direct machine access to the API rather than scraping the website.
- UN Statistics Division, [Policy on Comtrade Data Use](https://uncomtrade.org/docs/policy-on-comtrade-data-use/) and [Re-dissemination of data](https://uncomtrade.org/docs/re-dissemination-of-data/).
- Natural Earth, [Terms of Use](https://www.naturalearthdata.com/about/terms-of-use/).
- World Bank, [Commodity Markets / Pink Sheet](https://www.worldbank.org/en/research/commodity-markets).
- Wikidata, [Data reuse policy](https://www.wikidata.org/wiki/Wikidata:Data_reuse).

## Build-time credentials

EDINET API credentials are inputs for private, rate-limited refresh scripts, not browser assets. The scripts read `EDINET_API_KEY` (or its legacy alias `EDINET_KEY`) from the process environment and send it in `Ocp-Apim-Subscription-Key`. Keep credentials out of URLs, commits, run logs, static assets, and Scenario Bundles. A refresh-key assignment is not a statement of permission to redistribute its resulting data.
