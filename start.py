#!/usr/bin/env python3
"""
Quiz Platform Startup Script
"""

import sys
import os

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app import init_database, app

def main():
    print("Starting Quizze...")
    print("=" * 40)
    
    # Initialize database
    print("Initializing database...")
    try:
        init_database()
        print("Database ready!")
    except Exception as e:
        print(f"Database error: {e}")
        return
    
    print("=" * 40)
    print("Server: http://localhost:5000")
    print("Press Ctrl+C to stop")
    print("=" * 40)
    
    # Start the Flask application
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\nQuizze stopped!")

if __name__ == '__main__':
    main()
