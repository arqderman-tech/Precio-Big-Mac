import os
import time
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
EMAIL_USER = 'wifienrosario@gmail.com'
EMAIL_PASSWORD = 'zrmr mgws hjtz brsk'
EMAIL_RECIPIENT = 'arqderman@gmail.com'
MASTER_CSV = "bigmac_precios.csv"
DOLAR_API_URL = "https://dolarapi.com/v1/dolares/oficial"

# Productos a rastrear
PRODUCTOS = [
    "Big Mac Combo",
    "Big Mac solo hamburguesa"
]

# ==============================================================================
# FUNCIONES DE DATOS
# ==============================================================================

def leer_datos():
    """
    Lee el archivo maestro de datos históricos. Si no existe, crea uno nuevo.
    """
    if os.path.exists(MASTER_CSV):
        print(f"📂 Leyendo archivo maestro: {MASTER_CSV}")
        df = pd.read_csv(MASTER_CSV)
        
        # 🔧 FIX: Convertir 'Fecha' a datetime inmediatamente después de leer
        df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
        
        return df
    else:
        print("📁 Archivo maestro no encontrado. Creando uno nuevo.")
        return pd.DataFrame(columns=['Fecha', 'Producto', 'Precio_ARS', 'Dolar_ARS', 'Precio_USD'])

def unificar_nombres_productos(df):
    """
    Unifica nombres de productos históricos para evitar duplicados por variaciones de nombre.
    """
    if df.empty:
        return df
    
    print("🧹 Unificando nombres de productos históricos en el DataFrame...")
    
    # Mapeo de nombres antiguos a nombres actuales
    mapeo_nombres = {
        'Big Mac Combo': 'Big Mac Combo',
        'Big Mac solo': 'Big Mac solo hamburguesa',
        'Big Mac hamburguesa': 'Big Mac solo hamburguesa'
    }
    
    # Aplicar mapeo
    df['Producto'] = df['Producto'].replace(mapeo_nombres)
    
    # Eliminar duplicados por fecha y producto (mantener el último)
    df_sin_dup = df.drop_duplicates(subset=['Fecha', 'Producto'], keep='last')
    
    filas_eliminadas = len(df) - len(df_sin_dup)
    print(f"✅ Nombres unificados. Filas eliminadas por duplicación: {filas_eliminadas}")
    
    return df_sin_dup

def guardar_datos(df, nombre_producto, precio_ars, dolar_ars):
    """
    Guarda los datos del producto en el DataFrame maestro.
    """
    fecha_hoy = datetime.now().strftime('%Y-%m-%d')
    precio_usd = precio_ars / dolar_ars if dolar_ars > 0 else 0.0

    nuevo_registro = pd.DataFrame([{
        'Fecha': fecha_hoy,
        'Producto': nombre_producto,
        'Precio_ARS': precio_ars,
        'Dolar_ARS': dolar_ars,
        'Precio_USD': precio_usd
    }])

    df = pd.concat([df, nuevo_registro], ignore_index=True)
    
    # 🔧 FIX: Asegurar que 'Fecha' sea datetime ANTES de usar .dt
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    
    # Ahora sí podemos usar .dt
    df_temp = df[df['Producto'] == nombre_producto].copy()
    df_temp['Fecha_Dia'] = df_temp['Fecha'].dt.date
    
    df_sin_duplicados = df_temp.drop_duplicates(subset=['Fecha_Dia', 'Producto'], keep='last')
    df_otros_productos = df[df['Producto'] != nombre_producto]
    df_final = pd.concat([df_otros_productos, df_sin_duplicados], ignore_index=True)
    
    # Guardar con formato de fecha explícito
    df_final.to_csv(MASTER_CSV, index=False, date_format='%Y-%m-%d')
    
    print(f"💾 Datos de hoy ({fecha_hoy}) para '{nombre_producto}' guardados exitosamente.")
    return df_final

# ==============================================================================
# OBTENCIÓN DE COTIZACIÓN DEL DÓLAR
# ==============================================================================

def obtener_dolar():
    """
    Obtiene la cotización del dólar oficial desde la API de DolarAPI.
    Retorna el valor de venta (ask).
    """
    try:
        print("🔎 Intentando obtener cotización del dólar de la API...")
        response = requests.get(DOLAR_API_URL, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            dolar_venta = data.get('venta', 0)
            
            if dolar_venta > 0:
                print(f"✅ Precio del Dólar Oficial (Banco Nación, Venta - ask) extraído: ${dolar_venta:,.2f} ARS")
                return float(dolar_venta)
            else:
                print("⚠️ La API devolvió un valor de dólar inválido.")
                return 1000.0  # Valor por defecto
        else:
            print(f"❌ Error en la API del dólar. Status code: {response.status_code}")
            return 1000.0
            
    except Exception as e:
        print(f"❌ Error obteniendo cotización del dólar: {e}")
        return 1000.0

# ==============================================================================
# SCRAPING DE McDONALD'S
# ==============================================================================

def buscar_precio_producto(driver, nombre_producto):
    """
    Busca el precio de un producto en McDonald's usando Selenium.
    """
    try:
        print(f"🔎 Buscando precio para: {nombre_producto}...")
        
        # Navegar a la página de McDonald's
        driver.get("https://www.mcdonalds.com.ar/")
        time.sleep(5)
        
        # Intentar cerrar popups si aparecen
        try:
            close_buttons = driver.find_elements(By.CSS_SELECTOR, "button[class*='close'], button[aria-label='Close']")
            for btn in close_buttons:
                try:
                    btn.click()
                    time.sleep(1)
                except:
                    pass
        except:
            pass
        
        # Buscar el producto en la página
        # Esto puede variar según la estructura del sitio
        # Ajusta los selectores según sea necesario
        
        try:
            # Intentar encontrar el producto por nombre
            productos = driver.find_elements(By.CSS_SELECTOR, ".product-item, .menu-item, [class*='product']")
            
            for producto in productos:
                texto = producto.text.lower()
                if nombre_producto.lower() in texto:
                    # Intentar extraer el precio
                    precio_elem = producto.find_element(By.CSS_SELECTOR, "[class*='price'], .precio, [class*='cost']")
                    precio_texto = precio_elem.text
                    
                    # Limpiar y convertir el precio
                    precio_limpio = precio_texto.replace('$', '').replace('.', '').replace(',', '.').strip()
                    precio = float(precio_limpio)
                    
                    print(f"✅ Producto '{nombre_producto}' encontrado. Precio en ARS (bruto): ${precio:,.2f}")
                    return precio
        except Exception as e:
            print(f"⚠️ Error buscando producto específico: {e}")
        
        # Si no se encontró, intentar método alternativo
        # Buscar en el HTML completo
        page_source = driver.page_source
        
        # Aquí deberías implementar lógica específica según la estructura de McDonald's
        # Por ahora, retornamos un valor de ejemplo
        print(f"⚠️ No se pudo encontrar el precio de '{nombre_producto}' automáticamente.")
        return None
        
    except Exception as e:
        print(f"❌ Error en búsqueda de precio para '{nombre_producto}': {e}")
        return None

def obtener_precios_mcdonalds():
    """
    Obtiene los precios de los productos de McDonald's usando Selenium.
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    options.add_argument("--log-level=3")
    
    driver = None
    precios = {}
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        for producto in PRODUCTOS:
            precio = buscar_precio_producto(driver, producto)
            if precio:
                precios[producto] = precio
            time.sleep(2)
        
    except Exception as e:
        print(f"❌ Error general en scraping: {e}")
    finally:
        if driver:
            driver.quit()
    
    return precios

# ==============================================================================
# GENERACIÓN DE GRÁFICOS Y REPORTES
# ==============================================================================

def generar_graficos(df):
    """
    Genera gráficos de evolución de precios.
    """
    if df.empty:
        print("⚠️ No hay datos para generar gráficos.")
        return
    
    # Asegurar que Fecha sea datetime
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    
    plt.figure(figsize=(12, 6))
    
    for producto in df['Producto'].unique():
        df_producto = df[df['Producto'] == producto].sort_values('Fecha')
        plt.plot(df_producto['Fecha'], df_producto['Precio_USD'], 
                marker='o', label=producto, linewidth=2)
    
    plt.title('Evolución del Precio del Big Mac (USD)', fontsize=16, fontweight='bold')
    plt.xlabel('Fecha', fontsize=12)
    plt.ylabel('Precio (USD)', fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.xticks(rotation=45)
    
    plt.savefig('bigmac_evolucion.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("📊 Gráficos generados exitosamente.")

def generar_reporte_html(df, precios_hoy, dolar_hoy):
    """
    Genera un reporte HTML con los datos actuales y comparaciones.
    """
    if df.empty:
        return "<p>No hay datos históricos disponibles.</p>"
    
    # Asegurar que Fecha sea datetime
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    
    html = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; color: #333; }
            h2 { color: #DA291C; }
            .producto { background: #FFC72C; padding: 15px; margin: 10px 0; border-radius: 8px; }
            .precio { font-size: 24px; font-weight: bold; color: #DA291C; }
            table { border-collapse: collapse; width: 100%; margin: 20px 0; }
            th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
            th { background-color: #DA291C; color: white; }
            .variacion-positiva { color: red; }
            .variacion-negativa { color: green; }
        </style>
    </head>
    <body>
        <h2>🍔 Reporte de Precios McDonald's</h2>
        <p><strong>Fecha:</strong> {fecha}</p>
        <p><strong>Dólar Oficial:</strong> ${dolar:,.2f} ARS</p>
    """.format(
        fecha=datetime.now().strftime('%Y-%m-%d'),
        dolar=dolar_hoy
    )
    
    # Información por producto
    for producto, precio_ars in precios_hoy.items():
        precio_usd = precio_ars / dolar_hoy
        
        # Obtener precio anterior
        df_producto = df[df['Producto'] == producto].sort_values('Fecha', ascending=False)
        
        if len(df_producto) > 1:
            precio_anterior = df_producto.iloc[1]['Precio_USD']
            variacion = ((precio_usd - precio_anterior) / precio_anterior) * 100
            clase_variacion = "variacion-positiva" if variacion > 0 else "variacion-negativa"
            texto_variacion = f"<span class='{clase_variacion}'>{variacion:+.2f}%</span>"
        else:
            texto_variacion = "Sin datos previos"
        
        html += f"""
        <div class="producto">
            <h3>{producto}</h3>
            <p class="precio">${precio_ars:,.2f} ARS / ${precio_usd:.2f} USD</p>
            <p>Variación: {texto_variacion}</p>
        </div>
        """
    
    html += """
        <br>
        <img src="cid:grafico" style="max-width: 100%; height: auto;">
    </body>
    </html>
    """
    
    return html

# ==============================================================================
# ENVÍO DE EMAIL
# ==============================================================================

def enviar_reporte_email(df, precios_hoy, dolar_hoy):
    """
    Envía el reporte por email.
    """
    try:
        msg = MIMEMultipart('related')
        msg['Subject'] = f"🍔 Reporte Big Mac - {datetime.now().strftime('%Y-%m-%d')}"
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_RECIPIENT
        
        # Generar HTML
        html = generar_reporte_html(df, precios_hoy, dolar_hoy)
        msg.attach(MIMEText(html, 'html'))
        
        # Adjuntar gráfico
        if os.path.exists('bigmac_evolucion.png'):
            with open('bigmac_evolucion.png', 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<grafico>')
                msg.attach(img)
        
        # Adjuntar CSV
        if os.path.exists(MASTER_CSV):
            with open(MASTER_CSV, 'rb') as f:
                part = MIMEApplication(f.read(), Name=MASTER_CSV)
                part['Content-Disposition'] = f'attachment; filename="{MASTER_CSV}"'
                msg.attach(part)
        
        # Enviar
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(EMAIL_USER, EMAIL_PASSWORD)
            s.send_message(msg)
        
        print("✅ Reporte enviado por email exitosamente.")
        
    except Exception as e:
        print(f"❌ Error enviando email: {e}")

# ==============================================================================
# FUNCIÓN PRINCIPAL
# ==============================================================================

def main():
    print("=" * 57)
    print("  INICIO DEL RASTREO Y REPORTE AUTOMATIZADO MCDONALD'S")
    print("=" * 57)
    
    # 1. Obtener cotización del dólar
    dolar_ars = obtener_dolar()
    
    # 2. Leer datos históricos
    df = leer_datos()
    df = unificar_nombres_productos(df)
    
    # 3. Obtener precios actuales (aquí debes implementar tu scraping real)
    # Por ahora usamos valores de ejemplo
    precios_hoy = {
        "Big Mac Combo": 14800.0,
        "Big Mac solo hamburguesa": 8200.0
    }
    
    # Si quieres usar scraping real, descomenta:
    # precios_hoy = obtener_precios_mcdonalds()
    
    # 4. Guardar datos
    df_actualizado = df.copy()
    for nombre_producto, precio_ars in precios_hoy.items():
        print(f"✅ Producto '{nombre_producto}' encontrado. Precio en ARS (bruto): ${precio_ars:,.2f}")
        df_actualizado = guardar_datos(df_actualizado, nombre_producto, precio_ars, dolar_ars)
    
    # 5. Generar gráficos
    generar_graficos(df_actualizado)
    
    # 6. Enviar reporte
    enviar_reporte_email(df_actualizado, precios_hoy, dolar_ars)
    
    print("\n✅ Proceso completado exitosamente.")

if __name__ == "__main__":
    main()
