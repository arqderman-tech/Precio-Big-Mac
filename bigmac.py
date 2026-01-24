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
# ----------------------------
# CONFIGURACIÓN (editar si hace falta)
# ----------------------------
# Credenciales y destino del email
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# ✅ CAMBIO IMPORTANTE PARA GITHUB ACTIONS:
# En vez de dejar usuario/clave en el código, los leemos desde variables de entorno (Secrets)
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "").strip()
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "").strip()

# Validación simple de secrets (evita que falle raro)
if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
    print("❌ Faltan variables de entorno EMAIL_USER / EMAIL_PASSWORD / EMAIL_RECIPIENT")
    print("👉 Si estás en GitHub Actions: Repo → Settings → Secrets and variables → Actions")
    sys.exit(1)

# Configuración de archivos
MASTER_CSV = "mcdonalds_precios.csv"
REPORT_XLSX = "mcdonalds_reporte.xlsx"
CHART_DIR = "charts_mcdonalds"

# Configuración de APIs (usamos dos productos)
RESTAURANT_ID = "6197a01dc6ad5fd383abd98f"
RESTAURANT_ID_BURGER = "6197a035c6ad5fa5daabdb9f"

# Producto 1: Big Mac Combo (UNIFICADO)
PRODUCTO_1_ID = "26000"
PRODUCTO_1_NOMBRE = "Big Mac Combo"  # <<-- NOMBRE ÚNICO PARA EL COMBO
API_MCD_URL_1 = f"https://api-mcd-ecommerce-ar.appmcdonalds.com/catalog/product/{PRODUCTO_1_ID}/detail?restaurant={RESTAURANT_ID}&area=MOP&outdaypart=true"

# Producto 2: Big Mac Hamburguesa Sola
PRODUCTO_2_ID = "220"
PRODUCTO_2_NOMBRE = "Big Mac solo hamburguesa"
API_MCD_URL_2 = f"https://api-mcd-ecommerce-ar.appmcdonalds.com/catalog/product/{PRODUCTO_2_ID}/detail?restaurant={RESTAURANT_ID_BURGER}&area=MOP&outdaypart=true"

PRODUCTOS_A_RASTREAR = [
    {'id': PRODUCTO_1_ID, 'nombre': PRODUCTO_1_NOMBRE, 'url': API_MCD_URL_1, 'restaurant': RESTAURANT_ID},
    {'id': PRODUCTO_2_ID, 'nombre': PRODUCTO_2_NOMBRE, 'url': API_MCD_URL_2, 'restaurant': RESTAURANT_ID_BURGER}
]

# MODIFICACIÓN CLAVE: Mapeo para unificar nombres históricos del COMBO Big Mac en el CSV
UNIFIED_NAMES = {
    "Big Mac Combo Mediano": PRODUCTO_1_NOMBRE,
    "Big Mac": PRODUCTO_1_NOMBRE,
    # Si ves otros nombres para el combo en tu CSV, agrégalos aquí.
}

# API del Dólar
API_DOLAR_URL = "https://api.comparadolar.ar/usd"

# Crear directorio para gráficos
os.makedirs(CHART_DIR, exist_ok=True)
# ==============================================================================

# --- Funciones de Lógica de Extracción de Precios (McDonald's y Dólar) ---

def obtener_precio_dolar_api(url_api):
    """
    Realiza una solicitud a la API del dólar, busca la cotización de
    Banco Nación y retorna el valor 'ask' (venta).
    """
    print("🔎 Intentando obtener cotización del dólar de la API...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        response = requests.get(url_api, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()

        cotizacion_nacion = next((item for item in data if item.get('slug') == 'banco-nacion'), None)

        if cotizacion_nacion and 'ask' in cotizacion_nacion:
            precio_dolar = float(cotizacion_nacion['ask'])
            print(f"✅ Precio del Dólar Oficial (Banco Nación, Venta - ask) extraído: ${precio_dolar:,.2f} ARS")
            return precio_dolar
        else:
            print("❌ No se pudo encontrar la cotización 'banco-nacion' o el campo 'ask'. Usando 1.0.")
            return 1.0

    except json.JSONDecodeError:
        print("❌ Error al decodificar JSON: La API del dólar devolvió una respuesta no válida.")
        return 1.0

    except requests.exceptions.RequestException as e:
        print(f"❌ Error de conexión al obtener el precio del dólar de la API: {e}. Usando 1.0.")
        return 1.0
    except Exception as e:
        print(f"❌ Error inesperado: {e}. Usando 1.0.")
        return 1.0


def obtener_precio_mcdonalds(url_api, nombre_defecto):
    """
    Llama a la API de McDonald's y extrae el nombre del producto y su precio bruto.
    """
    print(f"🔎 Buscando precio para: {nombre_defecto}...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url_api, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Usamos siempre el nombre descriptivo configurado para evitar ambigüedad.
        nombre = nombre_defecto

        # El precio se busca igual, dividiendo por 100
        precio_ars_int = data.get("price", {}).get("amount", 0) / 100

        if precio_ars_int == 0:
            raise ValueError(f"Precio del producto '{nombre_defecto}' no encontrado o es cero.")

        print(f"✅ Producto '{nombre}' encontrado. Precio en ARS (bruto): ${precio_ars_int:,.2f}")
        return nombre, precio_ars_int

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener el precio de McDonald's para {nombre_defecto}: {e}")
        return None, None
    except ValueError as e:
        print(f"❌ Error en el JSON de McDonald's para {nombre_defecto}: {e}")
        return None, None


# --- Funciones de Data Management (CSV Maestro) ---

def cargar_o_crear_maestro():
    """Carga el DataFrame maestro desde CSV o crea uno nuevo."""
    columnas = ['Fecha', 'Producto', 'Precio_ARS', 'Precio_USD', 'Dolar_ARS']
    if os.path.exists(MASTER_CSV):
        try:
            df = pd.read_csv(MASTER_CSV)
            # Normalizar para que la fecha sea solo el día (hora 00:00:00)
            df['Fecha'] = pd.to_datetime(df['Fecha']).dt.normalize()
            return df
        except Exception as e:
            print(f"⚠️ Error al leer el CSV: {e}. Creando un DataFrame vacío.")
            return pd.DataFrame(columns=columnas)
    else:
        print("📁 Archivo maestro no encontrado. Creando uno nuevo.")
        return pd.DataFrame(columns=columnas)


def unificar_nombres_productos(df, mapping):
    """Aplica un mapeo a la columna 'Producto' para estandarizar nombres históricos y elimina duplicados."""
    print("🧹 Unificando nombres de productos históricos en el DataFrame...")

    df['Producto'] = df['Producto'].astype(str).replace(mapping)

    filas_antes = df.shape[0]
    df = df.drop_duplicates(subset=['Fecha', 'Producto'], keep='first').reset_index(drop=True)

    print(f"✅ Nombres unificados. Filas eliminadas por duplicación: {filas_antes - df.shape[0]}")
    return df


def guardar_datos(df, nombre, precio_ars, dolar_ars):
    """Añade los datos de hoy al maestro si no existe una entrada para la fecha y el producto."""
    now = datetime.now()
    hoy = now.date()

    df_temp = df.copy()
    if not df_temp.empty:
        df_temp['Fecha_Dia'] = df_temp['Fecha'].dt.date
    else:
        df_temp['Fecha_Dia'] = pd.Series([], dtype='object')

    ya_existe = ((df_temp['Fecha_Dia'] == hoy) & (df_temp['Producto'] == nombre)).any()

    if not ya_existe:
        precio_usd = precio_ars / dolar_ars

        fecha_almacenamiento = now.replace(hour=0, minute=0, second=0, microsecond=0)

        nueva_fila = pd.DataFrame([{
            'Fecha': fecha_almacenamiento,
            'Producto': nombre,
            'Precio_ARS': precio_ars,
            'Precio_USD': precio_usd,
            'Dolar_ARS': dolar_ars
        }])

        df_final = pd.concat([df, nueva_fila], ignore_index=True)
        df_final = df_final.sort_values(by=['Fecha', 'Producto']).reset_index(drop=True)

        df_final.to_csv(MASTER_CSV, index=False)
        print(f"💾 Datos de hoy ({hoy}) para '{nombre}' guardados exitosamente.")
        return df_final
    else:
        print(f"ℹ️ Ya existe una entrada para hoy ({hoy}) y para '{nombre}'. No se añade nada.")
        return df


# --- Funciones de Reporte y Análisis (Excel y Gráficos) ---

def generar_reporte_y_graficos(df):
    """Genera el archivo Excel con las pestañas de análisis y los gráficos individuales."""

    if df.shape[0] < 1:
        print("⚠️ No hay suficientes datos para generar el reporte.")
        return None, "No hay datos."

    df = df.sort_values(by=['Fecha', 'Producto']).reset_index(drop=True)

    productos = df['Producto'].unique()

    # Cálculo de Variación (Aplicado por producto)
    df_list = []
    tiene_variacion = False
    for producto in productos:
        df_prod = df[df['Producto'] == producto].copy()

        if df_prod.shape[0] >= 2:
            df_prod['Variacion_ARS'] = df_prod['Precio_ARS'].pct_change() * 100
            df_prod['Variacion_USD'] = df_prod['Precio_USD'].pct_change() * 100
            tiene_variacion = True
        else:
            df_prod['Variacion_ARS'] = None
            df_prod['Variacion_USD'] = None

        df_list.append(df_prod)

    df_con_variacion = pd.concat(df_list, ignore_index=True)
    df_con_variacion = df_con_variacion.sort_values(by=['Fecha', 'Producto']).reset_index(drop=True)

    writer = pd.ExcelWriter(REPORT_XLSX, engine='xlsxwriter')

    # Pestaña 1: Maestro
    df_maestro = df_con_variacion[['Fecha', 'Producto', 'Precio_ARS', 'Precio_USD', 'Dolar_ARS']].copy()
    df_maestro['Fecha'] = df_maestro['Fecha'].dt.strftime('%Y-%m-%d')
    df_maestro.to_excel(writer, sheet_name='1. Maestro ARS USD', index=False)

    # Pestañas de Precios
    df_pivot_ars = df_con_variacion.pivot_table(index='Producto', columns='Fecha', values='Precio_ARS')
    df_pivot_usd = df_con_variacion.pivot_table(index='Producto', columns='Fecha', values='Precio_USD')

    df_ars = df_pivot_ars.copy()
    df_ars.columns = df_ars.columns.strftime('%Y-%m-%d')
    df_ars.reset_index(inplace=True)
    df_ars.insert(1, 'Moneda', 'ARS')
    df_ars.to_excel(writer, sheet_name='2. Precios ARS', index=False)

    df_usd = df_pivot_usd.copy()
    df_usd.columns = df_usd.columns.strftime('%Y-%m-%d')
    df_usd.reset_index(inplace=True)
    df_usd.insert(1, 'Moneda', 'USD')
    df_usd.to_excel(writer, sheet_name='3. Precios USD', index=False)

    if tiene_variacion:
        df_variacion_diaria = df_con_variacion[['Fecha', 'Producto', 'Variacion_ARS', 'Variacion_USD']].dropna(
            subset=['Variacion_ARS', 'Variacion_USD']).copy()
        df_variacion_diaria['Fecha'] = df_variacion_diaria['Fecha'].dt.strftime('%Y-%m-%d')
        df_variacion_diaria['Variacion_ARS'] = df_variacion_diaria['Variacion_ARS'].map('{:.2f}%'.format)
        df_variacion_diaria['Variacion_USD'] = df_variacion_diaria['Variacion_USD'].map('{:.2f}%'.format)
        df_variacion_diaria.to_excel(writer, sheet_name='4. Variacion Diaria', index=False)

        # Variación Mensual y Anual
        df_variaciones = pd.DataFrame(columns=['Periodo', 'Moneda', 'Producto', 'Variacion (%)'])

        for producto in productos:
            df_prod = df_con_variacion[df_con_variacion['Producto'] == producto]

            df_mensual_ars = df_prod.groupby(df_prod['Fecha'].dt.to_period('M'))['Precio_ARS'].last().pct_change().dropna() * 100
            df_mensual_usd = df_prod.groupby(df_prod['Fecha'].dt.to_period('M'))['Precio_USD'].last().pct_change().dropna() * 100

            if not df_mensual_ars.empty:
                df_variaciones.loc[len(df_variaciones)] = ['Mensual', 'ARS', producto, f"{df_mensual_ars.iloc[-1]:.2f}%"]
            if not df_mensual_usd.empty:
                df_variaciones.loc[len(df_variaciones)] = ['Mensual', 'USD', producto, f"{df_mensual_usd.iloc[-1]:.2f}%"]

            df_anual_ars = df_prod.groupby(df_prod['Fecha'].dt.to_period('Y'))['Precio_ARS'].last().pct_change().dropna() * 100
            df_anual_usd = df_prod.groupby(df_prod['Fecha'].dt.to_period('Y'))['Precio_USD'].last().pct_change().dropna() * 100

            if not df_anual_ars.empty:
                df_variaciones.loc[len(df_variaciones)] = ['Anual', 'ARS', producto, f"{df_anual_ars.iloc[-1]:.2f}%"]
            if not df_anual_usd.empty:
                df_variaciones.loc[len(df_variaciones)] = ['Anual', 'USD', producto, f"{df_anual_usd.iloc[-1]:.2f}%"]

        df_variaciones.to_excel(writer, sheet_name='5. Variacion Mensual Anual', index=False)
    else:
        pd.DataFrame().to_excel(writer, sheet_name='4. Variacion Diaria', index=False)
        pd.DataFrame().to_excel(writer, sheet_name='5. Variacion Mensual Anual', index=False)

    writer.close()
    print(f"📄 Archivo Excel de reporte guardado en {REPORT_XLSX}.")

    # --- Generación de Gráficos INDIVIDUALES ---
    sns.set_theme(style="whitegrid")
    imagenes_generadas = []

    for i, producto in enumerate(productos):
        df_prod = df_con_variacion[df_con_variacion['Producto'] == producto].copy()

        nombre_limpio = producto.replace(' ', '_').replace('/', '_').replace('-', '_').lower()

        # 1. Gráfico: Precios Históricos en ARS
        plt.figure(figsize=(10, 6))
        ax = sns.lineplot(x='Fecha', y='Precio_ARS', data=df_prod, marker='o')
        plt.title(f'Precios Históricos: {producto} (ARS)')
        plt.xlabel('Fecha')
        plt.ylabel('Precio ARS')

        if df_prod.shape[0] > 1:
            ymin, ymax = df_prod['Precio_ARS'].min(), df_prod['Precio_ARS'].max()
            escala = 100
            ymin_ajustado = int(ymin // escala * escala)
            ymax_ajustado = int((ymax // escala + 1) * escala)
            ax.set_yticks(range(ymin_ajustado, ymax_ajustado + escala, escala))

        plt.xticks(rotation=45)
        plt.tight_layout()
        chart_file_ars = os.path.join(CHART_DIR, f"{i+1}_{nombre_limpio}_precio_ars.png")
        plt.savefig(chart_file_ars)
        plt.close()
        imagenes_generadas.append({'file': chart_file_ars, 'name': f"Precio Histórico: {producto} (ARS)"})

        # 2. Gráfico: Precios Históricos en USD
        plt.figure(figsize=(10, 6))
        ax = sns.lineplot(x='Fecha', y='Precio_USD', data=df_prod, marker='o')
        plt.title(f'Precios Históricos: {producto} (USD)')
        plt.xlabel('Fecha')
        plt.ylabel('Precio USD')

        if df_prod.shape[0] > 1:
            ymin, ymax = df_prod['Precio_USD'].min(), df_prod['Precio_USD'].max()
            escala_usd = 0.10
            min_tick = int(ymin / escala_usd)
            max_tick = int(ymax / escala_usd) + 1
            ticks = [round(i * escala_usd, 2) for i in range(min_tick, max_tick)]
            ax.set_yticks(ticks)

        plt.xticks(rotation=45)
        plt.tight_layout()
        chart_file_usd = os.path.join(CHART_DIR, f"{i+1}_{nombre_limpio}_precio_usd.png")
        plt.savefig(chart_file_usd)
        plt.close()
        imagenes_generadas.append({'file': chart_file_usd, 'name': f"Precio Histórico: {producto} (USD)"})

        if df_prod.shape[0] >= 2:
            # 3. Variación ARS
            df_variacion_diaria_ars = df_prod[['Fecha', 'Variacion_ARS']].dropna()

            if not df_variacion_diaria_ars.empty:
                plt.figure(figsize=(10, 6))
                ax = sns.barplot(x='Fecha', y='Variacion_ARS', data=df_variacion_diaria_ars,
                                 color=sns.color_palette()[i])
                plt.title(f'Variación Diaria: {producto} (ARS %)')
                plt.xlabel('Fecha')
                plt.ylabel('Variación (%)')

                v_min, v_max = df_variacion_diaria_ars['Variacion_ARS'].min(), df_variacion_diaria_ars['Variacion_ARS'].max()
                escala_var = 0.5
                ticks = [i * escala_var for i in range(int(v_min / escala_var) - 1, int(v_max / escala_var) + 2)]
                ax.set_yticks([round(t, 2) for t in ticks])

                plt.xticks(rotation=45)
                plt.tight_layout()
                chart_file_var_ars = os.path.join(CHART_DIR, f"{i+1}_{nombre_limpio}_variacion_ars.png")
                plt.savefig(chart_file_var_ars)
                plt.close()
                imagenes_generadas.append({'file': chart_file_var_ars, 'name': f"Variación Diaria: {producto} (ARS)"})

            # 4. Variación USD
            df_variacion_diaria_usd = df_prod[['Fecha', 'Variacion_USD']].dropna()

            if not df_variacion_diaria_usd.empty:
                plt.figure(figsize=(10, 6))
                ax = sns.barplot(x='Fecha', y='Variacion_USD', data=df_variacion_diaria_usd,
                                 color=sns.color_palette()[i])
                plt.title(f'Variación Diaria: {producto} (USD %)')
                plt.xlabel('Fecha')
                plt.ylabel('Variación (%)')

                v_min, v_max = df_variacion_diaria_usd['Variacion_USD'].min(), df_variacion_diaria_usd['Variacion_USD'].max()
                escala_var_usd = 0.20
                ticks = [i * escala_var_usd for i in range(int(v_min / escala_var_usd) - 1, int(v_max / escala_var_usd) + 2)]
                ax.set_yticks([round(t, 2) for t in ticks])

                plt.xticks(rotation=45)
                plt.tight_layout()
                chart_file_var_usd = os.path.join(CHART_DIR, f"{i+1}_{nombre_limpio}_variacion_usd.png")
                plt.savefig(chart_file_var_usd)
                plt.close()
                imagenes_generadas.append({'file': chart_file_var_usd, 'name': f"Variación Diaria: {producto} (USD)"})

    print(f"📊 Gráficos guardados en {CHART_DIR}.")
    return imagenes_generadas, "Reporte generado correctamente."


# --- Función de Email ---

def enviar_email(df, imagenes_generadas):
    """Envía el email con el reporte adjunto y gráficos incrustados."""

    msg = MIMEMultipart('related')
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = f"Reporte Automatizado: Precios McDonald's ({datetime.now().strftime('%Y-%m-%d')})"

    # Resumen de datos para el cuerpo del email
    if not df.empty:
        hoy = datetime.now().date()
        df_hoy = df[df['Fecha'].dt.date == hoy].sort_values(by='Producto')

        if not df_hoy.empty:
            resumen_productos = ""
            for index, row in df_hoy.iterrows():
                resumen_productos += f"""
                    <p><strong>{row['Producto']}</strong></p>
                    <ul>
                        <li>Precio ARS: ${row['Precio_ARS']:,.2f}</li>
                        <li>Precio USD: ${row['Precio_USD']:,.2f}</li>
                    </ul>
                """

            ultima_data = df_hoy.iloc[-1]
            resumen_html = f"""
                <h3>Resumen de Datos (Última Entrada: {ultima_data['Fecha'].strftime('%d/%m/%Y')})</h3>
                <p><strong>Dólar Oficial (BN):</strong> ${ultima_data['Dolar_ARS']:,.2f} ARS</p>
                {resumen_productos}
            """
        else:
            resumen_html = "<p>No hay datos nuevos para hoy.</p>"
    else:
        resumen_html = "<p>No hay suficientes datos históricos para mostrar un resumen.</p>"

    # HTML de charts
    html_charts = ""
    for idx, item in enumerate(imagenes_generadas):
        cid_name = f"chart_{idx+1}"
        html_charts += f'''
            <p><strong>{idx+1}. {item['name']}</strong></p>
            <img src="cid:{cid_name}" width="700" height="400">
        '''

    html_body = f"""
    <html>
        <body>
            <h2>Reporte Diario de Precios McDonald's</h2>
            <p><strong>Fecha del Reporte:</strong> {datetime.now().strftime('%d/%m/%Y')}</p>
            <p>Este informe automatizado rastrea el precio de múltiples productos en ARS y USD.</p>

            {resumen_html}

            <p>El archivo adjunto <strong>{REPORT_XLSX}</strong> contiene las pestañas detalladas.</p>

            <h3>Gráficos de Análisis Individual</h3>
            {html_charts}

            <br>
            <p><i>Este correo fue generado automáticamente.</i></p>
        </body>
    </html>
    """
    msg.attach(MIMEText(html_body, 'html'))

    # Adjuntar Excel
    try:
        with open(REPORT_XLSX, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(REPORT_XLSX))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(REPORT_XLSX)}"'
            msg.attach(part)
    except FileNotFoundError:
        print(f"❌ No se pudo adjuntar el archivo {REPORT_XLSX}. Revisar generación.")

    # Incrustar gráficos
    for idx, item in enumerate(imagenes_generadas):
        file_path = item['file']
        cid_name = f"chart_{idx+1}"
        try:
            with open(file_path, 'rb') as fp:
                img = MIMEImage(fp.read())
                img.add_header('Content-ID', f'<{cid_name}>')
                msg.attach(img)
        except FileNotFoundError:
            print(f"❌ No se pudo incrustar el gráfico {file_path}. Revisar generación.")

    # Enviar email
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USER, EMAIL_RECIPIENT, msg.as_string())
        server.quit()
        print(f"\n📧 Reporte enviado exitosamente a {EMAIL_RECIPIENT}.")
    except Exception as e:
        print(f"\n❌ Error al enviar el email. Verifique la contraseña de aplicación (App Password): {e}")


# ==============================================================================
# --- Flujo Principal de Ejecución (Envuelto en main) ---
# ==============================================================================

def main():
    print("=========================================================")
    print("  INICIO DEL RASTREO Y REPORTE AUTOMATIZADO MCDONALD'S")
    print("=========================================================")

    # 1. Obtener cotización del dólar (solo una vez)
    dolar_ars = obtener_precio_dolar_api(API_DOLAR_URL)

    if dolar_ars == 1.0:
        print("\n❌ Falla crítica: No se pudo obtener la cotización del dólar.")
        return

    # 2. Cargar el maestro CSV
    df_maestro = cargar_o_crear_maestro()

    # Unificar nombres
    df_maestro = unificar_nombres_productos(df_maestro, UNIFIED_NAMES)

    df_actualizado = df_maestro.copy()

    # 3. Iterar sobre los productos para obtener precio y guardar
    for producto in PRODUCTOS_A_RASTREAR:
        nombre_producto, precio_ars = obtener_precio_mcdonalds(producto['url'], producto['nombre'])

        if precio_ars is not None:
            df_actualizado = guardar_datos(df_actualizado, nombre_producto, precio_ars, dolar_ars)

    if df_actualizado.shape[0] > 0:
        # 4. Generar Reporte, Análisis y Gráficos
        imagenes, mensaje_reporte = generar_reporte_y_graficos(df_actualizado)

        # 5. Enviar Reporte por Email
        enviar_email(df_actualizado, imagenes)
    else:
        print("\nℹ️ No se pudo recopilar ningún dato para procesar. No se genera reporte ni email.")

    print("\n=========================================================")
    print("                   EJECUCIÓN FINALIZADA")


if __name__ == "__main__":
    main()
