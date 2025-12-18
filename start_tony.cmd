set DATABASE_URL=sqlite:///./data/tonys.db
python -m uvicorn sandwich_bot.main:app --port 8002 --reload