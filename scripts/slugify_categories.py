# from sqlalchemy import select
# from slugify import slugify

# from app.db.database import get_session_maker
# from app.models.courses import Category


# 
import sys
from pathlib import Path

# Add project root (server/) to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from slugify import slugify

from app.db.database import get_session_maker
from app.models.courses import Category

def backfill_category_slugs():
    SessionLocal = get_session_maker()

    db = SessionLocal()

    try:
        result = db.execute(
            select(Category).where(Category.slug.is_(None))
        )

        categories = result.scalars().all()

        print(f"Found {len(categories)} categories with NULL slugs.")

        updated = 0

        for category in categories:
            source = category.title or category.name or category.description

            if not source:
                print(f"Skipping category {category.id}: no name.")
                continue

            new_slug = slugify(source)

            print(
                f"{category.id}: "
                f"{source!r} -> {new_slug!r}"
            )

            category.slug = new_slug
            updated += 1

        if updated:
            db.commit()
            print(f"Successfully updated {updated} categories.")
        else:
            print("Nothing to update.")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    backfill_category_slugs()

