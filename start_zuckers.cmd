set DATABASE_URL=sqlite:///./data/zuckers.db
python -m uvicorn sandwich_bot.main:app --port 8004 --reload
