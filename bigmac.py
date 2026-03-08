import requests
import json
import os
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
import sys

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "").strip()
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "").strip()

if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
    print("❌ Faltan variables de entorno EMAIL_USER / EMAIL_PASSWORD / EMAIL_RECIPIENT")
    sys.exit(1)

MASTER_CSV = "mcdonalds_precios.csv"
REPORT_XLSX = "mcdonalds_reporte.xlsx"
# Configuración para GitHub Pages
DOCS_DIR = "docs"
CHART_DIR = os.path.join(DOCS_DIR, "charts")
INDEX_HTML = os.path.join(DOCS_DIR, "index.html")

RESTAURANT_ID = "6197a01dc6ad5fd383abd98f"
RESTAURANT_ID_BURGER = "6197a035c6ad5fa5daabdb9f"

PRODUCTO_1_ID = "26000"
PRODUCTO_1_NOMBRE = "Big Mac Combo"
API_MCD_URL_1 = f"https://api-mcd-ecommerce-ar.appmcdonalds.com/catalog/product/{PRODUCTO_1_ID}/detail?restaurant={RESTAURANT_ID}&area=MOP&outdaypart=true"

PRODUCTO_2_ID = "220"
PRODUCTO_2_NOMBRE = "Big Mac solo hamburguesa"
API_MCD_URL_2 = f"https://api-mcd-ecommerce-ar.appmcdonalds.com/catalog/product/{PRODUCTO_2_ID}/detail?restaurant={RESTAURANT_ID_BURGER}&area=MOP&outdaypart=true"

PRODUCTOS_A_RASTREAR = [
    {'id': PRODUCTO_1_ID, 'nombre': PRODUCTO_1_NOMBRE, 'url': API_MCD_URL_1},
    {'id': PRODUCTO_2_ID, 'nombre': PRODUCTO_2_NOMBRE, 'url': API_MCD_URL_2}
]

UNIFIED_NAMES = {
    "Big Mac Combo Mediano": PRODUCTO_1_NOMBRE,
    "Big Mac": PRODUCTO_1_NOMBRE,
}

API_DOLAR_URL = "https://api.comparadolar.ar/usd"

# Asegurar directorios
os.makedirs(CHART_DIR, exist_ok=True)

# ==============================================================================
# LÓGICA DE EXTRACCIÓN
# ==============================================================================

def obtener_precio_dolar_api(url_api):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url_api, headers=headers, timeout=10)
        data = response.json()
        cotizacion = next((item for item in data if item.get('slug') == 'banco-nacion'), None)
        if cotizacion:
            return float(cotizacion['ask'])
        return 1.0
    except Exception as e:
        print(f"❌ Error dólar: {e}")
        return 1.0

def obtener_precio_mcdonalds(url_api, nombre_defecto):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url_api, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        precio = data.get("price", {}).get("amount", 0) / 100
        return nombre_defecto, precio
    except Exception as e:
        print(f"❌ Error MCD {nombre_defecto}: {e}")
        return None, None

def cargar_o_crear_maestro():
    if os.path.exists(MASTER_CSV):
        df = pd.read_csv(MASTER_CSV)
        df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce').dt.normalize()
        return df.dropna(subset=['Fecha'])
    return pd.DataFrame(columns=['Fecha', 'Producto', 'Precio_ARS', 'Precio_USD', 'Dolar_ARS'])

def guardar_datos(df, nombre, precio_ars, dolar_ars):
    hoy = datetime.now().date()
    # Limpieza de nombres históricos
    df['Producto'] = df['Producto'].replace(UNIFIED_NAMES)
    
    ya_existe = ((df['Fecha'].dt.date == hoy) & (df['Producto'] == nombre)).any()
    if not ya_existe:
        nueva_fila = pd.DataFrame([{
            'Fecha': datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            'Producto': nombre,
            'Precio_ARS': precio_ars,
            'Precio_USD': precio_ars / dolar_ars,
            'Dolar_ARS': dolar_ars
        }])
        df = pd.concat([df, nueva_fila], ignore_index=True)
        df.sort_values(by=['Fecha', 'Producto']).to_csv(MASTER_CSV, index=False)
    return df

# ==============================================================================
# REPORTES Y WEB
# ==============================================================================

def generar_reporte_y_visuales(df):
    if df.empty: return [], "Sin datos"
    
    sns.set_theme(style="whitegrid")
    imagenes = []
    productos = df['Producto'].unique()
    
    # Excel
    writer = pd.ExcelWriter(REPORT_XLSX, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Historial', index=False)
    writer.close()

    # Gráficos
    for i, prod in enumerate(productos):
        df_p = df[df['Producto'] == prod].tail(30) # Últimos 30 días para la web
        plt.figure(figsize=(10, 5))
        sns.lineplot(x='Fecha', y='Precio_ARS', data=df_p, marker='o', color='#ffbc0d')
        plt.title(f'Tendencia ARS: {prod}')
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        fname = f"trend_{i}.png"
        fpath = os.path.join(CHART_DIR, fname)
        plt.savefig(fpath)
        plt.close()
        imagenes.append({'file': fpath, 'name': prod})
    
    return imagenes, "OK"

def generar_sitio_web(df, imagenes):
    df_hoy = df[df['Fecha'].dt.date == datetime.now().date()]
    dolar_val = df.iloc[-1]['Dolar_ARS'] if not df.empty else 0
    
    cards = ""
    for prod in df['Producto'].unique():
        ult = df[df['Producto'] == prod].iloc[-1]
        cards += f"""
        <div class="card">
            <h3>{prod}</h3>
            <div class="price">${ult['Precio_ARS']:,.2f} ARS</div>
            <div class="sub-price">U$D {ult['Precio_USD']:,.2f}</div>
        </div>"""

    charts = "".join([f'<div class="chart-box"><h4>{img["name"]}</h4><img src="charts/{os.path.basename(img["file"])}"></div>' for img in imagenes])

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Big Mac Index AR</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/water.css@2/out/water.css">
        <style>
            body {{ max-width: 1000px; margin: auto; background-color: #f8f9fa; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin: 20px 0; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; border-top: 6px solid #db0007; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; }}
            .price {{ font-size: 2.2rem; font-weight: bold; color: #2d3436; }}
            .sub-price {{ color: #636e72; font-size: 1.1rem; }}
            .chart-box {{ background: white; padding: 15px; border-radius: 8px; margin-top: 20px; }}
            img {{ width: 100%; height: auto; border-radius: 4px; }}
            footer {{ text-align: center; margin-top: 50px; font-size: 0.8rem; opacity: 0.6; }}
        </style>
    </head>
    <body>
        <h1>🍔 McDonald's Price Tracker</h1>
        <p>Monitoreo automatizado de precios en Argentina. <strong>Dólar Oficial (BN): ${dolar_val:,.2f}</strong></p>
        <div class="grid">{cards}</div>
        <h2>Histórico (Últimos 30 días)</h2>
        <div class="grid">{charts}</div>
        <footer>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} | Sistema Legacy Curiosities</footer>
    </body>
    </html>"""
    
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)

def enviar_email(df, imagenes):
    # Lógica de email original resumida para el flujo
    msg = MIMEMultipart('related')
    msg['Subject'] = f"Reporte Precios MCD - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'], msg['To'] = EMAIL_USER, EMAIL_RECIPIENT
    msg.attach(MIMEText("Reporte diario actualizado. Ver adjunto y Dashboard.", 'plain'))
    
    try:
        with open(REPORT_XLSX, "rb") as f:
            part = MIMEApplication(f.read(), Name=REPORT_XLSX)
            part['Content-Disposition'] = f'attachment; filename="{REPORT_XLSX}"'
            msg.attach(part)
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USER, EMAIL_RECIPIENT, msg.as_string())
        server.quit()
        print("📧 Email enviado.")
    except Exception as e:
        print(f"❌ Error email: {e}")

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    dolar = obtener_precio_dolar_api(API_DOLAR_URL)
    df = cargar_o_crear_maestro()
    
    for p in PRODUCTOS_A_RASTREAR:
        nombre, precio = obtener_precio_mcdonalds(p['url'], p['nombre'])
        if precio:
            df = guardar_datos(df, nombre, precio, dolar)
    
    imgs, status = generar_reporte_y_visuales(df)
    generar_sitio_web(df, imgs)
    enviar_email(df, imgs)
    print("✅ Proceso finalizado con éxito.")

if __name__ == "__main__":
    main()
    
