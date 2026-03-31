from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, IntegerField
from wtforms.validators import InputRequired, Length
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pymysql
import os
import uuid
import subprocess
from datetime import datetime
from config import DB_CONFIG, SECRET_KEY, UPLOAD_FOLDER, MAX_CONTENT_LENGTH

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'audio'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'video'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'images'), exist_ok=True)

# Database helper functions
def get_db_connection():
    config = DB_CONFIG.copy()
    config['cursorclass'] = pymysql.cursors.DictCursor
    return pymysql.connect(**config)

def create_database_if_not_exists():
    # Connect without specifying database to create it
    config_without_db = DB_CONFIG.copy()
    db_name = config_without_db.pop('database')
    
    conn = pymysql.connect(**config_without_db)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
            print(f"Database '{db_name}' created or already exists")
    finally:
        conn.close()

def init_database():
    # First ensure database exists
    create_database_if_not_exists()
    
    # Now connect to specific database
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Create users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(80) UNIQUE NOT NULL,
                    email VARCHAR(120) UNIQUE NOT NULL,
                    password_hash VARCHAR(200) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create quizzes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quizzes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    timer_minutes INT NOT NULL,
                    creator_id INT NOT NULL,
                    share_code VARCHAR(36) UNIQUE NOT NULL,
                    show_results BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (creator_id) REFERENCES users(id)
                )
            ''')
            
            # Create questions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    quiz_id INT NOT NULL,
                    question_text TEXT NOT NULL,
                    question_type VARCHAR(20) NOT NULL,
                    media_file VARCHAR(500),
                    option_a VARCHAR(500),
                    option_b VARCHAR(500),
                    option_c VARCHAR(500),
                    option_d VARCHAR(500),
                    correct_answer VARCHAR(10) NOT NULL,
                    FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
                )
            ''')
            
            # Create quiz_attempts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    quiz_id INT NOT NULL,
                    participant_name VARCHAR(100),
                    score INT NOT NULL,
                    total_questions INT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
                )
            ''')
            
        conn.commit()
        print("All database tables created successfully")
    finally:
        conn.close()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['id'])
        self.username = user_data['username']
        self.email = user_data['email']
        self.password_hash = user_data['password_hash']

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (int(user_id),))
            user_data = cursor.fetchone()
            if user_data:
                return User(user_data)
    finally:
        conn.close()
    return None

# Forms
class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=20)])
    email = StringField('Email', validators=[InputRequired(), Length(min=6, max=50)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=6, max=20)])

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired()])
    password = PasswordField('Password', validators=[InputRequired()])

class QuizForm(FlaskForm):
    title = StringField('Quizze Title', validators=[InputRequired(), Length(max=200)])
    description = TextAreaField('Description')
    timer_minutes = IntegerField('Timer (minutes)', validators=[InputRequired()])

def allowed_file(filename, file_type):
    ALLOWED_EXTENSIONS = {
        'audio': {'mpeg', 'mp3', 'wav', 'ogg'},
        'video': {'mp4', 'avi', 'mov'},
        'image': {'png', 'jpg', 'jpeg', 'gif'}
    }
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS.get(file_type, set())

def get_video_duration(file_path):
    """Get video duration in seconds using ffprobe (requires ffmpeg)"""
    try:
        # Try to use ffprobe from ffmpeg
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', 
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            return duration
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    
    # Fallback: estimate based on file size (rough approximation)
    try:
        file_size = os.path.getsize(file_path)
        # Rough estimate: 1MB ≈ 5 seconds of video (very approximate)
        estimated_duration = file_size / (1024 * 1024) * 5
        return estimated_duration
    except:
        return 0

def validate_video_file(file_path):
    """Validate video file and check duration"""
    if not os.path.exists(file_path):
        return False, "File does not exist"
    
    duration = get_video_duration(file_path)
    if duration > 60:  # More than 1 minute
        os.remove(file_path)  # Remove the invalid file
        return False, f"Video duration ({duration:.1f}s) exceeds 1 minute limit"
    
    return True, "Video is valid"

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Check if username exists
                cursor.execute("SELECT id FROM users WHERE username = %s", (form.username.data,))
                if cursor.fetchone():
                    flash('Username already exists!')
                    return render_template('register.html', form=form)
                
                # Check if email exists
                cursor.execute("SELECT id FROM users WHERE email = %s", (form.email.data,))
                if cursor.fetchone():
                    flash('Email already registered!')
                    return render_template('register.html', form=form)
                
                # Create new user
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                    (form.username.data, form.email.data, generate_password_hash(form.password.data))
                )
                conn.commit()
                flash('Registration successful! Please login.')
                return redirect(url_for('login'))
        finally:
            conn.close()
    
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (form.username.data,))
                user_data = cursor.fetchone()
                if user_data and check_password_hash(user_data['password_hash'], form.password.data):
                    user = User(user_data)
                    login_user(user)
                    return redirect(url_for('dashboard'))
                flash('Invalid username or password!')
        finally:
            conn.close()
    
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quizzes WHERE creator_id = %s ORDER BY created_at DESC", (int(current_user.id),))
            quizzes = cursor.fetchall()
    finally:
        conn.close()
    return render_template('dashboard.html', quizzes=quizzes)

@app.route('/create_quiz', methods=['GET', 'POST'])
@login_required
def create_quiz():
    form = QuizForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO quizzes (title, description, timer_minutes, creator_id, share_code) VALUES (%s, %s, %s, %s, %s)",
                    (form.title.data, form.description.data, form.timer_minutes.data, int(current_user.id), str(uuid.uuid4()))
                )
                conn.commit()
                quiz_id = cursor.lastrowid
                flash('Quizze created! Now add questions.')
                return redirect(url_for('add_questions', quiz_id=quiz_id))
        finally:
            conn.close()
    
    return render_template('create_quiz.html', form=form)

@app.route('/add_questions/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def add_questions(quiz_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Get quiz info
            cursor.execute("SELECT * FROM quizzes WHERE id = %s", (quiz_id,))
            quiz = cursor.fetchone()
            if not quiz or quiz['creator_id'] != int(current_user.id):
                flash('Access denied!')
                return redirect(url_for('dashboard'))
            
            if request.method == 'POST':
                question_text = request.form.get('question_text')
                question_type = request.form.get('question_type')
                correct_answer = request.form.get('correct_answer')
                
                media_file = None
                if question_type in ['audio', 'video']:
                    file = request.files.get('media_file')
                    if file and allowed_file(file.filename, question_type):
                        filename = secure_filename(file.filename)
                        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], question_type + 's')
                        file_path = os.path.join(upload_path, filename)
                        file.save(file_path)
                        
                        # Validate video duration
                        if question_type == 'video':
                            is_valid, message = validate_video_file(file_path)
                            if not is_valid:
                                flash(message)
                                return render_template('add_questions.html', quiz=quiz, questions=questions)
                        
                        media_file = os.path.join(question_type + 's', filename)
                
                cursor.execute(
                    """INSERT INTO questions 
                       (quiz_id, question_text, question_type, media_file, option_a, option_b, option_c, option_d, correct_answer) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (quiz_id, question_text, question_type, media_file,
                     request.form.get('option_a'), request.form.get('option_b'), 
                     request.form.get('option_c'), request.form.get('option_d'), correct_answer)
                )
                conn.commit()
                flash('Question added!')
            
            # Get questions
            cursor.execute("SELECT * FROM questions WHERE quiz_id = %s ORDER BY id", (quiz_id,))
            questions = cursor.fetchall()
    finally:
        conn.close()
    
    return render_template('add_questions.html', quiz=quiz, questions=questions)

@app.route('/quiz/<share_code>')
def take_quiz(share_code):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quizzes WHERE share_code = %s", (share_code,))
            quiz = cursor.fetchone()
            if not quiz:
                flash('Quizze not found!')
                return redirect(url_for('index'))
            
            cursor.execute("SELECT * FROM questions WHERE quiz_id = %s ORDER BY id", (quiz['id']))
            questions = cursor.fetchall()
    finally:
        conn.close()
    
    return render_template('take_quiz.html', quiz=quiz, questions=questions)

@app.route('/submit_quiz/<int:quiz_id>', methods=['POST'])
def submit_quiz(quiz_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quizzes WHERE id = %s", (quiz_id,))
            quiz = cursor.fetchone()
            if not quiz:
                flash('Quizze not found!')
                return redirect(url_for('index'))
            
            cursor.execute("SELECT * FROM questions WHERE quiz_id = %s", (quiz_id))
            questions = cursor.fetchall()
            
            score = 0
            total = len(questions)
            
            for question in questions:
                user_answer = request.form.get(f'question_{question["id"]}')
                if user_answer == question['correct_answer']:
                    score += 1
            
            participant_name = request.form.get('participant_name', 'Anonymous')
            
            # Store attempt
            cursor.execute(
                "INSERT INTO quiz_attempts (quiz_id, participant_name, score, total_questions) VALUES (%s, %s, %s, %s)",
                (quiz_id, participant_name, score, total)
            )
            conn.commit()
            
            # Check if results should be shown
            if quiz['show_results']:
                return render_template('quiz_result.html', score=score, total=total, quiz=quiz)
            else:
                return render_template('quiz_pending.html', quiz=quiz)
    finally:
        conn.close()

@app.route('/toggle_results/<int:quiz_id>')
@login_required
def toggle_results(quiz_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quizzes WHERE id = %s", (quiz_id,))
            quiz = cursor.fetchone()
            if not quiz or quiz['creator_id'] != int(current_user.id):
                flash('Access denied!')
                return redirect(url_for('dashboard'))
            
            new_status = not quiz['show_results']
            cursor.execute("UPDATE quizzes SET show_results = %s WHERE id = %s", (new_status, quiz_id))
            conn.commit()
            
            status_text = "shown" if new_status else "hidden"
            flash(f'Results are now {status_text} for participants.')
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))

@app.route('/quiz_attempts/<int:quiz_id>')
@login_required
def quiz_attempts(quiz_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quizzes WHERE id = %s", (quiz_id,))
            quiz = cursor.fetchone()
            if not quiz or quiz['creator_id'] != int(current_user.id):
                flash('Access denied!')
                return redirect(url_for('dashboard'))
            
            cursor.execute("SELECT * FROM quiz_attempts WHERE quiz_id = %s ORDER BY completed_at DESC", (quiz_id,))
            attempts = cursor.fetchall()
    finally:
        conn.close()
    
    return render_template('quiz_attempts.html', quiz=quiz, attempts=attempts)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    init_database()
    app.run(debug=True)
