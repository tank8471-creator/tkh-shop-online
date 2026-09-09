import sqlite3
import io
import base64
import webbrowser
from flask import Flask, render_template_string, request, session, jsonify, redirect, url_for
from promptpay_qr import generate_qr_image

app = Flask(__name__)
app.secret_key = "tkh-shop-secret-key"

# 🔑 รหัสผ่านสำหรับเจ้าของร้านเข้าสู่ระบบจัดการ (เปลี่ยนเป็นรหัสของคุณได้ตรงนี้)
ADMIN_PASSWORD = "123456"

PROMPTPAY_ID = "0948206384"
DEFAULT_HERO_BG = "https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=80"

# ==========================================
# ⚡ ตัวแปรสัญญาณสำหรับเชื่อมต่อกับ ESP32
# ==========================================
payment_triggered = False

# ===== ระบบจัดการฐานข้อมูล SQLite =====
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    
    # 1. ตารางสินค้า
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            desc TEXT,
            category TEXT DEFAULT 'ทั่วไป',
            image_b64 TEXT,
            stock INTEGER DEFAULT 10,
            sold INTEGER DEFAULT 0
        )
    ''')
    
    # 2. ตารางตั้งค่าเว็บไซต์
    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    try:
        conn.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'ทั่วไป'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT 10")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE products ADD COLUMN sold INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()

    default_contacts = {
        'phone': '094-820-6384',
        'line': '@tkhshop',
        'facebook': 'TKH Shop อะไหล่แต่งมอเตอร์ไซค์',
        'address': '123/45 ถนนมิตรภาพ อ.เมือง จ.นครราชสีมา 30000',
        'hours': 'จันทร์ - เสาร์ (09:00 - 18:00 น.)'
    }
    for key, val in default_contacts.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (f"contact_{key}", val))
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        sample_products = [
            ("ชุดท่อไอเสียแต่ง Wave 110i", 850.00, "งานสแตนเลสยิงทราย ตรงรุ่น Wave 110i เพิ่มอัตราเร่ง", "Wave 110i", "", 15, 3),
            ("ชุดเบาะแต่งทรงเชง Wave 125R/S/บังลม", 650.00, "ผ้าเรดเดอร์ สกรีนโลโก้ ตรงรุ่น Wave 125R/S/บังลม", "Wave 125R/S/บังลม", "", 20, 8),
            ("โช้คอัพหลังปรับระดับ Wave 125i", 1290.00, "นุ่มแน่น ซับแรงกระแทกเยี่ยม ตรงรุ่น Wave 125i ปลาวาฬ/LED", "Wave 125i LED", "", 10, 5),
            ("ชุดชามแต่งพร้อมเม็ด PCX 160", 1590.00, "เพิ่มปลายนอน ลื่นไหล ปลดรอบ PCX 150/160", "PCX 150/160", "", 8, 12),
            ("ตะแกรงท้ายสไตล์คลาสสิก Giorno+", 890.00, "งานเหล็กหนาแข็งแรง ตรงรุ่น Honda Giorno+ เพิ่มความอเนกประสงค์", "Giorno+", "", 12, 4),
            ("ชุดชามแต่งข้างเต็มระบบ Lead 125", 1450.00, "ปลดรอบ บิดติดมือ ออกตัวไว ตรงรุ่น Honda Lead 125 (4 วาล์ว)", "Lead 125", "", 14, 6),
            ("ชามหน้าแต่งพูเล่ Click 125i/160", 1190.00, "เพิ่มอัตราเร่งแซง ท้ายไม่ตัด", "Click 125i/160", "", 9, 2),
            ("ท่อสูตรทรานเซป FORZA 350", 4500.00, "เสียงนุ่มบาสลึก ตรงรุ่น FORZA 350", "FORZA 350", "", 5, 1)
        ]
        cur.executemany("INSERT INTO products (name, price, desc, category, image_b64, stock, sold) VALUES (?, ?, ?, ?, ?, ?, ?)", sample_products)
        conn.commit()
    conn.close()

init_db()

def get_hero_bg():
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = 'hero_bg'").fetchone()
    conn.close()
    return row['value'] if row and row['value'] else DEFAULT_HERO_BG

def get_contact_info():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'contact_%'").fetchall()
    conn.close()
    return {r['key'].replace('contact_', ''): r['value'] for r in rows}

# ===== CSS COMMON =====
COMMON_STYLE = """
<link href="https://fonts.googleapis.com/css2?family=Kanit:ital,wght@0,300;0,400;0,600;0,800;1,800&display=swap" rel="stylesheet">
<style>
    * { box-sizing: border-box; font-family: 'Kanit', sans-serif; margin: 0; padding: 0; }
    body { background-color: #0b0b0b; color: #ffffff; padding-bottom: 50px; }
    a { text-decoration: none; color: inherit; }
    
    .navbar {
        background-color: #111111;
        border-bottom: 1px solid #222;
        padding: 15px 5%;
        display: flex;
        justify-content: space-between;
        align-items: center;
        position: sticky;
        top: 0;
        z-index: 1000;
    }
    .logo { font-size: 24px; font-weight: 800; font-style: italic; color: #fff; display: flex; align-items: center; gap: 5px; }
    .logo span { color: #e50914; }
    .nav-links { display: flex; gap: 25px; list-style: none; font-size: 14px; font-weight: 600; text-transform: uppercase; color: #ccc; align-items: center; }
    .nav-links a:hover { color: #e50914; }
    
    .dropdown { position: relative; display: inline-block; }
    .dropdown-btn { cursor: pointer; display: flex; align-items: center; gap: 4px; padding: 10px 0; }
    .dropdown-content {
        display: none;
        position: absolute;
        background-color: #141414;
        min-width: 220px;
        box-shadow: 0px 8px 16px 0px rgba(0,0,0,0.8);
        border: 1px solid #222;
        border-top: 3px solid #e50914;
        border-radius: 4px;
        z-index: 1001;
        top: 100%;
        left: 0;
    }
    .dropdown-content a { color: #ccc; padding: 10px 16px; display: block; font-size: 13px; transition: background 0.2s; }
    .dropdown-content a:hover { background-color: #1f1f1f; color: #e50914; }
    .dropdown:hover .dropdown-content { display: block; }
    
    .nav-actions { display: flex; align-items: center; gap: 15px; }
    
    .btn {
        padding: 10px 20px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 14px;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        transition: all 0.2s ease;
        border: none;
    }
    .btn-red { background-color: #e50914; color: #fff; }
    .btn-red:hover { background-color: #b80710; transform: translateY(-2px); }
    .btn-outline { background: transparent; border: 1px solid #444; color: #fff; }
    .btn-outline:hover { border-color: #e50914; color: #e50914; }
    .btn-gray { background: #222; color: #ccc; }
    .btn-gray:hover { background: #333; color: #fff; }
    
    .container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }
    
    .form-card {
        background: #141414;
        padding: 30px;
        border-radius: 8px;
        border: 1px solid #222;
        max-width: 600px;
        margin: 40px auto;
    }
    .form-group { margin-bottom: 20px; }
    .form-group label { display: block; margin-bottom: 8px; color: #aaa; font-size: 14px; }
    .form-group input, .form-group textarea, .form-group select {
        width: 100%;
        padding: 12px;
        background: #080808;
        border: 1px solid #333;
        color: #fff;
        border-radius: 4px;
        font-size: 15px;
    }
    .form-group input:focus, .form-group textarea:focus, .form-group select:focus { border-color: #e50914; outline: none; }

    .stock-dashboard {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 30px;
    }
    .stock-stat-card {
        background: #141414;
        border: 1px solid #222;
        border-radius: 8px;
        padding: 15px 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .stock-stat-card.sales { border-left: 4px solid #00ff66; }
    .stock-stat-card.total { border-left: 4px solid #e50914; }
    .stat-val { font-size: 24px; font-weight: 800; color: #fff; }
    .stat-lbl { font-size: 12px; color: #888; text-transform: uppercase; }
</style>
"""

@app.route('/check-payment')
def check_payment():
    global payment_triggered
    if payment_triggered:
        payment_triggered = False
        return jsonify({"paid": True})
    return jsonify({"paid": False})

# ===== ระบบยืนยันตัวตน Admin =====
def is_admin_logged_in():
    return session.get('is_admin', False)

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return '<script>alert("❌ รหัสผ่านผู้ดูแลระบบไม่ถูกต้อง!"); location.href="/admin-login";</script>'
            
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>เข้าสู่ระบบผู้ดูแลร้าน - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/" class="btn btn-outline">← กลับหน้าหลัก</a>
        </nav>
        <div class="container">
            <div class="form-card">
                <h2 style="margin-bottom: 20px; text-align: center;">🔐 เข้าสู่ระบบผู้ดูแลร้าน (Admin)</h2>
                <form method="post">
                    <div class="form-group">
                        <label>กรอกรหัสผ่านผู้ดูแลระบบ:</label>
                        <input type="password" name="password" placeholder="ใส่รหัสผ่านที่นี่..." required>
                    </div>
                    <button type="submit" class="btn btn-red" style="width: 100%; padding: 12px;">เข้าสู่ระบบ</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/admin-logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))
        
    conn = get_db()
    total_stock_all = conn.execute("SELECT SUM(stock) FROM products").fetchone()[0] or 0
    total_sold_all = conn.execute("SELECT SUM(sold) FROM products").fetchone()[0] or 0
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()

    products_rows = ""
    for p in products:
        products_rows += f"""
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px;">{p['id']}</td>
            <td style="padding: 12px; font-weight: bold;">{p['name']}</td>
            <td style="padding: 12px; color: #e50914;">฿{p['price']:,.2f}</td>
            <td style="padding: 12px;">{p['stock']} ชิ้น</td>
            <td style="padding: 12px; color: #00ff66;">{p['sold']} ชิ้น</td>
            <td style="padding: 12px;">
                <a href="/edit-product/{p['id']}" class="btn btn-gray" style="padding: 4px 8px; font-size: 12px;">✏️ แก้ไข</a>
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>แผงควบคุมผู้ดูแลร้าน - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span> <small style="font-size: 12px; color: #e50914;">[ADMIN]</small></a>
            <div class="nav-actions">
                <a href="/add-product" class="btn btn-outline">➕ เพิ่มสินค้าใหม่</a>
                <a href="/change-hero-bg" class="btn btn-gray">🖼️ เปลี่ยนรูปพื้นหลัง</a>
                <a href="/admin-logout" class="btn btn-red">ออกจากระบบ</a>
            </div>
        </nav>

        <div class="container" style="margin-top: 30px;">
            <h2 style="margin-bottom: 20px;">📊 ภาพรวมร้านค้าและจัดการสต็อก</h2>
            <div class="stock-dashboard">
                <div class="stock-stat-card total">
                    <div>
                        <div class="stat-lbl">📦 จำนวนสินค้าคงเหลือรวม</div>
                        <div class="stat-val">{total_stock_all:,} <span style="font-size:14px; font-weight:normal; color:#aaa;">ชิ้น</span></div>
                    </div>
                </div>
                <div class="stock-stat-card sales">
                    <div>
                        <div class="stat-lbl">🔥 จำนวนสินค้าขายออกแล้ว</div>
                        <div class="stat-val" style="color: #00ff66;">{total_sold_all:,} <span style="font-size:14px; font-weight:normal; color:#aaa;">ชิ้น</span></div>
                    </div>
                </div>
            </div>

            <h3 style="margin-bottom: 15px;">📦 รายการสินค้าทั้งหมด</h3>
            <table style="width: 100%; border-collapse: collapse; background: #141414; border-radius: 8px; overflow: hidden; border: 1px solid #222; text-align: left;">
                <thead>
                    <tr style="background: #1f1f1f; color: #aaa; font-size: 13px;">
                        <th style="padding: 12px;">ID</th>
                        <th style="padding: 12px;">ชื่อสินค้า</th>
                        <th style="padding: 12px;">ราคา</th>
                        <th style="padding: 12px;">คงเหลือ</th>
                        <th style="padding: 12px;">ขายแล้ว</th>
                        <th style="padding: 12px;">จัดการ</th>
                    </tr>
                </thead>
                <tbody>
                    {products_rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return html


# ===== 1. หน้าแรก (สำหรับลูกค้าทั่วไป) =====
@app.route('/')
def index():
    cart = session.get('cart', [])
    selected_cat = request.args.get('category', '')
    
    conn = get_db()
    if selected_cat and selected_cat != 'ทั้งหมด':
        products = conn.execute("SELECT * FROM products WHERE category = ? ORDER BY id DESC", (selected_cat,)).fetchall()
    else:
        products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    
    products_html = ""
    for p in products:
        img_html = f'<img src="{p["image_b64"]}" class="product-img">' if p['image_b64'] else '<div class="product-img-placeholder">ไม่มีรูปภาพ</div>'
        cat_badge = f'<span class="cat-badge">{p["category"]}</span>' if 'category' in p.keys() and p['category'] else ''
        
        stock_count = p['stock'] if 'stock' in p.keys() else 0
        sold_count = p['sold'] if 'sold' in p.keys() else 0
        
        stock_status = f'<span style="color: #00ff66;">📦 คงเหลือ: {stock_count} ชิ้น</span>' if stock_count > 0 else '<span style="color: #ff4d4d; font-weight: bold;">❌ สินค้าหมด</span>'
        
        products_html += f"""
        <div class="product-card">
            <div class="product-img-container">
                <span class="badge">ขายดี</span>
                {img_html}
            </div>
            <div class="product-info">
                <div class="product-header">
                    {cat_badge}
                    <h3 class="product-title">{p['name']}</h3>
                    <div class="product-price">฿{p['price']:,.2f}</div>
                </div>
                <p class="product-desc">{p['desc']}</p>
                
                <div style="background: #080808; padding: 8px 12px; border-radius: 4px; border: 1px solid #222; font-size: 12px; display: flex; justify-content: space-between; margin-bottom: 12px;">
                    {stock_status}
                    <span style="color: #aaa;">🔥 ขายแล้ว: <strong style="color: #fff;">{sold_count}</strong> ชิ้น</span>
                </div>

                <div class="product-actions">
                    <form action="/add-to-cart" method="post" style="flex: 1;">
                        <input type="hidden" name="pid" value="{p['id']}">
                        <button class="btn btn-red" style="width: 100%;" {"disabled" if stock_count <= 0 else ""}>{"สั่งซื้อทันที" if stock_count > 0 else "หมด"}</button>
                    </form>
                    <form action="/add-to-cart" method="post">
                        <input type="hidden" name="pid" value="{p['id']}">
                        <button class="btn btn-gray" title="เพิ่มลงตะกร้า" {"disabled" if stock_count <= 0 else ""}>🛒</button>
                    </form>
                </div>
            </div>
        </div>
        """
        
    if not products_html:
        products_html = '<div style="grid-column: 1/-1; text-align: center; padding: 50px; color: #666;">ไม่พบสินค้าในหมวดหมู่นี้</div>'

    hero_bg_url = get_hero_bg()
    hero_bg_style = f"background: linear-gradient(90deg, rgba(11,11,11,0.92) 30%, rgba(11,11,11,0.6) 100%), url('{hero_bg_url}') center/cover;"
    title_display = f"สินค้าสำหรับรุ่น: {selected_cat}" if selected_cat and selected_cat != 'ทั้งหมด' else "รายการสินค้าทั้งหมด"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>TKH Shop - อะไหล่แต่งมอเตอร์ไซค์คุณภาพสูง</title>
        {COMMON_STYLE}
        <style>
            .hero {{
                {hero_bg_style}
                padding: 80px 0;
                margin-bottom: 30px;
                border-bottom: 1px solid #222;
                position: relative;
            }}
            .hero-content {{ max-width: 600px; }}
            .hero-subtitle {{ color: #e50914; font-weight: 800; letter-spacing: 2px; font-size: 14px; text-transform: uppercase; margin-bottom: 10px; }}
            .hero-title {{ font-size: 48px; font-weight: 800; font-style: italic; line-height: 1.1; margin-bottom: 15px; text-shadow: 2px 2px 4px rgba(0,0,0,0.8); }}
            .hero-text {{ color: #aaa; font-size: 16px; margin-bottom: 25px; line-height: 1.5; }}

            .section-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 2px solid #222; padding-bottom: 10px; }}
            .section-title {{ font-size: 22px; font-weight: 800; font-style: italic; text-transform: uppercase; position: relative; }}
            .section-title::after {{ content: ''; position: absolute; bottom: -12px; left: 0; width: 60px; height: 2px; background: #e50914; }}
            
            .product-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; }}
            .product-card {{
                background: #141414;
                border-radius: 8px;
                border: 1px solid #222;
                overflow: hidden;
                display: flex;
                flex-direction: column;
                transition: transform 0.2s;
            }}
            .product-card:hover {{ transform: translateY(-4px); border-color: #333; }}
            .product-img-container {{ position: relative; width: 100%; height: 200px; background: #080808; display: flex; align-items: center; justify-content: center; }}
            .product-img {{ width: 100%; height: 100%; object-fit: cover; }}
            .product-img-placeholder {{ color: #444; font-size: 14px; }}
            .badge {{ position: absolute; top: 12px; left: 12px; background: #e50914; color: #fff; font-size: 10px; font-weight: 800; padding: 4px 8px; border-radius: 3px; text-transform: uppercase; }}
            .cat-badge {{ display: inline-block; background: #222; color: #ffb700; font-size: 11px; padding: 2px 6px; border-radius: 3px; margin-bottom: 5px; font-weight: 600; }}

            .product-info {{ padding: 18px; display: flex; flex-direction: column; flex-grow: 1; }}
            .product-header {{ margin-bottom: 8px; }}
            .product-title {{ font-size: 16px; font-weight: 700; margin-bottom: 4px; color: #fff; }}
            .product-price {{ color: #e50914; font-size: 18px; font-weight: 800; }}
            .product-desc {{ color: #888; font-size: 13px; margin-bottom: 12px; line-height: 1.4; flex-grow: 1; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
            .product-actions {{ display: flex; gap: 8px; }}
        </style>
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <ul class="nav-links">
                <li><a href="/">หน้าแรก</a></li>
                <li><a href="/#products">ร้านค้า</a></li>
                <li class="dropdown">
                    <span class="dropdown-btn">หมวดหมู่สินค้า ▾</span>
                    <div class="dropdown-content">
                        <a href="/?category=Wave+125R/S/บังลม">🏎️ Honda Wave 125R / S / บังลม</a>
                        <a href="/?category=Wave+125i+LED">🏎️ Honda Wave 125i / LED</a>
                        <a href="/?category=Wave+110i">🏎️ Honda Wave 110i</a>
                        <a href="/?category=Giorno%2B">🛵 Honda Giorno+</a>
                        <a href="/?category=Lead+125">🛵 Honda Lead 125</a>
                        <a href="/?category=PCX+150/160">🏎️ Honda PCX 150 / 160</a>
                        <a href="/?category=Click+125i/160">🏎️ Honda Click 125i / 160</a>
                        <a href="/?category=FORZA+350">🏎️ Honda FORZA 350</a>
                        <a href="/?category=Grom/MSX">🏎️ Honda Grom / MSX</a>
                        <hr style="border:0; border-top: 1px solid #222; margin: 5px 0;">
                        <a href="/?category=ทั้งหมด">🏍️ ดูอะไหล่ทุกรุ่น</a>
                    </div>
                </li>
                <li><a href="/about">เกี่ยวกับเรา</a></li>
                <li><a href="/contact">ติดต่อเรา</a></li>
            </ul>
            <div class="nav-actions">
                <a href="/cart" class="btn btn-red">🛒 ตะกร้า ({len(cart)})</a>
                <a href="/admin-login" class="btn btn-outline" style="font-size: 11px; padding: 6px 10px;">🔒 ผู้ดูแลระบบ</a>
            </div>
        </nav>

        <div class="hero">
            <div class="container">
                <div class="hero-content">
                    <div class="hero-subtitle">สร้างสรรค์เพื่อความแรง</div>
                    <h1 class="hero-title">ยกระดับความแรง<br>มอเตอร์ไซค์ของคุณ</h1>
                    <p class="hero-text">ศูนย์รวมอะไหล่แต่งและอะไหล่แท้คุณภาพสูง สำหรับมอเตอร์ไซค์ Honda ทุกรุ่น ตอบโจทย์สายเชง สายซิ่ง และใช้งานทั่วไป</p>
                    <a href="#products" class="btn btn-red" style="padding: 12px 28px; font-size: 16px;">ช้อปเลย &gt;</a>
                </div>
            </div>
        </div>

        <div class="container" id="products">
            <div class="section-header">
                <h2 class="section-title">{title_display}</h2>
                <a href="/" style="color: #e50914; font-size: 13px; font-weight: 700;">ดูทั้งหมด &gt;</a>
            </div>

            <div class="product-grid">
                {products_html}
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

# ===== 2. เพิ่มสินค้าใหม่ (Admin Only) =====
@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        name = request.form.get('name')
        price = float(request.form.get('price', 0))
        category = request.form.get('category', 'ทั่วไป')
        stock = int(request.form.get('stock', 10))
        desc = request.form.get('desc')
        file = request.files.get('image')
        
        image_b64 = ""
        if file and file.filename != '':
            image_bytes = file.read()
            encoded = base64.b64encode(image_bytes).decode('utf-8')
            mime_type = file.mimetype or "image/png"
            image_b64 = f"data:{mime_type};base64,{encoded}"
            
        conn = get_db()
        conn.execute("INSERT INTO products (name, price, desc, category, image_b64, stock, sold) VALUES (?, ?, ?, ?, ?, ?, 0)",
                     (name, price, desc, category, image_b64, stock))
        conn.commit()
        conn.close()
        return '<script>alert("✅ เพิ่มสินค้าเรียบร้อย!"); location.href="/admin";</script>'
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>เพิ่มสินค้าใหม่ - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/admin" class="btn btn-outline">← กลับหน้าผู้ดูแล</a>
        </nav>
        <div class="container">
            <div class="form-card">
                <h2 style="margin-bottom: 20px; font-style: italic; text-transform: uppercase;">➕ เพิ่มสินค้าใหม่</h2>
                <form method="post" enctype="multipart/form-data">
                    <div class="form-group">
                        <label>ชื่อสินค้า / อะไหล่:</label>
                        <input type="text" name="name" required placeholder="เช่น ท่อสูตรแต่งประสิทธิภาพสูง...">
                    </div>
                    <div class="form-group">
                        <label>รุ่นรถ Honda (หมวดหมู่):</label>
                        <select name="category">
                            <option value="Wave 125R/S/บังลม">Honda Wave 125R / S / บังลม</option>
                            <option value="Wave 125i LED">Honda Wave 125i / LED</option>
                            <option value="Wave 110i">Honda Wave 110i</option>
                            <option value="Giorno+">Honda Giorno+</option>
                            <option value="Lead 125">Honda Lead 125</option>
                            <option value="PCX 150/160">Honda PCX 150 / 160</option>
                            <option value="Click 125i/160">Honda Click 125i / 160</option>
                            <option value="FORZA 350">Honda FORZA 350</option>
                            <option value="Grom/MSX">Honda Grom / MSX</option>
                            <option value="ทั่วไป">รถทั่วไป / หลายรุ่น</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>ราคา (บาท):</label>
                        <input type="number" step="0.01" name="price" required placeholder="850">
                    </div>
                    <div class="form-group">
                        <label>จำนวนสต็อกคงเหลือ (ชิ้น):</label>
                        <input type="number" name="stock" value="10" required placeholder="10">
                    </div>
                    <div class="form-group">
                        <label>รายละเอียดสินค้า:</label>
                        <textarea name="desc" rows="4" placeholder="ระบุสเปกหรือรายละเอียดเพิ่มเติม..."></textarea>
                    </div>
                    <div class="form-group">
                        <label>รูปภาพสินค้า:</label>
                        <input type="file" name="image" accept="image/*">
                    </div>
                    <br>
                    <button type="submit" class="btn btn-red" style="width:100%; padding: 12px;">💾 บันทึกสินค้า</button>
                    <a href="/admin" class="btn btn-gray" style="width:100%; text-align:center; margin-top:10px; padding: 12px;">ยกเลิก</a>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ===== 3. แก้ไขสินค้า (Admin Only) =====
@app.route('/edit-product/<int:pid>', methods=['GET', 'POST'])
def edit_product(pid):
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))

    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    
    if not product:
        conn.close()
        return "ไม่พบสินค้า"
        
    if request.method == 'POST':
        name = request.form.get('name')
        price = float(request.form.get('price', 0))
        category = request.form.get('category', 'ทั่วไป')
        stock = int(request.form.get('stock', 0))
        sold = int(request.form.get('sold', 0))
        desc = request.form.get('desc')
        file = request.files.get('image')
        
        image_b64 = product['image_b64']
        if file and file.filename != '':
            image_bytes = file.read()
            encoded = base64.b64encode(image_bytes).decode('utf-8')
            mime_type = file.mimetype or "image/png"
            image_b64 = f"data:{mime_type};base64,{encoded}"
            
        conn.execute("UPDATE products SET name = ?, price = ?, desc = ?, category = ?, image_b64 = ?, stock = ?, sold = ? WHERE id = ?",
                     (name, price, desc, category, image_b64, stock, sold, pid))
        conn.commit()
        conn.close()
        return '<script>alert("✅ แก้ไขข้อมูลสินค้าสำเร็จ!"); location.href="/admin";</script>'
        
    conn.close()
    
    current_img = f'<img src="{product["image_b64"]}" style="max-width:120px; border-radius:4px; margin:8px 0; border: 1px solid #333;">' if product['image_b64'] else '<span style="color:#666;">ไม่มีรูปภาพ</span>'
    current_cat = product['category'] if 'category' in product.keys() else 'ทั่วไป'
    current_stock = product['stock'] if 'stock' in product.keys() else 10
    current_sold = product['sold'] if 'sold' in product.keys() else 0
    
    categories = ["Wave 125R/S/บังลม", "Wave 125i LED", "Wave 110i", "Giorno+", "Lead 125", "PCX 150/160", "Click 125i/160", "FORZA 350", "Grom/MSX", "ทั่วไป"]
    cat_options = "".join([f'<option value="{c}" {"selected" if c == current_cat else ""}>{c}</option>' for c in categories])

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>แก้ไขสินค้า - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/admin" class="btn btn-outline">← กลับหน้าผู้ดูแล</a>
        </nav>
        <div class="container">
            <div class="form-card">
                <h2 style="margin-bottom: 20px; font-style: italic; text-transform: uppercase;">✏️ แก้ไขรายการสินค้า</h2>
                <form method="post" enctype="multipart/form-data">
                    <div class="form-group">
                        <label>ชื่อสินค้า / อะไหล่:</label>
                        <input type="text" name="name" value="{product['name']}" required>
                    </div>
                    <div class="form-group">
                        <label>รุ่นรถ Honda (หมวดหมู่):</label>
                        <select name="category">
                            {cat_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>ราคา (บาท):</label>
                        <input type="number" step="0.01" name="price" value="{product['price']}" required>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                        <div class="form-group">
                            <label>จำนวนสต็อกคงเหลือ:</label>
                            <input type="number" name="stock" value="{current_stock}" required>
                        </div>
                        <div class="form-group">
                            <label>จำนวนที่ขายออกไปแล้ว:</label>
                            <input type="number" name="sold" value="{current_sold}" required>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>รายละเอียดสินค้า:</label>
                        <textarea name="desc" rows="4">{product['desc']}</textarea>
                    </div>
                    <div class="form-group">
                        <label>รูปภาพสินค้าปัจจุบัน:</label><br>
                        {current_img}<br>
                        <input type="file" name="image" accept="image/*" style="margin-top:8px;">
                    </div>
                    <br>
                    <button type="submit" class="btn btn-red" style="width:100%; padding: 12px;">🔄 อัปเดตข้อมูล</button>
                    <a href="/delete-product/{product['id']}" class="btn btn-gray" style="width:100%; text-align:center; margin-top:10px; padding: 12px; color: #ff4d4d;" onclick="return confirm('ยืนยันที่จะลบสินค้านี้ใช่หรือไม่?');">🗑️ ลบสินค้านี้</a>
                    <a href="/admin" class="btn btn-gray" style="width:100%; text-align:center; margin-top:10px; padding: 12px;">ยกเลิก</a>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/delete-product/<int:pid>')
def delete_product(pid):
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return '<script>alert("🗑️ ลบสินค้าเรียบร้อยแล้ว!"); location.href="/admin";</script>'

@app.route('/change-hero-bg', methods=['GET', 'POST'])
def change_hero_bg():
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))
        
    if request.method == 'POST':
        bg_url = request.form.get('bg_url')
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('hero_bg', ?)", (bg_url,))
        conn.commit()
        conn.close()
        return '<script>alert("✅ เปลี่ยนรูปพื้นหลังสำเร็จ!"); location.href="/admin";</script>'
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>เปลี่ยนรูปพื้นหลัง - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/admin" class="btn btn-outline">← กลับหน้าผู้ดูแล</a>
        </nav>
        <div class="container">
            <div class="form-card">
                <h2 style="margin-bottom: 20px;">🖼️ เปลี่ยนรูปภาพพื้นหลัง (Hero Banner)</h2>
                <form method="post">
                    <div class="form-group">
                        <label>ใส่ลิงก์รูปภาพ (Image URL):</label>
                        <input type="text" name="bg_url" value="{get_hero_bg()}" required>
                    </div>
                    <button type="submit" class="btn btn-red" style="width:100%; padding: 12px;">💾 บันทึกรูปภาพ</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ===== 4. ตะกร้าสินค้าและการชำระเงิน =====
@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    pid = int(request.form.get('pid'))
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    conn.close()
    
    if not product:
        return "ไม่พบสินค้า"
    if product['stock'] <= 0:
        return '<script>alert("❌ ขออภัย สินค้านี้หมดสต็อกแล้ว!"); location.href="/";</script>'
    
    cart = session.get('cart', [])
    cart.append({
        "id": product['id'],
        "name": product['name'],
        "price": product['price']
    })
    session['cart'] = cart
    return '<script>alert("✅ เพิ่มลงตะกร้าเรียบร้อย!"); location.href="/";</script>'

@app.route('/remove/<int:idx>')
def remove_from_cart(idx):
    cart = session.get('cart', [])
    if 0 <= idx < len(cart):
        cart.pop(idx)
        session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    cart = session.get('cart', [])
    total = sum(item['price'] for item in cart)
    
    items_html = ""
    for idx, item in enumerate(cart):
        items_html += f"""
        <div style="background: #141414; padding: 15px 20px; border-radius: 6px; border: 1px solid #222; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 16px; font-weight: 600;">🏎️ {item['name']}</span>
            <div>
                <span style="color: #e50914; font-weight: 800; font-size: 18px; margin-right: 20px;">฿{item['price']:,.2f}</span>
                <a href="/remove/{idx}" class="btn btn-gray" style="padding: 4px 10px; font-size: 12px;">ลบ</a>
            </div>
        </div>
        """
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>ตะกร้าสินค้า - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/" class="btn btn-outline">← เลือกสินค้าเพิ่ม</a>
        </nav>
        <div class="container" style="margin-top: 40px; max-width: 800px;">
            <h2 style="margin-bottom: 20px; font-style: italic; text-transform: uppercase;">🛒 ตะกร้าสินค้าของคุณ</h2>
    """
    if not cart:
        html += """
        <div style="text-align:center; padding: 60px 0; background: #141414; border-radius: 8px; border: 1px solid #222;">
            <h3 style="color: #666; margin-bottom: 20px;">ยังไม่มีสินค้าในตะกร้า</h3>
            <a href="/" class="btn btn-red">ไปเลือกซื้อสินค้า</a>
        </div>
        """
    else:
        html += f"""
            {items_html}
            <div style="background: #141414; padding: 20px; border-radius: 8px; border: 1px solid #e50914; margin-top: 20px; text-align: center;">
                <span style="font-size: 18px; color: #aaa;">ยอดรวมทั้งหมด:</span>
                <span style="font-size: 28px; font-weight: 800; color: #e50914; margin-left: 10px;">฿{total:,.2f}</span>
                <br><br>
                <a href="/checkout" class="btn btn-red" style="width: 100%; padding: 14px; font-size: 18px;">💳 ชำระเงินผ่าน PromptPay QR</a>
            </div>
        """
    html += """
        </div>
    </body>
    </html>
    """
    return html

@app.route('/checkout')
def checkout():
    cart = session.get('cart', [])
    if not cart:
        return redirect(url_for('index'))
        
    total = sum(item['price'] for item in cart)
    
    # สแกน PromptPay QR Code
    img = generate_qr_image(PROMPTPAY_ID, total)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    # หักสต็อกและบวกยอดขายทันทีเมื่อสั่งซื้อชำระเงิน
    conn = get_db()
    for item in cart:
        conn.execute("UPDATE products SET stock = MAX(0, stock - 1), sold = sold + 1 WHERE id = ?", (item['id'],))
    conn.commit()
    conn.close()
    
    session['cart'] = [] # ล้างตะกร้า
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>ชำระเงิน - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
        </nav>
        <div class="container" style="margin-top: 40px; text-align: center; max-width: 500px;">
            <div style="background: #141414; padding: 30px; border-radius: 8px; border: 1px solid #222;">
                <h2 style="color: #00ff66; margin-bottom: 10px;">สแกนเพื่อชำระเงิน</h2>
                <p style="color: #aaa; margin-bottom: 20px;">ยอดชำระทั้งสิ้น: <strong style="color: #fff; font-size: 20px;">฿{total:,.2f}</strong></p>
                <img src="data:image/png;base64,{qr_b64}" style="width: 250px; height: 250px; background: white; padding: 10px; border-radius: 8px;">
                <p style="font-size: 12px; color: #888; margin-top: 15px;">ชื่อบัญชี: TKH Shop (PromptPay: {PROMPTPAY_ID})</p>
                <br>
                <a href="/" class="btn btn-red" style="width: 100%;">เสร็จสิ้น / กลับหน้าหลัก</a>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/about')
def about():
    info = get_contact_info()
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>เกี่ยวกับเรา - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/" class="btn btn-outline">← กลับหน้าหลัก</a>
        </nav>
        <div class="container" style="margin-top: 40px; max-width: 800px;">
            <div style="background: #141414; padding: 40px; border-radius: 8px; border: 1px solid #222;">
                <h1 style="color: #e50914; font-style: italic; margin-bottom: 20px;">ABOUT TKH SHOP</h1>
                <p style="line-height: 1.8; color: #ccc;">ยินดีต้อนรับสู่ TKH Shop ศูนย์รวมอะไหล่แต่งและอะไหล่แท้คุณภาพสูง สำหรับมอเตอร์ไซค์ Honda ทุกรุ่น เรามุ่งมั่นคัดสรรอะไหล่แต่งที่ดีที่สุด รับประกันคุณภาพและมาตรฐาน ตอบโจทย์ความต้องการของสายเชง สายซิ่ง และผู้ใช้รถทั่วไปทุกท่าน</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/contact')
def contact():
    info = get_contact_info()
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>ติดต่อเรา - TKH Shop</title>
        {COMMON_STYLE}
    </head>
    <body>
        <nav class="navbar">
            <a href="/" class="logo">TKH<span>SHOP</span></a>
            <a href="/" class="btn btn-outline">← กลับหน้าหลัก</a>
        </nav>
        <div class="container" style="margin-top: 40px; max-width: 600px;">
            <div style="background: #141414; padding: 40px; border-radius: 8px; border: 1px solid #222;">
                <h2 style="color: #e50914; font-style: italic; margin-bottom: 20px;">📞 ข้อมูลการติดต่อ</h2>
                <div style="line-height: 2; color: #ccc;">
                    <p>📱 <strong>เบอร์โทรศัพท์:</strong> {info.get('phone', '')}</p>
                    <p>💬 <strong>Line Official:</strong> {info.get('line', '')}</p>
                    <p>📘 <strong>Facebook:</strong> {info.get('facebook', '')}</p>
                    <p>📍 <strong>ที่อยู่ร้าน:</strong> {info.get('address', '')}</p>
                    <p>⏰ <strong>เวลาทำการ:</strong> {info.get('hours', '')}</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
