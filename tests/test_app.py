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
