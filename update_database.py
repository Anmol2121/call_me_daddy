# update_database.py
#!/usr/bin/env python3
"""
Database update script to add missing columns for student login
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from sqlalchemy import text

def update_database_schema():
    """Add missing columns to existing database"""
    with app.app_context():
        try:
            # Check current schema
            print("Checking database schema...")
            
            # Add student_id column to users table if it doesn't exist
            result = db.engine.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='student_id'
            """)).fetchone()
            
            if not result:
                print("Adding student_id column to users table...")
                db.engine.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN student_id INTEGER REFERENCES students(id)
                """))
                print("✅ Added student_id column to users table")
            else:
                print("✅ student_id column already exists in users table")
            
            # Add user_id column to students table if it doesn't exist
            result = db.engine.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='students' AND column_name='user_id'
            """)).fetchone()
            
            if not result:
                print("Adding user_id column to students table...")
                db.engine.execute(text("""
                    ALTER TABLE students 
                    ADD COLUMN user_id INTEGER REFERENCES users(id)
                """))
                print("✅ Added user_id column to students table")
            else:
                print("✅ user_id column already exists in students table")
            
            # Add foreign key constraint if it doesn't exist
            print("Checking foreign key constraints...")
            
            print("\n✅ Database schema updated successfully!")
            
            return True
            
        except Exception as e:
            print(f"❌ Error updating database schema: {e}")
            return False

def verify_schema():
    """Verify the database schema is correct"""
    with app.app_context():
        try:
            print("\n=== Verifying Database Schema ===")
            
            # Check users table
            print("\nUsers table columns:")
            result = db.engine.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name='users'
                ORDER BY ordinal_position
            """)).fetchall()
            
            for col in result:
                print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")
            
            # Check students table
            print("\nStudents table columns:")
            result = db.engine.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name='students'
                ORDER BY ordinal_position
            """)).fetchall()
            
            for col in result:
                print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")
            
            # Check foreign key relationships
            print("\nForeign key relationships:")
            result = db.engine.execute(text("""
                SELECT
                    tc.table_name, 
                    kcu.column_name, 
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM 
                    information_schema.table_constraints AS tc 
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY' 
                  AND (tc.table_name IN ('users', 'students'))
                ORDER BY tc.table_name;
            """)).fetchall()
            
            for fk in result:
                print(f"  - {fk[0]}.{fk[1]} → {fk[2]}.{fk[3]}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error verifying schema: {e}")
            return False

if __name__ == '__main__':
    print("🚀 Updating School ERP Database Schema...")
    
    if update_database_schema():
        verify_schema()
        print("\n✨ Database update completed!")
        print("\n📋 Next steps:")
        print("1. Run: python setup_database.py (to ensure all tables exist)")
        print("2. Run: python app.py (to start the application)")
    else:
        print("\n❌ Database update failed. Please check the error above.")