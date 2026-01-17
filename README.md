# Sandwich Shop Chatbot MVP

This package contains a functional skeleton for a Python-based sandwich shop chatbot,
using FastAPI, PostgreSQL (Neon), SQLAlchemy, and OpenAI.

## 📦 Directory Structure

```
orderbot/
│
├── llm_client.py
├── order_logic.py
├── inventory.py
├── models.py
├── menu_index_builder.py
├── README.md
│
└── tests/
    ├── test_llm_client.py
    ├── test_order_logic.py
    └── test_inventory.py
```

## 🚀 Requirements

```
python 3.10+
pip install fastapi uvicorn sqlalchemy openai pytest
```

## 🗄 Database Setup

Set the `DATABASE_URL` environment variable to your Postgres connection string:

```
export DATABASE_URL=postgresql://user:pass@host/dbname
```

Then run migrations and populate the menu:

```
alembic upgrade head
python populate_zuckers_menu.py
```

## 🧪 Running Tests

```
pytest -q
```

## 📝 Notes

- `llm_client.py` builds prompts and calls OpenAI (mocked in unit tests).
- `order_logic.py` performs deterministic updates to the order.
- `inventory.py` decrements stock after confirmation.
- `models.py` defines the SQLAlchemy models.
- `menu_index_builder.py` loads menu items from the database.

This is a **minimal runnable scaffold** designed to be extended into a full FastAPI service.
