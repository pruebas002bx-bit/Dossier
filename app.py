import os
import io
import time
import requests
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from psycopg2.extras import RealDictCursor
from deep_translator import GoogleTranslator

app = Flask(__name__)
app.secret_key = 'alpha_super_secret_key'

# --- CONFIGURACIÓN ---
DB_URL = os.environ.get("DATABASE_URL", "postgresql://usuario:password@host:port/defaultdb")
IMGBB_API_KEY = "df01bb05ce03159d54c33e1e22eba2cf"
CURRENCY_API_KEY = "1a9b899a5a19988a73d68cde"

# --- CACHÉ MONEDA ---
currency_cache = { "rate": 4150, "last_updated": 0 }

def get_usd_to_cop_rate():
    now = time.time()
    if now - currency_cache["last_updated"] < 3600:
        return currency_cache["rate"]
    try:
        url = f"https://v6.exchangerate-api.com/v6/{CURRENCY_API_KEY}/latest/USD"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data['result'] == 'success':
            rate = data['conversion_rates']['COP']
            currency_cache["rate"] = rate
            currency_cache["last_updated"] = now
            return rate
    except:
        pass
    return currency_cache["rate"]

def get_db_connection():
    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Error DB: {e}")
        return None

def compress_and_upload(file):
    try:
        image = Image.open(file)
        if image.mode in ("RGBA", "P"): image = image.convert("RGB")
        img_byte_arr = io.BytesIO()
        # Calidad reducida al 50%
        image.save(img_byte_arr, format='JPEG', quality=50, optimize=True)
        img_byte_arr.seek(0)
        
        payload = {'key': IMGBB_API_KEY}
        files = {'image': img_byte_arr}
        response = requests.post("https://api.imgbb.com/1/upload", data=payload, files=files, timeout=15)
        data = response.json()
        if data['success']: return data['data']['url']
    except Exception as e:
        print(f"Error Upload: {e}")
    return None

def translate_text(text, target_lang):
    if target_lang == 'es' or not text: return text
    try:
        lang_map = {'en': 'en', 'pt': 'pt'}
        translator = GoogleTranslator(source='auto', target=lang_map.get(target_lang, 'en'))
        translated = translator.translate(text)
        return translated if translated else text
    except:
        return text

# --- DICCIONARIO UI ---
UI_TRANSLATIONS = {
    'es': {'offers': 'Ofertas', 'scenarios': 'Escenarios', 'weapons': 'Armas', 'kits': 'Kit de Tiro', 'sims': 'Simuladores', 'cart': 'Carrito', 'admin': 'Admin', 'contact': 'Contacto', 'details': 'Ver Detalles', 'add': 'Añadir', 'desc': 'Descripción', 'ship': 'Envíos Certificados', 'filter_title': 'Filtros', 'cat_title': 'Categorías', 'price_title': 'Rango de Precio', 'apply': 'Aplicar Filtro'},
    'en': {'offers': 'Offers', 'scenarios': 'Scenarios', 'weapons': 'Weapons', 'kits': 'Shooting Kits', 'sims': 'Simulators', 'cart': 'Cart', 'admin': 'Admin', 'contact': 'Contact', 'details': 'View Details', 'add': 'Add', 'desc': 'Description', 'ship': 'Certified Shipping', 'filter_title': 'Filters', 'cat_title': 'Categories', 'price_title': 'Price Range', 'apply': 'Apply Filter'},
    'pt': {'offers': 'Ofertas', 'scenarios': 'Cenários', 'weapons': 'Armas', 'kits': 'Kits de Tiro', 'sims': 'Simuladores', 'cart': 'Carrinho', 'admin': 'Admin', 'contact': 'Contato', 'details': 'Ver Detalhes', 'add': 'Adicionar', 'desc': 'Descrição', 'ship': 'Envios Certificados', 'filter_title': 'Filtros', 'cat_title': 'Categorias', 'price_title': 'Faixa de Preço', 'apply': 'Aplicar Filtro'}
}

@app.context_processor
def inject_globals():
    lang = session.get('lang', 'es')
    return dict(t=UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['es']), current_lang=lang)

# --- RUTAS ---
@app.route('/set_language/<lang>')
def set_language(lang):
    session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    products = []
    available_categories = []
    
    # Obtener parámetros de filtro
    cat_filter = request.args.get('cat', '').lower()
    min_price = request.args.get('min_price', 0)
    max_price = request.args.get('max_price', 99999)
    search_query = request.args.get('q', '').lower()

    if conn:
        cur = conn.cursor()
        
        # 1. Obtener categorías dinámicas (basadas en lo que existe en DB)
        cur.execute("SELECT DISTINCT category FROM products ORDER BY category ASC")
        cats = cur.fetchall()
        available_categories = [c['category'] for c in cats if c['category']]

        # 2. Construir Query Dinámico para Productos
        query = "SELECT * FROM products WHERE price_usd >= %s AND price_usd <= %s"
        params = [min_price, max_price]

        if cat_filter and cat_filter != 'ofertas':
            query += " AND LOWER(category) = %s"
            params.append(cat_filter)
        
        if search_query:
            query += " AND (LOWER(name) LIKE %s OR LOWER(specs) LIKE %s)"
            params.append(f"%{search_query}%")
            params.append(f"%{search_query}%")

        query += " ORDER BY id DESC"

        cur.execute(query, tuple(params))
        products = cur.fetchall()
        cur.close()
        conn.close()

    cop_rate = get_usd_to_cop_rate()
    target_lang = session.get('lang', 'es')

    for p in products:
        # Precio
        if p['price_usd']: p['price_cop'] = float(p['price_usd']) * cop_rate
        else: p['price_cop'] = 0
        
        # Imágenes
        if p['image_urls']: p['images'] = p['image_urls'].split(',')
        else: p['images'] = []

        # Traducción
        if target_lang != 'es':
            p['name'] = translate_text(p['name'], target_lang)
            p['specs'] = translate_text(p['specs'], target_lang)
            p['category'] = translate_text(p['category'], target_lang)

    return render_template('index.html', products=products, categories=available_categories)

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == "1032491753Outlook*":
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Error de contraseña')
    return render_template('login.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        specs = request.form['specs']
        price_usd = request.form['price_usd']
        
        uploaded_files = request.files.getlist('images')
        new_urls = []
        for file in uploaded_files:
            if file.filename != '':
                url = compress_and_upload(file)
                if url: new_urls.append(url)
        
        final_images = ",".join(new_urls)

        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO products (name, category, specs, price_usd, price_cop, image_urls) VALUES (%s, %s, %s, %s, %s, %s)",
                        (name, category, specs, price_usd, 0, final_images))
            conn.commit()
            cur.close()
            conn.close()
            flash('Producto Guardado')

    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)