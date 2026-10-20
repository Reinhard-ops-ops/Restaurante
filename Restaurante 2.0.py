"""
SISTEMA DE RESERVAS DE MESAS (un solo archivo)

Diagrama entidad-relación:
  Usuario (Id PK, Nombre, #Teléfono, Cédula, Otro contacto, Rol)
  Reserva (Id PK, Usuario FK, Mesa FK, Comensales, Fecha/hora, Nombre, Observación)
  Mesa    (Id PK, #Mesa, Capacidad, Ubicación)
"""
import getpass
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
        cedula        TEXT NOT NULL UNIQUE,
        otro_contacto TEXT,
        rol           TEXT NOT NULL DEFAULT 'cliente',
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
        usuario_id  INTEGER NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
        mesa_id     INTEGER NOT NULL REFERENCES mesa(id),
        comensales  INTEGER NOT NULL,
        fecha_hora  TEXT NOT NULL,
        nombre      TEXT NOT NULL,
        observacion TEXT
    );
    """)
    
    # Crear mesas iniciales si está vacía
    if con.execute("SELECT COUNT(*) FROM mesa").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO mesa (numero, capacidad, ubicacion) VALUES (?,?,?)",
            MESAS_INICIALES,
        )
        
    # Crear usuario Administrador por defecto si no existe
    if con.execute("SELECT COUNT(*) FROM usuario WHERE rol = 'admin'").fetchone()[0] == 0:
        sal = os.urandom(16).hex()
        con.execute(
            "INSERT INTO usuario (nombre, telefono, cedula, otro_contacto, rol, sal, clave_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            ("Administrador", "0000000000", "admin", "admin@restaurante.com", "admin", sal, _hash("admin123", sal)),
        )
    con.commit()


# =====================================================
#  SEGURIDAD Y USUARIOS
# =====================================================
def _hash(clave, sal):
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), 100_000).hex()


def crear_cuenta_db(con, nombre, telefono, cedula, otro_contacto, clave, rol="cliente"):
    sal = os.urandom(16).hex()
    try:
        cur = con.execute(
            "INSERT INTO usuario (nombre, telefono, cedula, otro_contacto, rol, sal, clave_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (nombre, telefono, cedula, otro_contacto, rol, sal, _hash(clave, sal)),
        )
        con.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Ya existe una cuenta registrada con esa Cédula.")


def validar_usuario(con, cedula, clave):
    fila = con.execute(
        "SELECT id, nombre, telefono, cedula, otro_contacto, rol, sal, clave_hash FROM usuario WHERE cedula = ?",
        (cedula,),
    ).fetchone()
    if fila is None:
        return None
    id_, nombre, telefono, ced, otro, rol, sal, clave_hash = fila
    if not hmac.compare_digest(_hash(clave, sal), clave_hash):
        return None
    return {
        "id": id_,
        "nombre": nombre,
        "telefono": telefono,
        "cedula": ced,
        "otro_contacto": otro,
        "rol": rol,
    }


def actualizar_usuario_db(con, usuario_id, nombre, telefono, cedula, otro_contacto, clave_nueva=None):
    try:
        if clave_nueva:
            sal = os.urandom(16).hex()
            clave_hash = _hash(clave_nueva, sal)
            con.execute(
                "UPDATE usuario SET nombre=?, telefono=?, cedula=?, otro_contacto=?, sal=?, clave_hash=? WHERE id=?",
                (nombre, telefono, cedula, otro_contacto, sal, clave_hash, usuario_id),
            )
        else:
            con.execute(
                "UPDATE usuario SET nombre=?, telefono=?, cedula=?, otro_contacto=? WHERE id=?",
                (nombre, telefono, cedula, otro_contacto, usuario_id),
            )
        con.commit()
    except sqlite3.IntegrityError:
        raise ValueError("La cédula ingresada ya pertenece a otro usuario.")


def eliminar_cuenta_db(con, usuario_id):
    con.execute("DELETE FROM usuario WHERE id = ?", (usuario_id,))
    con.commit()


# =====================================================
#  ENTRADAS DE DATOS Y UTILIDADES
# =====================================================
def pausar():
    input("\nPresiona Enter para continuar...")


def pedir_texto(mensaje, obligatorio=True):
    while True:
        valor = input(mensaje).strip()
        if valor or not obligatorio:
            return valor
        print("Este campo es obligatorio.")


def pedir_clave(mensaje):
    """Solicita la contraseña usando getpass para ocultar los caracteres."""
    while True:
        valor = getpass.getpass(mensaje).strip()
        if len(valor) >= 4:
            return valor
        print("La contraseña debe tener al menos 4 caracteres.")


def pedir_entero(mensaje, minimo=1, maximo=None):
    while True:
        texto = input(mensaje)
        coincidencia = re.search(r"\d+", texto)
        if coincidencia:
            n = int(coincidencia.group())
            if n >= minimo and (maximo is None or n <= maximo):
                return n
        print("Ingresa un número válido.")


def pedir_fecha_hora(mensaje):
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
#  RESERVAS Y MESA (CRUD)
# =====================================================
def mesas_disponibles(con, fecha_hora, comensales, reserva_id_actual=None):
    return con.execute("""
        SELECT id, numero, capacidad, ubicacion FROM mesa
        WHERE capacidad >= ?
          AND id NOT IN (
              SELECT mesa_id FROM reserva 
              WHERE fecha_hora = ? AND (? IS NULL OR id != ?)
          )
        ORDER BY capacidad, numero
    """, (comensales, fecha_hora, reserva_id_actual, reserva_id_actual)).fetchall()


def crear_reserva(con, usuario_id, mesa_id, comensales, fecha_hora, nombre, observacion):
    cur = con.execute(
        "INSERT INTO reserva (usuario_id, mesa_id, comensales, fecha_hora, nombre, observacion) "
        "VALUES (?,?,?,?,?,?)",
        (usuario_id, mesa_id, comensales, fecha_hora, nombre, observacion),
    )
    con.commit()
    return cur.lastrowid


def actualizar_reserva_db(con, reserva_id, mesa_id, comensales, fecha_hora, nombre, observacion):
    con.execute(
        "UPDATE reserva SET mesa_id=?, comensales=?, fecha_hora=?, nombre=?, observacion=? WHERE id=?",
        (mesa_id, comensales, fecha_hora, nombre, observacion, reserva_id),
    )
    con.commit()


def cancelar_reserva_db(con, reserva_id, usuario_id, es_admin=False):
    if es_admin:
        cur = con.execute("DELETE FROM reserva WHERE id = ?", (reserva_id,))
    else:
        cur = con.execute("DELETE FROM reserva WHERE id = ? AND usuario_id = ?", (reserva_id, usuario_id))
    con.commit()
    return cur.rowcount > 0


def mis_reservas(con, usuario_id):
    return con.execute("""
        SELECT r.id, r.fecha_hora, r.nombre, m.numero, m.ubicacion, r.comensales
        FROM reserva r JOIN mesa m ON m.id = r.mesa_id
        WHERE r.usuario_id = ?
        ORDER BY r.fecha_hora
    """, (usuario_id,)).fetchall()


def generar_ticket(con, reserva_id, usuario_id=None, es_admin=False):
    if es_admin:
        fila = con.execute("""
            SELECT r.id, r.nombre, r.fecha_hora, r.comensales, r.observacion,
                   m.numero, m.ubicacion, u.telefono
            FROM reserva r
            JOIN mesa m    ON m.id = r.mesa_id
            JOIN usuario u ON u.id = r.usuario_id
            WHERE r.id = ?
        """, (reserva_id,)).fetchone()
    else:
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
#  OPCIONES DE USUARIO / PERFIL
# =====================================================
def opcion_ver_informacion_usuario(usuario):
    linea = "=" * 36
    print(f"\n{linea}")
    print("      INFORMACIÓN DEL USUARIO")
    print(linea)
    print(f"Nombre:        {usuario['nombre']}")
    print(f"Teléfono:      {usuario['telefono']}")
    print(f"Cédula:        {usuario['cedula']}")
    print(f"Otro contacto: {usuario['otro_contacto'] or '-'}")
    print(f"Tipo de cuenta:{usuario['rol'].upper()}")
    print(linea)
    pausar()


def opcion_editar_perfil(con, usuario):
    print("\n--- Editar Perfil ---")
    print("Deja el campo vacío si deseas conservar el valor actual.")
    nombre = input(f"Nombre [{usuario['nombre']}]: ").strip() or usuario["nombre"]
    telefono = input(f"Teléfono [{usuario['telefono']}]: ").strip() or usuario["telefono"]
    cedula = input(f"Cédula [{usuario['cedula']}]: ").strip() or usuario["cedula"]
    otro = input(f"Otro contacto [{usuario['otro_contacto'] or 'N/A'}]: ").strip()
    if not otro and usuario["otro_contacto"]:
        otro = usuario["otro_contacto"]

    cambiar_clave = input("¿Deseas cambiar la contraseña? (s/N): ").strip().lower()
    clave_nueva = None
    if cambiar_clave == "s":
        clave_nueva = pedir_clave("Nueva contraseña: ")
        if clave_nueva != pedir_clave("Repite la nueva contraseña: "):
            print("Las contraseñas no coinciden. Edición cancelada.")
            pausar()
            return usuario

    try:
        actualizar_usuario_db(con, usuario["id"], nombre, telefono, cedula, otro, clave_nueva)
        usuario["nombre"] = nombre
        usuario["telefono"] = telefono
        usuario["cedula"] = cedula
        usuario["otro_contacto"] = otro
        print("Perfil actualizado correctamente.")
    except ValueError as e:
        print(f"Error: {e}")
    pausar()
    return usuario


def opcion_borrar_cuenta(con, usuario):
    print("\n--- Borrar Cuenta ---")
    print("¡ATENCIÓN! Se eliminará tu cuenta y TODAS tus reservas asociadas.")
    confirmacion = input("Escribe 'ELIMINAR' para confirmar: ").strip()
    if confirmacion == "ELIMINAR":
        eliminar_cuenta_db(con, usuario["id"])
        print("Tu cuenta ha sido eliminada exitosamente.")
        pausar()
        return None
    print("Operación cancelada.")
    pausar()
    return usuario


# =====================================================
#  OPCIONES DE RESERVAS
# =====================================================
def opcion_formulario_reserva(con, usuario):
    print("\n--- Formulario de Reserva ---")
    fecha_hora = pedir_fecha_hora("Fecha/hora (AAAA-MM-DD HH:MM): ")
    nombre = pedir_texto(f"Nombre del titular [{usuario['nombre']}]: ", obligatorio=False) or usuario["nombre"]
    comensales = pedir_entero("Cantidad de comensales: ", maximo=20)
    observacion = pedir_texto("Observación (Enter para omitir): ", obligatorio=False)

    libres = mesas_disponibles(con, fecha_hora, comensales)
    if not libres:
        print("No hay mesas disponibles para esa fecha/hora y cantidad de personas.")
        pausar()
        return

    print("\nMesas disponibles:")
    for _id, numero, capacidad, ubicacion in libres:
        print(f"  Mesa #{numero} | Capacidad: {capacidad} pers. | Ubicación: {ubicacion}")

    numeros = {m[1]: m[0] for m in libres}
    while True:
        elegida = pedir_entero("Ingrese el número de la mesa elegida: ")
        if elegida in numeros:
            break
        print("Esa mesa no está disponible en la lista.")

    rid = crear_reserva(
        con, usuario["id"], numeros[elegida], comensales, fecha_hora, nombre, observacion
    )
    print("\n¡Reserva exitosa!")
    print(generar_ticket(con, rid, usuario["id"]))
    pausar()


def opcion_ver_reservas(con, usuario):
    print("\n--- Mis Reservas ---")
    lista = mis_reservas(con, usuario["id"])
    if not lista:
        print("Aún no tienes reservas registradas.")
        pausar()
        return

    for rid, fh, nombre, mesa, ubic, com in lista:
        print(f"Ticket #{rid:05d} | {fh} | {nombre} | Mesa #{mesa} ({ubic}) | {com} pers.")

    texto = input("\nIngresa el número de ticket para ver detalles (Enter para volver): ").strip()
    if texto.isdigit():
        t = generar_ticket(con, int(texto), usuario["id"])
        print("\n" + (t or "No se encontró esa reserva entre tus registros."))
    pausar()


def opcion_editar_reserva(con, usuario):
    print("\n--- Editar Reserva ---")
    texto = input("Ingresa el número de ticket de la reserva a editar: ").strip()
    if not texto.isdigit():
        print("Número de ticket inválido.")
        pausar()
        return

    rid = int(texto)
    reserva = con.execute(
        "SELECT id, mesa_id, comensales, fecha_hora, nombre, observacion FROM reserva WHERE id = ? AND usuario_id = ?",
        (rid, usuario["id"]),
    ).fetchone()

    if not reserva:
        print("Reserva no encontrada.")
        pausar()
        return

    _r_id, mesa_id_act, com_act, fh_act, nom_act, obs_act = reserva
    print("Llena los nuevos datos (Enter para conservar el actual):")
    
    fecha_hora = input(f"Fecha/hora [{fh_act}]: ").strip() or fh_act
    nombre = input(f"Nombre [{nom_act}]: ").strip() or nom_act
    
    com_str = input(f"Comensales [{com_act}]: ").strip()
    comensales = int(com_str) if com_str.isdigit() else com_act
    
    observacion = input(f"Observación [{obs_act or '-'}]: ").strip()
    if not observacion and obs_act:
        observacion = obs_act

    libres = mesas_disponibles(con, fecha_hora, comensales, reserva_id_actual=rid)
    if not libres:
        print("No hay mesas disponibles para esos nuevos cambios.")
        pausar()
        return

    print("\nMesas disponibles:")
    for _id, numero, capacidad, ubicacion in libres:
        print(f"  Mesa #{numero} | Capacidad: {capacidad} pers. | Ubicación: {ubicacion}")

    numeros = {m[1]: m[0] for m in libres}
    while True:
        elegida = pedir_entero("Ingrese el número de la mesa elegida: ")
        if elegida in numeros:
            break
        print("Esa mesa no está disponible en la lista.")

    actualizar_reserva_db(con, rid, numeros[elegida], comensales, fecha_hora, nombre, observacion)
    print("\nReserva actualizada exitosamente.")
    print(generar_ticket(con, rid, usuario["id"]))
    pausar()


def opcion_cancelar_reserva(con, usuario):
    print("\n--- Cancelar Reserva ---")
    texto = input("Ingresa el número de ticket a cancelar: ").strip()
    if texto.isdigit():
        rid = int(texto)
        if cancelar_reserva_db(con, rid, usuario["id"]):
            print(f"La reserva #{rid:05d} fue cancelada correctamente.")
        else:
            print("No se pudo cancelar. Verifica que el ticket exista y sea tuyo.")
    else:
        print("Número inválido.")
    pausar()


# =====================================================
#  PANEL DE ADMINISTRADOR
# =====================================================
def menu_administrador(con, admin_usuario):
    while True:
        print("\n" + "=" * 40)
        print("      PANEL DE ADMINISTRACIÓN")
        print("=" * 40)
        print("1. Ver todos los usuarios registrados")
        print("2. Ver todas las reservas registradas")
        print("3. Buscar ticket de reserva por número")
        print("4. Cancelar cualquier reserva")
        print("5. Volver al menú principal")

        opc = input("Seleccione una opción: ").strip()
        if opc == "1":
            print("\n--- USUARIOS REGISTRADOS ---")
            usuarios = con.execute("SELECT id, nombre, telefono, cedula, rol FROM usuario").fetchall()
            for u_id, nom, tel, ced, rol in usuarios:
                print(f"ID: {u_id:03d} | Nombre: {nom} | Tel: {tel} | Cédula: {ced} | Rol: {rol}")
            pausar()
        elif opc == "2":
            print("\n--- TODAS LAS RESERVAS ---")
            reservas = con.execute("""
                SELECT r.id, r.fecha_hora, u.nombre, m.numero, r.comensales
                FROM reserva r
                JOIN usuario u ON u.id = r.usuario_id
                JOIN mesa m ON m.id = r.mesa_id
                ORDER BY r.fecha_hora
            """).fetchall()
            if not reservas:
                print("No hay reservas registradas.")
            for r_id, fh, nom, mesa, com in reservas:
                print(f"Ticket #{r_id:05d} | {fh} | Usuario: {nom} | Mesa #{mesa} | {com} pers.")
            pausar()
        elif opc == "3":
            texto = input("Ingrese el número de ticket: ").strip()
            if texto.isdigit():
                t = generar_ticket(con, int(texto), es_admin=True)
                print("\n" + (t or "Ticket no encontrado."))
            pausar()
        elif opc == "4":
            texto = input("Ingrese el número de ticket a cancelar: ").strip()
            if texto.isdigit():
                if cancelar_reserva_db(con, int(texto), usuario_id=None, es_admin=True):
                    print("Reserva cancelada por el administrador.")
                else:
                    print("No se encontró esa reserva.")
            pausar()
        elif opc == "5":
            break


# =====================================================
#  MENÚS Y FLUJO PRINCIPAL
# =====================================================
def opcion_crear_cuenta(con):
    print("\n--- Crear cuenta ---")
    nombre = pedir_texto("Nombre: ")
    telefono = pedir_texto("Teléfono: ")
    cedula = pedir_texto("Cédula: ")
    otro = pedir_texto("Otro contacto (Enter para omitir): ", obligatorio=False)
    clave = pedir_clave("Contraseña: ")
    if clave != pedir_clave("Repite la contraseña: "):
        print("Las contraseñas no coinciden.")
        pausar()
        return
    try:
        crear_cuenta_db(con, nombre, telefono, cedula, otro, clave)
        print("Cuenta creada con éxito. Ya puedes iniciar sesión.")
    except ValueError as e:
        print(e)
    pausar()


def opcion_iniciar_sesion(con):
    print("\n--- Iniciar Sesión ---")
    cedula = pedir_texto("Cédula: ")
    clave = pedir_clave("Contraseña: ")
    usuario = validar_usuario(con, cedula, clave)
    if usuario is None:
        print("Cédula o contraseña incorrecta.")
        pausar()
    else:
        print(f"\n¡Bienvenido/a, {usuario['nombre']}!")
        pausar()
    return usuario


def mostrar_menu(usuario):
    print("\n" + "=" * 40)
    if usuario:
        print(f"Sesión activa: {usuario['nombre']} ({usuario['rol'].upper()})")
        print("1. Información del usuario")
        print("2. Editar perfil")
        print("3. Borrar cuenta")
        print("4. Llenar Formulario de Reserva")
        print("5. Ver Mis Reservas")
        print("6. Editar Reserva")
        print("7. Cancelar Reserva")
        if usuario["rol"] == "admin":
            print("8. Panel de Administrador")
            print("9. Cerrar Sesión")
            print("10. Salir")
        else:
            print("8. Cerrar Sesión")
            print("9. Salir")
    else:
        print("MENÚ PRINCIPAL")
        print("1. Crear Cuenta")
        print("2. Iniciar Sesión")
        print("3. Salir")


def main():
    con = conectar()
    crear_tablas(con)
    usuario = None

    while True:
        mostrar_menu(usuario)
        opcion = input("Seleccione una opción: ").strip()

        if usuario is None:
            if opcion == "1":
                opcion_crear_cuenta(con)
            elif opcion == "2":
                usuario = opcion_iniciar_sesion(con)
            elif opcion == "3":
                print("Hasta pronto.")
                break
            else:
                print("Opción inválida.")
        else:
            if opcion == "1":
                opcion_ver_informacion_usuario(usuario)
            elif opcion == "2":
                usuario = opcion_editar_perfil(con, usuario)
            elif opcion == "3":
                usuario = opcion_borrar_cuenta(con, usuario)
            elif opcion == "4":
                opcion_formulario_reserva(con, usuario)
            elif opcion == "5":
                opcion_ver_reservas(con, usuario)
            elif opcion == "6":
                opcion_editar_reserva(con, usuario)
            elif opcion == "7":
                opcion_cancelar_reserva(con, usuario)
            elif usuario["rol"] == "admin" and opcion == "8":
                menu_administrador(con, usuario)
            elif (usuario["rol"] == "admin" and opcion == "9") or (usuario["rol"] != "admin" and opcion == "8"):
                print(f"Sesión cerrada. ¡Hasta luego, {usuario['nombre']}!")
                usuario = None
            elif (usuario["rol"] == "admin" and opcion == "10") or (usuario["rol"] != "admin" and opcion == "9"):
                print("Hasta pronto.")
                break
            else:
                print("Opción inválida.")

    con.close()


if __name__ == "__main__":
    main()