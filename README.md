# yxdesu Stream — Live Streaming Dashboard

Dashboard web untuk mengelola sesi live streaming (YouTube / platform lain) dengan tampilan modern dark mode.

## Fitur

- Dashboard: lihat sesi live aktif, statistik, dan durasi
- Buat Live: pilih file video, masukkan stream key YouTube, atur jadwal & auto-stop
- Berkas: unduh file dari Google Drive, kelola daftar video
- Pengaturan: ganti sandi, atur zona waktu (WIB/WITA/WIT)

## Cara Pakai (Local)

```bash
pip install flask flask-sqlalchemy
python app.py
```

Buka `http://127.0.0.1:8080` di browser. Default akun: `admin` / `admin123`.

## Deploy ke VPS (Ubuntu 24.04)

```bash
# 1. Install dependensi
sudo apt update
sudo apt install -y python3-pip python3-venv nginx ffmpeg

# 2. Clone repo
git clone https://github.com/dedefalevi21/live.git
cd live

# 3. Buat virtualenv & install
python3 -m venv venv
source venv/bin/activate
pip install flask flask-sqlalchemy

# 4. Buat akun admin pertama
python3 -c "
from app import db, User
from werkzeug.security import generate_password_hash
with app.app_context():
    db.create_all()
    u = User(username='admin', password_hash=generate_password_hash('admin123'), role='admin')
    db.session.add(u)
    db.session.commit()
    print('Akun admin: admin / admin123')
"

# 5. Jalankan Flask (background)
nohup python app.py > /tmp/flask.log 2>&1 &

# 6. Konfigurasi nginx (contoh)
sudo cp nginx.conf /etc/nginx/sites-available/live
sudo ln -sf /etc/nginx/sites-available/live /etc/nginx/sites-enabled/live
sudo nginx -t && sudo systemctl reload nginx
```

## Catatan

- Gunakan `debug=False` di production (sudah diatur)
- Ganti sandi default `admin123` setelah pertama kali login
- Pastikan `yxdede123.JPG` ada di folder yang sama dengan `dashboard.html`
- Untuk YouTube live stream, gunakan Stream Key dari YouTube Studio → Go Live