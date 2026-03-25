import sqlite3
import os

# Lấy đường dẫn thư mục gốc để lưu file .db chung chỗ với app.py
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'router_data.db')

def get_db_connection():
    """Hàm mở kết nối tới Database"""
    conn = sqlite3.connect(DB_PATH)
    # Cấu hình này giúp dữ liệu trả về giống dạng Dictionary của Python (dễ biến thành JSON)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Hàm chạy 1 lần lúc bật server để tạo bảng nếu chưa có"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tạo bảng Devices với các cột cần thiết
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Devices (
            MacAddress TEXT PRIMARY KEY,
            IpAddress TEXT,
            OriginalName TEXT,
            CustomName TEXT,
            IsBlocked INTEGER DEFAULT 0,
            LastSeen DATETIME DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    conn.commit()
    conn.close()
    print("[+] SQLite Database đã sẵn sàng!")