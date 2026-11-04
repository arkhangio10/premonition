# Preparación de calibración real

Actualizado el 2 de noviembre de 2026, America/Lima.

## Incidente actual: vibración, pruebas suspendidas

Tras aproximaciones con referencias visuales, el operador negó contacto físico en los
candidatos de base 1802 y 1743 µs. Se realizaron retiradas: dos pequeñas no produjeron
movimiento visible pese a cambiar registros; la retirada más amplia 1626→1566 µs (lectura
1567) sí levantó claramente la punta. Esto no identifica por sí solo la causa de la respuesta
irregular. No se estableció que fuera juego mecánico, alimentación o atasco.

Se cambió después el alcance del brazo con hombro 1367→1427→1450 (lectura intermedia1426),
manteniendo base 1743 y codo 1694. El último ensayo, `e99bb931cac04ed79a8cacefe8cb2ff3`,
ordenó codo 1694→1734 µs en 4 s, lectura 1733. El operador informó «vibra pero no se mueve
que estas haciendo». Se suspendieron las pruebas sin enviar nuevos movimientos.
Se pidió apoyar el brazo y desenchufar su fuente externa; confirmación física pendiente.

Lectura posterior de solo lectura: MODE1=33, PRESCALE=121; base 1743, hombro 1450, codo 1733,
pitch 1602, roll 1499, pinza 1616 µs. Ningún proceso del brazo. Estos registros no prueban
posición o fuerza reales. No se enviaron HOME ni liberación PWM para evitar un movimiento
adicional o una caída del brazo sin apoyo.

Se creó `motion_hold.json`. Su presencia bloquea las utilidades de aproximación, muñeca,
preparación de pasos y reinicio HOME antes de acceder al controlador. Incluso un archivo
vacío o malformado mantiene el bloqueo. Se requiere revisión y resolución física documentada
antes de quitarlo. Pruebas de interbloqueo y constructores: 68 aprobadas; suite completa previa
371 aprobada. Las pruebas de software no verifican la capacidad mecánica ni el contacto.

Referencias seleccionadas visualmente, solo píxeles aproximados: P0 esquina de tabla
[1360,512], T superficie de esponja [720,682], J punta blanca inicial [712,599]. Artefacto
`inspection/contact-reference-points-20261102.jpg`. Correlación de imágenes comprobó cámara y
esponja quietas en las primeras pruebas, pero la superposición de punta y borde no probó
contacto físico. Hubo cambio de iluminación; foco manual seguía en 30, gain 0 y exposición
automática. No se modificaron esos controles en esta sesión.

También se reforzó el ejecutor para exigir que las revisiones nuevas indiquen el archivo y
SHA-256 exactos de la foto inspeccionada. El límite de antigüedad bloqueó un intento de base
antes de iniciar el controlador; tras inspeccionar otra foto, se vinculó la misma orden aún
sin usar y se ejecutó una sola vez. No se repitieron órdenes de resultado incierto.

Estado y ensayos: `runs/real/calibration/transfer_session_20261102.json`; incidente:
`runs/real/calibration/vibration_incident_20261102.json`. No hay contacto, agarre ni
transferencia validados. Lo siguiente es historial anterior al incidente.

## Sesión anterior: alineación elevada y aproximación sin contacto

El operador confirmó estabilidad tras los primeros pasos de base y codo. Se registró
APPROACH_BASE_ELBOW_01, id `2b2d0d2912e549f99aaf53cad7818a4e`, con los pulsos 1558,1372,
1558,1602,1499,1616 µs. Después se ejecutaron cuatro pasos independientes de base:
1558→1618 (lectura 1616), 1616→1676 (1675), 1675→1735 (1733), 1733→1793 (1792).
Cada orden duró 4 s y se revisó la imagen antes de continuar. A continuación se movió solo
codo 1558→1618 en 4 s, lectura 1616. Los otros cinco canales conservaron sus registros.

Ensayos: `716cf22b562942ccb763f0b924bd5b32`, `35ded1c45d854e21a2fa924799a01d8b`,
`64109e699d5e4ead9d82c868927894ba`, `32a590af591849da8d3c1c6285fa92d9` y
`e34da910f3fc4afdb72bc211e34a6ce8`. Se mantienen las comprobaciones de servicio, estado
inicial exacto, imagen reciente, vídeo, revisión de un uso, ACK y lectura posterior.

Pulsos actuales: base 1792, hombro 1372, codo 1616, pitch 1602, roll 1499, pinza 1616 µs.
MODE1=33, PRESCALE=121, sin procesos del brazo y salidas activas mantenidas por el PCA.
La pinza quedó cerca de la parte superior de la esponja en la imagen; se pidió observación
lateral del operador (encima/delante/detrás y separación aproximada) antes de otro descenso.
La postura exacta actual sigue como candidata, sin aceptación implícita ni agarre ejecutado.

La nueva escena `75581d9487d542b299857b5a67dc8e56`, foto `20261102-144924-604aef83.jpg`,
dio por primera vez gripper_detail=clear. Muse ve mordazas abiertas y SAM devuelve una máscara
del conjunto guiada por la caja de Muse, más una esponja por nombre. La búsqueda de pinza solo
por texto sigue en cero. Cuatro HTTP 200 y USD 0.01655875 estimados. Captura de interfaz:
`inspection/pregrasp-clear-gripper-20261102.png`. El vídeo se reabrió después del análisis.

El usuario preguntó por movimientos más rápidos. Se explicó la diferencia entre calibrar una
trayectoria nueva y temporizar otra ya validada; se conservaron los 4 s actuales. No hay
encoders ni profundidad calibrada. La herramienta `inspection/prepare_transfer_step_20261102.py`
solo registra el par de imágenes y prepara una revisión, comprobando lectura actual y que la
imagen sea posterior a la orden anterior; no actúa. No se ejecutó agarre ni transferencia.

## Sesión anterior: mesa preparada, base y codo

El operador confirmó esponja colocada sobre la tabla, zonas despejadas y manos fuera del
recorrido. La foto nueva muestra la esponja entera. Muse y SAM la localizaron en
[593,630,855,867], escena `8ef96202c176454ba41924c58d977fec`. Está parcialmente fuera del
recuadro original, por lo que no se marcó la propuesta como región aceptada por el operador.

Se ejecutaron dos órdenes independientes de 4 s: base 1499→1559 (lectura 1558), ensayo
`84f1ea1e89984a05a1c7adff1aa1b57a`; codo 1499→1559 (lectura 1558), ensayo
`f179da0131264572a59eab23080a3c14`. Vídeo activo, imagen reciente, servicio verificado,
lectura inicial exacta, ACK y lectura posterior; los otros cinco canales no cambiaron.
La pinza continúa elevada y abierta. Se pidió observar estabilidad y ruido antes de seguir.

Muse dejó la comparación del codo como incierta. Se contrastó con dos consultas SAM usando
la misma caja seleccionada manualmente [350,100,810,400] sobre los JPEG originales completos.
Las máscaras, revisadas visualmente, cubren el conjunto de la pinza antes y después. El centro
de máscara pasó de [638.08,216.37] a [609.61,266.44], delta [-28.47,+50.08] píxeles. Es una
medida de segmentación en imagen; no distancia física, suavidad o trayectoria validada.
Evidencia: `step_vision/f179da0131264572a59eab23080a3c14_sam.json` y
`inspection/elbow-sam-before-after-20261102.png`. Coste adicional SAM: USD 0.005 estimados.
Comparación Muse del codo: USD 0.015252, HTTP 200; se conserva su abstención.

Estado actual: base 1558, hombro 1372, codo 1558, pitch 1602, roll 1499, pinza 1616 µs;
MODE1=33, PRESCALE=121, sin procesos del brazo y salidas mantenidas. El próximo paso de base
1558→1618 está preparado, sin ejecutar. No hay agarre, transferencia ni una nueva pose
confirmada por el operador. Suite completa: 370 pruebas aprobadas y una advertencia de
deprecación de TestClient. El ejecutor de pasos revisados limita cada orden a una articulación,
60 µs (80 solo en pinza), 4 s, dentro de la envolvente histórica sin alcanzar sus extremos;
estas restricciones no sustituyen la revisión física de cada paso.

## Sesión anterior: primer paso de aproximación supervisada

El operador confirmó que la base está fijada firmemente a la mesa y pidió enseñar la recogida,
elevación y colocación de la esponja. Las referencias históricas dependen de un punto marcado;
usan extremos de la envolvente y registran un atasco de pitch. No se ejecutó esa secuencia.

Se preparó una prueba de hombro únicamente: 1450→1430 µs en 3 s, lectura 1431. Muse comparó
los JPEG originales y no distinguió movimiento fiable. El operador indicó que no la había
observado y pidió repetir; se devolvió 1431→1450 y repitió 1450→1430, con fotos intermedias.
Después solicitó un movimiento más amplio: 1431→1370 µs en 4 s, lectura 1372. Esta vez la
pinza se desplazó claramente a la izquierda y abajo en la imagen, confirmado también por
Muse. El operador confirmó suavidad y estabilidad; se guardó **APPROACH_SHOULDER_01**.

Estado actual: base 1499, hombro 1372, codo 1499, pitch 1602, roll 1499, pinza 1616 µs;
MODE1=33, PRESCALE=121, ningún proceso del brazo y pulsos mantenidos por el PCA.
Cada orden fue única, con revisión consumida antes de iniciar el controlador, hash del servicio
verificado, vídeo activo, captura reciente, vector inicial exacto y lectura final. No se reenvía
una orden dudosa ni se energizan canales liberados. Los otros cinco registros no cambiaron.

Ensayos en `trials/`: `3de862a2b67347a498aff2d95fc35a91`, `87facbfffd7245a98722f112c6cfd4ab`,
`fe2ab573822f48a29837ecc88616f1c0` y `ad3810a341ee4b5c8570d8844a67ffb6`. Comparaciones Muse
en `step_vision/`: primera USD 0.0118155 y ampliada USD 0.015751 estimados, ambas HTTP 200.
También se actualizó el análisis de escena antes de mover: `bd083481cc1142d8b932837058f07227`,
con una esponja y una segmentación parcial de pinza guiada por Muse.

Se propusieron zonas de mesa en `workspace_proposal_transfer_20261102.json`: Pick up
(700,560,230,170) y Place (1230,530,190,150), x,y,w,h en píxeles. La esponja actual se ve
cortada por el borde inferior y sobre una pieza blanca; hay cables en la zona de trabajo.
Se pidió al operador colocarla directamente sobre la tabla, despejar ambas áreas y retirar
las manos antes de seguir. La foto queda pausada con las zonas para facilitar la preparación;
la propuesta no cuenta como aceptación ni como coordenadas del robot.

Pasaron las 27 comprobaciones del constructor de prueba y la suite completa de 349 pruebas,
con una advertencia de deprecación de TestClient. Estado y referencias en
`runs/real/calibration/transfer_session_20261102.json`. No se ejecutó agarre ni transferencia.

## Sesión anterior: vídeo en vivo y detección guiada

El usuario pidió mover el brazo hasta detectar la pinza y ver vídeo en vivo. Se habilitó una
vista de cámara independiente del análisis: MJPEG 1280×720, unos 8 fps medidos, memoria limitada
al último fotograma y cierre del proceso al pausar o desconectarse. El mismo bloqueo de cámara
evita capturas simultáneas. El análisis pausa el vídeo y toma una foto nueva 1920×1080;
las máscaras no se reutilizan sobre fotogramas posteriores. El vídeo no llama a Meta ni a I2C.

Con vista en vivo se enviaron, una sola vez cada una, cuatro órdenes de 3 s dentro de los tramos
ya observados: roll 1499→1579 (lectura 1577), 1577→1657 (lectura 1655), retorno 1655→1499 y
pinza 1499→1618 (lectura 1616). Base, hombro, codo y pitch no cambiaron. Un intento previo al
retorno fue rechazado por foto antigua y no envió movimiento; se tomó una nueva antes de seguir.
Los cuatro ACK y lecturas están en los ensayos `6f9d3527e3b3499aa202d4cff1984f8e`,
`98258daa113e400ca62cd0a53c804d74`, `c50f96b7804a41adb6b668c07228aa48` y
`8a969a657dcf498bbc2fce0cbd0f82af`. El operador confirmó que los giros y la apertura fueron
suaves y el brazo quedó estable, sin vibración ni zumbido fuerte.

Estado final leído: MODE1=33, PRESCALE=121; base 1499, hombro 1450, codo 1499, pitch 1602,
roll 1499, pinza 1616 µs. No quedan procesos del brazo; el PCA mantiene las salidas activas.
Coincide con la pose guardada GRIPPER_OPEN_PROBE. No son ángulos medidos ni una ruta validada.

SAM no detectó la pinza por nombre, tampoco con un recorte literal. Una prueba guiada por una
caja elegida al inspeccionar la imagen sí delimitó el conjunto de pinza. Después se implementó
la alternativa automática: Muse devuelve una caja nullable en píxeles originales y SAM recibe
esa guía si su búsqueda por nombre da cero. Solo una máscara realmente devuelta cuenta como
objeto. Se conservan la búsqueda original fallida, la caja y el modo **model-guided**. Existe
también **Select gripper** para seleccionar manualmente sobre la foto actual, identificado como
**selected**. Formato contrastado con la [documentación oficial de SAM](https://dev.meta.ai/docs/sam/segmenting).

Prueba automática real `806e0cea686a4676b7c7856daf2d7230`: foto
`20261102-135520-533f404f.jpg`, cuatro HTTP 200, USD 0.0198975 estimados. Muse indicó
[484,113,640,182]; SAM devolvió una máscara de 3876 píxeles, caja [460,112,591,175].
La inspección visual confirma coincidencia con parte de las puntas de las mordazas, no con
el conjunto completo. Muse mantiene detalle limitado; no prueba apertura útil ni agarre.
La esponja sí se detectó por nombre. Evidencia visual anotada, separada del JPEG original:
`inspection/gripper-roi/model-guided-overlay.jpg`.

Validación final: 322 pruebas aprobadas; una advertencia de deprecación de Starlette/TestClient.
Se comprobó vídeo, pausa, captura nueva, análisis, procedencia de máscaras y liberación de la
cámara. Resumen y referencias en `runs/real/calibration/visibility_session_20261102.json`.
Siguen pendientes geometría cámara-robot, poses de recogida/colocación y umbrales; no se
ejecutó una transferencia. Lo siguiente documenta sesiones anteriores.

## Reanudación: HOME, Muse, SAM y regiones

El operador identificó la parada como desenchufar la fuente externa de los servos de la corriente.
La inspección encontró MODE1=17, PRESCALE=30 y las seis salidas desactivadas, sin procesos del
brazo. El hash de `mindarm_arm.py` seguía siendo el verificado. Una consulta previa de procesos
falló por las comillas de PowerShell: `servo_test` y `premonition_agent` se interpretaron como
comandos y no existían en PATH. La inspección posterior por stdin confirmó que no se iniciaron
programas del brazo. Los scripts de control e inspección usan `ssh_argv` desde Python.

Con apoyo, postura cercana a HOME, pinza vacía, recorrido libre y corte accesible confirmados
de nuevo por el operador, se envió exactamente un `start`: 1500, 1450, 1500, 1600, 1500 y 1500 µs,
con stagger 0.5 s. El controlador respondió correctamente; lectura posterior 1499, 1450, 1499,
1602, 1499 y 1499 µs. El operador confirmó reposo estable. Se guardó OBSERVE_C922, con dos lecturas
coincidentes y confirmación del operador, y se configuró como pose de observación.
El cierre del controlador conserva los pulsos; no corta el par.

El nuevo análisis de escena envió una foto real C922 a Muse Spark y la misma foto a SAM con
dos consultas. Los tres HTTP fueron 200. Muse describió brazo y esponja, con detalle de pinza
limitado. SAM encontró una esponja y ninguna pinza; no se sustituyó la ausencia por un rectángulo
inventado. Contorno, caja, hash de la foto y datos de uso están en
`scenes/b5ceeabe47314b518964c55e1f55095e.json`. Coste estimado: USD 0.01443775.
Las detecciones no prueban agarres ni distancias físicas.

Se preparó una propuesta de origen sobre la esponja (645,762,299,306) y destino en una zona
libre de la mesa (1230,480,160,140), como x,y,w,h en píxeles. El usuario eligió otro sector
de la misma mesa. Falta revisar la zona concreta antes de guardar su aceptación. La web permite
dibujarlas y rechaza solapamientos, límites inválidos, fotos alteradas o una captura anterior.
No se definieron movimientos de recogida, elevación o colocación a partir de esos píxeles.

Validación: 113 pruebas afectadas aprobadas tras corregir las pruebas que suponían que la
configuración real siempre estaría vacía. Las pruebas de datos faltantes ahora construyen
una celda incompleta explícita, independiente de la calibración del usuario.
La suite completa posterior pasó 294 pruebas. Las 25 pruebas finales de escena/regiones
también pasaron tras añadir la carga de propuestas sin aceptación implícita. La revisión
visual detectó y corrigió el uso de `.hidden` en SVG: ahora se añade o retira el atributo
explícitamente, para que máscaras y regiones se dibujen. Se comprobó su visibilidad real,
el borrador tras recarga, el botón de guardar sin confirmar y el diseño a 390 px.

## Prueba de la cámara nueva, 2 de noviembre

Se identificó la C922 Pro Stream Webcam en `/dev/video0` por UVC, con controles
`focus_auto` y `focus_absolute` disponibles. Se capturó a 1920×1080 por MJPEG.
La primera vista apuntaba alta y enfocaba el fondo; el encuadre cambió durante
la revisión para incluir el brazo completo y la mesa. Se repitió la comparación
de foco con una región de la pinza en el encuadre nuevo (x=470, y=30, w=460, h=230).
Se probaron 0, 10, 15, 20, 25, 30 y 40; el valor 30 dio el mayor contraste de
bordes de esa región entre los candidatos (140.28 de varianza de Laplaciano).
Es una comparación relativa, no un umbral de visión calibrado ni una medición
de distancia. Se dejó el autofocus desactivado y el foco en 30; la lectura final
confirmó ambos valores después de cerrar y reabrir la captura tres veces.

Las fotos nuevas desde la interfaz fueron `20261102-120759-16de1fbc.jpg`,
`20261102-120801-ed3d5508.jpg` y `20261102-120803-c92e641b.jpg`, todas 1920×1080.
La última quedó visible en `/calibration`, con 0.92% de píxeles saturados.
El navegador no informó errores ni advertencias. Se inició de nuevo el servidor
local porque no estaba escuchando. No se modificó el código de captura o de la
interfaz: el enlace existente funciona con la C922. Se añadieron solamente las
evidencias de inspección y esta documentación. No hubo órdenes al brazo, lecturas
de I2C ni llamadas a Meta. La interfaz ofrece fotografías, no vídeo continuo.

## Comprobación anterior: vista de cámara y Muse, 1 de noviembre

El usuario autorizó mover el brazo para observar mejor la pinza y verificar con
cámara. Se movió solo roll en dos pasos de 80 µs: objetivos 1579 y 1657 µs,
lecturas 1577 y 1655 µs. Cada paso duró 3 s y se inspeccionó su foto antes de
continuar. Se devolvió la pinza de 1616 al pulso HOME 1499 µs en 3 s. Un paso
exploratorio de pitch 1602→1562 µs no mejoró apreciablemente el encuadre y se
restauró a 1602 µs en otros 3 s. Base, hombro y codo mantuvieron sus registros.
Las cinco órdenes id 3–7 tuvieron ACK correcto, sin reenvíos.

Lectura final: base 1499, hombro 1450, codo 1499, pitch 1602, roll 1655 y pinza
1499 µs. El controlador está cerrado, no quedan procesos del brazo y el PCA
mantiene los pulsos con la fuente externa encendida. La postura actual conserva
el nuevo roll para la vista de cámara; no es el HOME guardado completo. No se
guardó otra pose como observada por el operador.

Se usó realmente `muse-spark-1.3` con tres JPEG originales: vista inicial, vista
tras roll con pinza abierta y esa misma vista tras el retorno. Se adjuntó el
contexto del ensayo distinguiendo comandos PWM de posiciones medidas. HTTP 200,
14.12 s, 8907 tokens de entrada y 1833 de salida; coste estimado USD 0.018924.
Muse dejó tanto el cambio de vista como el de apertura como inciertos por la
imagen borrosa. Recomendó una toma lateral cercana, estable y enfocada. Su
confianza declarada de 0.35 es subjetiva y no una medida calibrada. No se validó
cierre completo, repetibilidad, límites físicos ni un agarre.

El cliente antes solo enviaba texto a Spark; ahora incorpora envío multimodal,
contexto y validación estructurada en `premonition/arm_vision.py`. El comando
`analyze-arm --trial <ID>` usa una llamada y USD 0.10 estimados como límite.
La interfaz muestra el resultado guardado y enlaza a sus fotos sin nuevas llamadas
al abrirse. La interpretación del modelo no acciona el brazo.

Evidencia: `runs/real/calibration/trials/5add7cfdcdeb4391979dd0011aa26d9d.json` y
`runs/real/calibration/vision/5add7cfdcdeb4391979dd0011aa26d9d.json`.
La foto final es `runs/real/captures/20261101-235448-fda5cb18.jpg`. El siguiente
paso es obtener una imagen enfocada de las mordazas antes de seguir calibrando.

## Historial de HOME y dos pruebas de pinza

Con la confirmación del operador se ejecutó únicamente la inicialización HOME
histórica, canal por canal con 0.5 s entre activaciones. El controlador respondió
ok=true y stopped=false. La lectura posterior es MODE1=33, PRESCALE=121, con
pulsos base 1499, hombro 1450, codo 1499, pitch 1602, roll 1499 y pinza 1499 µs.
Las diferencias de 1–2 µs respecto del objetivo corresponden a cuantización PWM.

Se tomó una foto nueva y el usuario confirmó la postura esperada, sin roces,
tirones, zumbido fuerte ni vibración y con pinza semiabierta. Se registró HOME
como la primera pose observada. Sigue siendo lectura de pulsos y observación
humana; no es una medida de ángulos articulares.

El programa de control se cerró y no queda otro proceso del brazo. El PCA9685
conserva los pulsos: **los servos permanecen energizados**. No se ejecutaron
recorridos de recogida. Evidencia: `runs/real/calibration/first_home_result.json`
y `runs/real/calibration/poses.json`.

Tras la autorización «dale» se ejecutó una única prueba de pinza: 1499→1539 µs
en 2 s. El controlador respondió ok=true y stopped=false. La lectura posterior
fue 1538 µs para la pinza por cuantización; los pulsos de las otras cinco
articulaciones permanecieron idénticos a HOME. MODE1=33 y PRESCALE=121.

Se cerró el controlador y se comprobó que no queda otro proceso del brazo.
Los servos siguen energizados. La postura actual conserva HOME en las cinco
articulaciones, con la pinza en el pulso de prueba; no es el HOME guardado exacto.
Se tomaron fotos reales antes y después. El operador respondió «No noté
movimiento». Se registró el resultado físico como inconcluso: no se conoce el
sentido de movimiento y no se confirmó suavidad ni ausencia de ruido. No se
guardó una nueva pose ni un extremo de apertura.

Una comprobación posterior sin escrituras confirmó los mismos seis pulsos,
MODE1=33, MODE2=4, PRESCALE=121, el mismo hash del controlador y ningún proceso
del brazo. Esto no mide la señal eléctrica en el conector, la alimentación de
los servos ni el estado del pin OE. El operador confirmó después «Fuente
encendida; pinza a medio abrir». Esta observación no mide el voltaje en el servo.
No se amplió el recorrido ni se repitió la orden.

La segunda prueba se ejecutó tras la confirmación «Sí, estoy mirando la pinza»:
solo pinza de 1538 a 1618 µs en 3 s (80 µs adicionales), manteniendo los otros
cinco comandos iguales. La consulta previa y el saludo del controlador
coincidieron con lo esperado. La orden id=2 terminó con ok=true y stopped=false;
se envió una sola vez. La lectura final de pinza es 1616 µs por cuantización.
Los otros cinco registros siguieron iguales a HOME y no quedó ningún proceso
del brazo tras cerrar el controlador.

El operador confirmó «Se abrió suavemente». En este tramo, aumentar el pulso
abre la pinza. Se registró la pose observada `GRIPPER_OPEN_PROBE`, con pinza
1616 µs y las otras articulaciones en sus pulsos de HOME. No es una medida de
apertura, un extremo máximo ni una calibración de agarre. No se probó el cierre
ni el retorno. Los servos siguen alimentados y el PCA conserva los últimos
pulsos; cerrar SSH no los desenergiza.

Evidencia de esta segunda prueba:
`runs/real/calibration/trials/ccac2c7a0e21474f9b855a711a7db050.json`.
Foto posterior: `runs/real/captures/20261101-234446-a3af974c.jpg`.
La tarjeta ejecutada, que ya no debe repetirse, está en
`runs/calibration/session-20261101/real/second_motion_card.json`.
El siguiente paso propuesto es comprobar el retorno hacia el pulso HOME de
pinza, observando el cierre y la repetibilidad antes de buscar otros extremos.

Evidencia: `runs/real/calibration/trials/a38053bbfd224cffafab1c8b204ee5e5.json`.
La tarjeta ejecutada se conserva en
`runs/calibration/session-20261101/real/first_motion_card.json` como referencia
histórica; ya no representa los pulsos actuales previos a un movimiento.

## Inspección previa a la primera prueba

- Jetson accesible por OpenSSH con verificación del host; `abelbrayan-desktop`.
- Cámara USB real de 1920 × 1080, OpenCV y SMBus disponibles.
- PCA9685: MODE1=17, PRESCALE=30; los seis canales están desactivados. No hay
  una posición física medida ni una postura activa que pueda guardarse todavía.
- No se ejecutaron programas de servos, inicializaciones ni movimientos.
- El agente nuevo solo tiene backend falso y no está instalado en la Jetson.

`/calibration` muestra cámara real, lectura del controlador, registro de poses y
estado de la integración Meta. No habilita movimiento. El registro de poses exige
salidas activas a la frecuencia esperada, dos lecturas iguales, coincidencia con
los valores mostrados al operador y confirmación de que observó esa postura.
Las poses guardadas no validan rutas ni se activan en `cell.json`.

## Coordenadas recuperadas

Fuente analizada como datos, sin ejecutar sus programas:
`C:\Users\braya\Desktop\project_personal\nvdia_hackathon\mindarm\config\jetson_arm.yaml`.
Contexto contrastado con `hardware_bringup/HANDOFF.md` y `mindarm/docs/SPEC.md`.
Las referencias se guardan en `config/reference_poses.json`, con hash del origen,
unidades, límites previos y obligación de revalidar el montaje actual.

| Referencia | Base | Hombro | Codo | Muñeca pitch | Muñeca roll | Pinza |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HOME | 1500 | 1450 | 1500 | 1600 | 1500 | 1500 |
| MOVE_ABOVE | 1600 | 1230 | 2000 | 1400 | 1010 | 1900 |
| GRASP | — | — | — | — | — | 1150 |
| LIFT | 1600 | 1380 | 2000 | 1250 | 1010 | — |
| HANDOVER | 1000 | 1430 | 1800 | 1200 | 1010 | 1150 |
| RELEASE | — | — | — | — | — | 1900 |

Valores en microsegundos. «—» significa conservar el comando anterior, no un
valor medido. HOME y las poses de esponja son históricas (28 de octubre), no
coordenadas del kit nuevo. `joint_limits.yaml` usa grados del simulador y no se
importó como calibración física. No se modificaron los proyectos de origen.

El informe previo documenta una muñeca trabada, posiciones en los extremos de
la envolvente y un punto de recogida fijo marcado con cinta. Estos antecedentes
deben revisarse antes de repetir un recorrido. Falta confirmar con el operador
el corte físico de alimentación y la disposición actual de la zona de trabajo.

## Cámara

La captura inicial tenía brillo medio 216.2/255 y 48.96 % de píxeles saturados.
Se probaron exposiciones manuales 10, 40, 80, 160, 320 y 640 en unidades V4L2.
Con 640: brillo 118.3, saturación 0.0037 % y nitidez por laplaciano 24.4 en la
captura de prueba. Se inspeccionó visualmente la imagen, sin modificarla.

Quedaron aplicados en la cámara, para esta sesión:

```text
exposure_auto=1
exposure_absolute=640
exposure_auto_priority=0
backlight_compensation=0
```

V4L2 interpreta la exposición absoluta en unidades de 100 µs: 640 equivale a
64 ms. Es un ajuste de exposición, no una calibración de percepción. El enfoque
sigue siendo insuficiente para una validación de identidad/posición fina y debe
revisarse físicamente; la cámara no anuncia control de enfoque en sus controles.
El perfil no se aplica automáticamente tras reiniciar/desconectar la cámara.
Las pruebas y ajustes originales se conservan en `inspection/camera_exposure_2026-11-01/`.

## Meta: acceso real comprobado

No se necesita una clave para calibrar motores. El producto del hackathon usa
Meta para proponer planes y generar referencias previas. El adaptador SAM existe,
pero no se ha conectado aún a la percepción física.

La clave se configura localmente mediante `tools/configure-meta-key.ps1`, sin
imprimirla ni pasarla en argumentos de proceso. Se guarda como MODEL_API_KEY en
`.env`, ya excluido de Git. La aplicación requiere reinicio para cargarla. La prueba
`meta-smoke` tiene un máximo de tres llamadas y USD 0.05 estimados.

El usuario configuró la clave mediante la entrada oculta local y se completó una
prueba real con entrada sintética, sin imágenes privadas del brazo ni actuadores:

| Modelo | Resultado | Latencia | Coste estimado |
| --- | --- | ---: | ---: |
| muse-spark-1.3 | HTTP 200; plan JSON devuelto | 4.14 s | USD 0.00129825 |
| muse-image-1.0 | HTTP 200; imagen devuelta | 9.27 s | USD 0.01 |
| sam-3.1 | HTTP 200; un objeto segmentado | 1.13 s | USD 0.0025 |

Total estimado: USD 0.01379825. La imagen de prueba está en
`runs/meta-smoke-20261101/real/meta_smoke/reference.jpg`. El informe de acceso
guarda solo metadatos permitidos y un hash para vincularlo a la clave comprobada;
no guarda la clave ni los prompts. La interfaz solo muestra acceso verificado si
coincide esa clave y pasaron los tres modelos. Se reinició la aplicación para
cargar la configuración local. No se entrenaron pesos de modelos.

## Preparación de la primera postura

Se preparó `runs/real/calibration/initial_home_review.json` con HOME histórico,
orden `start`, separación de 0.5 s entre canales y duración de 2 s. Se validó el
protocolo de la clase Arm extraída por AST del controlador previo usando un PCA
falso: seis escrituras simuladas en el orden y los valores previstos, ninguna en
hardware. La lectura real de esa preparación mostraba los seis canales desactivados;
la ejecución y confirmación posteriores se describen al inicio de este documento.

La primera energización de un canal liberado va directamente a su pulso objetivo;
la duración no hace gradual ese primer desplazamiento. La propuesta requiere
confirmar postura, apoyo y corte físico con el operador antes de habilitarla.

## Comprobaciones

- Primera fase: 42 pruebas aprobadas de aplicación web, registro de poses y acceso Meta.
- Integración de visión: 58 pruebas relevantes aprobadas entre adaptadores Meta,
  análisis multimodal, acceso y web. Se comprueba adjuntar los JPEG, rechazar
  evidencia alterada o pares que cambien otra articulación, conservar incertidumbre
  y rechazar comandos de movimiento o respuestas incompletas del modelo.
- Resultado Muse visible en escritorio y a 390 px sin desborde ni errores de consola.
- Rechazo de canales desactivados, frecuencia incorrecta, pulsos fuera de envolvente,
  cambios entre lecturas, datos distintos a los observados y nombres duplicados.
- La apertura de la página y las consultas iniciales no acceden al hardware.
- Consulta real y foto nueva desde la interfaz; guardar permanece deshabilitado
  mientras el controlador no está preparado. La web no ordena movimientos; HOME
  y la prueba de pinza se ejecutaron por el controlador SSH previamente revisado.

Fuentes: [controles V4L2](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/ext-ctrls-camera.html),
[autenticación Meta Model API](https://dev.meta.ai/docs/quickstart).
