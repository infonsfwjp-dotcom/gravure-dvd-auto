# Gravure DVD Auto v0.4

3メーカーの新作グラビアDVDを定期取得し、FANZA/DMM商品照合、静的サイト生成まで自動化するためのMVPです。

## 対応メーカー
- スパイスビジュアル
- ラインコミュニケーションズ / I-ONE
- 竹書房

## GitHub Actions
- 毎日 03:17 JST 前後に自動実行
- Actions > Update site > Run workflow で手動実行可能
- DMM/FANZA認証情報はGitHub Secretsへ登録
- サンプルメディア取得はサイト生成を長時間ブロックしないよう時間制限付きで実行

必要なSecrets:
- `DMM_API_ID`
- `DMM_AFFILIATE_ID`

## Cloudflare Pages（推奨）
このプロジェクトは静的HTMLなので、Cloudflare PagesのGit連携が最も簡単です。

1. GitHubへこのリポジトリをpush
2. Cloudflare Dashboard → Workers & Pages → Create application → Pages → Connect to Git
3. GitHubリポジトリを選択
4. Production branch: `main`
5. Build command: 空欄
6. Build output directory: `dist`
7. 保存してデプロイ

Git連携を使うと、GitHubへのpushごとにPagesが自動デプロイします。

## 注意
- メーカーサイトのrobots.txt、利用規約、著作権条件を必ず確認してください。
- メーカー画像・記事を無断転載しないでください。
- FANZA/DMM APIの利用規約・アフィリエイト規約に従ってください。
- FANZA商品照合の確信度が低い商品は自動リンクしない設計です。
- 現在の実行環境では外部メーカーサイトへの完全な実地検証ができないため、初回Actions実行後に取得結果を確認してください。
