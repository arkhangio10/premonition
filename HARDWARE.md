# Hardware y primera prueba física

**Estado actual, 4 de noviembre: el brazo se mueve de forma autónoma desde la terminal.** La suspensión
por vibración del 2 de noviembre se levantó ese mismo día (`motion_hold.cleared_by_operator_20261102.json`).
Desde entonces, el brazo escaneó su alcance y aprendió a agarrar. El 4 de noviembre, a la 01:32, levantó
y soltó la esponja por sí solo. El estado al día está al principio de [STATUS.md](STATUS.md). Lo que
sigue es el registro histórico de la puesta en marcha.

**Estado del 2 de noviembre (histórico): movimientos suspendidos.** El operador informó vibración
sin movimiento esperado. Incidente: `runs/real/calibration/vibration_incident_20261102.json`.

**Estado previo de aproximación, 2 de noviembre:** estabilidad de los primeros pasos de base/codo confirmada;
se guardó APPROACH_BASE_ELBOW_01. Después se avanzó hasta base **1792**, hombro **1372**,
codo **1616**, pitch 1602, roll 1499, pinza 1616 µs. MODE1=33, PRESCALE=121, sin procesos
del brazo; el PCA mantiene los pulsos. La pinza está próxima a la esponja en imagen, abierta,
y Muse ya describe detalle claro. Falta observación lateral de separación/alineación antes
de bajar más. La postura exacta actual aún no está guardada como observada por el operador.
No se ejecutó agarre ni transferencia. Detalle: `runs/real/calibration/transfer_session_20261102.json`.

**Estado anterior de primeros pasos de base/codo, 2 de noviembre:** el operador confirmó base fija, esponja colocada y zonas
despejadas. Se probaron por separado base y codo, 60 µs en 4 s cada uno, con la pinza elevada.
Lectura actual: base **1558**, hombro **1372**, codo **1558**, pitch 1602, roll 1499, pinza
1616 µs. MODE1=33, PRESCALE=121, sin procesos del brazo y pulsos mantenidos por el PCA.
Imágenes y máscaras SAM respaldan desplazamiento visible; falta la observación del operador
sobre estabilidad y ruido de esos dos pasos. No se ejecutó agarre ni transferencia.
Sesión: `runs/real/calibration/transfer_session_20261102.json`.

**Estado anterior de primera aproximación, 2 de noviembre:** base fijada a la mesa según el operador. Primera prueba del
hombro ampliada a 1370 µs en 4 s, lectura final **1372 µs**, desplazamiento visible y movimiento
suave/estable confirmado. Se guardó **APPROACH_SHOULDER_01**. Los otros registros siguen en
base 1499, codo 1499, pitch 1602, roll 1499 y pinza 1616 µs. MODE1=33, PRESCALE=121, sin
procesos del brazo; el PCA mantiene las salidas. La siguiente aproximación espera que el
operador coloque la esponja y despeje las zonas marcadas. Sin agarre ni transferencia.
Sesión: `runs/real/calibration/transfer_session_20261102.json`.

**Estado previo de vista de pinza, 2 de noviembre:** tras restaurar HOME y mejorar la vista con movimientos
supervisados, se devolvió roll a 1499 µs y se abrió la pinza a 1616 µs. El operador confirmó
estabilidad. Lectura final MODE1=33, PRESCALE=121; base 1499, hombro 1450, codo 1499,
pitch 1602, roll 1499 y pinza 1616 µs. Coincide con GRIPPER_OPEN_PROBE; OBSERVE_C922 conserva
su HOME anterior. No quedan procesos del brazo y el PCA mantiene los pulsos con los servos
alimentados. Parada identificada: desenchufar la fuente externa de los servos de la
corriente; no se probó el corte. No hay ruta de transferencia validada. Resultado:
`runs/real/calibration/visibility_session_20261102.json`.

**Vídeo y visión, última comprobación:** `/calibration` ofrece vídeo real 1280×720 a unos
8 fps mediante **Go live**. El análisis pausa el vídeo y usa una foto nueva 1920×1080.
Muse propuso una región de las mordazas y SAM devolvió una máscara parcial de sus puntas;
el resultado se identifica como guiado por modelo, sin validar apertura útil o agarre.
La esponja se detectó por nombre. No hay seguimiento continuo ni transformación cámara-robot.

**Comprobación inicial de cámara, 2 de noviembre:** Logitech C922 Pro Stream reconocida por UVC
en `/dev/video0`. Captura real MJPEG 1920×1080 y enfoque manual comprobados;
ajuste actual `focus_auto=0`, `focus_absolute=30`. Tres fotos consecutivas
mostradas correctamente en `/calibration`. El encuadre actual incluye el brazo
completo y la mesa. No se ordenó ningún movimiento ni se accedió al controlador
del brazo durante esta prueba. El ajuste de foco es de la sesión actual y puede
necesitar restablecerse al reconectar la cámara. La calibración de visión sigue
pendiente. Evidencia en `inspection/c922-interface-final.png`.

**Comprobación anterior de cámara, 1 de noviembre:** roll quedó en 1655 µs tras dos pequeños giros
para observar la pinza. La pinza volvió a 1499 µs y pitch se restauró a 1602 µs;
base 1499, hombro 1450 y codo 1499 µs. No quedan procesos del brazo y el PCA conserva
los pulsos. Muse Spark analizó tres fotos reales con su contexto, pero dejó la
verificación de vista y cierre como incierta por el desenfoque. No se guardó esta
vista como pose humana validada. Detalle en [CALIBRATION_SESSION.md](CALIBRATION_SESSION.md).

**Actualización posterior del 1 de noviembre:** se inicializó HOME con confirmación
del operador y se registró su pose observada. MODE1=33, PRESCALE=121 y seis canales
activos. El controlador se cerró y el PCA conserva los pulsos: los servos siguen
energizados. Después se ejecutó una prueba autorizada de pinza 1499→1539 µs en
2 s: lectura final 1538 µs, las otras cinco articulaciones sin cambios. El operador
no notó movimiento; no se validó el sentido ni una nueva pose. La lectura posterior
sigue igual. El operador confirmó fuente encendida y pinza semiabierta. La segunda
prueba autorizada solo de pinza (1538→1618 µs en 3 s) terminó correctamente:
lectura 1616 µs, otros cinco registros sin cambios y apertura suave observada por
el operador. Se guardó `GRIPPER_OPEN_PROBE`, sin validar apertura máxima, cierre
ni agarre. Los pulsos actuales son los de HOME en las cinco articulaciones y
1616 µs en pinza. No se ejecutaron
recorridos de recogida. Ver [CALIBRATION_SESSION.md](CALIBRATION_SESSION.md).

**Inspección anterior del 1 de noviembre:** el controlador tenía SLEEP activo, PRESCALE=30 y
los seis canales liberados. La tarjeta y los pulsos del 30 de octubre son históricos;
`first-motion-card` rechaza correctamente el estado actual. Se necesita preparar otra prueba
presencial antes de energizar.

La web no inicia el servicio de servos. Las pruebas físicas documentadas se ejecutaron con
utilidades específicas revisadas, autorización y observación del operador. La prueba histórica
de abajo no es una instrucción para repetir los movimientos actuales.

## Qué se comprobó y qué no

| Elemento | Estado el 30 de octubre de 2026 |
| --- | --- |
| SSH USB `jetson-usb` | Funciona con OpenSSH nativo y verificación del host. |
| Python 3.6.9 | Compila los tres scripts de `agent/` sin ejecutar su `main`. |
| Cámara `/dev/video0` | Entrega 1920×1080 y sostuvo unos 30 fps durante 6 s con Python 3.6 y OpenCV. |
| PCA9685 | Lectura de registros sin escrituras. Pulsos comandados abajo. |
| Posición física, carga, repetibilidad, colisiones | Sin medir. |
| Parada física de los servos | Sin identificar ni probar. |
| Rutas, bandeja, piezas, regiones | No existen todavía. |

Pulsos comandados leídos a las 17:52 (Lima). **Son lo último que se ordenó, no dónde está el brazo:**

| `base` | `shoulder` | `elbow` | `wrist_pitch` | `wrist_roll` | `gripper` |
| --- | --- | --- | --- | --- | --- |
| 1499 | 1450 | 1499 | 1602 | 1499 | 1499 |

## Primera prueba supervisada

**Movimiento:** solo la pinza, de 1499 a 1539 µs en 2 s (20 µs/s, el 2 % del tope del controlador).
Las otras cinco articulaciones reciben su pulso actual y `mindarm_arm.py` no las escribe.

Salto y duración son una propuesta de prueba, no una calibración. Si quieres un movimiento menor,
reduce `gripper` en la orden. Se desconoce si 1539 abre o cierra la pinza: averiguarlo es parte de
la prueba.

**Objetivo:** confirmar que un cambio pequeño de pulso produce un movimiento pequeño y en qué
sentido. No demuestra agarre ni precisión.

### Antes de empezar

1. Retira piezas, manos y cables del recorrido de la pinza.
2. Identifica cómo cortar la alimentación de los servos y mantén la mano a su alcance.
3. Si vas a cortarla, sujeta o apoya el brazo: sin par puede caer.
4. Regenera la tarjeta justo antes, porque los pulsos pueden haber cambiado:

   ```powershell
   .\.venv\Scripts\python.exe -m premonition first-motion-card
   ```

   La tarjeta se niega a generarse si el servicio escribiría registros al arrancar, si un canal
   está liberado o si un pulso está fuera de la envolvente. La orden exacta queda en
   `runs/real/first_motion_card.json`, campo `command_line`.

### Ejecución

Abre una terminal aparte y arranca el servicio existente:

```powershell
& 'C:\Windows\System32\OpenSSH\ssh.exe' -T jetson-usb 'python3 /home/abelbrayan/mindarm_arm.py'
```

La primera línea debe tener `"ok": true` y `positions` idéntico a `commanded_us` de la tarjeta. Si
difiere, no sigas: cierra con Ctrl+C. Si coincide, pega la línea `command_line`. Con los valores de
hoy sería:

```json
{"id": 1, "cmd": "move", "targets": {"base": 1499, "shoulder": 1450, "elbow": 1499, "wrist_pitch": 1602, "wrist_roll": 1499, "gripper": 1539}, "duration": 2.0}
```

### Cómo detenerla

- **Parada de software:** pulsa Enter en esa terminal. Cualquier línea recibida detiene la rampa y
  mantiene el último pulso. No es un paro de emergencia.
- **Parada física:** corta la alimentación de los servos. Está sin verificar en este montaje.

### Al terminar

Cierra con Ctrl+C. El servicio mantiene los últimos pulsos: cerrar no corta el par.

La respuesta `positions` es el pulso comandado, no prueba la posición física. Anota lo que viste:

- ¿La pinza se movió? ¿Abre o cierra al subir el pulso?
- ¿Hubo zumbido, vibración o tirón al arrancar?
- ¿Cómo se corta la alimentación de los servos?

Con eso se confirma `stop_procedure_confirmed` en `config/cell.json` y empieza la segunda entrega.

## Reglas de la integración

- No ejecutar `servo_test.py`: puede desactivar salidas y liberar los servos al salir.
- `start` puede energizar canales liberados directamente en su objetivo; esta prueba no lo usa.
- Una línea recibida durante una rampa la interrumpe y se consume: no enviar nada más mientras dure.
- Usar `C:\Windows\System32\OpenSSH\ssh.exe`, no el SSH de Git Bash.
- En PowerShell, evitar comillas dobles y `|` dentro del comando remoto: PowerShell las altera y la
  tubería termina ejecutándose en la Jetson. Para scripts, enviarlos por stdin con finales LF.

## Antes de evaluar visión

La misma cámara, sin cambiar ningún control, dio estos resultados el mismo día:

| Momento | Brillo medio (0–255) | Nitidez (varianza del laplaciano) | Observación |
| --- | --- | --- | --- |
| Inspección, de día | sin medir | sin medir | Contraluz intenso y zonas sobreexpuestas. |
| 17:52 | 8.9 | 20.6 | Casi negra; solo se ve la zona de la ventana. |
| Minutos después | 104.8 | 17.9 | El brazo se ve, con desenfoque y esquinas oscuras. |

Aumentar de 8 a 180 lecturas no cambió el brillo de las 17:52, así que no era falta de tiempo de
arranque. La exposición automática está activa y la ganancia es 0. El cambio entre las dos últimas
filas parece venir de la luz del cuarto; no se comprobó cuál fue el cambio.

La percepción no se puede calibrar con esta variación. Hace falta fijar la cámara, encuadrar la
bandeja, iluminar de forma estable, evitar el contraluz y revisar el enfoque. Ni la bandeja ni las
piezas aparecen todavía en el encuadre.

## Agente nuevo

`agent/premonition_agent.py` resuelve las limitaciones de `mindarm_arm.py`: una sola orden
pendiente, IDs correlacionados, rechazo de duplicados, `status` y heartbeat sin interrumpir la
rampa, `stop` con ACK, watchdog y diario en disco. Solo se probó con un backend falso y no se
instaló en la Jetson. No puede tocar I²C: añadir ese backend corresponde a la segunda entrega.
