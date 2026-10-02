import os
import re

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import Post, create_app, db  # noqa: E402


@pytest.fixture
def client():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "ADMIN_USERNAME": "mama",
        "ADMIN_PASSWORD": "secret-pass",
    })
    with app.test_client() as c:
        c.app = app
        yield c


def csrf(client, path="/admin/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client, password="secret-pass"):
    token = csrf(client)
    return client.post("/admin/login", data={
        "csrf_token": token, "username": "mama", "password": password,
    })


def test_admin_requires_login(client):
    r = client.get("/admin")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["Location"]


def test_wrong_password(client):
    r = login(client, "nope")
    assert "違います" in r.get_data(as_text=True)
    assert client.get("/admin").status_code == 302


def test_post_without_csrf_is_rejected(client):
    r = client.post("/admin/login", data={"username": "mama", "password": "secret-pass"})
    assert r.status_code == 400


def test_create_publish_and_view(client):
    assert login(client).status_code == 302
    token = csrf(client, "/admin/posts/new")
    client.post("/admin/posts/new", data={
        "csrf_token": token, "title": "開店しました", "body": "1行目\n<b>2行目</b>", "published": "1",
    })
    client.post("/admin/posts/new", data={
        "csrf_token": token, "title": "下書き記事", "body": "x",
    })
    with client.app.app_context():
        published = Post.query.filter_by(title="開店しました").one()
        draft = Post.query.filter_by(title="下書き記事").one()
        pid, did = published.id, draft.id

    detail = client.get(f"/blog/{pid}").get_data(as_text=True)
    assert "1行目<br>&lt;b&gt;2行目&lt;/b&gt;" in detail

    client.post("/admin/logout", data={"csrf_token": token})
    listing = client.get("/blog").get_data(as_text=True)
    assert "開店しました" in listing
    assert "下書き記事" not in listing
    assert client.get(f"/blog/{did}").status_code == 404
    assert "開店しました" in client.get("/").get_data(as_text=True)


def test_edit_and_delete(client):
    login(client)
    token = csrf(client, "/admin/posts/new")
    client.post("/admin/posts/new", data={"csrf_token": token, "title": "A", "body": ""})
    with client.app.app_context():
        pid = Post.query.one().id
    client.post(f"/admin/posts/{pid}/edit", data={"csrf_token": token, "title": "B", "body": "", "published": "1"})
    with client.app.app_context():
        post = db.session.get(Post, pid)
        assert post.title == "B" and post.published
    client.post(f"/admin/posts/{pid}/delete", data={"csrf_token": token})
    with client.app.app_context():
        assert Post.query.count() == 0


def test_change_password(client):
    login(client)
    token = csrf(client, "/admin/password")
    client.post("/admin/password", data={
        "csrf_token": token, "current_password": "secret-pass",
        "new_password": "new-pass-123", "new_password_confirm": "new-pass-123",
    })
    client.post("/admin/logout", data={"csrf_token": token})
    login(client, "secret-pass")
    assert client.get("/admin").status_code == 302
    login(client, "new-pass-123")
    assert client.get("/admin").status_code == 200


def test_open_redirect_blocked(client):
    token = csrf(client)
    r = client.post("/admin/login?next=//evil.example", data={
        "csrf_token": token, "username": "mama", "password": "secret-pass",
    })
    assert r.headers["Location"] == "/admin"


def test_generated_admin_password_and_persistent_secret(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    uri = f"sqlite:///{tmp_path / 'x.db'}"
    app1 = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri})
    out = capsys.readouterr().out
    password = re.search(r"パスワード=(\S+)", out).group(1)
    app2 = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri})
    assert app1.config["SECRET_KEY"] == app2.config["SECRET_KEY"]
    assert "初期管理者" not in capsys.readouterr().out
    with app2.test_client() as c:
        token = csrf(c)
        c.post("/admin/login", data={"csrf_token": token, "username": "admin", "password": password})
        assert c.get("/admin").status_code == 200


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_public_pages_render_when_empty(client):
    for path in ["/", "/system", "/cast", "/gallery", "/access", "/recruit", "/blog"]:
        assert client.get(path).status_code == 200, path


def test_store_info_shown_on_site(client):
    login(client)
    token = csrf(client, "/admin/store")
    client.post("/admin/store", data={
        "csrf_token": token, "store_name": "祇園", "phone": "086-000-0000",
        "address": "岡山市北区1-2-3", "recruit_text": "キャスト募集中",
    })
    top = client.get("/").get_data(as_text=True)
    assert "祇園" in top and 'href="tel:0860000000"' in top
    assert "maps.google.com" in client.get("/access").get_data(as_text=True)
    assert "キャスト募集中" in client.get("/recruit").get_data(as_text=True)


def test_store_rejects_javascript_url(client):
    login(client)
    token = csrf(client, "/admin/store")
    r = client.post("/admin/store", data={"csrf_token": token, "line_url": "javascript:alert(1)"})
    assert "https://" in r.get_data(as_text=True)
    assert "javascript:alert" not in client.get("/").get_data(as_text=True)


def test_prices_grouped_on_system_page(client):
    login(client)
    token = csrf(client, "/admin/prices/new")
    client.post("/admin/prices/new", data={"csrf_token": token, "category": "セット料金", "name": "60分", "price": "3,000円", "sort_order": "1"})
    client.post("/admin/prices/new", data={"csrf_token": token, "category": "ボトル", "name": "焼酎", "price": "5,000円", "sort_order": "2"})
    html = client.get("/system").get_data(as_text=True)
    assert html.index("セット料金") < html.index("60分") < html.index("ボトル") < html.index("焼酎")


def test_cast_with_photo(client):
    import io
    login(client)
    token = csrf(client, "/admin/casts/new")
    client.post("/admin/casts/new", data={
        "csrf_token": token, "name": "さくら", "visible": "1",
        "photo": (io.BytesIO(PNG), "a.png"),
    }, content_type="multipart/form-data")
    client.post("/admin/casts/new", data={"csrf_token": token, "name": "かくれ"})
    from app import Cast
    with client.app.app_context():
        sakura = Cast.query.filter_by(name="さくら").one()
        hidden = Cast.query.filter_by(name="かくれ").one()
        sid, hid, image_id = sakura.id, hidden.id, sakura.image_id
    img = client.get(f"/images/{image_id}")
    assert img.status_code == 200 and img.mimetype == "image/png"

    client.post("/admin/logout", data={"csrf_token": token})
    listing = client.get("/cast").get_data(as_text=True)
    assert "さくら" in listing and "かくれ" not in listing
    assert client.get(f"/cast/{hid}").status_code == 404
    assert client.get(f"/cast/{sid}").status_code == 200


def test_non_image_upload_rejected(client):
    import io
    login(client)
    token = csrf(client, "/admin/gallery")
    r = client.post("/admin/gallery", data={
        "csrf_token": token, "photos": (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg"),
    }, content_type="multipart/form-data", follow_redirects=True)
    assert "画像を選んでください" in r.get_data(as_text=True)
    from app import GalleryPhoto, Image
    with client.app.app_context():
        assert GalleryPhoto.query.count() == 0 and Image.query.count() == 0


def test_gallery_upload_and_delete(client):
    import io
    login(client)
    token = csrf(client, "/admin/gallery")
    client.post("/admin/gallery", data={
        "csrf_token": token, "caption": "カウンター",
        "photos": [(io.BytesIO(PNG), "a.png"), (io.BytesIO(PNG), "b.png")],
    }, content_type="multipart/form-data")
    from app import GalleryPhoto, Image
    with client.app.app_context():
        assert GalleryPhoto.query.count() == 2
        pid = GalleryPhoto.query.first().id
    assert "カウンター" in client.get("/gallery").get_data(as_text=True)
    client.post(f"/admin/gallery/{pid}/delete", data={"csrf_token": token})
    with client.app.app_context():
        assert GalleryPhoto.query.count() == 1 and Image.query.count() == 1


def test_admin_pages_require_login(client):
    for path in ["/admin/store", "/admin/prices", "/admin/casts", "/admin/gallery"]:
        assert client.get(path).status_code == 302, path
