def test_admin_menu_returns_items(client):
    resp = client.get("/admin/menu")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = {item["name"] for item in data}
    assert "Turkey Club" in names
    assert "soda" in names
