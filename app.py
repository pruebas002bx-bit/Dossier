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
app.secret_key = 'alpha_super_secret_key'  # Cambia esto en producción

# --- CONFIGURACIÓN ---
# Usa tu URL de base de datos real aquí
DB_URL = os.environ.get("DATABASE_URL", "postgresql://usuario:password@host:port/defaultdb")
IMGBB_API_KEY = "df01bb05ce03159d54c33e1e22eba2cf"
CURRENCY_API_KEY = "1a9b899a5a19988a73d68cde"

# --- CACHÉ MONEDA (Para no gastar peticiones API) ---
currency_cache = { "rate": 4150, "last_updated": 0 }

def get_usd_to_cop_rate():
    """Obtiene la tasa USD -> COP con caché de 1 hora."""
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
    except Exception as e:
        print(f"Error obteniendo tasa cambio: {e}")
        pass
    return currency_cache["rate"]

def get_db_connection():
    """Conexión robusta a PostgreSQL."""
    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Error conectando a DB: {e}")
        return None

def compress_and_upload(file):
    """Comprime imagen y la sube a ImgBB."""
    try:
        image = Image.open(file)
        # Convertir a RGB si es PNG transparente
        if image.mode in ("RGBA", "P"): 
            image = image.convert("RGB")
            
        # Redimensionar si es muy grande (Max 1200px) para optimizar carga
        max_width = 1200
        if image.width > max_width:
            ratio = max_width / float(image.width)
            new_height = int((float(image.height) * float(ratio)))
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

        img_byte_arr = io.BytesIO()
        # Calidad reducida al 50% como solicitaste
        image.save(img_byte_arr, format='JPEG', quality=50, optimize=True)
        img_byte_arr.seek(0)
        
        payload = {'key': IMGBB_API_KEY}
        files = {'image': img_byte_arr}
        response = requests.post("https://api.imgbb.com/1/upload", data=payload, files=files, timeout=15)
        data = response.json()
        if data['success']: 
            return data['data']['url']
    except Exception as e:
        print(f"Error Subida ImgBB: {e}")
    return None

def translate_text(text, target_lang):
    """Traduce texto usando Deep Translator."""
    if target_lang == 'es' or not text: return text
    try:
        lang_map = {'en': 'en', 'pt': 'pt'}
        translator = GoogleTranslator(source='auto', target=lang_map.get(target_lang, 'en'))
        translated = translator.translate(text)
        return translated if translated else text
    except:
        return text

# --- DICCIONARIO UI (Textos fijos de la interfaz) ---
UI_TRANSLATIONS = {
    'es': {
        'offers': 'Ofertas', 'scenarios': 'Escenarios', 'weapons': 'Armas', 
        'kits': 'Kit de Tiro', 'sims': 'Simuladores', 'cart': 'Carrito', 
        'admin': 'Admin', 'contact': 'Contacto', 'details': 'Ver Detalles', 
        'add': 'Añadir al Carrito', 'desc': 'Descripción', 'ship': 'Envíos Certificados',
        'products_title': 'Catálogo General', 'search_ph': 'Buscar productos...',
        'filter_price': 'Filtrar por Precio', 'filter_cat': 'Categorías',
        'stock': 'En Stock', 'sku': 'SKU', 'fbt': 'Frecuentemente comprados juntos'
    },
    'en': {
        'offers': 'Offers', 'scenarios': 'Scenarios', 'weapons': 'Weapons', 
        'kits': 'Shooting Kits', 'sims': 'Simulators', 'cart': 'Cart', 
        'admin': 'Admin', 'contact': 'Contact', 'details': 'View Details', 
        'add': 'Add to Cart', 'desc': 'Description', 'ship': 'Certified Shipping',
        'products_title': 'Product Catalog', 'search_ph': 'Search products...',
        'filter_price': 'Filter by Price', 'filter_cat': 'Categories',
        'stock': 'In Stock', 'sku': 'SKU', 'fbt': 'Frequently bought together'
    },
    'pt': {
        'offers': 'Ofertas', 'scenarios': 'Cenários', 'weapons': 'Armas', 
        'kits': 'Kits de Tiro', 'sims': 'Simuladores', 'cart': 'Carrinho', 
        'admin': 'Admin', 'contact': 'Contato', 'details': 'Ver Detalhes', 
        'add': 'Adicionar', 'desc': 'Descrição', 'ship': 'Envios Certificados',
        'products_title': 'Catálogo de Produtos', 'search_ph': 'Procurar produtos...',
        'filter_price': 'Filtrar por Preço', 'filter_cat': 'Categorias',
        'stock': 'Em Estoque', 'sku': 'SKU', 'fbt': 'Frequentemente comprados juntos'
    }
}

@app.context_processor
def inject_globals():
    """Inyecta variables globales a todas las plantillas."""
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
    
    # Parámetros de filtro desde la URL (Frontend sidebar)
    cat_filter = request.args.get('cat', '').lower()
    search_query = request.args.get('q', '').lower()
    
    if conn:
        try:
            cur = conn.cursor()
            
            # Construcción dinámica de la consulta SQL
            query = "SELECT * FROM products WHERE 1=1"
            params = []
            
            if cat_filter and cat_filter != 'ofertas': # 'ofertas' suele ser un flag, no una categoría exacta
                query += " AND LOWER(category) LIKE %s"
                params.append(f"%{cat_filter}%")
            
            if search_query:
                query += " AND (LOWER(name) LIKE %s OR LOWER(specs) LIKE %s)"
                params.append(f"%{search_query}%", f"%{search_query}%")
                
            query += " ORDER BY id DESC"
            
            cur.execute(query, tuple(params))
            products = cur.fetchall()
            cur.close()
        except Exception as e:
            print(f"Error SQL: {e}")
        finally:
            conn.close()

    cop_rate = get_usd_to_cop_rate()
    target_lang = session.get('lang', 'es')

    # Procesamiento de datos para el Frontend
    processed_products = []
    for p in products:
        # Copia para no modificar el objeto original del cursor si es inmutable
        prod = dict(p)
        
        # Cálculo de precio
        try:
            price_usd = float(prod['price_usd']) if prod['price_usd'] else 0.0
            prod['price_usd'] = price_usd
            prod['price_cop'] = price_usd * cop_rate
        except:
            prod['price_usd'] = 0.0
            prod['price_cop'] = 0.0
        
        # Procesar imágenes (string DB -> lista Python)
        if prod.get('image_urls'):
            prod['images'] = prod['image_urls'].split(',')
        else:
            prod['images'] = [] # Lista vacía si no hay imágenes

        # Traducción (Solo si no es español)
        if target_lang != 'es':
            prod['name'] = translate_text(prod['name'], target_lang)
            prod['specs'] = translate_text(prod['specs'], target_lang)
            prod['category'] = translate_text(prod['category'], target_lang)
            
        processed_products.append(prod)

    return render_template('index.html', products=processed_products)

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        # Contraseña especificada por el usuario
        if request.form['password'] == "1032491753Outlook*":
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Error de contraseña')
    return render_template('login.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('logged_in'): 
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
            name = request.form['name']
            category = request.form['category']
            specs = request.form['specs']
            price_usd = request.form['price_usd']
            
            # Guardar imágenes
            uploaded_files = request.files.getlist('images')
            new_urls = []
            
            # Procesar cada imagen
            for file in uploaded_files:
                if file and file.filename != '':
                    url = compress_and_upload(file)
                    if url: 
                        new_urls.append(url)
            
            # Convertir lista de URLs a string separado por comas para guardar en SQL
            final_images_str = ",".join(new_urls)

            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                # Insertar en base de datos
                cur.execute(
                    "INSERT INTO products (name, category, specs, price_usd, price_cop, image_urls) VALUES (%s, %s, %s, %s, %s, %s)",
                    (name, category, specs, price_usd, 0, final_images_str)
                )
                conn.commit()
                cur.close()
                conn.close()
                flash('Producto Guardado Exitosamente')
        except Exception as e:
            flash(f'Error al guardar: {str(e)}')

    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)