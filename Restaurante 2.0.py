"""
SISTEMA DE RESERVAS DE MESAS (un solo archivo)

Diagrama entidad-relación:
  Usuario (Id PK, Nombre, #Teléfono, Documentación, Otro contacto)
  Reserva (Id PK, Usuario FK, Mesa FK, Comensales, Fecha/hora, Nombre, Observación)
  Mesa    (Id PK, #Mesa, Capacidad, Ubicación)

Flujo: Crear cuenta -> Iniciar sesión -> Formulario de reserva -> Ticket
"""
import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

# =====================================================
#  BASE DE DATOS
# =====================================================
RUTA_DB = Path(__file__).with_name("reservas.db")

MESAS_INICIALES = [  # (#Mesa, Capacidad, Ubicación)
    (1, 2, "Ventana"),
    (2, 4, "Salón"),
    (3, 4, "Terraza"),
    (4, 6, "Salón"),
    (5, 8, "Terraza"),
]


def conectar():
    con = sqlite3.connect(RUTA_DB)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def crear_tablas(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS usuario (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre        TEXT NOT NULL,
        telefono      TEXT NOT NULL,
        documentacion TEXT NOT NULL UNIQUE,
        otro_contacto TEXT,
        sal           TEXT NOT NULL,
        clave_hash    TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS mesa (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        numero    INTEGER NOT NULL UNIQUE,
        capacidad INTEGER NOT NULL,
        ubicacion TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reserva (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id  INTEGER NOT NULL REFERENCES usuario(id),
        mesa_id     INTEGER NOT NULL REFERENCES mesa(id),
        comensales  INTEGER NOT NULL,
        fecha_hora  TEXT NOT NULL,
        nombre      TEXT NOT NULL,
        observacion TEXT
    );
    """)
    if con.execute("SELECT COUNT(*) FROM mesa").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO mesa (numero, capacidad, ubicacion) VALUES (?,?,?)",
            MESAS_INICIALES,
        )
    con.commit()


# =====================================================
#  USUARIOS: crear cuenta e iniciar sesión
# =====================================================
def _hash(clave, sal):
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), 100_000).hex()


def crear_cuenta_db(con, nombre, telefono, documentacion, otro_contacto, clave):
    sal = os.urandom(16).hex()
    try:
        cur = con.execute(
            "INSERT INTO usuario (nombre, telefono, documentacion, otro_contacto, sal, clave_hash) "
            "VALUES (?,?,?,?,?,?)",
            (nombre, telefono, documentacion, otro_contacto, sal, _hash(clave, sal)),
        )
        con.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Ya existe una cuenta con esa documentación.")


def validar_usuario(con, documentacion, clave):
    """Devuelve un dict con el usuario si los datos son correctos, o None."""
    fila = con.execute(
        "SELECT id, nombre, telefono, sal, clave_hash FROM usuario WHERE documentacion = ?",
        (documentacion,),
    ).fetchone()
    if fila is None:
        return None
    id_, nombre, telefono, sal, clave_hash = fila
    if not hmac.compare_digest(_hash(clave, sal), clave_hash):
        return None
    return {"id": id_, "nombre": nombre, "telefono": telefono}


# =====================================================
#  ENTRADAS: pedir y validar datos por consola
# =====================================================
def pedir_texto(mensaje, obligatorio=True):
    while True:
        valor = input(mensaje).strip()
        if valor or not obligatorio:
            return valor
        print("Este campo es obligatorio.")


def pedir_clave(mensaje):
    while True:
        valor = input(mensaje).strip()
        if len(valor) >= 4:
            return valor
        print("La contraseña debe tener al menos 4 caracteres.")


def pedir_entero(mensaje, minimo=1, maximo=None):
    """Acepta '3', '#3' o 'Mesa #3': toma el primer número que encuentre."""
    while True:
        texto = input(mensaje)
        coincidencia = re.search(r"\d+", texto)
        if coincidencia:
            n = int(coincidencia.group())
            if n >= minimo and (maximo is None or n <= maximo):
                return n
        print("Ingresa un número válido.")


def pedir_fecha_hora(mensaje):
    """Pide 'AAAA-MM-DD HH:MM' y no permite fechas pasadas."""
    while True:
        texto = input(mensaje).strip()
        try:
            fecha = datetime.strptime(texto, "%Y-%m-%d %H:%M")
        except ValueError:
            print("Formato inválido. Ejemplo: 2026-10-25 19:30")
            continue
        if fecha < datetime.now():
            print("Esa fecha ya pasó. Elige una fecha futura.")
            continue
        return fecha.strftime("%Y-%m-%d %H:%M")


# =====================================================
#  RESERVAS
# =====================================================
def mesas_disponibles(con, fecha_hora, comensales):
    return con.execute("""
        SELECT id, numero, capacidad, ubicacion FROM mesa
        WHERE capacidad >= ?
          AND id NOT IN (SELECT mesa_id FROM reserva WHERE fecha_hora = ?)
        ORDER BY capacidad, numero
    """, (comensales, fecha_hora)).fetchall()


def crear_reserva(con, usuario_id, mesa_id, comensales, fecha_hora, nombre, observacion):
    cur = con.execute(
        "INSERT INTO reserva (usuario_id, mesa_id, comensales, fecha_hora, nombre, observacion) "
        "VALUES (?,?,?,?,?,?)",
        (usuario_id, mesa_id, comensales, fecha_hora, nombre, observacion),
    )
    con.commit()
    return cur.lastrowid


def mis_reservas(con, usuario_id):
    return con.execute("""
        SELECT r.id, r.fecha_hora, r.nombre, m.numero, m.ubicacion, r.comensales
        FROM reserva r JOIN mesa m ON m.id = r.mesa_id
        WHERE r.usuario_id = ?
        ORDER BY r.fecha_hora
    """, (usuario_id,)).fetchall()


# =====================================================
#  TICKET
# =====================================================
def generar_ticket(con, reserva_id, usuario_id):
    fila = con.execute("""
        SELECT r.id, r.nombre, r.fecha_hora, r.comensales, r.observacion,
               m.numero, m.ubicacion, u.telefono
        FROM reserva r
        JOIN mesa m    ON m.id = r.mesa_id
        JOIN usuario u ON u.id = r.usuario_id
        WHERE r.id = ? AND r.usuario_id = ?
    """, (reserva_id, usuario_id)).fetchone()
    if fila is None:
        return None
    rid, nombre, fh, com, obs, mesa, ubic, tel = fila
    linea = "=" * 36
    return (
        f"{linea}\n"
        f"      TICKET DE RESERVA #{rid:05d}\n"
        f"{linea}\n"
        f"Nombre:      {nombre}\n"
        f"Teléfono:    {tel}\n"
        f"Fecha/hora:  {fh}\n"
        f"Comensales:  {com}\n"
        f"Mesa:        #{mesa} ({ubic})\n"
        f"Observación: {obs or '-'}\n"
        f"{linea}"
    )


# =====================================================
#  OPCIONES DEL MENÚ
# =====================================================
def opcion_crear_cuenta(con):
    print("\n--- Crear cuenta (llenar datos) ---")
    nombre = pedir_texto("Nombre: ")
    telefono = pedir_texto("#Teléfono: ")
    documentacion = pedir_texto("Documentación: ")
    otro = pedir_texto("Otro contacto (Enter para omitir): ", obligatorio=False)
    clave = pedir_clave("Contraseña: ")
    if clave != pedir_clave("Repite la contraseña: "):
        print("Las contraseñas no coinciden.")
        return
    try:
        crear_cuenta_db(con, nombre, telefono, documentacion, otro, clave)
        print("Cuenta creada. Ahora inicia sesión (opción 2).")
    except ValueError as e:
        print(e)


def opcion_iniciar_sesion(con):
    print("\n--- Iniciar sesión ---")
    documentacion = pedir_texto("Documentación: ")
    clave = pedir_clave("Contraseña: ")
    usuario = validar_usuario(con, documentacion, clave)
    if usuario is None:
        print("Documentación o contraseña incorrecta.")
    else:
        print(f"Bienvenido, {usuario['nombre']}.")
    return usuario


def opcion_formulario_reserva(con, usuario):
    print("\n--- Formulario de reserva ---")
    fecha_hora = pedir_fecha_hora("Fecha/hora (AAAA-MM-DD HH:MM): ")
    nombre = pedir_texto(f"Nombre [{usuario['nombre']}]: ", obligatorio=False) or usuario["nombre"]
    comensales = pedir_entero("Comensales: ", maximo=20)
    observacion = pedir_texto("Observación (Enter para omitir): ", obligatorio=False)

    libres = mesas_disponibles(con, fecha_hora, comensales)
    if not libres:
        print("No hay mesas disponibles para esa fecha/hora y cantidad de personas.")
        return
    print("\nMesas disponibles:")
    for _id, numero, capacidad, ubicacion in libres:
        print(f"  Mesa #{numero} - capacidad {capacidad} - {ubicacion}")
    numeros = {m[1]: m[0] for m in libres}
    while True:
        elegida = pedir_entero("Número de mesa: ")
        if elegida in numeros:
            break
        print("Esa mesa no está en la lista de disponibles.")

    rid = crear_reserva(con, usuario["id"], numeros[elegida], comensales,
                        fecha_hora, nombre, observacion)
    print("\n" + generar_ticket(con, rid, usuario["id"]))


def opcion_ver_reservas(con, usuario):
    lista = mis_reservas(con, usuario["id"])
    print("\n--- Mis reservas ---")
    if not lista:
        print("Aún no tienes reservas.")
        return
    for rid, fh, nombre, mesa, ubic, com in lista:
        print(f"#{rid:05d} | {fh} | {nombre} | Mesa {mesa} ({ubic}) | {com} personas")
    texto = input("\nN.º de reserva para ver el ticket (Enter para volver): ").strip()
    if texto.isdigit():
        t = generar_ticket(con, int(texto), usuario["id"])
        print("\n" + (t or "No encontré esa reserva entre las tuyas."))


def mostrar_menu(usuario):
    print("\n" + "=" * 40)
    if usuario:
        print(f"Sesión: {usuario['nombre']}")
    print("1. Crear Cuenta")
    print("2. Iniciar Sesión")
    print("3. Llenar Formulario de Reserva")
    print("4. Ver Mis Reservas")
    print("5. Cerrar Sesión")
    print("6. Salir")


# =====================================================
#  PROGRAMA PRINCIPAL
# =====================================================
def main():
    con = conectar()
    crear_tablas(con)
    usuario = None
    while True:
        mostrar_menu(usuario)
        opcion = input("Seleccione una opción (1-6): ").strip()
        if opcion == "1":
            opcion_crear_cuenta(con)
        elif opcion == "2":
            if usuario:
                print("Ya tienes una sesión abierta. Ciérrala primero (opción 5).")
            else:
                usuario = opcion_iniciar_sesion(con)
        elif opcion in ("3", "4"):
            if usuario is None:
                print("Primero inicia sesión (opción 2).")
            elif opcion == "3":
                opcion_formulario_reserva(con, usuario)
            else:
                opcion_ver_reservas(con, usuario)
        elif opcion == "5":
            print("Sesión cerrada." if usuario else "No hay sesión abierta.")
            usuario = None
        elif opcion == "6":
            print("Hasta pronto.")
            break
        else:
            print("Opción inválida. Escribe un número del 1 al 6.")
    con.close()


if __name__ == "__main__":
    main()