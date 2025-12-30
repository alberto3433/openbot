# sandwich_bot/reset_orders.py

from sqlalchemy import text  # you can remove this import if you don't use text elsewhere
from sandwich_bot.db import SessionLocal
from sandwich_bot.models import Order, OrderItem


def reset_orders():
    db = SessionLocal()
    try:
        # Delete child rows first
        db.query(OrderItem).delete()
        db.query(Order).delete()

        db.commit()
        print("Orders and order_items cleared.")
    finally:
        db.close()


if __name__ == "__main__":
    reset_orders()
