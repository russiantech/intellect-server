"""
Intellect LMS — Database Seeder
Creates default roles, super admin, brand config and sample categories.
Run: python seed.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from app.db.database import SessionLocal, create_tables
from app.models import Role, User, BrandConfig, Category
from app.models.courses import Tag
from app.core.security.security import hash_password

ROLES = ["super_admin", "admin", "creator", "tutor", "student", "partner"]
CATEGORIES = [
    ("Technology", "Programming, AI, Web Dev", "💻"),
    ("Business", "Entrepreneurship, Finance, Marketing", "📊"),
    ("Design", "UI/UX, Graphic Design, Motion", "🎨"),
    ("Data Science", "ML, Analytics, Statistics", "📈"),
    ("Languages", "English, French, Spanish and more", "🌍"),
    ("Personal Development", "Leadership, Productivity, Mindset", "🚀"),
    ("Health & Fitness", "Nutrition, Yoga, Mental Health", "🏋️"),
    ("Creative Arts", "Music, Photography, Writing", "🎵"),
]


def seed():
    create_tables()
    db = SessionLocal()
    try:
        # Roles
        for rn in ROLES:
            if not db.query(Role).filter(Role.name == rn).first():
                db.add(Role(name=rn, description=f"{rn.replace('_', ' ').title()} role"))
        db.commit()
        print(f"✅ {len(ROLES)} roles seeded")

        # Super admin
        ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@intellect.ng")
        ADMIN_PASS  = os.getenv("ADMIN_PASSWORD", "Admin@1234!")
        if not db.query(User).filter(User.email == ADMIN_EMAIL).first():
            admin = User(
                name="Super Admin",
                username="superadmin",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASS),
                email_verified=True,
                is_creator=True,
                creator_approved=True,
            )
            db.add(admin); db.flush()
            sa_role = db.query(Role).filter(Role.name == "super_admin").first()
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            if sa_role: admin.roles.append(sa_role)
            if admin_role: admin.roles.append(admin_role)
            db.commit()
            print(f"✅ Super admin created: {ADMIN_EMAIL} / {ADMIN_PASS}")
        else:
            print("ℹ️  Super admin already exists")

        # Brand config
        if not db.query(BrandConfig).filter(BrandConfig.id == 1).first():
            db.add(BrandConfig(id=1, site_name="Intellect",
                               tagline="Your Digital Learning Companion",
                               email="hello@intellect.ng"))
            db.commit()
            print("✅ Brand config seeded")

        # Categories
        from slugify import slugify
        for title, desc, icon in CATEGORIES:
            if not db.query(Category).filter(Category.title == title).first():
                db.add(Category(title=title, description=desc, icon=icon, slug=slugify(title)))
        db.commit()
        print(f"✅ {len(CATEGORIES)} categories seeded")

        # Sample tags
        sample_tags = ["Python", "JavaScript", "React", "FastAPI", "Machine Learning",
                       "Design", "Finance", "Leadership", "Productivity", "Health"]
        for t in sample_tags:
            if not db.query(Tag).filter(Tag.name == t).first():
                db.add(Tag(name=t))
        db.commit()
        print(f"✅ {len(sample_tags)} sample tags seeded")

        print("\n🎉 Database seeded successfully!")
    except Exception as e:
        db.rollback()
        print(f"❌ Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
