# bloom

スナックのホームページ。Docker Compose (Flask + PostgreSQL)。

## 機能

公開ページ

| URL | 内容 |
| --- | --- |
| `/` | トップ(キャッチコピー、お店紹介、新着ブログ、キャスト、料金、ギャラリー、店舗情報、求人バナー) |
| `/system` | 料金システム(分類ごとの料金表 + 注意書き) |
| `/cast`, `/cast/<id>` | キャスト一覧・プロフィール |
| `/gallery` | 店内写真 |
| `/blog`, `/blog/<id>` | お知らせ・ブログ(公開記事のみ) |
| `/access` | 住所・営業時間・地図 |
| `/recruit` | 求人情報 |

管理画面 `/admin` (要ログイン)

- ブログ: 作成・編集・削除、公開/下書き
- 店舗情報: 店名、キャッチコピー、電話、住所、営業時間、求人内容、SNS など
- 料金: 分類・項目・金額の登録と並び順
- キャスト: 写真つきプロフィール、表示/非表示、並び順
- ギャラリー: 写真の複数アップロード、説明・並び順の編集、削除
- パスワード変更

画像は DB に保存するため、デプロイでコンテナを作り直しても消えない。

## 起動

```sh
cp .env.example .env   # 任意。SECRET_KEY と ADMIN_PASSWORD を書き換える
docker compose up --build
```

http://localhost:8080/admin/login から `.env` の `ADMIN_USERNAME` / `ADMIN_PASSWORD` でログインする。
管理者は DB に管理者が一人もいない初回起動時にだけ作成される。以降のパスワード変更は管理画面から行う。

`.env` が無い場合(自動デプロイなど)は初期パスワードを自動生成し、コンテナのログに出力する:

```sh
docker compose logs web | grep 初期管理者
```

## ローカル開発(Docker なし)

`DATABASE_URL` 未設定時は SQLite (`instance/bloom.db`) を使う。

```sh
pip install -r requirements-dev.txt
ADMIN_PASSWORD=dev-pass SECRET_KEY=dev flask --app app run --debug
pytest
```
