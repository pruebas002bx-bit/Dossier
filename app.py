import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = 'alpha_super_secret_key' # Necesario para sesiones

# CONFIGURACIÓN BASE DE DATOS (Aiven/Render)
# En Render, configurarás la variable de entorno DATABASE_URL
DB_URL = os.environ.get("DATABASE_URL", "postgresql://usuario:password@host:port/defaultdb")

def get_db_connection():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

# --- RUTAS ---

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', products=products)

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form['password']
        # Contraseña solicitada
        if password == "1032491753Outlook*":
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Contraseña incorrecta', 'error')
    return render_template('login.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        specs = request.form['specs']
        image_url = request.form['image_url']
        price_usd = float(request.form['price_usd'])
        
        # Calculo automático de COP (Ejemplo: 1 USD = 4150 COP)
        tasa_cambio = 4150 
        price_cop = price_usd * tasa_cambio

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO products (name, category, specs, price_usd, price_cop, image_url)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, category, specs, price_usd, price_cop, image_url))
        conn.commit()
        cur.close()
        conn.close()
        flash('Producto agregado exitosamente', 'success')
        
    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)