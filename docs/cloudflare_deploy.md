# Cloudflare Pages デプロイガイド

> **アーカイブ：このガイドは旧Three.js 3D viewer用で、現在のRIPPLEに適用できません。** 内容の`exit 0`手順では現行Vite appはビルドされず、masterへのpushで自動公開されるとみなさないでください。現行のローカルbuildは[README](../README.md)に記載し、ホスティングは明示的に選んでから別途設定します。

このページは旧3Dビューアの歴史的記録として保管しています。

## 前提条件

- Cloudflareアカウント（無料プランでOK）
- Node.js 18以上
- Git（GitHubリポジトリを使用する場合）

## 方法1: GitHub連携（推奨・自動デプロイ）

最も簡単で、`git push`するだけで自動的にデプロイされます。

### 手順

1. **Cloudflareダッシュボードにアクセス**
   - https://dash.cloudflare.com にログイン
   - 左側メニューの「Workers & Pages」をクリック

2. **新規プロジェクト作成**
   - 「Create application」→「Pages」タブ
   - 「Connect to Git」を選択

3. **GitHub認証**
   - 初回はGitHubアカウントの認証を求められます
   - `socratesyama/cyber-economy-map` リポジトリを選択
   - 「Begin setup」をクリック

4. **ビルド設定**
   ```
   Production branch: master
   Build command: exit 0
   Build output directory: viz
   ```
   - `exit 0` = ビルド不要（静的サイト）
   - `viz` = index.htmlとdata/graph.jsonがあるディレクトリ

5. **デプロイ完了**
   - `https://cyber-economy-map.pages.dev` でアクセス可能
   - `master`ブランチにpushすると自動で再デプロイ

### カスタムドメイン（任意）

1. Pagesプロジェクトの「Custom domains」タブ
2. 「Set up a domain」でドメインを追加
3. DNSレコードは自動設定（Cloudflare管理のドメインの場合）

---

## 方法2: Wrangler CLI（手動デプロイ）

GitHub連携なしで、ローカルから直接デプロイする方法。

### インストールと認証

```bash
# wranglerインストール（グローバル）
npm install -g wrangler

# Cloudflareアカウントにログイン（ブラウザが開く）
wrangler login
```

### デプロイ実行

```bash
cd /path/to/cyber-economy-map

# vizディレクトリをデプロイ
npx wrangler pages deploy ./viz --project-name cyber-economy-map
```

初回実行時にプロジェクト名とプロダクションブランチの入力を求められます。

### プロジェクト作成を先にする場合

```bash
# プロジェクト作成
npx wrangler pages project create
# → プロジェクト名: cyber-economy-map
# → プロダクションブランチ: master

# デプロイ
npx wrangler pages deploy ./viz --project-name cyber-economy-map
```

---

## 方法3: ダッシュボードからドラッグ&ドロップ

最もシンプルな方法。ビルド済みのフォルダを直接アップロード。

1. Cloudflareダッシュボード → Workers & Pages → Create → Pages
2. 「Direct Upload」を選択
3. `viz`フォルダをドラッグ&ドロップ
4. 完了

---

## よくある問題と解決策

### 404エラーが出る
- `viz/index.html`がルートに存在することを確認
- Build output directoryが`viz`になっているか確認

### graph.jsonが読み込めない
- `viz/data/graph.json`（1.2MB）が含まれているか確認
- Cloudflare Pagesのファイルサイズ上限は25MB（無料プラン）

### デプロイが失敗する
- Build commandを`exit 0`に設定（ビルド不要の場合）
- Node.jsのバージョンを確認（環境変数`NODE_VERSION=18`）

### 古いバージョンが表示される
- ブラウザキャッシュのクリア
- Cloudflareダッシュボードで「Purge cache」を実行

---

## 2025年以降の注意点

Cloudflareは2025年4月以降、新規プロジェクトには**Workers with static assets**を推奨しています。Pagesは引き続きサポートされますが、新機能はWorkersにのみ追加されます。

### Workersでデプロイする場合

```bash
# wrangler.jsonc を作成
cat > wrangler.jsonc << 'EOF'
{
  "name": "cyber-economy-map",
  "compatibility_date": "2025-04-01",
  "assets": {
    "directory": "./viz"
  }
}
EOF

# デプロイ
npx wrangler deploy
```

どちらの方法でも `*.pages.dev` または `*.workers.dev` のURLで公開されます。

---

## 現在のデプロイ状態

| 項目 | 値 |
|------|-----|
| GitHubリポジトリ | https://github.com/socratesyama/cyber-economy-map |
| デプロイ対象 | `viz/` ディレクトリ |
| エントリーポイント | `viz/index.html` |
| データファイル | `viz/data/graph.json` (1.2MB) |
| フレームワーク | なし（純静的サイト・Three.js CDN） |

## 推奨構成

```
cyber-economy-map/
├── viz/           ← デプロイ対象
│   ├── index.html
│   └── data/
│       └── graph.json
├── docs/
├── scripts/
├── db/
└── ...
```

Cloudflare PagesのBuild output directoryに `viz` を指定すれば、`viz/`以下のみが公開されます。
