#!/usr/bin/env python3
"""
Database setup script for School ERP System
"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

def create_database():
    """Create PostgreSQL database if it doesn't exist"""
    try:
        # Connect to PostgreSQL server
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', '5432'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', "Ac@5121999")
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if database exists
        db_name = os.environ.get('DB_NAME', 'school_erp')
        cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (db_name,))
        exists = cursor.fetchone()
        
        if not exists:
            print(f"Creating database: {db_name}")
            cursor.execute(f'CREATE DATABASE {db_name}')
            print("Database created successfully!")
        else:
            print(f"Database '{db_name}' already exists.")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error creating database: {e}")
        sys.exit(1)

def setup_initial_data():
    """Setup initial database schema and developer account"""
    from app import app, db, User
    
    with app.app_context():
        try:
            # Create all tables
            print("Creating database tables...")
            db.create_all()
            
            # Check if developer exists
            developer = User.query.filter_by(role='developer').first()
            if not developer:
                print("Creating developer account...")
                developer = User(
                    email='developer@schoolerp.com',
                    full_name='System Developer',
                    role='developer',
                    must_change_password=False
                )
                developer.set_password('developer123')
                db.session.add(developer)
                db.session.commit()
                print("Developer account created:")
                print("  Email: developer@schoolerp.com")
                print("  Password: developer123")
                print("⚠️  IMPORTANT: Change this password immediately!")
            else:
                print("Developer account already exists.")
            
            print("\n✅ Database setup completed successfully!")
            
        except Exception as e:
            print(f"Error during setup: {e}")
            print("Trying to recreate tables...")
            try:
                db.drop_all()
                db.create_all()
                print("Tables recreated successfully.")
                
                # Create developer account
                developer = User(
                    email='developer@schoolerp.com',
                    full_name='System Developer',
                    role='developer',
                    must_change_password=False
                )
                developer.set_password('developer123')
                db.session.add(developer)
                db.session.commit()
                print("Developer account recreated.")
                
            except Exception as e2:
                print(f"Fatal error: {e2}")
                sys.exit(1)

if __name__ == '__main__':
    print("🚀 Setting up School ERP Database...")
    create_database()
    setup_initial_data()