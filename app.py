import os
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
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
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    published = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///bloom.db"),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        SITE_NAME=os.environ.get("SITE_NAME", "bloom"),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        _ensure_admin(app)

    register_routes(app)
    return app


def _ensure_admin(app):
    """管理者がまだいなければ、環境変数の ADMIN_USERNAME / ADMIN_PASSWORD で作成する。"""
    if Admin.query.first():
        return
    username = app.config.get("ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME", "admin")
    password = app.config.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    if not password:
        app.logger.warning("ADMIN_PASSWORD が未設定のため管理者を作成しませんでした")
        return
    admin = Admin(username=username)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()


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
        return {
            "csrf_token": session["csrf_token"],
            "site_name": app.config["SITE_NAME"],
            "is_admin": bool(session.get("admin_id")),
        }

    @app.template_filter("nl2br")
    def nl2br(text):
        return Markup("<br>".join(escape(text or "").split("\n")))

    # ---- 公開ページ ----

    @app.route("/")
    def index():
        posts = (
            Post.query.filter_by(published=True)
            .order_by(Post.created_at.desc())
            .limit(3)
            .all()
        )
        return render_template("index.html", posts=posts)

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

    # ---- 管理画面 ----

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
