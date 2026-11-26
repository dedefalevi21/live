import os
import re
import signal
import subprocess
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.permanent_session_lifetime = 3600  # sesi 1 jam
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'database.db').replace('\\', '/')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

UPLOAD_DIR = os.path.join(app.root_path, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)


class LiveStream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.String(200), nullable=False)
    stream_key = db.Column(db.String(200), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='inactive', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schedule_start = db.Column(db.DateTime, nullable=True)
    schedule_stop = db.Column(db.DateTime, nullable=True)
    auto_stop_hours = db.Column(db.Integer, default=0)
    auto_stop_minutes = db.Column(db.Integer, default=0)
    schedule_mode = db.Column(db.String(20), default='manual')
    pid = db.Column(db.Integer, nullable=True)


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(500), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    size_bytes = db.Column(db.Integer, nullable=True)
    source = db.Column(db.String(20), default='upload')


def login_required(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Silakan login terlebih dahulu.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def extract_drive_id(url):
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    return None


def ensure_schema():
    """Tambahkan kolom baru ke tabel lama tanpa menghapus data."""
    from sqlalchemy import text

    def cols_of(table):
        try:
            rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        except Exception:
            return set()
        return {r[1] for r in rows}

    alter_statements = []

    live_cols = cols_of('live_stream')
    if live_cols:
        for name, ddl in (
            ('title', 'VARCHAR(200)'),
            ('schedule_start', 'DATETIME'),
            ('schedule_stop', 'DATETIME'),
            ('auto_stop_hours', 'INTEGER DEFAULT 0'),
            ('auto_stop_minutes', 'INTEGER DEFAULT 0'),
            ('schedule_mode', "VARCHAR(20) DEFAULT 'manual'"),
            ('created_at', 'DATETIME'),
            ('pid', 'INTEGER'),
        ):
            if name not in live_cols:
                alter_statements.append(f"ALTER TABLE live_stream ADD COLUMN {name} {ddl}")

    file_cols = cols_of('file')
    if file_cols:
        for name, ddl in (
            ('filepath', 'VARCHAR(500)'),
            ('size_bytes', 'INTEGER'),
            ('source', "VARCHAR(20) DEFAULT 'upload'"),
            ('uploaded_at', 'DATETIME'),
        ):
            if name not in file_cols:
                alter_statements.append(f"ALTER TABLE file ADD COLUMN {name} {ddl}")

    for stmt in alter_statements:
        db.session.execute(text(stmt))
    if alter_statements:
        db.session.commit()


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session.permanent = False
            return redirect(url_for('dashboard'))

        flash('Username atau password salah.', 'error')
        return render_template('login.html'), 401

    return render_template('login.html')


@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    lives = LiveStream.query.filter_by(user_id=user_id).order_by(LiveStream.created_at.desc()).all()
    files = File.query.filter_by(user_id=user_id).order_by(File.uploaded_at.desc()).all()
    active = sum(1 for l in lives if l.status == 'active')

    # Hitung storage terpakai dari file-file user (dalam GB)
    storage_used_bytes = sum(f.size_bytes or 0 for f in files)
    storage_used_gb = storage_used_bytes / (1024 * 1024 * 1024)
    storage_limit_gb = 5  # batas 5 GB
    storage_free_gb = max(storage_limit_gb - storage_used_gb, 0)

    return render_template('dashboard.html',
                           lives=lives,
                           files=files,
                           active_count=active,
                           storage_used=storage_used_gb,
                           storage_limit=storage_limit_gb,
                           storage_free=storage_free_gb)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('dashboard'))


@app.route('/create_live', methods=['POST'])
@login_required
def create_live():
    user_id = session.get('user_id')
    if request.method == 'POST':
        video_id = request.form.get('video_id', '').strip()
        stream_key = request.form.get('stream_key', '').strip()
        video_title = request.form.get('video_title', '').strip()
        schedule_mode = request.form.get('schedule_mode', 'manual')
        auto_stop_hours = int(request.form.get('auto_stop_hours') or 0)
        auto_stop_minutes = int(request.form.get('auto_stop_minutes') or 0)

        # Parse schedule start/stop
        schedule_start_raw = request.form.get('schedule_start', '').strip()
        schedule_stop_raw = request.form.get('schedule_stop', '').strip()
        start_dt = None
        stop_dt = None

        if schedule_start_raw:
            try:
                start_dt = datetime.strptime(schedule_start_raw, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Format Jadwal Mulai tidak valid. Gunakan YYYY-MM-DDTHH:MM.', 'error')
                return redirect(url_for('dashboard'))

        if schedule_stop_raw:
            try:
                stop_dt = datetime.strptime(schedule_stop_raw, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Format Jadwal Berakhir tidak valid. Gunakan YYYY-MM-DDTHH:MM.', 'error')
                return redirect(url_for('dashboard'))

        live = LiveStream(
            user_id=user_id,
            video_id=video_id or f"LIVE{uuid.uuid4().hex[:4].upper()}",
            stream_key=stream_key,
            title=video_title or f"Live {video_id}",
            status='active',
            schedule_start=start_dt,
            schedule_stop=stop_dt,
            auto_stop_hours=auto_stop_hours,
            auto_stop_minutes=auto_stop_minutes,
            schedule_mode=schedule_mode,
        )
        db.session.add(live)
        db.session.commit()

        # Start streaming via ffmpeg
        try:
            # Get the file path
            f = File.query.filter_by(user_id=user_id, filename=video_id).first()
            if f and f.filepath and os.path.exists(f.filepath):
                video_path = f.filepath
            else:
                video_path = os.path.join(UPLOAD_DIR, video_id)

            # Check if file exists
            if not os.path.exists(video_path):
                flash(f'File video "{video_id}" tidak ditemukan di server.', 'error')
                return redirect(url_for('dashboard'))

            # Build ffmpeg command
            cmd = [
                'ffmpeg',
                '-re',  # Input dalam real-time
                '-stream_loop', '-1',  # Loop video terus menerus
                '-i', video_path,
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-b:v', '2500k',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', '44100',
                '-f', 'flv',
                f'rtmp://a.rtmp.youtube.com/live2/{stream_key}'
            ]

            # Start process in background
            import subprocess
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )

            # Save PID to database
            live.pid = process.pid
            live.status = 'active'
            db.session.commit()

            flash(f"Live stream '{video_title or video_id}' berhasil dimulai! PID: {process.pid}", 'success')

        except Exception as e:
            flash(f'Gagal memulai streaming: {str(e)}', 'error')

        return redirect(url_for('dashboard'))

    return redirect(url_for('dashboard'))


@app.route('/start_live/<int:live_id>', methods=['POST'])
@login_required
def start_live(live_id):
    live = LiveStream.query.filter_by(id=live_id, user_id=session.get('user_id')).first()
    if not live:
        flash('Live stream tidak ditemukan.', 'error')
        return redirect(url_for('dashboard'))

    if live.status == 'active' and live.pid:
        flash('Live stream sudah berjalan.', 'error')
        return redirect(url_for('dashboard'))

    # Check if file exists
    f = File.query.filter_by(user_id=session.get('user_id'), filename=live.video_id).first()
    if f and f.filepath and os.path.exists(f.filepath):
        video_path = f.filepath
    else:
        video_path = os.path.join(UPLOAD_DIR, live.video_id)

    if not os.path.exists(video_path):
        flash(f'File video "{live.video_id}" tidak ditemukan di server.', 'error')
        return redirect(url_for('dashboard'))

    # Build ffmpeg command
    cmd = [
        'ffmpeg',
        '-re',
        '-stream_loop', '-1',
        '-i', video_path,
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-b:v', '2500k',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-f', 'flv',
        f'rtmp://a.rtmp.youtube.com/live2/{live.stream_key}'
    ]

    try:
        import subprocess
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        )

        live.pid = process.pid
        live.status = 'active'
        db.session.commit()

        flash(f'Live stream dimulai! PID: {process.pid}', 'success')
    except Exception as e:
        flash(f'Gagal memulai streaming: {str(e)}', 'error')

    return redirect(url_for('dashboard'))


@app.route('/stop_live/<int:live_id>', methods=['POST'])
@login_required
def stop_live(live_id):
    live = LiveStream.query.filter_by(id=live_id, user_id=session.get('user_id')).first()
    if not live:
        flash('Live stream tidak ditemukan.', 'error')
        return redirect(url_for('dashboard'))

    if live.pid:
        try:
            import signal
            os.kill(live.pid, signal.SIGTERM)
            flash('Live stream dihentikan.', 'success')
        except ProcessLookupError:
            flash('Proses streaming sudah berhenti.', 'error')
        except Exception as e:
            flash(f'Gagal menghentikan streaming: {str(e)}', 'error')
    else:
        flash('Tidak ada proses streaming yang berjalan.', 'error')

    live.status = 'inactive'
    live.pid = None
    db.session.commit()

    return redirect(url_for('dashboard'))


@app.route('/delete_live/<int:live_id>')
@login_required
def delete_live(live_id):
    live = LiveStream.query.filter_by(id=live_id, user_id=session.get('user_id')).first()
    if live:
        # Stop streaming if active
        if live.pid and live.status == 'active':
            try:
                import signal
                os.kill(live.pid, signal.SIGTERM)
            except Exception:
                pass

        db.session.delete(live)
        db.session.commit()
        flash('Sesi live dihapus.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/delete_file/<int:file_id>')
@login_required
def delete_file(file_id):
    f = File.query.filter_by(id=file_id, user_id=session.get('user_id')).first()
    if f:
        if f.filepath and os.path.exists(f.filepath):
            try:
                os.remove(f.filepath)
            except OSError:
                pass
        db.session.delete(f)
        db.session.commit()
        flash('File dihapus.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/download_drive', methods=['POST'])
@login_required
def download_drive():
    user_id = session.get('user_id')
    url = request.form.get('drive_url', '').strip()
    file_id = extract_drive_id(url)
    if not file_id:
        flash('URL Google Drive tidak valid.', 'error')
        return redirect(url_for('dashboard'))

    filename = f"drive_{file_id}.mp4"
    filepath = os.path.join(UPLOAD_DIR, filename)
    try:
        import gdown
        gdown.download(id=file_id, output=filepath, quiet=False)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            flash('Gagal mengunduh: file kosong atau tidak ditemukan.', 'error')
            return redirect(url_for('dashboard'))
        f = File(user_id=user_id, filename=filename, filepath=filepath,
                 size_bytes=os.path.getsize(filepath), source='drive')
        db.session.add(f)
        db.session.commit()
        flash(f'File {filename} berhasil diunduh.', 'success')
    except Exception as e:
        flash(f'Gagal mengunduh: {e}', 'error')
    return redirect(url_for('dashboard'))


@app.route('/rename_file/<int:file_id>', methods=['POST'])
@login_required
def rename_file(file_id):
    user_id = session.get('user_id')
    f = File.query.filter_by(id=file_id, user_id=user_id).first()
    if not f:
        flash('File tidak ditemukan.', 'error')
        return redirect(url_for('dashboard'))

    new_name = request.form.get('new_filename', '').strip()
    if not new_name:
        flash('Nama file tidak boleh kosong.', 'error')
        return redirect(url_for('dashboard'))

    # Ensure .mp4 extension if missing
    if not new_name.lower().endswith(('.mp4', '.mkv')):
        new_name += '.mp4'

    old_filepath = f.filepath
    new_filepath = os.path.join(os.path.dirname(old_filepath) if old_filepath else UPLOAD_DIR, new_name)

    if old_filepath != new_filepath:
        try:
            if old_filepath and os.path.exists(old_filepath):
                os.rename(old_filepath, new_filepath)
            elif old_filepath is None:
                new_filepath = None
        except OSError as e:
            flash(f'Gagal mengubah nama file: {e}', 'error')
            return redirect(url_for('dashboard'))

    f.filename = new_name
    f.filepath = new_filepath
    db.session.commit()
    flash(f'File diubah namanya menjadi {new_name}.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/preview/<int:file_id>')
@login_required
def preview_file(file_id):
    f = File.query.filter_by(id=file_id, user_id=session.get('user_id')).first()
    if not f or not f.filepath or not os.path.exists(f.filepath):
        abort(404)
    return send_file(f.filepath)


@app.route('/settings')
@login_required
def settings():
    return render_template('dashboard.html')


if __name__ == '__main__':
    os.makedirs(app.instance_path, exist_ok=True)
    with app.app_context():
        db.create_all()
        ensure_schema()
        if not User.query.filter_by(username='yxdesu').first():
            u = User(username='yxdesu',
                     password_hash=generate_password_hash('yxdesu070707'),
                     role='admin')
            db.session.add(u)
            db.session.commit()
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
