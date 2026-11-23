import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'database.db').replace('\\', '/')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)

class LiveStream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.String(50), nullable=False)
    stream_key = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='inactive', nullable=False)
    created_at = db.Column(db.DateTime, nullable=True)
    paused_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(100), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['username'] = username
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('dashboard.html', user=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/create_live', methods=['GET', 'POST'])
def create_live():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        video_id = request.form['video_id']
        stream_key = request.form['stream_key']
        video_file = request.files['video_file']
        if video_file:
            filename = video_file.filename
            video_file.save(f'uploads/{filename}')
            file = File(user_id=user.id, filename=filename, size_bytes=os.path.getsize(f'uploads/{filename}'))
            db.session.add(file)
            db.session.commit()
        live_stream = LiveStream(
            user_id=user.id,
            video_id=video_id,
            stream_key=stream_key,
            status='active'
        )
        db.session.add(live_stream)
        db.session.commit()
        flash('Live stream created successfully', 'success')
        return redirect(url_for('dashboard'))
    return render_template('create_live.html')

@app.route('/files')
def files():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    files = File.query.filter_by(user_id=user.id).all()
    return render_template('files.html', files=files)

@app.route('/settings')
def settings():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('settings.html', user=user)

if __name__ == '__main__':
    os.makedirs(app.instance_path, exist_ok=True)
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)