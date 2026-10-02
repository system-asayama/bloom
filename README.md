# bloom

スナックのホームページ。Docker Compose (Flask + PostgreSQL)。

## 機能

- トップページ(新着ブログ3件)
- ブログ一覧・記事ページ(公開記事のみ表示)
- 管理画面 `/admin`
  - 管理者ログイン / ログアウト
  - ブログ記事の作成・編集・削除、公開/下書きの切り替え
  - パスワード変更

## 起動

```sh
cp .env.example .env   # SECRET_KEY と ADMIN_PASSWORD を必ず書き換える
docker compose up --build
```

http://localhost:8080/admin/login から `.env` の `ADMIN_USERNAME` / `ADMIN_PASSWORD` でログインする。
管理者は DB に管理者が一人もいない初回起動時にだけ作成される。以降のパスワード変更は管理画面から行う。

## ローカル開発(Docker なし)

`DATABASE_URL` 未設定時は SQLite (`instance/bloom.db`) を使う。

```sh
pip install -r requirements-dev.txt
ADMIN_PASSWORD=dev-pass SECRET_KEY=dev flask --app app run --debug
pytest
```
