"""
Database configuration.

Local dev / demo: SQLite (zero setup, file-based).
Production: swap DATABASE_URL to a real Postgres connection string
(Render, Railway, Supabase, RDS, etc. all work unchanged since we use
SQLAlchemy's standard engine interface).
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./persongraph.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
