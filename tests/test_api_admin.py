def test_admin_menu_returns_items(client, admin_auth):
    """Test that admin menu endpoint returns items with valid auth."""
    resp = client.get("/api/v1/admin/menu", auth=admin_auth)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = {item["name"] for item in data}
    # These items are created by the test fixture with TEST_ prefix
    assert "TEST Turkey Club" in names
    assert "TEST Chips" in names


def test_admin_menu_requires_auth(client):
    """Test that admin menu endpoint returns 401 without auth."""
    resp = client.get("/api/v1/admin/menu")
    assert resp.status_code == 401


def test_admin_menu_rejects_invalid_auth(client):
    """Test that admin menu endpoint returns 401 with invalid credentials."""
    resp = client.get("/api/v1/admin/menu", auth=("wrong", "credentials"))
    assert resp.status_code == 401
