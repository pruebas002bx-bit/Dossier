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
        image.save(img_byte_arr, format='JPEG', quality=60, optimize=True)
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

UI_TRANSLATIONS = {
    'es': {'offers': 'Ofertas', 'scenarios': 'Escenarios', 'weapons': 'Armas', 'kits': 'Kit de Tiro', 'sims': 'Simuladores', 'cart': 'Carrito', 'admin': 'Admin', 'contact': 'Contacto', 'details': 'Ver Detalles', 'add': 'Añadir', 'desc': 'Descripción', 'ship': 'Envíos Certificados', 'filter_title': 'Filtros', 'cat_title': 'Categorías', 'price_title': 'Rango de Precio', 'apply': 'Aplicar Filtro', 'search_ph': 'Buscar productos...'},
    'en': {'offers': 'Offers', 'scenarios': 'Scenarios', 'weapons': 'Weapons', 'kits': 'Shooting Kits', 'sims': 'Simulators', 'cart': 'Cart', 'admin': 'Admin', 'contact': 'Contact', 'details': 'View Details', 'add': 'Add', 'desc': 'Description', 'ship': 'Certified Shipping', 'filter_title': 'Filters', 'cat_title': 'Categories', 'price_title': 'Price Range', 'apply': 'Apply Filter', 'search_ph': 'Search products...'},
    'pt': {'offers': 'Ofertas', 'scenarios': 'Cenários', 'weapons': 'Armas', 'kits': 'Kits de Tiro', 'sims': 'Simuladores', 'cart': 'Carrinho', 'admin': 'Admin', 'contact': 'Contato', 'details': 'Ver Detalhes', 'add': 'Adicionar', 'desc': 'Descrição', 'ship': 'Envios Certificados', 'filter_title': 'Filtros', 'cat_title': 'Categorias', 'price_title': 'Faixa de Preço', 'apply': 'Aplicar Filtro', 'search_ph': 'Procurar produtos...'}
}

@app.context_processor
def inject_globals():
    lang = session.get('lang', 'es')
    return dict(t=UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['es']), current_lang=lang)

@app.route('/set_language/<lang>')
def set_language(lang):
    session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    products = []
    available_categories = []
    
    # 1. Obtener parámetros y limpiarlos
    cat_filter = request.args.get('cat', '').strip()
    search_query = request.args.get('q', '').strip()
    
    try:
        min_price = float(request.args.get('min_price', 0) or 0)
        max_price = float(request.args.get('max_price', 999999) or 999999)
    except ValueError:
        min_price = 0
        max_price = 999999

    if conn:
        try:
            cur = conn.cursor()
            
            # 2. Obtener categorías existentes para el sidebar
            cur.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category ASC")
            cats = cur.fetchall()
            available_categories = [c['category'] for c in cats]

            # 3. Construir Query de Productos (ROBUSTA)
            query = "SELECT * FROM products WHERE price_usd >= %s AND price_usd <= %s"
            params = [min_price, max_price]

            # Filtro por Categoría (Usando ILIKE para ignorar mayúsculas)
            if cat_filter:
                if cat_filter.lower() == 'ofertas':
                    # Si tienes lógica especial para ofertas, añádela aquí. Si es solo una categoría:
                    query += " AND category ILIKE %s"
                    params.append('Ofertas')
                else:
                    query += " AND category ILIKE %s"
                    params.append(cat_filter)
            
            # Filtro por Buscador (Nombre o Specs)
            if search_query:
                query += " AND (name ILIKE %s OR specs ILIKE %s)"
                search_term = f"%{search_query}%"
                params.append(search_term)
                params.append(search_term)

            query += " ORDER BY id DESC"
            
            # Ejecutar
            cur.execute(query, tuple(params))
            products = cur.fetchall()
            cur.close()
        except Exception as e:
            print(f"Error SQL: {e}")
        finally:
            conn.close()

    cop_rate = get_usd_to_cop_rate()
    target_lang = session.get('lang', 'es')

    # Procesar resultados
    processed_products = []
    for p in products:
        prod = dict(p)
        prod['price_cop'] = float(prod['price_usd'] or 0) * cop_rate
        prod['images'] = prod['image_urls'].split(',') if prod['image_urls'] else []
        
        if target_lang != 'es':
            prod['name'] = translate_text(prod['name'], target_lang)
            prod['specs'] = translate_text(prod['specs'], target_lang)
            prod['category'] = translate_text(prod['category'], target_lang)
        
        processed_products.append(prod)

    return render_template('index.html', products=processed_products, categories=available_categories)

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == "1032491753Outlook*":
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Contraseña incorrecta')
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
        
        # Guardar string separado por comas
        final_images = ",".join(new_urls) if new_urls else ""

        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO products (name, category, specs, price_usd, price_cop, image_urls) VALUES (%s, %s, %s, %s, %s, %s)",
                        (name, category, specs, price_usd, 0, final_images))
            conn.commit()
            cur.close()
            conn.close()
            flash('Producto Guardado Correctamente')

    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)