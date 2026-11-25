from app import app, db, User
from werkzeug.security import generate_password_hash
with app.app_context():
    u = User.query.filter_by(username='yxdesu').first()
    if u:
        u.password_hash = generate_password_hash('yxdesu070707')
        db.session.commit()
        print('Password sudah diubah')
    else:
        print('User tidak ditemukan')