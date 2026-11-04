"""Tarjeta de la primera prueba motriz supervisada. Genera texto para el operador; no ejecuta nada.

El salto y la duración son parámetros de prueba propuestos, no calibración: solo buscan un
movimiento pequeño y lento de la pinza alrededor del pulso que el controlador ya tiene comandado.
"""
import json

from .models import Cell

SLEEP, AUTO_INCREMENT = 0x10, 0x20
PRESCALE_50HZ = 121
PROPOSED_DELTA_US, PROPOSED_DURATION_S = 40, 2.0
SERVICE = "/home/abelbrayan/mindarm_arm.py"


class CardRefused(RuntimeError):
    pass


def _check_service_will_not_write(reading: dict):
    """mindarm_arm.py solo evita escribir al iniciar si el chip ya está a 50 Hz, activo y con autoincremento."""
    if reading["prescale"] != PRESCALE_50HZ:
        raise CardRefused(f"prescale={reading['prescale']}: mindarm_arm.py escribiría registros al iniciar")
    if reading["mode1"] & SLEEP:
        raise CardRefused("SLEEP activo: mindarm_arm.py escribiría registros al iniciar")
    if not reading["mode1"] & AUTO_INCREMENT:
        raise CardRefused("AUTO_INCREMENT apagado: mindarm_arm.py escribiría registros al iniciar")


def build_card(reading: dict, cell: Cell, delta_us: int = PROPOSED_DELTA_US,
               duration_s: float = PROPOSED_DURATION_S) -> dict:
    _check_service_will_not_write(reading)
    pulses = reading["commanded_us"]
    for joint in cell.joints:
        value = pulses[joint]
        low, high = cell.envelope_us[joint]
        if value is None:
            raise CardRefused(f"{joint} está liberado: esta prueba no energiza canales")
        if not low <= value <= high:
            raise CardRefused(f"{joint}: {value} µs fuera de la envolvente [{low}, {high}]")
    low, high = cell.envelope_us["gripper"]
    direction = 1 if pulses["gripper"] <= (low + high) / 2 else -1
    target = pulses["gripper"] + direction * delta_us
    targets = {joint: (target if joint == "gripper" else pulses[joint]) for joint in cell.joints}
    command = {"id": 1, "cmd": "move", "targets": targets, "duration": duration_s}
    return {
        "movement": f"Solo la pinza: de {pulses['gripper']} a {target} µs en {duration_s} s. "
                    "Las otras cinco articulaciones reciben su pulso actual y no se escriben.",
        "speed_us_s": abs(target - pulses["gripper"]) / duration_s,
        "proposed_parameters": "Salto y duración son propuestas de prueba, no calibración; el operador puede reducirlos.",
        "commanded_us": pulses,
        "before": [
            "Retira piezas, manos y cables del recorrido de la pinza.",
            "Identifica el interruptor o conector de la alimentación de los servos y mantén la mano a su alcance.",
            "Sujeta o apoya el brazo si vas a cortar la alimentación: sin par puede caer.",
            "Abre una terminal aparte; ningún otro proceso debe estar usando el PCA9685.",
        ],
        "start_service": f"& 'C:\\Windows\\System32\\OpenSSH\\ssh.exe' -T jetson-usb 'python3 {SERVICE}'",
        "check_first_line": "La primera línea debe tener ok=true y positions idéntico a commanded_us. "
                            "Si difiere, no pegues la orden: cierra con Ctrl+C.",
        "command_line": json.dumps(command),
        "stop": [
            "Parada de software: pulsa Enter en esa terminal. Cualquier línea detiene la rampa y mantiene el último "
            "pulso; no es un paro de emergencia.",
            "Parada física: corta la alimentación de los servos. No está verificada en este montaje.",
        ],
        "after": [
            "Comprueba a simple vista si la pinza se movió en el sentido esperado y anota si abre o cierra.",
            "La respuesta positions es el pulso comandado: no prueba la posición física.",
            "Cierra con Ctrl+C. El servicio mantiene los últimos pulsos: cerrar no corta el par.",
        ],
    }
