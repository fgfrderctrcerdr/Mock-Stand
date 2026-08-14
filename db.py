"""Подключение к БД. См. db.py в web_onboarding — паттерн тот же."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./local_dev.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# QA L3: get_db() (FastAPI-dependency generator) был мёртвым кодом — доступ
# к БД идёт через request.state.db (см. OrgSessionMiddleware в main.py),
# не через Depends(get_db). Убрано, чтобы не путать будущего читателя
# несуществующим вторым способом получить сессию.
