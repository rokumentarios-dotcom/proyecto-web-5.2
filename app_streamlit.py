from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
import sqlite3
import urllib.parse
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import libsql  # <--- Agregada

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS (Nube / Local)
# ==========================================
TURSO_URL = st.secrets.get("TURSO_DATABASE_URL", os.getenv("TURSO_DATABASE_URL", ""))
TURSO_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", os.getenv("TURSO_AUTH_TOKEN", ""))

def obtener_conexion():
    """Retorna una conexión activa a Turso (en la nube) o SQLite (en local)."""
    if TURSO_URL and TURSO_TOKEN:
        return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    else:
        return sqlite3.connect("clientes_streaming.db")
        
def ejecutar_consulta(query, parametros=None):
    """Ejecuta consultas de forma unificada para SQLite local o Turso en la nube."""
    conexion = obtener_conexion()
    if TURSO_URL and TURSO_TOKEN:
        resultado = conexion.execute(query, parametros or [])
        if query.strip().upper().startswith("SELECT"):
            filas = resultado.rows
            columnas = [col.name for col in resultado.columns]
            return pd.DataFrame(filas, columns=columnas)
        else:
            return True
    else:
        if query.strip().upper().startswith("SELECT"):
            df = pd.read_sql(query, conexion, params=parametros)
            conexion.close()
            return df
        else:
            cursor = conexion.cursor()
            cursor.execute(query, parametros or [])
            conexion.commit()
            conexion.close()
            return True

# Configuración de la página
st.set_page_config(
    page_title="FullStream - ClientControl v6.2.2", page_icon="📺", layout="wide"
)

# --- CLASE PARA FORMATEO SEGURO DE VARIABLES ---
class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"

# --- ESTILOS VISUALES GENERALES Y RESPONSIVOS ---
st.markdown("""
    <style>
    html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', Helvetica, Arial, sans-serif;
    }
    
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        width: 100%;
        transition: all 0.2s ease-in-out;
    }
    
    [data-testid="stSidebar"] {
        background-color: #0F172A;
        color: #FFFFFF;
    }
    
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p {
        color: #E2E8F0 !important;
    }

    [data-testid="stSidebar"] [data-testid="stImage"] {
        background-color: #FFFFFF !important;
        padding: 10px !important;
        border-radius: 8px !important;
    }

    /* Adaptación para dispositivos móviles (Smartphones) */
    @media (max-width: 768px) {
        .card-cliente-responsive {
            flex-direction: column !important;
            align-items: flex-start !important;
        }
        .card-derecha-responsive {
            text-align: left !important;
            margin-top: 8px !important;
            min-width: 100% !important;
            border-top: 1px solid #1e293b;
            padding-top: 6px;
        }
        [data-testid="column"] {
            width: 100% !important;
            flex: 100% !important;
            min-width: 100% !important;
            margin-bottom: 5px;
        }
    }
    </style>
""", unsafe_allow_html=True)


# --- BASE DE DATOS Y CONFIGURACIÓN ---
def init_db():
    ejecutar_consulta("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL
        )
    """)

    df_count = ejecutar_consulta("SELECT COUNT(*) FROM usuarios WHERE username = 'admin'")
    if df_count.iloc[0, 0] == 0:
        ejecutar_consulta(
            "INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)",
            ("admin", "admin123", "admin"),
        )

    ejecutar_consulta("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            alias TEXT,
            telefono TEXT NOT NULL,
            servicio TEXT,
            vencimiento DATE,
            notas TEXT,
            mensaje_enviado TEXT DEFAULT 'ninguno',
            creado_por TEXT DEFAULT 'admin'
        )
    """)

    ejecutar_consulta("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATETIME,
            usuario TEXT,
            accion TEXT,
            detalles TEXT
        )
    """)

    try:
        df_info = ejecutar_consulta("PRAGMA table_info(clientes)")
        columnas = df_info["name"].tolist() if "name" in df_info.columns else []
        if "alias" not in columnas:
            ejecutar_consulta("ALTER TABLE clientes ADD COLUMN alias TEXT")
        if "notas" not in columnas:
            ejecutar_consulta("ALTER TABLE clientes ADD COLUMN notas TEXT")
        if "mensaje_enviado" not in columnas:
            ejecutar_consulta(
                "ALTER TABLE clientes ADD COLUMN mensaje_enviado TEXT DEFAULT 'ninguno'"
            )
        if "creado_por" not in columnas:
            ejecutar_consulta(
                "ALTER TABLE clientes ADD COLUMN creado_por TEXT DEFAULT 'admin'"
            )
    except:
        pass

    ejecutar_consulta("""
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            monto REAL NOT NULL,
            fecha_pago DATETIME,
            metodo_pago TEXT NOT NULL,
            meses_renovados INTEGER DEFAULT 1,
            referencia TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE CASCADE
        )
    """)

    ejecutar_consulta("""
        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        )
    """)
    
    msgs = [
        ('msg_vencido', '¡Hola, {nombre}! ⚠️ Te recordamos que tu servicio de {servicio} venció el {vencimiento}.\n\nPara reactivar tu señal y seguir disfrutando del contenido, realiza tu pago y envía tu comprobante por este medio.\n\n💡 ¡Tu cuenta se reactiva al instante!'),
        ('msg_vencido_semana', '¡Hola, {nombre}! 🚨 Notamos que tu servicio de {servicio} lleva más de una semana vencido ({vencimiento}). Si ya no deseas continuar con el servicio, avísanos; de lo contrario, realiza tu pago para liberar tu cuenta permanentemente.'),
        ('msg_hoy', '¡Hola, {nombre}! ⏰ Te recordamos que hoy {vencimiento} vence tu servicio de {servicio}.\n\nPuedes realizar tu renovación en el transcurso del día para mantener tu señal activa sin interrupciones.\n\n📩 Quedamos a la espera de tu comprobante.'),
        ('msg_prox', '¡Hola, {nombre}! 👋 Tu servicio de {servicio} está próximo a vencer ({vencimiento}).\n\nTe enviamos este recordatorio por si deseas realizar tu renovación con anticipación y evitar cortes en tus pantallas.'),
        ('msg_activo_general', '¡Hola, {nombre}! ✨ Te saludamos de FullStream para verificar que todo marche excelente con tu servicio de {servicio} (Vence: {vencimiento}).\n\nEstamos a tus órdenes para cualquier duda o soporte técnico.')
    ]
    for clave, valor in msgs:
        ejecutar_consulta("INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))

init_db()


def registrar_auditoria(usuario, accion, detalles):
    try:
        ejecutar_consulta(
            "INSERT INTO audit_log (fecha, usuario, accion, detalles) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), usuario, accion, detalles)
        )
    except:
        pass


def obtener_config(clave, por_defecto=""):
    df = ejecutar_consulta("SELECT valor FROM config WHERE clave = ?", (clave,))
    if not df.empty and "valor" in df.columns:
        return df["valor"].iloc[0]
    return por_defecto


def guardar_config_db(clave, valor):
    ejecutar_consulta(
        "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
        (clave, valor),
    )


def procesar_renovacion_cliente(fecha_vencimiento_actual_str, meses_pagados):
    try:
        if fecha_vencimiento_actual_str:
            fecha_actual = datetime.strptime(
                fecha_vencimiento_actual_str.split()[0], "%Y-%m-%d"
            )
        else:
            fecha_actual = datetime.now()
    except (ValueError, TypeError):
        fecha_actual = datetime.now()

    hoy_date = datetime.now().date()
    fecha_base = (
        fecha_actual if fecha_actual.date() >= hoy_date else datetime.now()
    )

    nueva_fecha_vencimiento = fecha_base + relativedelta(
        months=int(meses_pagados)
    )

    return nueva_fecha_vencimiento.strftime("%Y-%m-%d")


# --- CONTROL DE SESIÓN ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["usuario"] = ""
    st.session_state["rol"] = ""

params = st.query_params
if not st.session_state["autenticado"] and "sesion_usuario" in params:
    u_url = params.get("sesion_usuario")
    df_user_url = ejecutar_consulta("SELECT username, rol FROM usuarios WHERE username = ?", (u_url,))
    if not df_user_url.empty:
        st.session_state["autenticado"] = True
        st.session_state["usuario"] = df_user_url.iloc[0]["username"]
        st.session_state["rol"] = df_user_url.iloc[0]["rol"]

if not st.session_state["autenticado"]:
    st.title("📺 FULLSTREAM - Iniciar Sesión (v6.2.2)")
    with st.form("form_login"):
        user_input = st.text_input("Usuario")
        pass_input = st.text_input("Contraseña", type="password")
        btn_login = st.form_submit_button("🔑 Entrar al Sistema")

        if btn_login:
            df_login = ejecutar_consulta(
                "SELECT rol FROM usuarios WHERE username = ? AND password = ?",
                (user_input, pass_input),
            )
            if not df_login.empty:
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = user_input
                st.session_state["rol"] = df_login.iloc[0]["rol"]
                st.query_params["sesion_usuario"] = user_input
                registrar_auditoria(user_input, "LOGIN", "Inicio de sesión exitoso")
                st.success("¡Acceso concedido!")
                st.rerun()
            else:
                st.error("❌ Usuario o contraseña incorrectos.")
    st.stop()


usuario_actual = st.session_state["usuario"]
rol_actual = st.session_state["rol"]

# --- BARRA LATERAL ---
with st.sidebar:
    if os.path.exists("logo_fullstream.png"):
        st.image("logo_fullstream.png", use_container_width=True)
    else:
        st.markdown("## 📺 **FULLSTREAM v6.2.2**")
        
    st.markdown("---")
    st.markdown(
        f"👤 **Usuario:** `{usuario_actual}`<br>🛡️ **Rol:** `{rol_actual.upper()}`",
        unsafe_allow_html=True,
    )

    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        registrar_auditoria(usuario_actual, "LOGOUT", "Cierre de sesión")
        st.session_state["autenticado"] = False
        st.session_state["usuario"] = ""
        st.session_state["rol"] = ""
        if "sesion_usuario" in st.query_params:
            del st.query_params["sesion_usuario"]
        st.rerun()

    st.markdown("---")
    st.header("⚙️ Herramientas")

    if st.button("📊 Descargar Respaldo Excel (Clientes)", use_container_width=True):
        try:
            conn = sqlite3.connect("clientes_streaming.db")
            if rol_actual == "admin":
                df_respaldo = pd.read_sql_query(
                    "SELECT id, nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por FROM clientes", 
                    conn
                )
            else:
                df_respaldo = pd.read_sql_query(
                    "SELECT id, nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por FROM clientes WHERE creado_por = ?",
                    conn,
                    params=(usuario_actual,),
                )
            conn.close()
            
            nombre_excel = f"respaldo_clientes_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
            df_respaldo.to_excel(nombre_excel, index=False)
            registrar_auditoria(usuario_actual, "RESPALDO_EXCEL", "Descarga de respaldo Excel")
            
            with open(nombre_excel, "rb") as f_ex:
                st.sidebar.download_button(
                    label="📥 Descargar archivo .xlsx generado",
                    data=f_ex,
                    file_name=nombre_excel,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        except Exception as e:
            st.sidebar.error(f"Error al generar el respaldo de Excel: {e}")

    archivo_subido = st.file_uploader(
        "📤 Importar Clientes (Excel)", type=["xlsx", "xls"]
    )
    if archivo_subido is not None:
        if st.button("🚀 Procesar e Importar", use_container_width=True):
            try:
                df_imp = pd.read_excel(archivo_subido)
                df_imp.columns = [str(c).strip().lower() for c in df_imp.columns]

                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                importados = 0
                duplicados = 0

                for _, row in df_imp.iterrows():
                    nombre = str(
                        row.get(
                            "usuario",
                            row.get("nombre", row.get("cliente", "Sin Nombre")),
                        )
                    ).strip()
                    alias = str(row.get("alias", ""))
                    telefono = str(
                        row.get("teléfono", row.get("telefono", ""))
                    )
                    servicio = str(row.get("servicio", "FULLSTREAM"))
                    vencimiento = str(
                        row.get("vencimiento", str(datetime.now().date()))
                    )[:10]
                    notas = str(row.get("notas", ""))

                    if (
                        pd.notna(telefono)
                        and str(telefono).strip() != ""
                        and str(telefono) != "nan"
                        and nombre != "nan"
                        and nombre != ""
                    ):
                        tel_limpio = "".join(filter(str.isdigit, str(telefono)))
                        tel_referencia = tel_limpio[-10:] if len(tel_limpio) >= 10 else tel_limpio

                        if tel_referencia:
                            cursor.execute(
                                "SELECT id FROM clientes WHERE LOWER(nombre) = LOWER(?) AND telefono LIKE ?", 
                                (nombre, f"%{tel_referencia}")
                            )
                            existe = cursor.fetchone()

                            if not existe:
                                cursor.execute(
                                    "INSERT INTO clientes (nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por) VALUES (?, ?, ?, ?, ?, ?, 'ninguno', ?)",
                                    (
                                        nombre,
                                        alias if alias != "nan" else "",
                                        tel_limpio,
                                        servicio if servicio != "nan" else "FULLSTREAM",
                                        vencimiento if vencimiento != "nan" else str(datetime.now().date()),
                                        notas if notas != "nan" else "",
                                        usuario_actual,
                                    ),
                                )
                                importados += 1
                            else:
                                duplicados += 1

                conn.commit()
                conn.close()
                registrar_auditoria(usuario_actual, "IMPORTAR_EXCEL", f"Importados: {importados}, Duplicados omitidos: {duplicados}")
                st.success(f"✅ ¡Importación completa! Nuevos: {importados} | Omitidos por duplicados (Usuario + Teléfono): {duplicados}")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")

    if st.button("⚙️ Plantillas WhatsApp", use_container_width=True):
        st.session_state["editando_config"] = True

    if st.session_state.get("editando_config", False):
        with st.form("form_config"):
            st.info("💡 Puedes usar comodines como `{nombre}`, `{usuario}`, `{cliente}`, `{servicio}`, `{vencimiento}`, `{telefono}`, `{alias}` y `{notas}`.")
            m_v = st.text_area(
                "Plantilla Vencido", value=obtener_config("msg_vencido")
            )
            m_vs = st.text_area(
                "Plantilla +1 Semana Vencido", value=obtener_config("msg_vencido_semana")
            )
            m_h = st.text_area(
                "Plantilla Vence Hoy", value=obtener_config("msg_hoy")
            )
            m_p = st.text_area(
                "Plantilla Próximo", value=obtener_config("msg_prox")
            )
            m_act = st.text_area(
                "Plantilla Todos los Activos", value=obtener_config("msg_activo_general")
            )
            if st.form_submit_button("Guardar Plantillas"):
                guardar_config_db("msg_vencido", m_v)
                guardar_config_db("msg_vencido_semana", m_vs)
                guardar_config_db("msg_hoy", m_h)
                guardar_config_db("msg_prox", m_p)
                guardar_config_db("msg_activo_general", m_act)
                st.session_state["editando_config"] = False
                registrar_auditoria(usuario_actual, "EDITAR_PLANTILLAS", "Actualización de plantillas de WhatsApp")
                st.success("¡Plantillas actualizadas!")
                st.rerun()

    st.markdown("---")
    st.header("📊 Finanzas y Caja")

    with st.expander("📅 Filtrar Fechas de Finanzas"):
        f_inicio_def = datetime.now().date().replace(day=1)
        f_fin_def = datetime.now().date()
        filtro_fi = st.date_input("Fecha Inicio", value=f_inicio_def)
        filtro_ff = st.date_input("Fecha Fin", value=f_fin_def)

    if st.button("📊 Ver Resumen Financiero", use_container_width=True):
        conn = sqlite3.connect("clientes_streaming.db")
        cursor = conn.cursor()
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        mes_str = datetime.now().strftime("%Y-%m")
        fi_str = filtro_fi.strftime("%Y-%m-%d")
        ff_str = filtro_ff.strftime("%Y-%m-%d")

        if rol_actual == "admin":
            cursor.execute("SELECT SUM(monto) FROM pagos WHERE DATE(fecha_pago) = DATE(?)", (hoy_str,))
            thoy = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT SUM(monto) FROM pagos WHERE strftime('%Y-%m', fecha_pago) = ?", (mes_str,))
            tmes = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT SUM(monto) FROM pagos WHERE DATE(fecha_pago) BETWEEN DATE(?) AND DATE(?)", (fi_str, ff_str))
            trango = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT SUM(monto) FROM pagos")
            thist = cursor.fetchone()[0] or 0.0
        else:
            cursor.execute("SELECT SUM(p.monto) FROM pagos p JOIN clientes c ON p.cliente_id = c.id WHERE c.creado_por = ? AND DATE(p.fecha_pago) = DATE(?)", (usuario_actual, hoy_str))
            thoy = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT SUM(p.monto) FROM pagos p JOIN clientes c ON p.cliente_id = c.id WHERE c.creado_por = ? AND strftime('%Y-%m', p.fecha_pago) = ?", (usuario_actual, mes_str))
            tmes = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT SUM(p.monto) FROM pagos p JOIN clientes c ON p.cliente_id = c.id WHERE c.creado_por = ? AND DATE(p.fecha_pago) BETWEEN DATE(?) AND DATE(?)", (usuario_actual, fi_str, ff_str))
            trango = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT SUM(p.monto) FROM pagos p JOIN clientes c ON p.cliente_id = c.id WHERE c.creado_por = ?", (usuario_actual,))
            thist = cursor.fetchone()[0] or 0.0
        conn.close()

        st.success(f"🟢 Hoy: ${thoy:.2f}")
        st.info(f"🔵 Mes Actual: ${tmes:.2f}")
        st.warning(f"📅 Rango ({fi_str} a {ff_str}): ${trango:.2f}")
        st.markdown(f"🟣 **Histórico:** ${thist:.2f}")

    if st.button("📜 Historial de Pagos", use_container_width=True):
        conn = sqlite3.connect("clientes_streaming.db")
        if rol_actual == "admin":
            df_pagos = pd.read_sql_query(
                "SELECT p.fecha_pago as Fecha, c.nombre as Cliente, p.monto as Monto, p.metodo_pago as Metodo, p.meses_renovados as Meses, p.referencia as Ref, c.creado_por as Operador FROM pagos p JOIN clientes c ON p.cliente_id = c.id ORDER BY p.fecha_pago DESC LIMIT 50",
                conn,
            )
        else:
            df_pagos = pd.read_sql_query(
                "SELECT p.fecha_pago as Fecha, c.nombre as Cliente, p.monto as Monto, p.metodo_pago as Metodo, p.meses_renovados as Meses, p.referencia as Ref FROM pagos p JOIN clientes c ON p.cliente_id = c.id WHERE c.creado_por = ? ORDER BY p.fecha_pago DESC LIMIT 50",
                conn,
                params=(usuario_actual,),
            )
        conn.close()
        st.dataframe(df_pagos)

    if rol_actual == "admin":
        st.markdown("---")
        st.markdown("🛠️ **Admin Global**")

        if os.path.exists("clientes_streaming.db"):
            with open("clientes_streaming.db", "rb") as f:
                st.download_button(
                    label="💾 Descargar Base (.db)",
                    data=f,
                    file_name="fullstream_general.db",
                    mime="application/octet-stream",
                    use_container_width=True,
                )

        db_subida = st.file_uploader(
            "📂 Restaurar Base (.db)", type=["db"]
        )
        if db_subida is not None:
            if st.button(
                "⚠️ Sobrescribir Base Completa", use_container_width=True
            ):
                try:
                    with open("clientes_streaming.db", "wb") as f:
                        f.write(db_subida.getbuffer())
                    registrar_auditoria(usuario_actual, "RESTAURAR_DB", "Restauración de base de datos completa")
                    st.success("¡Base restaurada con éxito!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        with st.expander("📜 Registro de Auditoría (Logs)"):
            conn = sqlite3.connect("clientes_streaming.db")
            df_audit = pd.read_sql_query("SELECT fecha as Fecha, usuario as Usuario, accion as Accion, detalles as Detalles FROM audit_log ORDER BY id DESC LIMIT 100", conn)
            conn.close()
            st.dataframe(df_audit)

        with st.expander("🧹 Limpieza de Duplicados"):
            st.markdown("Elimina automáticamente registros idénticos basándose en la coincidencia exacta de **Usuario + Teléfono** (conserva el más reciente).")
            if st.button("🗑️ Eliminar Clientes Duplicados", use_container_width=True):
                try:
                    conn = sqlite3.connect("clientes_streaming.db")
                    cursor = conn.cursor()
                    
                    cursor.execute("SELECT id, nombre, telefono FROM clientes ORDER BY id DESC")
                    todos_los_clientes = cursor.fetchall()
                    
                    vistos = set()
                    ids_a_eliminar = []
                    
                    for cid, nom, tel in todos_los_clientes:
                        if tel and nom:
                            tel_limpio = "".join(filter(str.isdigit, str(tel)))
                            ref10 = tel_limpio[-10:] if len(tel_limpio) >= 10 else tel_limpio
                            clave_unica = (str(nom).strip().lower(), ref10)
                            
                            if clave_unica in vistos:
                                ids_a_eliminar.append(cid)
                            else:
                                vistos.add(clave_unica)
                                    
                    if ids_a_eliminar:
                        cursor.executemany("DELETE FROM clientes WHERE id = ?", [(i,) for i in ids_a_eliminar])
                        conn.commit()
                        eliminados_total = len(ids_a_eliminar)
                    else:
                        eliminados_total = 0
                        
                    conn.close()
                    registrar_auditoria(usuario_actual, "LIMPIEZA_DUPLICADOS", f"Eliminados {eliminados_total} registros duplicados")
                    st.success(f"¡Limpieza exitosa! Se eliminaron {eliminados_total} registros duplicados (Mismo Usuario y Teléfono).")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al limpiar duplicados: {e}")

        with st.expander("🧹 Limpiar Clientes Huérfanos"):
            st.markdown("Elimina los clientes cuyo operador creador ya no existe en el sistema.")
            if st.button("🗑️ Purgar Clientes de Operadores Borrados", use_container_width=True):
                try:
                    conn = sqlite3.connect("clientes_streaming.db")
                    cursor = conn.cursor()
                    cursor.execute("""
                        DELETE FROM clientes 
                        WHERE creado_por NOT IN (SELECT username FROM usuarios)
                    """)
                    eliminados = cursor.rowcount
                    conn.commit()
                    conn.close()
                    registrar_auditoria(usuario_actual, "PURGAR_HUERFANOS", f"Eliminados {eliminados} clientes huérfanos")
                    st.success(f"¡Se eliminaron {eliminados} registros huérfanos correctamente!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al purgar registros: {e}")

        with st.expander("👥 Operadores y Roles"):
            st.markdown("##### ➕ Crear Cuenta")
            with st.form("form_nuevo_op"):
                nuevo_user = st.text_input("Usuario")
                nuevo_pass = st.text_input("Contraseña", type="password")
                nuevo_rol = st.selectbox("Rol", ["operador", "supervisor", "admin"])
                if st.form_submit_button("Crear"):
                    if nuevo_user and nuevo_pass:
                        try:
                            conn = sqlite3.connect("clientes_streaming.db")
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)",
                                (nuevo_user, nuevo_pass, nuevo_rol),
                            )
                            conn.commit()
                            conn.close()
                            registrar_auditoria(usuario_actual, "CREAR_USUARIO", f"Creado usuario {nuevo_user} con rol {nuevo_rol}")
                            st.success(f"Creado: {nuevo_user} ({nuevo_rol})")
                            st.rerun()
                        except:
                            st.error("El usuario ya existe.")
                    else:
                        st.error("Llena todos los campos.")

            st.markdown("##### ✏️ Editar Cuentas")
            conn = sqlite3.connect("clientes_streaming.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, rol FROM usuarios")
            lista_ops = cursor.fetchall()
            conn.close()

            ops_dict = {f"{op[1]} ({op[2].upper()})": op[0] for op in lista_ops}
            op_seleccionado = st.selectbox(
                "Selecciona cuenta", list(ops_dict.keys())
            )

            if op_seleccionado:
                op_id_sel = ops_dict[op_seleccionado]
                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT username, password, rol FROM usuarios WHERE id = ?",
                    (op_id_sel,),
                )
                u_data = cursor.fetchone()
                conn.close()

                if u_data:
                    with st.form("form_edit_op"):
                        e_user_op = st.text_input(
                            "Usuario", value=u_data[0]
                        )
                        e_pass_op = st.text_input(
                            "Contraseña", value=u_data[1]
                        )
                        e_rol_op = st.selectbox(
                            "Rol",
                            ["admin", "supervisor", "operador"],
                            index=["admin", "supervisor", "operador"].index(u_data[2]) if u_data[2] in ["admin", "supervisor", "operador"] else 2,
                        )

                        c_eo1, c_eo2 = st.columns(2)
                        with c_eo1:
                            if st.form_submit_button("💾 Guardar"):
                                try:
                                    conn = sqlite3.connect(
                                        "clientes_streaming.db"
                                    )
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "UPDATE usuarios SET username = ?, password = ?, rol = ? WHERE id = ?",
                                        (
                                            e_user_op,
                                            e_pass_op,
                                            e_rol_op,
                                            op_id_sel,
                                        ),
                                    )
                                    conn.commit()
                                    conn.close()
                                    registrar_auditoria(usuario_actual, "EDITAR_USUARIO", f"Modificado usuario ID {op_id_sel}")
                                    st.success("¡Actualizado!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        with c_eo2:
                            if st.form_submit_button("🗑️ Borrar"):
                                if u_data[0] == "admin":
                                    st.error("No puedes eliminar al admin principal.")
                                else:
                                    conn = sqlite3.connect(
                                        "clientes_streaming.db"
                                    )
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "DELETE FROM usuarios WHERE id = ?",
                                        (op_id_sel,),
                                    )
                                    conn.commit()
                                    conn.close()
                                    registrar_auditoria(usuario_actual, "BORRAR_USUARIO", f"Eliminado usuario ID {op_id_sel}")
                                    st.success("Eliminado.")
                                    st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("📺 FULLSTREAM - ClientControl (v6.2.2)")
st.markdown("##### Sistema Profesional de Gestión de Suscriptores con CRM Inteligente y Auditoría")

# --- CENTRO DE ENVÍO MASIVO Y MENSAJES GENERALES ---
with st.expander("📢 Centro de Envío Masivo y Mensajes Generales de WhatsApp"):
    tab_masivo, tab_general = st.tabs(["🚀 Envío Masivo por Filtro (Cobros)", "💬 Mensaje General / Anuncios por Servicio"])
    
    with tab_masivo:
        st.markdown("Filtra y genera enlaces rápidos de envío masivo para recordar pagos pendientes según su estado.")
        
        opciones_filtro = [
            "Vencidos (+1 semana)", 
            "Vencidos (General)", 
            "Próximos a vencer (Hoy o 2 días)", 
            "Todos los activos"
        ]

        tipo_masivo = st.selectbox(
            "Filtrar destinatarios masivos por cobro",
            opciones_filtro
        )
        
        # Plantilla automática y fija según el filtro seleccionado
        if tipo_masivo == "Vencidos (+1 semana)":
            plantilla_masiva_editable = obtener_config("msg_vencido_semana")
        elif tipo_masivo == "Vencidos (General)":
            plantilla_masiva_editable = obtener_config("msg_vencido")
        elif tipo_masivo == "Próximos a vencer (Hoy o 2 días)":
            plantilla_masiva_editable = obtener_config("msg_hoy")
        elif tipo_masivo == "Todos los activos":
            plantilla_masiva_editable = obtener_config("msg_activo_general")
        else:
            plantilla_masiva_editable = obtener_config("msg_prox")

        st.text_area(
            "Plantilla asignada para este filtro (configurable en Plantillas WhatsApp):",
            value=plantilla_masiva_editable,
            height=130,
            disabled=True
        )
        
        if st.button("🚀 Generar Enlaces Masivos de Cobro"):
            conn = sqlite3.connect("clientes_streaming.db")
            cursor = conn.cursor()
            if rol_actual == "admin":
                cursor.execute("SELECT id, nombre, alias, telefono, servicio, vencimiento, notas FROM clientes")
            else:
                cursor.execute("SELECT id, nombre, alias, telefono, servicio, vencimiento, notas FROM clientes WHERE creado_por = ?", (usuario_actual,))
            todos_c = cursor.fetchall()
            conn.close()
            
            hoy_dt = datetime.now().date()
            enlaces_generados = 0
            
            st.markdown("---")
            for cid_m, c_nom, c_alias, c_tel, c_serv, c_venc, c_notas in todos_c:
                alias_s = f" ({c_alias})" if c_alias and str(c_alias).strip() != "" and str(c_alias) != "nan" else ""
                nombre_con_alias = f"{c_nom}{alias_s}"
                
                try:
                    fv_d = datetime.strptime(c_venc, "%Y-%m-%d").date()
                    dias_diff = (fv_d - hoy_dt).days
                    
                    incluir = False
                    
                    if tipo_masivo == "Vencidos (+1 semana)" and dias_diff < -7:
                        incluir = True
                    elif tipo_masivo == "Vencidos (General)" and dias_diff < 0:
                        incluir = True
                    elif tipo_masivo == "Próximos a vencer (Hoy o 2 días)" and 0 <= dias_diff <= 2:
                        incluir = True
                    elif tipo_masivo == "Todos los activos":
                        incluir = True
                    
                    if incluir:
                        dict_mapeo = {
                            "nombre": nombre_con_alias,
                            "usuario": nombre_con_alias,
                            "cliente": nombre_con_alias,
                            "servicio": c_serv,
                            "vencimiento": c_venc,
                            "telefono": c_tel,
                            "alias": c_alias if c_alias and str(c_alias) != "nan" else "",
                            "notas": c_notas if c_notas and str(c_notas) != "nan" else ""
                        }
                        
                        msg_final = plantilla_masiva_editable.format_map(SafeDict(dict_mapeo))

                        url_w = f"https://wa.me/{c_tel}?text={urllib.parse.quote(msg_final)}"
                        st.markdown(f"💬 **{nombre_con_alias}** (`{c_tel}` - *{c_serv}*): <a href='{url_w}' target='_blank' style='color: #60A5FA !important;'>Abrir Chat WhatsApp</a>", unsafe_allow_html=True)
                        enlaces_generados += 1
                except Exception as e:
                    pass
                    
            if enlaces_generados == 0:
                st.info("No hay clientes que coincidan con este filtro.")
            else:
                registrar_auditoria(usuario_actual, "ENVIO_MASIVO", f"Generados {enlaces_generados} enlaces de cobro con filtro {tipo_masivo}")
                st.success(f"Se generaron {enlaces_generados} accesos de WhatsApp con éxito.")

    with tab_general:
        st.markdown("Redacta comunicados, avisos de mantenimiento, promociones o anuncios generales y selecciona a qué **Servicio específico** deseas enviárselo.")
        
        conn_serv = sqlite3.connect("clientes_streaming.db")
        cursor_serv = conn_serv.cursor()
        if rol_actual == "admin":
            cursor_serv.execute("SELECT DISTINCT servicio FROM clientes WHERE servicio IS NOT NULL AND servicio != ''")
        else:
            cursor_serv.execute("SELECT DISTINCT servicio FROM clientes WHERE creado_por = ? AND servicio IS NOT NULL AND servicio != ''", (usuario_actual,))
        servicios_disponibles_gen = [s[0] for s in cursor_serv.fetchall()]
        conn_serv.close()

        opciones_alcance = ["Todos los clientes"]
        if servicios_disponibles_gen:
            for s_item in servicios_disponibles_gen:
                opciones_alcance.append(f"Servicio: {s_item}")

        alcance_seleccionado = st.selectbox("Seleccionar alcance o servicio destinatario", opciones_alcance)

        plantilla_general = st.text_area(
            "Mensaje General (Puedes usar comodines como {nombre} o {servicio}):",
            "📢 *AVISO IMPORTANTE*\n\nHola {nombre}, te comunicamos que tu servicio de {servicio} tendrá mantenimiento el día de hoy durante algunas horas. Agradecemos tu comprensión.",
            height=150
        )
        
        if st.button("📤 Generar Enlaces de Anuncio General"):
            conn = sqlite3.connect("clientes_streaming.db")
            cursor = conn.cursor()
            
            if rol_actual == "admin":
                cursor.execute("SELECT nombre, alias, telefono, servicio, vencimiento, notas FROM clientes")
            else:
                cursor.execute("SELECT nombre, alias, telefono, servicio, vencimiento, notas FROM clientes WHERE creado_por = ?", (usuario_actual,))
            clientes_gen = cursor.fetchall()
            conn.close()
            
            st.markdown("---")
            enlaces_gen_count = 0
            for c_nom, c_alias, c_tel, c_serv, c_venc, c_notas in clientes_gen:
                if alcance_seleccionado.startswith("Servicio: "):
                    serv_filtro_exacto = alcance_seleccionado.replace("Servicio: ", "").strip()
                    if str(c_serv).strip().lower() != serv_filtro_exacto.lower():
                        continue

                alias_s = f" ({c_alias})" if c_alias and str(c_alias).strip() != "" and str(c_alias) != "nan" else ""
                nombre_con_alias = f"{c_nom}{alias_s}"
                
                dict_mapeo_gen = {
                    "nombre": nombre_con_alias,
                    "usuario": nombre_con_alias,
                    "cliente": nombre_con_alias,
                    "servicio": c_serv,
                    "vencimiento": c_venc,
                    "telefono": c_tel,
                    "alias": c_alias if c_alias and str(c_alias) != "nan" else "",
                    "notas": c_notas if c_notas and str(c_notas) != "nan" else ""
                }
                
                msg_gen_final = plantilla_general.format_map(SafeDict(dict_mapeo_gen))
                url_g = f"https://wa.me/{c_tel}?text={urllib.parse.quote(msg_gen_final)}"
                st.markdown(f"💬 **{nombre_con_alias}** (`{c_tel}` - *{c_serv}*): <a href='{url_g}' target='_blank' style='color: #60A5FA !important;'>Abrir Comunicado</a>", unsafe_allow_html=True)
                enlaces_gen_count += 1

            if enlaces_gen_count == 0:
                st.info("No se encontraron clientes para el alcance o servicio seleccionado.")
            else:
                registrar_auditoria(usuario_actual, "MENSAJE_GENERAL", f"Generados {enlaces_gen_count} enlaces de difusión general ({alcance_seleccionado})")
                st.success(f"¡Se generaron {enlaces_gen_count} enlaces generales correctamente!")

st.divider()

# --- FORMULARIO DE REGISTRO NUEVO ---
st.subheader("📝 Registrar Nuevo Usuario")

with st.form("form_usuario", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        f_nombre = st.text_input("Usuario *")
        f_telefono = st.text_input("Teléfono (con código de país, ej: 52...) *")
        f_vencimiento = st.text_input(
            "Vencimiento (AAAA-MM-DD)", value=str(datetime.now().date())
        )
    with col2:
        f_alias = st.text_input("Alias")
        f_servicio = st.text_input("Servicio", value="FULLSTREAM")
        f_notas = st.text_input("Notas")

    submitted = st.form_submit_button("💾 Guardar Usuario")
    if submitted:
        if f_nombre and f_telefono and f_vencimiento:
            tel_limpio = "".join(filter(str.isdigit, f_telefono))
            
            if len(tel_limpio) < 10:
                st.error("⚠️ El número de teléfono parece incompleto. Asegúrate de incluir el código de país y área (ej. 5255...).")
            else:
                tel_ref = tel_limpio[-10:]
                
                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT id FROM clientes WHERE LOWER(nombre) = LOWER(?) AND telefono LIKE ?",
                    (f_nombre.strip(), f"%{tel_ref}")
                )
                duplicado_manual = cursor.fetchone()
                
                if duplicado_manual:
                    st.error("⚠️ Ya existe un registro con este mismo nombre de usuario y número de teléfono. Si es otro servicio para el mismo cliente, usa un identificador de usuario diferente (ej. Juan - Netflix).")
                else:
                    cursor.execute(
                        "INSERT INTO clientes (nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por) VALUES (?, ?, ?, ?, ?, ?, 'ninguno', ?)",
                        (
                            f_nombre.strip(),
                            f_alias,
                            tel_limpio,
                            f_servicio,
                            f_vencimiento,
                            f_notas,
                            usuario_actual,
                        ),
                    )
                    conn.commit()
                    registrar_auditoria(usuario_actual, "CREAR_CLIENTE", f"Registrado cliente {f_nombre.strip()} ({f_servicio})")
                    st.success("✅ ¡Usuario guardado correctamente!")
                    st.rerun()
                conn.close()
        else:
            st.error("⚠️ Los campos Usuario, Teléfono y Vencimiento son obligatorios.")

st.divider()

# --- BUSCADOR Y FILTROS ---
c_bus, c_fil = st.columns([2, 1])
with c_bus:
    busqueda = st.text_input(
        "🔍 Buscar por nombre, alias o teléfono", ""
    ).lower()
with c_fil:
    filtro = st.selectbox(
        "Filtrar Estado", ["Todos", "Activos", "Próximos", "Vencidos"]
    )

# --- CARGAR Y FILTRAR CLIENTES SEGÚN ROL ---
conn = sqlite3.connect("clientes_streaming.db")
cursor = conn.cursor()

if rol_actual == "admin":
    cursor.execute(
        "SELECT id, nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por FROM clientes ORDER BY vencimiento ASC"
    )
else:
    cursor.execute(
        "SELECT id, nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por FROM clientes WHERE creado_por = ? ORDER BY vencimiento ASC",
        (usuario_actual,),
    )

filas_raw = cursor.fetchall()
conn.close()

hoy = datetime.now().date()
filas_filtradas = []

for row in filas_raw:
    cid, nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por = row
    alias_str = f" ({alias})" if alias and str(alias).strip() != "" and str(alias) != "nan" else ""
    nombre_con_alias = f"{nombre}{alias_str}"

    if (
        busqueda
        and busqueda not in nombre.lower()
        and (alias and busqueda not in alias.lower())
        and busqueda not in telefono
    ):
        continue

    try:
        fv = datetime.strptime(vencimiento, "%Y-%m-%d").date()
        dias = (fv - hoy).days
        if dias < 0:
            est_filtro = "Vencidos"
        elif dias <= 2:
            est_filtro = "Próximos"
        else:
            est_filtro = "Activos"
    except:
        est_filtro = "Activos"

    if filtro != "Todos" and est_filtro != filtro:
        continue

    filas_filtradas.append(row)

# --- CONFIGURACIÓN Y CÁLCULO DE PAGINACIÓN ---
total_registros = len(filas_filtradas)
por_pagina = 25
total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)

if "pagina_clientes" not in st.session_state:
    st.session_state["pagina_clientes"] = 1

if st.session_state["pagina_clientes"] > total_paginas:
    st.session_state["pagina_clientes"] = total_paginas

inicio_idx = (st.session_state["pagina_clientes"] - 1) * por_pagina
fin_idx = min(inicio_idx + por_pagina, total_registros)
filas_pagina = filas_filtradas[inicio_idx:fin_idx]

st.markdown(f"📋 **Mostrando {total_registros} clientes encontrados** (Paginado de {por_pagina} en {por_pagina})")

for row in filas_pagina:
    cid, nombre, alias, telefono, servicio, vencimiento, notas, mensaje_enviado, creado_por = row
    alias_str = f" ({alias})" if alias and str(alias).strip() != "" and str(alias) != "nan" else ""
    nombre_con_alias = f"{nombre}{alias_str}"

    try:
        fv = datetime.strptime(vencimiento, "%Y-%m-%d").date()
        dias = (fv - hoy).days
        if dias < 0:
            est_txt = "🔴 Vencido"
        elif dias <= 2:
            est_txt = "⚠️ Próximo"
        else:
            est_txt = "🟢 Normal"
    except:
        est_txt = "🟢 Normal"

    op_txt = f" [Op: {creado_por}]" if rol_actual == "admin" else ""
    notas_txt = f" - 📝 {notas}" if notas else ""
    
    mapa_estados_badge = {
        "ninguno": ("⏳ Sin Enviar", "#f97316"),
        "prox": ("✅ WApp Próximo Env.", "#22c55e"),
        "hoy": ("✅ WApp Vence Hoy Env.", "#22c55e"),
        "vencido": ("✅ WApp Vencido Env.", "#22c55e"),
        "semana": ("✅ WApp +1 Sem. Env.", "#22c55e")
    }
    msg_status_badge, msg_badge_color = mapa_estados_badge.get(mensaje_enviado, ("✅ WApp Enviado", "#22c55e"))
    
    st.markdown(f"""
        <div class="card-cliente-responsive" style="background-color: #0b1329; border-left: 4px solid #3b82f6; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
            <div style="overflow: hidden; padding-right: 8px;">
                <span style="font-size: 15px; font-weight: bold; color: #FFFFFF !important;">{nombre_con_alias}</span>
                <span style="font-size: 11px; color: #93c5fd !important;">{op_txt}</span><br>
                <span style="font-size: 13px; color: #cbd5e1 !important;">📞 {telefono} &nbsp;|&nbsp; 📺 {servicio}{notas_txt}</span>
            </div>
            <div class="card-derecha-responsive" style="text-align: right; min-width: 140px;">
                <span style="font-size: 13px; font-weight: bold; color: #FFFFFF !important;">📅 {vencimiento}</span><br>
                <span style="font-size: 12px; font-weight: bold; color: #facc15 !important;">{est_txt}</span><br>
                <span style="font-size: 11px; font-weight: bold; color: {msg_badge_color} !important;">{msg_status_badge}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    col_acc1, col_acc2, col_acc3, col_acc4 = st.columns(4)
    with col_acc1:
        if st.button("💬 WApp", key=f"btn_wapp_menu_{cid}", use_container_width=True):
            st.session_state[f"accion_{cid}"] = "whatsapp"

    with col_acc2:
        if st.button("💲 Pagar", key=f"btn_pago_{cid}", use_container_width=True):
            st.session_state[f"accion_{cid}"] = "pagar"

    with col_acc3:
        if st.button("✏️ Editar", key=f"btn_edit_{cid}", use_container_width=True):
            st.session_state[f"accion_{cid}"] = "editar"

    with col_acc4:
        if st.button("🗑️ Borrar", key=f"btn_del_{cid}", use_container_width=True):
            st.session_state[f"accion_{cid}"] = "borrar"

    # MANEJADOR DE ACCIÓN: WHATSAPP
    if st.session_state.get(f"accion_{cid}") == "whatsapp":
        try:
            fv_d = datetime.strptime(vencimiento, "%Y-%m-%d").date()
            dias_venc = (fv_d - hoy).days
            
            if dias_venc < -7:
                etapa_actual = "semana"
                plantilla_txt = obtener_config("msg_vencido_semana")
            elif dias_venc < 0:
                etapa_actual = "vencido"
                plantilla_txt = obtener_config("msg_vencido")
            elif dias_venc == 0:
                etapa_actual = "hoy"
                plantilla_txt = obtener_config("msg_hoy")
            else:
                etapa_actual = "prox"
                plantilla_txt = obtener_config("msg_prox")
                
            dict_mapeo = {
                "nombre": nombre_con_alias,
                "usuario": nombre_con_alias,
                "cliente": nombre_con_alias,
                "servicio": servicio,
                "vencimiento": vencimiento,
                "telefono": telefono,
                "alias": alias if alias and str(alias) != "nan" else "",
                "notas": notas if notas and str(notas) != "nan" else "",
            }
            mensaje_generado = plantilla_txt.format_map(SafeDict(dict_mapeo))
        except Exception as e:
            etapa_actual = "prox"
            mensaje_generado = f"Hola {nombre_con_alias}, tu servicio de {servicio} vence el {vencimiento}."

        ya_enviado_etapa = (mensaje_enviado == etapa_actual)

        if ya_enviado_etapa:
            st.warning(f"⚠️ Ya se le envió el recordatorio correspondiente a esta etapa (**{etapa_actual.upper()}**). Está inhibido para evitar duplicados.")
            forzar_envio = st.checkbox("🔓 Forzar envío de todas formas", key=f"chk_forzar_{cid}")
        else:
            forzar_envio = True

        if not ya_enviado_etapa or forzar_envio:
            with st.form(key=f"form_wapp_{cid}"):
                texto_personalizado = st.text_area(
                    "Editar mensaje antes de enviar",
                    value=mensaje_generado,
                    height=130,
                    key=f"txt_area_wapp_{cid}"
                )

                c_w1, c_w2 = st.columns(2)
                with c_w1:
                    btn_generar_link = st.form_submit_button("🔗 Generar Enlace Directo")
                with c_w2:
                    btn_cerrar_w = st.form_submit_button("❌ Cerrar")

                if btn_generar_link:
                    conn = sqlite3.connect("clientes_streaming.db")
                    cursor = conn.cursor()
                    cursor.execute("UPDATE clientes SET mensaje_enviado = ? WHERE id = ?", (etapa_actual, cid,))
                    conn.commit()
                    conn.close()
                    registrar_auditoria(usuario_actual, "WHATSAPP_ENLACE", f"Generado enlace WApp para cliente ID {cid} ({etapa_actual})")
                    st.session_state[f"wapp_url_{cid}"] = f"https://wa.me/{telefono}?text={urllib.parse.quote(texto_personalizado)}"
                    st.success("¡Mensaje registrado para esta etapa! Haz clic en el botón de abajo:")
                    st.rerun()

                if btn_cerrar_w:
                    if f"wapp_url_{cid}" in st.session_state:
                        del st.session_state[f"wapp_url_{cid}"]
                    st.session_state[f"accion_{cid}"] = None
                    st.rerun()
        else:
            if st.button("❌ Cerrar Panel", key=f"btn_cerrar_bloqueo_{cid}"):
                st.session_state[f"accion_{cid}"] = None
                st.rerun()

        if f"wapp_url_{cid}" in st.session_state:
            url_final_wa = st.session_state[f"wapp_url_{cid}"]
            st.markdown(f"""
                <div style="margin-top: 10px; margin-bottom: 15px;" id="wa_container_{cid}">
                    <a href="{url_final_wa}" target="_blank" id="wa_btn_{cid}" style="background-color: #25D366; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block;">
                        💬 Abrir WhatsApp Ahora (Confirmar Envío)
                    </a>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("✔️ Marcar como Enviado y Cerrar", key=f"btn_conf_enviado_{cid}"):
                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                cursor.execute("UPDATE clientes SET mensaje_enviado = ? WHERE id = ?", (etapa_actual, cid,))
                conn.commit()
                conn.close()
                if f"wapp_url_{cid}" in st.session_state:
                    del st.session_state[f"wapp_url_{cid}"]
                st.session_state[f"accion_{cid}"] = None
                st.success("¡Mensaje confirmado y registrado como enviado!")
                st.rerun()

    # MANEJADOR DE ACCIÓN: PAGAR
    if st.session_state.get(f"accion_{cid}") == "pagar":
        with st.form(key=f"form_pago_{cid}"):
            st.write(f"💳 Registrar Pago y Renovar para: **{nombre_con_alias}**")
            monto_p = st.number_input("Monto ($)", value=0.0, key=f"m_{cid}")
            metodo_p = st.selectbox(
                "Método de Pago",
                [
                    "Transferencia",
                    "Efectivo",
                    "OXXO",
                    "Mercado Pago",
                    "Otro",
                ],
                key=f"met_{cid}",
            )
            meses_p = st.number_input(
                "Meses a Renovar", value=1, step=1, key=f"mes_{cid}"
            )
            ref_p = st.text_input("Referencia / Folio", key=f"ref_{cid}")

            c_sub1, c_sub2 = st.columns(2)
            with c_sub1:
                btn_conf_pago = st.form_submit_button("✅ Confirmar y Generar WApp")
            with c_sub2:
                btn_canc_pago = st.form_submit_button("❌ Cancelar")

            if btn_conf_pago:
                nueva_f_str = procesar_renovacion_cliente(vencimiento, meses_p)
                fecha_actual_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO pagos (cliente_id, monto, fecha_pago, metodo_pago, meses_renovados, referencia) VALUES (?, ?, ?, ?, ?, ?)",
                    (cid, monto_p, fecha_actual_local, metodo_p, meses_p, ref_p),
                )
                cursor.execute(
                    "UPDATE clientes SET vencimiento = ?, mensaje_enviado = 'prox' WHERE id = ?",
                    (nueva_f_str, cid),
                )
                conn.commit()
                conn.close()

                registrar_auditoria(usuario_actual, "REGISTRAR_PAGO", f"Pago de ${monto_p} registrado para cliente ID {cid} ({meses_p} meses)")

                mensaje_pago_recibido = (
                    f"¡Hola, {nombre_con_alias}! 👋 Hemos recibido exitosamente tu pago de ${monto_p:.2f} por concepto de tu servicio de {servicio}.\n\n"
                    f"📅 Tu cuenta ha sido renovada por {meses_p} mes(es).\n"
                    f"🚀 Tu nueva fecha de vencimiento es el: *{nueva_f_str}*.\n\n"
                    f"¡Muchas gracias por tu preferencia! Disfruta de tu entretenimiento sin interrupciones. 📺✨"
                )

                st.session_state[f"wapp_pago_url_{cid}"] = f"https://wa.me/{telefono}?text={urllib.parse.quote(mensaje_pago_recibido)}"
                st.session_state[f"pago_exitoso_{cid}"] = True
                st.success(f"¡Pago registrado! Nueva fecha: {nueva_f_str}")

            if btn_canc_pago:
                if f"wapp_pago_url_{cid}" in st.session_state:
                    del st.session_state[f"wapp_pago_url_{cid}"]
                if f"pago_exitoso_{cid}" in st.session_state:
                    del st.session_state[f"pago_exitoso_{cid}"]
                st.session_state[f"accion_{cid}"] = None
                st.rerun()

        if st.session_state.get(f"pago_exitoso_{cid}", False) and f"wapp_pago_url_{cid}" in st.session_state:
            url_pago_wa = st.session_state[f"wapp_pago_url_{cid}"]
            st.markdown(f"""
                <div style="margin-top: 10px; margin-bottom: 15px;">
                    <a href="{url_pago_wa}" target="_blank" style="background-color: #25D366; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block;">
                        💬 Enviar Mensaje de Agradecimiento por WhatsApp
                    </a>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("✔️ Cerrar Panel de Pago", key=f"btn_cerrar_pago_def_{cid}"):
                if f"wapp_pago_url_{cid}" in st.session_state:
                    del st.session_state[f"wapp_pago_url_{cid}"]
                if f"pago_exitoso_{cid}" in st.session_state:
                    del st.session_state[f"pago_exitoso_{cid}"]
                st.session_state[f"accion_{cid}"] = None
                st.rerun()

    # MANEJADOR DE ACCIÓN: EDITAR
    if st.session_state.get(f"accion_{cid}") == "editar":
        with st.form(key=f"form_editar_{cid}"):
            st.write(f"✏️ Editando información de: **{nombre_con_alias}**")
            e_nombre = st.text_input("Nombre / Usuario", value=nombre, key=f"en_{cid}")
            e_alias = st.text_input("Alias", value=alias if alias else "", key=f"ea_{cid}")
            e_tel = st.text_input("Teléfono", value=telefono, key=f"et_{cid}")
            e_serv = st.text_input("Servicio", value=servicio, key=f"es_{cid}")
            e_venc = st.text_input("Vencimiento (AAAA-MM-DD)", value=vencimiento, key=f"ev_{cid}")
            e_notas = st.text_input("Notas", value=notas if notas else "", key=f"enotas_{cid}")
            
            opciones_est = ["ninguno", "prox", "hoy", "vencido", "semana"]
            idx_est = opciones_est.index(mensaje_enviado) if mensaje_enviado in opciones_est else 0
            e_enviado = st.selectbox("Estado Etapa WhatsApp", opciones_est, index=idx_est, key=f"eenviado_{cid}")

            if st.form_submit_button("💾 Guardar Cambios"):
                tel_limpio = "".join(filter(str.isdigit, e_tel))
                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE clientes SET nombre = ?, alias = ?, telefono = ?, servicio = ?, vencimiento = ?, notas = ?, mensaje_enviado = ? WHERE id = ?",
                    (e_nombre.strip(), e_alias, tel_limpio, e_serv, e_venc, e_notas, e_enviado, cid),
                )
                conn.commit()
                conn.close()
                registrar_auditoria(usuario_actual, "EDITAR_CLIENTE", f"Actualizado cliente ID {cid} ({e_nombre.strip()})")
                st.session_state[f"accion_{cid}"] = None
                st.success("¡Cliente actualizado!")
                st.rerun()

    # MANEJADOR DE ACCIÓN: BORRAR
    if st.session_state.get(f"accion_{cid}") == "borrar":
        with st.form(key=f"form_borrar_{cid}"):
            st.error(f"⚠️ ¿Estás seguro de eliminar permanentemente a **{nombre_con_alias}**?")
            
            c_del1, c_del2 = st.columns(2)
            with c_del1:
                btn_conf_del = st.form_submit_button("🗑️ Sí, Eliminar Definitivamente")
            with c_del2:
                btn_canc_del = st.form_submit_button("❌ Cancelar")

            if btn_conf_del:
                conn = sqlite3.connect("clientes_streaming.db")
                cursor = conn.cursor()
                cursor.execute("DELETE FROM clientes WHERE id = ?", (cid,))
                conn.commit()
                conn.close()
                registrar_auditoria(usuario_actual, "ELIMINAR_CLIENTE", f"Eliminado cliente ID {cid} ({nombre_con_alias})")
                st.session_state[f"accion_{cid}"] = None
                st.success("Cliente eliminado.")
                st.rerun()
                
            if btn_canc_del:
                st.session_state[f"accion_{cid}"] = None
                st.rerun()

    st.markdown("<div style='margin-bottom: 4px;'></div>", unsafe_allow_html=True)

# --- PAGINACIÓN AL FINAL DE LA LISTA DE CLIENTES ---
if total_paginas > 1:
    st.markdown("---")
    nueva_pagina = st.selectbox(
        "📄 Seleccionar Página de Clientes", 
        range(1, total_paginas + 1), 
        index=st.session_state["pagina_clientes"] - 1,
        format_func=lambda x: f"Página {x} de {total_paginas}",
        key="selector_paginacion_final"
    )
    
    if nueva_pagina != st.session_state["pagina_clientes"]:
        st.session_state["pagina_clientes"] = nueva_pagina
        st.rerun()
