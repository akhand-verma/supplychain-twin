"""Seeds the database on first start only."""
from sqlalchemy import func, inspect, select

from . import models, seed
from .database import SessionLocal, engine


def main():
    if inspect(engine).has_table("products"):
        with SessionLocal() as db:
            if db.scalar(select(func.count()).select_from(models.Product)):
                print("Database already seeded, skipping.")
                return
    seed.main()


if __name__ == "__main__":
    main()