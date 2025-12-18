set DATABASE_URL=sqlite:///./data/sammys.db
python -m uvicorn sandwich_bot.main:app --port 8000 --reload