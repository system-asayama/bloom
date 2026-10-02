import os
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from markupsafe import Markup, escape
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# 管理画面「店舗情報」で編集する項目: (キー, ラベル, 複数行か)
STORE_FIELDS = [
    ("store_name", "店名", False),
    ("catchcopy", "キャッチコピー(トップに大きく表示)", False),
    ("intro", "お店の紹介文", True),
    ("phone", "電話番号", False),
    ("hours", "営業時間", True),
    ("holiday", "定休日", False),
    ("address", "住所", False),
    ("access", "アクセス(最寄り駅からの道順など)", True),
    ("system_note", "料金ページの注意書き(税・サービス料、カードの可否など)", True),
    ("recruit_text", "求人内容", True),
    ("recruit_contact", "求人の連絡先", False),
    ("instagram_url", "Instagram の URL", False),
    ("line_url", "LINE 公式アカウントの URL", False),
]
URL_FIELDS = {"instagram_url", "line_url"}

IMAGE_TYPES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Setting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    published = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class Image(db.Model):
    """アップロード画像。デプロイでコンテナを作り直しても消えないよう DB に保存する。"""

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.LargeBinary, nullable=False)
    mimetype = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class Cast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    catchcopy = db.Column(db.String(200), nullable=False, default="")
    profile = db.Column(db.Text, nullable=False, default="")
    message = db.Column(db.Text, nullable=False, default="")
    image_id = db.Column(db.Integer, db.ForeignKey("image.id"))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    visible = db.Column(db.Boolean, nullable=False, default=True)


class GalleryPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey("image.id"), nullable=False)
    caption = db.Column(db.String(200), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class PriceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), nullable=False, default="")
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.String(80), nullable=False, default="")
    note = db.Column(db.String(200), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///bloom.db"),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        SITE_NAME=os.environ.get("SITE_NAME", "bloom"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        MAX_IMAGE_BYTES=5 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        if not app.config["SECRET_KEY"]:
            app.config["SECRET_KEY"] = _stored_secret_key()
        _ensure_admin(app)

    register_routes(app)
    return app


def _stored_secret_key():
    """SECRET_KEY 未設定時は DB に保存した鍵を使い、再起動でログインが切れないようにする。"""
    setting = db.session.get(Setting, "secret_key")
    if not setting:
        setting = Setting(key="secret_key", value=secrets.token_hex(32))
        db.session.add(setting)
        try:
            db.session.commit()
        except IntegrityError:  # 別ワーカーが先に作成した
            db.session.rollback()
            setting = db.session.get(Setting, "secret_key")
    return setting.value


def _ensure_admin(app):
    """管理者がまだいなければ作成する。

    ADMIN_PASSWORD 未設定時はランダムなパスワードを生成し、ログに出力する。
    """
    if Admin.query.first():
        return
    username = app.config.get("ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME", "admin")
    password = app.config.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(12)
        print(
            f"[bloom] 初期管理者を作成しました: ユーザー名={username} パスワード={password}"
            " (ログイン後に必ず変更してください)",
            flush=True,
        )
    admin = Admin(username=username)
    admin.set_password(password)
    db.session.add(admin)
    try:
        db.session.commit()
    except IntegrityError:  # 別ワーカーが先に作成した
        db.session.rollback()


def load_store():
    values = {
        s.key: s.value
        for s in Setting.query.filter(Setting.key.in_([k for k, _, _ in STORE_FIELDS]))
    }
    return {key: values.get(key, "") for key, _, _ in STORE_FIELDS}


def save_image(file, max_bytes):
    """アップロードされたファイルを Image として追加する。画像でなければ None。"""
    data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        flash(f"{file.filename}: 画像は{max_bytes // 1024 // 1024}MB以下にしてください", "error")
        return None
    mimetype = next((m for sig, m in IMAGE_TYPES.items() if data.startswith(sig)), None)
    if mimetype is None and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mimetype = "image/webp"
    if mimetype is None:
        flash(f"{file.filename}: JPEG / PNG / GIF / WebP の画像を選んでください", "error")
        return None
    image = Image(data=data, mimetype=mimetype)
    db.session.add(image)
    db.session.flush()
    return image


def delete_image(image_id):
    if image_id:
        image = db.session.get(Image, image_id)
        if image:
            db.session.delete(image)


def form_int(name, default=0):
    try:
        return int(request.form.get(name, default))
    except ValueError:
        return default


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def register_routes(app):
    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            token = session.get("csrf_token")
            if not token or token != request.form.get("csrf_token"):
                abort(400)

    @app.context_processor
    def inject_globals():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        store = load_store()
        return {
            "csrf_token": session["csrf_token"],
            "store": store,
            "site_name": store["store_name"] or app.config["SITE_NAME"],
            "is_admin": bool(session.get("admin_id")),
        }

    @app.template_filter("nl2br")
    def nl2br(text):
        return Markup("<br>".join(escape(text or "").split("\n")))

    @app.template_filter("tel")
    def tel(phone):
        return "".join(c for c in phone or "" if c.isdigit() or c == "+")

    @app.template_filter("map_embed")
    def map_embed(address):
        return f"https://maps.google.com/maps?q={quote(address)}&output=embed"

    @app.errorhandler(413)
    def too_large(_):
        flash("ファイルが大きすぎます(合計20MBまで)", "error")
        return redirect(request.referrer or url_for("admin_posts"))

    # ---- 公開ページ ----

    def visible_casts():
        return Cast.query.filter_by(visible=True).order_by(Cast.sort_order, Cast.id)

    def gallery_photos():
        return GalleryPhoto.query.order_by(GalleryPhoto.sort_order, GalleryPhoto.id)

    def price_groups():
        groups = {}
        for item in PriceItem.query.order_by(PriceItem.sort_order, PriceItem.id):
            groups.setdefault(item.category or "料金", []).append(item)
        return groups

    @app.route("/")
    def index():
        posts = (
            Post.query.filter_by(published=True)
            .order_by(Post.created_at.desc())
            .limit(3)
            .all()
        )
        return render_template(
            "index.html",
            posts=posts,
            casts=visible_casts().limit(8).all(),
            photos=gallery_photos().limit(6).all(),
            price_groups=price_groups(),
        )

    @app.route("/system")
    def system():
        return render_template("system.html", price_groups=price_groups())

    @app.route("/cast")
    def cast_list():
        return render_template("cast_list.html", casts=visible_casts().all())

    @app.route("/cast/<int:cast_id>")
    def cast_detail(cast_id):
        cast = db.get_or_404(Cast, cast_id)
        if not cast.visible and not session.get("admin_id"):
            abort(404)
        return render_template("cast_detail.html", cast=cast)

    @app.route("/gallery")
    def gallery():
        return render_template("gallery.html", photos=gallery_photos().all())

    @app.route("/access")
    def access():
        return render_template("access.html")

    @app.route("/recruit")
    def recruit():
        return render_template("recruit.html")

    @app.route("/blog")
    def blog_list():
        posts = (
            Post.query.filter_by(published=True).order_by(Post.created_at.desc()).all()
        )
        return render_template("blog_list.html", posts=posts)

    @app.route("/blog/<int:post_id>")
    def blog_detail(post_id):
        post = db.get_or_404(Post, post_id)
        if not post.published and not session.get("admin_id"):
            abort(404)
        return render_template("blog_detail.html", post=post)

    @app.route("/images/<int:image_id>")
    def image(image_id):
        img = db.get_or_404(Image, image_id)
        response = Response(img.data, mimetype=img.mimetype)
        # 画像は差し替え時に別 ID になるので長期キャッシュしてよい
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ---- 管理画面: ログイン ----

    @app.route("/admin/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            admin = Admin.query.filter_by(
                username=request.form.get("username", "")
            ).first()
            if admin and admin.check_password(request.form.get("password", "")):
                session.clear()
                session["admin_id"] = admin.id
                next_url = request.args.get("next", "")
                if not next_url.startswith("/") or next_url.startswith("//"):
                    next_url = url_for("admin_posts")
                return redirect(next_url)
            flash("ユーザー名またはパスワードが違います", "error")
        return render_template("admin/login.html")

    @app.route("/admin/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/admin/password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            admin = db.session.get(Admin, session["admin_id"])
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            if not admin or not admin.check_password(current):
                flash("現在のパスワードが違います", "error")
            elif len(new) < 8:
                flash("新しいパスワードは8文字以上にしてください", "error")
            elif new != request.form.get("new_password_confirm", ""):
                flash("確認用パスワードが一致しません", "error")
            else:
                admin.set_password(new)
                db.session.commit()
                flash("パスワードを変更しました", "success")
                return redirect(url_for("admin_posts"))
        return render_template("admin/password.html")

    # ---- 管理画面: ブログ ----

    @app.route("/admin")
    @login_required
    def admin_posts():
        posts = Post.query.order_by(Post.created_at.desc()).all()
        return render_template("admin/posts.html", posts=posts)

    @app.route("/admin/posts/new", methods=["GET", "POST"])
    @login_required
    def post_new():
        post = Post(title="", body="", published=False)
        if request.method == "POST":
            if _fill_post(post):
                db.session.add(post)
                db.session.commit()
                flash("記事を作成しました", "success")
                return redirect(url_for("admin_posts"))
        return render_template("admin/post_form.html", post=post, is_new=True)

    @app.route("/admin/posts/<int:post_id>/edit", methods=["GET", "POST"])
    @login_required
    def post_edit(post_id):
        post = db.get_or_404(Post, post_id)
        if request.method == "POST":
            if _fill_post(post):
                db.session.commit()
                flash("記事を更新しました", "success")
                return redirect(url_for("admin_posts"))
        return render_template("admin/post_form.html", post=post, is_new=False)

    @app.route("/admin/posts/<int:post_id>/delete", methods=["POST"])
    @login_required
    def post_delete(post_id):
        post = db.get_or_404(Post, post_id)
        db.session.delete(post)
        db.session.commit()
        flash("記事を削除しました", "success")
        return redirect(url_for("admin_posts"))

    # ---- 管理画面: 店舗情報 ----

    @app.route("/admin/store", methods=["GET", "POST"])
    @login_required
    def admin_store():
        if request.method == "POST":
            values = {key: request.form.get(key, "").strip() for key, _, _ in STORE_FIELDS}
            bad = [
                k for k in URL_FIELDS
                if values[k] and not values[k].startswith(("https://", "http://"))
            ]
            if bad:
                flash("URL は https:// から始めてください", "error")
                return render_template("admin/store.html", fields=STORE_FIELDS, values=values)
            for key, value in values.items():
                setting = db.session.get(Setting, key)
                if setting:
                    setting.value = value
                else:
                    db.session.add(Setting(key=key, value=value))
            db.session.commit()
            flash("店舗情報を保存しました", "success")
            return redirect(url_for("admin_store"))
        return render_template("admin/store.html", fields=STORE_FIELDS, values=load_store())

    # ---- 管理画面: 料金 ----

    @app.route("/admin/prices")
    @login_required
    def admin_prices():
        items = PriceItem.query.order_by(PriceItem.sort_order, PriceItem.id).all()
        return render_template("admin/prices.html", items=items)

    @app.route("/admin/prices/new", methods=["GET", "POST"])
    @app.route("/admin/prices/<int:item_id>/edit", methods=["GET", "POST"])
    @login_required
    def price_form(item_id=None):
        item = db.get_or_404(PriceItem, item_id) if item_id else PriceItem(
            category="", name="", price="", note="", sort_order=0
        )
        if request.method == "POST":
            item.category = request.form.get("category", "").strip()
            item.name = request.form.get("name", "").strip()
            item.price = request.form.get("price", "").strip()
            item.note = request.form.get("note", "").strip()
            item.sort_order = form_int("sort_order")
            if not item.name:
                flash("項目名を入力してください", "error")
            else:
                if not item_id:
                    db.session.add(item)
                db.session.commit()
                flash("料金を保存しました", "success")
                return redirect(url_for("admin_prices"))
        categories = [
            c for (c,) in db.session.query(PriceItem.category).distinct() if c
        ]
        return render_template("admin/price_form.html", item=item, categories=categories)

    @app.route("/admin/prices/<int:item_id>/delete", methods=["POST"])
    @login_required
    def price_delete(item_id):
        db.session.delete(db.get_or_404(PriceItem, item_id))
        db.session.commit()
        flash("料金を削除しました", "success")
        return redirect(url_for("admin_prices"))

    # ---- 管理画面: キャスト ----

    @app.route("/admin/casts")
    @login_required
    def admin_casts():
        casts = Cast.query.order_by(Cast.sort_order, Cast.id).all()
        return render_template("admin/casts.html", casts=casts)

    @app.route("/admin/casts/new", methods=["GET", "POST"])
    @app.route("/admin/casts/<int:cast_id>/edit", methods=["GET", "POST"])
    @login_required
    def cast_form(cast_id=None):
        cast = db.get_or_404(Cast, cast_id) if cast_id else Cast(
            name="", catchcopy="", profile="", message="", sort_order=0, visible=True
        )
        if request.method == "POST":
            cast.name = request.form.get("name", "").strip()
            cast.catchcopy = request.form.get("catchcopy", "").strip()
            cast.profile = request.form.get("profile", "")
            cast.message = request.form.get("message", "")
            cast.sort_order = form_int("sort_order")
            cast.visible = request.form.get("visible") == "1"
            photo = request.files.get("photo")
            ok = bool(cast.name)
            if not ok:
                flash("名前を入力してください", "error")
            elif photo and photo.filename:
                image = save_image(photo, app.config["MAX_IMAGE_BYTES"])
                if image:
                    delete_image(cast.image_id)
                    cast.image_id = image.id
                else:
                    ok = False
            elif request.form.get("remove_photo") == "1":
                delete_image(cast.image_id)
                cast.image_id = None
            if ok:
                if not cast_id:
                    db.session.add(cast)
                db.session.commit()
                flash("キャストを保存しました", "success")
                return redirect(url_for("admin_casts"))
            # 保存しない変更はリクエスト終了時に破棄される
        return render_template("admin/cast_form.html", cast=cast, is_new=not cast_id)

    @app.route("/admin/casts/<int:cast_id>/delete", methods=["POST"])
    @login_required
    def cast_delete(cast_id):
        cast = db.get_or_404(Cast, cast_id)
        image_id = cast.image_id
        db.session.delete(cast)
        delete_image(image_id)
        db.session.commit()
        flash("キャストを削除しました", "success")
        return redirect(url_for("admin_casts"))

    # ---- 管理画面: ギャラリー ----

    @app.route("/admin/gallery", methods=["GET", "POST"])
    @login_required
    def admin_gallery():
        if request.method == "POST":
            files = [f for f in request.files.getlist("photos") if f.filename]
            caption = request.form.get("caption", "").strip()
            added = 0
            next_order = (db.session.query(db.func.max(GalleryPhoto.sort_order)).scalar() or 0)
            for f in files:
                image = save_image(f, app.config["MAX_IMAGE_BYTES"])
                if image:
                    next_order += 1
                    db.session.add(
                        GalleryPhoto(image_id=image.id, caption=caption, sort_order=next_order)
                    )
                    added += 1
            db.session.commit()
            if added:
                flash(f"{added}枚の写真を追加しました", "success")
            elif not files:
                flash("写真を選んでください", "error")
            return redirect(url_for("admin_gallery"))
        return render_template("admin/gallery.html", photos=gallery_photos().all())

    @app.route("/admin/gallery/<int:photo_id>/edit", methods=["POST"])
    @login_required
    def gallery_edit(photo_id):
        photo = db.get_or_404(GalleryPhoto, photo_id)
        photo.caption = request.form.get("caption", "").strip()
        photo.sort_order = form_int("sort_order", photo.sort_order)
        db.session.commit()
        flash("写真を更新しました", "success")
        return redirect(url_for("admin_gallery"))

    @app.route("/admin/gallery/<int:photo_id>/delete", methods=["POST"])
    @login_required
    def gallery_delete(photo_id):
        photo = db.get_or_404(GalleryPhoto, photo_id)
        image_id = photo.image_id
        db.session.delete(photo)
        delete_image(image_id)
        db.session.commit()
        flash("写真を削除しました", "success")
        return redirect(url_for("admin_gallery"))


def _fill_post(post):
    """フォームの値を記事に反映する。入力エラーがあれば False を返す。"""
    post.title = request.form.get("title", "").strip()
    post.body = request.form.get("body", "")
    post.published = request.form.get("published") == "1"
    if not post.title:
        flash("タイトルを入力してください", "error")
        return False
    return True


app = create_app()
