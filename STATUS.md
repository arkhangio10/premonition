# Estado del proyecto

Última actualización: 4 de noviembre de 2026, 18:05, America/Lima. Entrega al hackathon: 4 de noviembre
de 2026, 21:00 de Lima (corte de funciones a las 18:00).

## H2 (4 de noviembre): en curso

**Tarea 8, 17:40–18:03: tres ciclos completos X → B con Muse en el lazo, en cinco corridas.** Configuración: agarre y soltada a 2090 µs, destino base 1700, `--repeat-success`, tope de 8 llamadas y USD 0,15 por corrida. La soltada a 2090 está en el código (`RELEASE_OPEN_US`); la apertura de agarre a 2090 se fijó con una variable del script de corrida de la sesión, y la política del repositorio sigue eligiendo 1850 o 1940. Desplazamiento medido en C922: +54 a +56 px hacia B (~2 cm).

| Corrida | Resultado | Agarre | Segundos | Llamadas | USD | Juicio de Muse |
|---|---|---|---|---|---|---|
| `20261104-174411` | **completo** | 1.er intento | 44,6 | 3 | 0,03541650 | agarre ✓, colocación ✓ |
| `20261104-174633` | `ask_human` | 3 `reach_failed` | 34,7 | 2 | 0,02269975 | agarre ✗ (coincide) |
| `20261104-174939` | **completo** | 4.º intento | 92,7 | 3 | 0,03499575 | agarre ✓, colocación ✗ (falso negativo: la mordaza tapaba la esponja; medido apoyado) |
| `20261104-175906` | `ask_human` | 3 `reach_failed` | 31,0 | 2 | 0,02154800 | agarre ✗ (coincide) |
| `20261104-180249` | **completo** | 1.er intento | 43,9 | 3 | 0,03440075 | agarre ✓, colocación ✓ |

- Videos: `inspection/video-174358/`, `video-174619/`, `video-174925/`, `video-175853/` y `video-180236/`. Además hubo un arranque detenido en el preflight por el parpadeo del tag (0 órdenes, 0 llamadas) y uno anterior (`20261104-174050`) detenido por un falso `object_moved`.
- Los dos `ask_human` ocurrieron con la esponja en x0 ≈ 613–616 px de la C922, en el borde izquierdo del atlas (base 1583). Con la esponja ~1 cm a la derecha de la X (x0 ≥ 630), las tres tomas funcionaron. Un atlas con columna en base 1533 permitiría usar la X.
- **Cambios de código de esta tanda (cada uno con su prueba; suite completa: 681 aprobadas):**
  - `RELEASE_OPEN_US` = 2090 en `place()`: a 1850 la espuma quedó trabada en la mordaza; a 2090 se liberó (probado en la mesa).
  - `released()` lee la altura en la USB: una esponja liberada que se endereza subió su borde superior 12 px en la C922; una trabada subió 57/35 px.
  - El guardia de aproximación exige que la caja USB se desplace entera: la mesa iluminada pegada a la caja movió solo x1, 96 px.
  - `place()` sube a la altura de despeje después de juzgar la soltada, para que la foto que recibe Muse muestre la pinza vacía.
- **Muse en todo el día:** 38 respuestas HTTP 200, USD 0,44439050, más los dos timeouts sin facturación confirmada. Tope total autorizado: USD 1.

**Avance de las 17:10.** Primer ciclo de Tarea 7 con Muse en el lazo físico, pero sin traslado: tomó y soltó en la misma base.

- **Recalibración USB** (se había movido ~27 px y girado ~0,9°). El primer reescaneo falló porque la esponja seguía sobre la X: el brazo la empujó y las pasadas discreparon 25–80 px en ambas vistas. `scan_marked_jaw.py` ahora no mueve si `locate_object` ve la esponja; en las fotos previas de los 7 escaneos del día separa sin errores. Segundo reescaneo activado a las 16:03: 32 posturas, marca visible 100 %, cero saltos, cámara estable 0,64/0,49 px.
- `20261104-160516.json`: `grasp_object_not_found` a los 10,8 s. En la vista USB nueva la cara se ve lavada (S≈104) y la semilla saturada oscilaba entre 1200 y 4700 px, alrededor del umbral de 3000: el 38 % de los cuadros quietos perdía la esponja. `scene_detect.py` ahora exige área ≥3000 y semilla ≥1000. Da la misma caja exacta donde antes detectaba (8 secuencias de video) y recupera 113/113 cuadros USB de esa corrida. La prueba nueva de `test_scene_detect.py` falló antes del cambio y pasa después; la suite completa terminó con salida 0.
- `20261104-162331.json`: **ciclo agarre → levantar → soltar con Muse planificando y juzgando**, 44,4 s, 3 llamadas, USD 0,035081. Primer intento con el perfil de H1; la esponja subió ~49 px en C922. Tras abrir y subir 180 µs la esponja no se movió: quedó apoyada. Muse confirmó el agarre; su juicio de colocación fue un falso negativo (con hombro 1400 la mordaza todavía tapa la esponja en las fotos). **Limitación:** tomó en base 1583, borde del atlas e igual al destino A, así que la soltó donde estaba. Video: `inspection/video-162318/`.
- Esponja en B (base ~1700): `20261104-163857.json` la volcó en el primer intento (la mordaza la tomó por el borde superior) y pidió ayuda tras 3 `reach_failed`; 2 llamadas, USD 0,022738. Un arranque previo se detuvo en el preflight por tag USB no detectado: 0 órdenes y 0 llamadas.
- **Muñeca:** el canal 4 (`wrist_roll`) inclina la pinza (~90 px en 360 µs). El canal 3 (`wrist_pitch`) la gira ~45–60° entre 1182 y ~1582 µs y casi nada más allá. En B las mordazas abren a lo largo de la cara ancha (~12 cm). Con el canal 3 en 1582 la USB pierde la cinta en parte del espacio; reescaneo con ese giro en curso, pedido por el operador.
- El reescaneo con el canal 3 en 1582 se detuvo en la 3.ª postura (`usb_tip_lost`); sigue activa la calibración de las 16:03.
- **Destino B (base 1700), aprobado por el operador a las 17:16:** `DEFAULT_PLACE_BASE_US` 1583 → 1700 y `BASE_RANGE_US` hasta 1700, con sus pruebas. `20261104-171755.json`: agarre al 3.er intento, solo con la mordaza clavada en la espuma; al girar hacia B la esponja se arrastró y la aproximación terminó en `reach_no_progress` (2 llamadas, USD 0,023439).
- **Pinza más abierta, autorizado por el operador:** límite de la pinza 1950 → 2100 en `mindarm_arm.py` de la Jetson (respaldo `mindarm_arm.py.bak-20261104-1728`; el diff es solo esa línea), en `arm_session.py` y en `agent/premonition_agent.py`; `CONTROLLER_SHA256` actualizado. Vacía, abre de forma pareja hasta 2090 (+25 px en C922). `20261104-172713.json` con apertura 2090: levantó al 3.er intento (Muse lo confirmó), llegó a B, pero `place_not_released`: al soltar la pinza solo abre a `GRIP_OPEN_US` = 1850 y la espuma quedó trabada; además, en base 1700 el destino cae en C922 y≈1045, junto al borde frontal. 3 llamadas, USD 0,035123.
- La detección del tag ArUco parpadea en ambas vistas (~1 de cada 5 cuadros) y el preflight usa un solo cuadro. La USB sigue derivando: 1,3 → 7 px en 40 min.
- **Muse en esta tanda:** 13 respuestas HTTP 200, USD 0,14728300 (dry-run 0,009307; corridas 0,021595, 0,035081, 0,022738, 0,023439 y 0,035123). Total confirmado del día: 23 respuestas, USD 0,27194525, más los dos timeouts sin facturación confirmada.

**Avance de las 15:44.** Cuatro corridas físicas de Tarea 7, cero ciclos completos. Las clases registradas de H2 son cinco `reach_failed` y una `too_shallow`; hay además una interrupción sin intento cerrado. La memoria conserva esas clases históricas y un único éxito de H1.

- `20261104-152934.json`: 25,2 s; tres `reach_failed/no_progress`, sin descenso ni cierre. La esponja no fue tocada. Plan agotó 25 s; el juicio quedó bloqueado por la reserva conservadora, no por el tope de llamadas. El costo de USD 0,06996975 es una estimación de timeout, no facturación confirmada.
- `20261104-153719.json`: 36,7 s; un intento con cinco pasos de descenso y cierre. El video muestra una sujeción y levantamiento breves antes de que el sistema abriera la pinza por la clasificación local `too_shallow`. La siguiente iteración terminó por objeto no encontrado. **Muse sí planificó y juzgó esta corrida física**: plan factible, juicio de agarre fallido y sugerencia `lower_more`; dos respuestas 200, 8,0/9,2 s y USD 0,02222375. No hubo fase de colocación ni ciclo completo.
- El borde claro de la esponja USB estaba en x≈629 pero el umbral saturado lo situaba en x=743. Ahora solo se incorpora la cara clara conectada a una semilla saturada de al menos 3000 píxeles; se siguen rechazando la mesa marrón, el tablero oscuro y una región clara sin semilla. En 21 muestras del video anterior, el borde USB queda en x=624–629 y no se pierde el objeto. Regresiones con recorte real y escena sintética fallaron antes del cambio y pasaron después.
- Plan y juicio usan razonamiento `low` y hasta 1024 tokens de salida; las otras consultas visuales conservan sus valores anteriores. Timeout HTTP sigue en 25 s. La regresión comprueba que el juicio cabe en USD 0,15 incluso tras reservar conservadoramente un plan agotado. Nuevo dry-run: 6,6 s y USD 0,00894175.
- Se reprodujo el falso negativo del levantamiento: antes/después, objeto USB 646→623 px y C922 748→722 px; punta C922 938,9→895,1 px, punta USB oculta después de subir. La regla nueva, en validación, compara objeto y punta dentro de C922 cuando USB pierde la marca y exige además subida USB ≥10 px. La regla lateral habitual se mantiene cuando hay punta USB. No se cambió ningún pulso ni límite de movimiento ni se reclasificó la memoria antigua.

**Contabilidad actual.** Diez respuestas HTTP 200 confirmadas, USD **0,12466250**: ocho planes, un juicio retrospectivo y un juicio de fase en corrida física. Hay dos timeouts con facturación sin confirmar; el último reservó USD 0,06996975. Tope por corrida: 8 llamadas y USD 0,15; total autorizado USD 1.

**Pruebas y estado.** Suite completa anterior: **672 aprobadas**. Corrección de levantamiento: 107 focalizadas aprobadas; suite completa de 676 en curso. Brazo energizado y sin controlador activo: MODE1=33, prescale=121, base 1611, hombro 1621, codo 2202, pitch 1182, roll 1567, pinza 1851. La guía de cámaras está activa para recolocar la esponja en la X; la repetición espera al operador y al cierre de pruebas.

**Evidencia nueva.** `inspection/video-152923/` corresponde a la corrida de tres aproximaciones; `inspection/video-153705/`, a la que descendió y cerró. Fotos de las tres aproximaciones: `inspection/task7-152934-try1-approach.jpg` a `try3`, revisadas sin personas. Hay cuatro fotos privadas de cierre, subida y reapertura de la última corrida, también revisadas sin personas; los videos completos aún requieren revisión individual antes de publicación.

**Corte del operador: 18:00 de Lima.** La entrega permanece a las 21:00. Tarea 7 aún sin ciclo completo; Tarea 8 pendiente. No se acredita todavía un ciclo físico planificado y juzgado por Muse.

**Primeras corridas, hasta las 13:21.** Dos corridas de Tarea 7:
- `20261104-125332.json`: 35,7 s, 23 órdenes; dos intentos `reach_failed/no_progress` y una tercera iteración sin objeto. Sin descenso, cierre ni colocación.
- `20261104-131633.json`: 31,5 s, 20 órdenes; interrumpida durante el alcance cuando una mordaza desplazó la esponja al girar. Sin intento de agarre terminado.
- Tercer arranque, hacia las 14:30: detenido en preflight por movimiento USB de 32,7 px; cero órdenes y cero llamadas de Meta. Se fijó el soporte USB, se dejó holgura al cable y se recalibró para esa posición.

**Preparación medida, 14:46–15:26.**
- Marca única en el extremo de la mordaza azul; se mide su borde inferior y se cargan del atlas el rango HSV y la zona válida por cámara.
- La holgura del hombro produjo 45,07 px frontales y 29,53 px laterales entre aproximaciones opuestas. Con precarga de 60 µs, los residuos fueron 0,67 y 0,78 px; con 20 µs eran 21,71 y 13,58 px. Se fijó únicamente el hombro en 60 µs. Se mantienen los límites de pulsos, duración, velocidad y delta por orden.
- Abrir de 1382 a 1940 desplaza la marca +55,65/−36,15 px en C922 y +10,25/−3,85 px en USB. La predicción, selección de postura inicial y objetivo de agarre consideran la abertura para no confundir la punta abierta con el centro de cierre.
- Atlas activo: **32 posturas**, dos pasadas completas y concordantes; base 1583–1750, hombro 1400–1640, codo 2170–2290, abertura 1940. Repetibilidad de la primera pasada: 1,60/1,15 px; segunda: 0,57/0,49 px. Cámara estable durante el escaneo: 0,22/0,93 px. Atlas y referencia anteriores respaldados.
- El preflight ahora usa las esquinas del tag guardadas desde el cuadro original: una foto JPEG de referencia podía perder el tag al decodificarse. La imagen actual debe seguir mostrando el tag. Comprobación posterior: ambas vistas `still/marker`, 0,63 y 2,39 px.
- Con la esponja presente apareció un reflejo rosa que competía con la cinta en USB. La regresión con el recorte real falló antes de filtrar componentes de saturación mediana inferior a 50. El filtro conserva exactamente las 140 detecciones de las dos pasadas: cero pérdidas y cero desplazamiento añadido. Comprobación en vivo y suite final en curso.

**Muse y presupuesto.** Siete respuestas HTTP 200 confirmadas, USD **0,09349700**: cinco planificaciones de dry-run/corridas hasta las 14:28, un juicio retrospectivo y el nuevo dry-run de las 15:22 (USD 0,01169575). El juicio retrospectivo costó USD 0,01705375 y confirmó el empuje de la segunda aproximación; no dirigió movimientos. Un primer dry-run agotó el timeout de 25 s y su costo facturado no está confirmado. Las dos corridas físicas conservaron cero juicios de fase en vivo: la primera salió antes de solicitarlos y la segunda fue interrumpida. El nuevo plan considera factible el destino A. Tope configurado por corrida: 8 llamadas y USD 0,15; presupuesto total USD 1.

**Destino y perfil.** Aprobación vigente del operador: A, base 1583, sobre la mesa y libre. Se usa esa base fija en lugar de +117 µs y se comprueba que esté cubierta por el atlas. El próximo ensayo comienza con el perfil que levantó en H1: offset 0, profundidad 90, 5 pasos, abertura 1940 y codo mínimo 2050; tras ese primer intento se reanuda la política habitual. El atlas actual limita el codo a su espacio medido.

**Código, cada cambio con su prueba.**
- `tests/test_autonomy.py`, `test_meta.py` y `test_skills.py`: cierre del registro ante errores/Ctrl+C; escritura atómica de log y memoria; respuestas fuera de esquema; timeout HTTP y espera de juicio de 25 s; conservación del plan y solicitud de juicio tras agarre fallido.
- `test_autonomy_preflight.py` y `test_view_check.py`: marcador actual obligatorio en ambas vistas; rebase de hasta 10 px traslada el atlas; ECC y deriva mayor detienen antes del controlador. Esquinas guardadas válidas, rechazo de datos inválidos y uso repetido sin acumular desplazamientos.
- `test_daylight_vision.py` y `test_scene_detect.py`: tag con el mismo diccionario/id y detección diurna de la esponja, HSV (1,130,130)–(20,255,255). La mesa marrón (13,124,150) y el tablero oscuro siguen rechazados.
- `test_visual_servo.py`, `test_atlas.py` y `test_reach.py`: marca, máscara de zona, rechazo del reflejo, contexto de calibración y corrección de abertura; selección de postura con la pinza cerrada sin duplicar el desplazamiento.
- `test_arm_session.py`: precarga del hombro de 60 µs y conservación de todos los límites.
- `test_skills.py` y `test_reach.py`: elevar antes del alcance, abrir al valor elegido y detener antes de cerrar si el objeto se pierde o se desplaza durante la aproximación.
- `test_grasp_policy.py` y `test_autonomy_preflight.py`: repetir primero un perfil exitoso válido, ignorar registros antiguos/colocaciones y volver después a la política sin repetir el último perfil.
- Última suite completa aprobada antes del filtro de reflejos: **668 pruebas**. La suite con ese filtro está en ejecución.

**Evidencia y privacidad.** Videos de fallos: `inspection/video-125318/` (376 C922, 236 USB) y `inspection/video-131612/` (301, 189). `inspection/video-142925/` quedó sin cuadros por el aborto previo al servidor. El grabador consume el MJPEG existente y guarda horas de recepción del PC. Las fotos históricas de H1 se respaldaron. Las capturas nuevas siguen pendientes de revisión individual; algunas contienen personas y no deben publicarse.

**Estado actual.** Brazo energizado y quieto. Última lectura: MODE1=33, prescale=121; base 1699, hombro 1641, codo 2290, pitch 1182, roll 1567, pinza 1938. Esponja sobre la X. Se está validando con cámaras antes del siguiente ensayo; sin proceso de control del brazo.

**Pendiente.** Completar Tarea 7 con Muse en el lazo físico, luego tres ciclos completos grabados con resultado, segundos, llamadas y USD por ciclo. Escala de 50 ± 3 mm y holdout de 10 posturas solo después de un éxito y si queda tiempo. El modelo 3D anterior no acredita precisión métrica para el atlas nuevo.

## H1 (noche del 3 al 4 de noviembre): primer agarre y soltada autónomos con aprendizaje

**Resultado.** Ronda 11, intento 5: la política levantó la esponja (offset 0, profundidad 90, 5 pasos, abertura 1940, codo ≥ 2050; subió 62 px con la punta 30 px) y la soltó en el mismo lugar, sobre la X. Fotos: `inspection/grasp-012956-try5-*.jpg` y `inspection/autonomy-place-20261103.jpg`. La memoria de agarre tiene 36 intentos no legacy, `successes: 1` y offset aprendido 0. **Suite: 581 aprobadas.**

**Estado físico al cerrar.**
- Brazo energizado (MODE1=33) en base 1650, hombro 1540, codo 2290, pitch 1182, roll 1567, pinza 1850.
- Esponja acostada sobre la X.
- ArUco pegado detrás de la base, hacia la fuente; las dos vistas lo ven en 93–97 % de los cuadros.
- Referencia de vistas guardada en el reescaneo. La USB deriva lentamente (hasta 3.4 px en la noche).

**Qué se hizo, en orden.**
1. **Reinicio:** el PCA estaba reiniciado (MODE1=17). Se energizó en la postura estimada desde las fotos; el codo y la muñeca estaban fuera de rango y el operador aceptó el salto.
2. **Atlas:**
   - reescaneo de 60 posturas, sin esponja;
   - extensión de filas altas en base 1600/1650 y 1700/1750;
   - filas bajas en base 1600/1650/1700;
   - resultado: **102 posturas, base 1150–1750**.
   - Respaldos en `runs/real/calibration/capabilities_before_extension*_20261104.json`.
3. **`agree`:** las vistas dan `still`, pero el atlas no concuerda (desfase sistemático de 9–39 px). No bloquea, porque `reach` cierra el lazo.
4. **Ensayos:** 11 rondas de `grasp_place --learn`. Cada fallo destapó un problema de lógica, que se corrigió.

**Correcciones de código esta noche (cada una con su prueba)**
- `view_check`:
  - con el tag solo cuenta el desplazamiento; la rotación y la escala de un tag de ~100 px daban falsos movimientos de 5–107 px;
  - la ventana adaptativa del detector va de 3 a 53 px.
- **Objetivo de agarre y colocación:** la C922 fija solo la posición lateral (el giro de la base) y la USB fija la altura. Antes los dos objetivos se contradecían.
- **Agarre con política:**
  - un `reach` fallido queda como intento `reach_failed`, con su error y su postura, y el agarre sigue con otros parámetros; con 3 seguidos pide ayuda;
  - `object_lost` solo cuando tampoco la ve la C922;
  - si una mordaza queda oculta detrás de la esponja, el descenso sigue mientras la C922 vea la punta (idea del operador);
  - «levantó» se juzga tras 2 pasos: la esponja debe subir al menos el 40 % de lo que sube la punta, con un mínimo de 10 px. Así, agarrada por una esquina y pivotando, también cuenta.
- **Soltada:** cuenta como soltada si la esponja no subió con la pinza, aunque al caer se haya corrido.
- **Política:** 20 juegos de parámetros; se agregaron los offsets hacia dentro +15 y +30.
- **Detector de esponja:** H ≥ 5, S ≥ 130, V ≥ 160. De noche la USB ve la cara en sombra más roja.
- **`grasp_place.py`:** sigue un `rebase` ≤ 10 px medido con el tag, que es la deriva de la USB, en vez de pedir un reescaneo.

**Pendiente para H2**
- **Colocación a +117:** desde la X sale del atlas y va hacia el borde de la mesa. Esta noche se soltó en el mismo lugar, con una copia temporal de `grasp_place.py` con `base=pick["base"]`. Hay que elegir un destino dentro del atlas y sobre la mesa.
- **Orientación de la esponja:** la pinza no rodea su lado ancho. Agarra por la esquina o de forma marginal hasta que se gira con el lado delgado entre las mordazas.
- **Entrega:** README y página de inicio.

## Para H1: cambios de la tarde del 3 de noviembre (sin hardware)

**Suite completa: 562 aprobadas** (antes 546). Nada corrió en hardware. Los subcomandos nuevos se simularon con cámaras y brazo falsos; todas las órdenes pasaron por el `_check` real de `ArmSession`. Los datos reales no cambiaron.

**Qué cambió para H1**
- **`grasp_place.py --learn` (Tarea 3.3)** registra cada intento solo:
  - `seconds` dentro de cada `attempt` de `skill_memory.json`;
  - dos fotos de ambas cámaras por intento: `inspection/grasp-<HHMMSS>-try<N>-descent-20261103.jpg` (fin del descenso, pinza todavía abierta) y `…-lift-…` (tras la primera subida). Cada foto suma ~0.5 s al intento.
  - Si se niega a mover porque una cámara se movió, ahora dice que hay que reescanear (ya no sugiere `agree`).
- **Muse** solo se consulta cuando la clase local del intento es `not_lifted`.
- **`autonomy_run_20261103.py --scan` ya está protegido:** si el escaneo no terminó o la revisión de vistas posterior no da `still`, la corrida se detiene antes de abrir `ArmSession`.
- **`ArmSession`:** la duración por defecto se redondea hacia arriba al milisegundo. Un paso de 158 µs ya no aborta la corrida, y ninguna orden pasa de 300 µs/s.
- **Holgura (Tarea 4.4, código):** `OVERSHOOT_US` por articulación, hoy 20 en todas; `travel` deja lugar al mayor sobrepaso del tramo. Con 20 en todas, las órdenes son idénticas a las de antes.
- **`/autonomy`:**
  - tabla «What it learned» con la tasa estimada de los 12 juegos de parámetros, el mejor primero;
  - aviso «Frozen since HH:MM:SS» junto a la cámara que lleva más de 4 s sin cuadros nuevos (en Live).
- **Al fijar `MARKER_HSV`, la suite sigue en verde:** las pruebas del detector azul ahora ponen `None` por su cuenta.

**Subcomandos nuevos** (`.venv/Scripts/python.exe -m inspection.arm_checks_20261103 …`)
- **`hsv`** (H1 paso 3; solo cámaras, no mueve el brazo):
  1. `hsv` sin cajas guarda `inspection/marker_hsv_c922.jpg` y `inspection/marker_hsv_usb.jpg` en 1920×1080. Abrirlas y anotar una caja en píxeles **dentro** de la cinta: sin mesa, mordaza ni borde.
  2. `hsv --box usb X0 Y0 X1 Y1 --box c922 X0 Y0 X1 Y1` imprime:
     - los percentiles HSV de cada caja;
     - un rango común, con la línea `MARKER_HSV = (…)` para pegar en `premonition/visual_servo.py`;
     - por vista: `marker`, `inside_box` y `accepts`, la fracción del cuadro que acepta el rango.
  3. **Aceptar** el rango solo si `inside_box` es `true` en las dos vistas y `accepts` < 0.01; un buen rango ronda 0.001. Si `accepts` es mayor, la caja tomó mordaza azul: dibujarla más chica.
  4. **Chequeo por postura:** con `MARKER_HSV` pegado, `hsv` sin cajas imprime el `marker` de cada vista. Repetirlo en las 10 posturas; la regla de 20 min y ≥ 95 % en la USB no cambia.
- **`backlash`** (Tarea 4.4; H1 paso 7, ~5 min, **esponja fuera de la mesa**):
  - Sirve la vista en vivo y va a base 1550, hombro 1480, codo 2170.
  - Para base, hombro y codo, 3 veces cada protocolo: B (desde abajo), A (desde arriba con `settle_move`) y C (desde arriba sin asentar).
  - Imprime cada articulación al terminarla. Al final escribe `runs/real/calibration/backlash_20261103.json` con `gap_px` y `gap_us` (A−B y C−B) y las puntas de cada repetición.
  - **Regla del plan:** solo si |A−B| > 5 px en la USB, cambiar a mano `OVERSHOOT_US[j] = min(60, ceil(gap_us) + 10)` en `premonition/arm_session.py`. Comparar antes con la dispersión de las repeticiones.
- **`scale`** (Tarea 1.3, H2; solo cámaras):
  - Necesita el ArUco visible en las dos vistas.
  - Escribe `mm_per_unit` y `table` en `runs/real/calibration/arm_model.json`. Si una vista no ve el tag, no escribe nada.
- **`holdout --poses 10`** (Tarea 1.3, H2, después de un ensayo exitoso, **esponja fuera de la mesa**):
  - Sirve la vista en vivo y visita 10 posturas al azar dentro de la caja escaneada.
  - Imprime primero las muestras crudas, y después el error en px por vista del modelo y del atlas y el error en mm (`null` si no se corrió `scale`).
- **Control independiente de la escala** (H2, no tiene subcomando). Con los extremos de la marca de 5 cm en píxeles de las dos vistas (por ejemplo, de los jpg que guarda `hsv`), el resultado debe dar 50 ± 3 mm:
  ```
  .venv/Scripts/python.exe -c "import json; from premonition import arm_model as m; k=m.from_json(json.load(open('runs/real/calibration/arm_model.json'))); r=m.scale_from_segment(k, {'c922': [(X0,Y0),(X1,Y1)], 'usb': [(X0,Y0),(X1,Y1)]}); print(round(50*k.mm_per_unit/r['mm_per_unit'],1), 'mm')"
  ```

**Cambios en los pasos de H1** (lista «Qué falta para H1», abajo)
- **Paso 3 (cinta):** muestrear con `arm_checks hsv` en vez de a mano.
- **Paso 6 (Tarea 3.3):** los segundos y las fotos quedan solos. Anotar los nombres de las fotos del primer intento que levante.
- **Paso 8:** `arm_checks backlash` ya existe. Correrlo si sobra tiempo, con la esponja fuera de la mesa.
- **`--scan`:** `autonomy_run_20261103.py --scan` ya se puede usar. Sigue siendo más directo reescanear con `python -m inspection.capability_scan_20261103`.

## Brazo 3D, aprendizaje del agarre y autocalibración: avance del 3 de noviembre (sin hardware)

Hoy no se movió el brazo ni se abrieron las cámaras.

**Hecho (código con pruebas; suite completa: 546 aprobadas, antes 478)**
- **Requisitos de H1, completos:**
  - **3.1** `premonition/grasp_policy.py`: 12 juegos de parámetros de agarre, la clase de cada fallo y la elección del siguiente intento por muestreo de Thompson.
  - **3.2** `grasp(..., choose=)` usa la política y registra cada intento en `skill_memory.json` (`attempts`; los 8 `failures` viejos quedan como `legacy`). Sin `choose`, mueve el brazo igual que antes (comprobado en 26 escenarios simulados).
  - **4.1** `premonition/view_check.py` detecta si una cámara se movió (ArUco de la mesa o ECC con máscara) y decide entre `still`, `rebase` y `rescan`.
  - **4.2** Detector de cinta magenta, apagado hasta fijar `MARKER_HSV`. Cada muestra del escaneo guarda además la punta azul (`tip_blue`), y el escaneo guarda los cuadros y un `detector_report`.
  - **4.3** `inspection/arm_checks_20261103.py views|agree|fit`, la revisión de vistas antes de mover en `autonomy_run_20261103.py`, y la referencia de vistas en el escaneo.
- **Línea 1 (3D):** 1.1 `premonition/arm_model.py`; 1.2 el ajuste conjunto. Ya están escritos `runs/real/calibration/arm_model.json` y `arm_model_fit_report.json`, marcados como **aproximados**.
- **Línea 2 (interfaz):** 2.1 las rutas `/api/arm/*` y `/api/autonomy/runs/{id}`; 2.2 `/autonomy` rehecho como banco en vivo, con video, brazo 3D en Canvas 2D y repetición.
- **Revisión final y ronda de arreglos:**
  - la vista en vivo se sirve antes del primer movimiento en `agree`, en el escaneo y en el preflight;
  - `agree/views --save` no guardan si la cámara se movió;
  - `grasp_place.py` revisa las vistas antes de mover y guarda la memoria aunque falle.

**Cambios de uso**
- `autonomy_run_20261103.py` aprende por defecto; con `--no-learn` vuelve a los desplazamientos fijos. `grasp_place.py --learn` hace hasta 5 intentos.
- **Paradas nuevas con la política:**
  - `object_lost` y 3 fallos seguidos de la misma clase → pide ayuda, con un texto por clase;
  - más de 300 s → `time_limit`.
- Después de un fallo, el brazo sube al menos lo que bajó.
- Si una cámara se movió, `grasp_place.py` se niega a mover. Solo lo destraba un reescaneo, y el mensaje ahora lo dice (tarde del 3 nov).
- `autonomy_run_20261103.py --scan` quedó protegido la tarde del 3 nov: si el escaneo no termina o la revisión posterior no da `still`, la corrida se detiene antes de mover.

**Tarea 4.1, paso 5: 209 pares consecutivos de capturas de la C922 del 2 nov (sin ArUco, por ECC)**
- El corrimiento de esa noche quedó entre `20261102-173845` y `20261102-222202`: `moved_px` 201.3 → `rescan`.
- Otros 5 pares pasan de 100 px, y todos son movimientos reales: la colocación de la cámara a las 12:05–12:07 y el salto de la noche.
- 196 pares salen `still` (p95 2.0 px, máximo 2.7 px).
- 7 salen `rebase`:
  - uno es real (`151125→151835`, 5.0 px);
  - seis son falsos positivos: una mano en cuadro (18.6 px), una persona con un objeto nuevo (4.5), un papel (3.3) y tres en el piso de ruido de ECC (3.0–3.3).
- No hubo falsos `rescan`. Tarda 0.30 s por par (mediana).

**Tarea 1.2, paso 5: ajuste conjunto de los tres atlas (`current`, `oldcams`, `gooseneck`), ~20 min de las 3 h**
- **RMS en `current`** (puntos ≤ 15 px): C922 6.27 px y USB 7.31 px; con todos los puntos, 7.76 y 11.79. **No cumple** el tope de 6 px.
- **Holdout por base, modelo contra atlas** (medianas):
  - C922 7.2 contra 22.7 px y USB 9.5 contra 14.2 px: cumple el criterio de ≤ 1.5×;
  - en los bordes **no cumple**: en 1150 gana en la C922 (7.3 contra 20.5) pero no en la USB (23.1 contra 22.5); en 1650 pierde en las dos (C922 21.2 contra 11.1, USB 12.2 contra 9.0).
- **Ganancia de la base:** 1.943e-3 rad/µs = **0.111 °/µs**, un 32 % sobre 0.084. **No cumple.** Cada atlas por separado da 0.103–0.119. El 0.084 salió de un barrido de 4 puntos con la f nominal, así que la referencia también es dudosa.
- **Error epipolar** (`current`): mediana 2.65 px, p90 14.7 y máximo 29.8, con 31 de 64 inliers.
- El residuo que queda parece **juego mecánico**: desfases del mismo signo en los tres atlas, hombro −6…−9 µs y codo −9…−13 µs. No se agregó al modelo; corresponde a la Tarea 4.4.
- Como dice el plan, la línea 1 se detiene aquí. La interfaz dibuja el ajuste con la leyenda «approximate geometry».
- La geometría ajustada tiene el brazo superior casi vertical con el hombro en 1500 (z_shoulder ≈ 471 µs, a1 −0.24, v −1.33). Conviene compararla con una foto antes del video.

**Qué falta para H1 (todo es hardware; el código requerido está listo)**
1. **Tarea 0:**
   - `both_cams.py <tmp> pre`, registros con MODE1=33, sin `motion_hold.json`;
   - si MODE1=17, reiniciar en la postura que se ve en las fotos.
2. **ArUco:**
   - Generar la imagen:
     ```
     .venv/Scripts/python.exe -c "import cv2,numpy as np; d=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50); m=cv2.aruco.generateImageMarker(d,0,591); c=np.full((827,827),255,np.uint8); c[118:709,118:709]=m; cv2.imwrite('inspection/aruco_4x4_50_id0_50mm_300dpi.png',c)"
     ```
   - Imprimirla a 100 % y medir el cuadro negro con la regla: debe dar 50.0 mm. Si no, guardar la medida en `TABLE_MARKER_MM` (`premonition/view_check.py`).
   - Pegarla plana junto a la base, fuera del barrido del brazo y de la esponja.
   - `python -m inspection.arm_checks_20261103 views` debe decir que las dos vistas ven el tag.
3. **Cinta magenta:**
   - Abrir y cerrar la pinza (1616↔1850) para ver cuál mordaza es fija.
   - Poner el anillo en la punta de la mordaza exterior.
   - Muestrear su HSV en un cuadro en vivo y fijar `MARKER_HSV` (el rango inicial de prueba es `((140, 80, 80), (172, 255, 255))`).
   - Comprobar 10 posturas a mano: `detector_report` no sirve para medir la visibilidad en la USB, porque el escaneo se detiene en cuanto la USB pierde la punta.
   - Si en 20 min no llega al 95 % en la USB: `MARKER_HSV = None`.
4. **Reescanear** con la esponja fuera de la mesa: `python -m inspection.capability_scan_20261103`.
   - Ahora sirve la vista en vivo y guarda los cuadros, el `detector_report` y la referencia de vistas.
   - El atlas anterior, con la extensión 1600/1650 que este escaneo borra, quedó respaldado en `runs/real/calibration/capabilities_before_h1_20261103.json`.
5. **Guardar la referencia verificada:** `python -m inspection.arm_checks_20261103 agree --save`, con manos y personas fuera de cuadro.
6. **Tarea 3.3:** `.venv/Scripts/python.exe inspection/session_tools_20261103/grasp_place.py --learn`.
7. **Si levanta:** `place` va incluido en `grasp_place.py`. Después, `autonomy_run_20261103.py --instruction "…" --dry-run`.
8. **`arm_checks backlash` (Tarea 4.4):** escrito la tarde del 3 nov; ver la sección de arriba.

**Para tener a mano esta noche:** el ArUco impreso al 100 % (la imagen mide 70 mm de lado y el tag negro 50 mm), una regla y cinta magenta.

## Autonomía: avance de la madrugada del 3 de noviembre y cómo retomar

**Hecho (código con pruebas; suite completa: 478 aprobadas)**
- **Tarea 1.** `premonition/arm_session.py` deja el controlador abierto toda la sesión. Medido: apertura 1.75 s, cada orden 0.5 s (antes ~7 s).
- **Tarea 2.** `premonition/dual_camera.py` mantiene las dos cámaras en transmisión: C922 a 8 fps, USB a 5–6 fps, cuadros reescalados a 1920×1080. `serve()` da una vista en vivo en http://127.0.0.1:8767 con los mismos cuadros.
- **Tarea 3.** `premonition/scene_detect.py` detecta la esponja. Umbral nuevo: H 10–20, S ≥ 110, V ≥ 170. En la USB la esponja sale lavada, y con el umbral viejo se tomaba la tabla rojiza en sombra.
- **Tarea 4.** `premonition/atlas.py` + `inspection/capability_scan_20261103.py`: el escaneo de capacidades es un solo comando (dos pases unidos, ~5 min, **con la esponja fuera de la mesa**).
  - Atlas actual: 60 posturas más 12 de extensión (base 1600/1650, solo hombro 1640/1560).
  - Repetibilidad: 0.4–0.5 px.
- **Tarea 5.** `premonition/reach.py`: alcance multiarticular con jacobiano local del atlas y Broyden. Con la vista anterior llegó en 2 movimientos y 7.8 s (error 1.9 px).
  - Pasos acotados a la caja escaneada.
  - Descarta la punta C922 que se aleja más de 80 px de lo que predice el atlas.
  - Un cuadro con salto se revisa dos veces antes de declarar divergencia.
- **Tareas 6–8 (sin validar en hardware).**
  - `premonition/skills.py`: agarrar y soltar con comprobación local y reintentos.
  - `premonition/autonomy.py`: Muse planifica y juzga, SAM sirve de respaldo.
  - Rutas `/autonomy` y panel `static/autonomy.html`.
  - Ejecutable `inspection/autonomy_run_20261103.py --instruction "…" [--scan] [--dry-run]`.

**Incidentes y hallazgos**
- **Cámara USB.** A las 01:41 se desconectó y su vista giró ~200 px durante un agarre (probable tirón del cable).
  - Montada detrás del brazo, en un soporte flexible, salió peor: repetibilidad 3.5 px y la punta saltaba.
  - Quedó de perfil a la izquierda, más alta; ahí repite a 0.4 px.
  - `BASE_PX` actual: C922 (1200, 770), USB (1130, 880). La C922 también se desplazó ~120 px.
  - Si una cámara se mueve: medir `BASE_PX` con `locate_tip` sobre una foto y reescanear.
- **`locate_tip` corregido.** Si el cuerpo azul alcanzado desde la base era corto, devolvía el centro de la imagen (959.5, 539.5) como punta.
- **Valores atípicos.** El detector C922 confunde a veces el brazo superior con la punta. Se anularon a mano dos valores atípicos del atlas (anotados en `capabilities.json`).

**Agarre: dónde quedó**
- **Posición de la esponja.** Está de pie sobre la X, ~2 cm más lejos del eje que el anillo donde agarra la pinza vertical (codo 2290, pitch 1182). El operador eligió ampliar el alcance:
  - el agarre sirve base, hombro y codo, con codo 2050–2290 (pinza algo inclinada);
  - tolerancia USB de 25 px;
  - pinza abierta a 1850 antes de bajar;
  - descenso de hasta 3 pasos de hombro −60, que se detiene si la esponja se desliza (lado interior `x1` ≥ 20 px).
- **Qué falla.** `reach` llega sobre el borde exterior en 1–2 movimientos, pero el descenso no mete la mordaza exterior por fuera del borde:
  - la punta queda ~20 px sobre el borde superior en la USB, y el brazo se desvía hacia la base porque las mordazas se apoyan en la cara superior;
  - la esponja es más ancha que la abertura de la pinza, así que hay que pellizcar el borde con la mordaza interior hundida en ella, como en el primer agarre.
- **Siguiente paso.** Apuntar la punta más afuera (borde exterior −15 a −30 px, no +15) y/o permitir más pasos de descenso. Alternativa: colocar la esponja dentro del anillo de la pinza vertical, con su lado delgado en la dirección del brazo.
- **Después.** `place` (destino base +117 µs), Tarea 7 en hardware (primero `--dry-run`) y ensayo y video de la Tarea 8.

**Estado físico al cerrar.** Base 1621, hombro 1401, codo 2051, pitch 1182, roll 1567, pinza 1851 (abierta), MODE1=33; la esponja sigue sobre la X. Si se apaga la Jetson o la fuente, el PCA se reinicia (MODE1=17): reiniciar en la postura que se vea en las fotos, con `inspection/session_tools_20261103/restart_last_pose.py` (ver «Contexto» del plan).

**Cómo retomar**
1. Ejecutar `both_cams.py <tmp> pre` y revisar registros, fotos y que las cámaras no se hayan movido.
2. Vista en vivo durante cualquier prueba: la sirve `DualCamera.serve()`. El visor `live_view.py` ocupa las cámaras: cerrarlo antes de mover el brazo.
3. Tras mover una cámara, primero `inspection/session_tools_20261103/repeat_check.py` y luego reescanear. Para agarrar y soltar: `.venv/Scripts/python.exe inspection/session_tools_20261103/grasp_place.py`. Para la tarea completa: `inspection/autonomy_run_20261103.py --dry-run`. Cómo se hizo la extensión del atlas: `inspection/session_tools_20261103/extend_scan.py`.

## Reinicio, detector azul y alcance, noche del 2 de noviembre

`locate_tip` ahora sigue la pinza azul en ambas cámaras (`BASE_PX` por vista). Recorre el brazo desde
la base, une las piezas azules por sus puntos más cercanos y promedia el extremo, para no saltar entre
mordazas. Se revisó a ojo en seis posturas y en las dos cámaras. Suite completa: **402 pruebas aprobadas**.

Al retomar, el PCA estaba reiniciado (MODE1=17, salidas apagadas) y **la C922 se había movido unos
150 px**: la escala de 5 cm y `arm_geometry_estimate_20261102.json` ya no valen para esa vista. Por
elección del operador se energizó la última postura, un canal cada 0.5 s
(`restart_last_pose_result_20261102.json`). En reposo no hay vibración visible: 1.2 px como máximo
en 6 s. Pasos `teaching_step_restart_*` y `teaching_step_twocam_*`; postura actual: base 1509,
hombro 1602, codo 2290, pitch 1562, roll 1567 y pinza 1616 µs (abierta).

Por indicación del operador («puedes girar más», «el brazo está sujeto») se recorrió la base hasta
1978 µs, de frente a la C922, y se volvió a 1567 µs, donde el brazo queda alineado con la esponja.
Se plegó el brazo fuera de lo recorrido antes, todo en pasos de 60 µs con foto vinculada: hombro
1309, codo 1997 (límite de la herramienta), pitch 1680, pinza abierta en 1616 µs. La pinza cuelga
casi vertical: la muñeca queda junto a la esquina superior izquierda de la esponja y las mordazas,
al costado de su extremo, fuera del borde de la mesa. Con la pinza colgando, subir el pitch la
inclina hacia la base; la primera medida de pitch con la pinza horizontal no sirve como guía.

**Agarre bloqueado por orientación:** las mordazas cierran en el plano del brazo, que coincide con el
lado largo de la esponja. El roll (1558→1968 µs y vuelta) no gira las mordazas en esta postura:
hace oscilar la pinza hacia un costado, porque gira alrededor del antebrazo, que aquí está casi
horizontal. Siguiente paso: que el operador gire la esponja 90°, con la cara ancha hacia la base y el
borde superior entre las mordazas. Después, cerrar la pinza y levantar.

**Lazo cerrado con las dos cámaras** (`visual_loop_twocam_hover01.json`; script de sesión
`inspection/session_tools_20261103/twocam_loop.py`). En cada iteración toma foto de ambas cámaras, detecta la punta azul y
la esponja (naranja con S≥160 para no confundirla con la madera) y apunta a 60 px sobre el centro
del borde superior de la esponja en las dos vistas. Aprende la sensibilidad de cada articulación en
4 coordenadas y da un paso de hasta 60 µs con la herramienta de siempre. Con el codo limitado a
2000 µs se estancó a ~320 px en la USB. Por orden del operador, **se amplió el límite superior del
codo a 2300 µs** en el controlador de la Jetson (respaldo `mindarm_arm.py.bak_20261102_elbow2000`,
hash nuevo `2ab17e54…` fijado en `approach_probe_20261102.py`). El lazo bajó el error a 207 px en la
USB y 108 px en la C922, con base 1509, hombro 1602, codo 2290, pitch 1562 y roll 1567 µs. Las
mordazas cuelgan junto a la esquina superior externa de la esponja. Suite: **403 pruebas aprobadas**.

Madrugada del 3 de noviembre, solo con movimientos del brazo: cerrar al costado no atrapó la esponja (la
empujó ~1.5 cm). Con la pinza baja tras su extremo exterior y un barrido de base 1147→1382 µs, el brazo
**giró la esponja ~90°**: ahora su espesor queda en la dirección de cierre de las mordazas. La pinza
quedó en su plegado máximo (codo 2290 de 2300, pitch 1182 de 1180 µs), justo en el borde exterior de la
esponja y ~2–3 cm sobre ella: le faltan ~2 cm hacia la base y bajar. Pasos `teaching_step_push_*` y
`teaching_step_grasp_*`.

**Primer agarre y levantamiento real, 3 de noviembre.** El operador acomodó la esponja bajo la pinza
abierta. Hombro −60 (mordaza exterior por fuera de la cara, bajo el borde), pinza 1616→1382 µs en tres
pasos y hombro +60 ×3: la esponja subió con la pinza en las dos cámaras (borde superior en la USB
569→510→466 px, ~4.7 cm, con aire bajo ella). Postura: base 1382, hombro 1582, codo 2290, pitch 1182,
roll 1567 y pinza 1382 µs, **sosteniendo la esponja**. Evidencia: `inspection/first-grasp-lift-20261103.jpg`;
pasos `teaching_step_final_*`. **Colocación:** base 1382→1616 (sobre la placa Arduino y el borde,
descartado) y vuelta a 1499; hombro hasta 1426 (contacto: el borde bajó 17 px en vez de ~35), pinza
1382→1616 y hombro +60 ×3. La esponja quedó en la mesa sin moverse: primer ciclo completo de agarre,
traslado (~3 cm) y suelta (`inspection/first-place-release-20261103.jpg`, pasos `teaching_step_place_*`).
El agarre depende de que la esponja
quede con su espesor en la dirección de cierre y dentro del alcance (≥ ~17 cm del eje con codo ≤2300).

El detector de punta falla en la C922 cuando la pinza apunta a esa cámara; en la USB sigue bien. Sensibilidades medidas con el brazo extendido en la USB (px/µs, x hacia la base):
hombro (+0.36, −0.64), codo (−0.16, +0.57); con el brazo plegado, el codo mueve la punta hacia la
base y hacia abajo.

## Corrección visual en ciclo cerrado, 2 de noviembre

Por orden explícita del operador se retiró el bloqueo (`motion_hold.cleared_by_operator_20261102.json`,
registro en `motion_hold_clearance_20261102.json`). **La causa de la vibración sigue sin identificarse**
y no se volvió a la postura con codo 1733. Las seis articulaciones respondieron en pasos pequeños.

Nuevo `premonition/visual_servo.py`: localiza la punta en la foto, elige una articulación, corrige su
sensibilidad medida y, si un paso no mueve la punta, reintenta más amplio y se detiene tras dos
reintentos. No sale de los pulsos ya recorridos. `inspection/visual_approach_20261102.py` separa
`decide`, que no mueve nada, de `execute`, que exige el hash de la foto revisada y usa el mismo paso
de una sola articulación. Primera ejecución, `visual_loop_hover01.json`: error de 141 a 3 px en
imagen, con 5 pasos y un reintento. No es autónomo todavía: cada foto se revisó antes de actuar.
Es posición en imagen: no mide profundidad y no hubo contacto, agarre ni transferencia.

Evaluación de inercia en `inertia_evaluation_20261102.json`: la velocidad no ayudó, un paso más
amplio sí, y llegar desde el mismo lado repite a 5 px frente a 46 px desde el contrario.
Corridas `rep01` y `rep02`: se alejó a 15.8 px de otro punto, límite de resolución del paso mínimo,
y volvió al objetivo inicial con 9.5 px de error y codo 1646, frente a 1616 en la primera llegada.
Barrido solo de base, `arm_geometry_estimate_20261102.json`: en esa postura la punta está a unos
24 cm de la mesa y 25 cm del eje, estimados con una cámara. La esponja queda a unos 15 cm, casi a
la izquierda del eje, fuera de las bases recorridas. La superposición en imagen no indicaba cercanía.
Últimos pulsos: base 1567, hombro 1367, codo 1646, pitch 1562, roll 1558 y pinza 1538 µs.
Suite completa: **398 pruebas aprobadas**. README y HARDWARE aún describen la suspensión.

Segunda cámara conectada a la Jetson: C922 en `/dev/video0` y USB 2.0 en `/dev/video1`, sobre el
escritorio superior y casi de perfil al brazo. Con luz del cuarto se ven brazo, pinza y esponja en
ambas. La cámara USB necesita al menos 30 lecturas (`--reads 30`) para estabilizar la exposición.
La app sigue mostrando solo la C922. Scripts y vistas de la sesión: `inspection/session_tools_20261102/`.

**Para retomar:** no mover las cámaras. 1) Cambiar `locate_tip` para seguir la pinza azul en ambas
vistas; el detector blanco queda fuera de zona y la pared está cerca de su umbral. 2) Calibrar la
cámara 2 con un giro corto de base y medir altura real. 3) Decidir entre mover la esponja frente al
brazo o girar la base, nunca probada, hacia unos 1140 µs. 4) Acercar y agarrar. Sigue pendiente la
primera corrida completa con Meta, mover a Git lo que está en `inspection/` y actualizar README.
El bloqueo sigue retirado por orden del operador; la causa de la vibración no está identificada.

## Movimiento suspendido: vibración sin respuesta fiable, 2 de noviembre

El operador informó «vibra pero no se mueve». Se suspendieron las pruebas y se pidió apoyar
el brazo y desenchufar la fuente externa de los servos. La desconexión física aún no está
confirmada. No quedan procesos del brazo; eso no desactiva las salidas del PCA ni quita fuerza.

Últimos pulsos comandados: base 1743, hombro 1450, codo 1733, pitch 1602, roll 1499 y pinza
1616 µs; MODE1=33, PRESCALE=121. **La postura física actual no está reconciliada.**
No se validaron contacto, agarre ni transferencia. El operador negó contacto en dos candidatos.

Se creó `runs/real/calibration/motion_hold.json`: su presencia bloquea las utilidades de
aproximación, muñeca y HOME antes de acceder al controlador. Se requiere resolver y documentar
la causa física antes de retirar ese bloqueo. No se enviaron HOME, liberación PWM ni nuevas
órdenes después del aviso. Incidente: `runs/real/calibration/vibration_incident_20261102.json`.

Referencias de imagen seleccionadas: esquina fija de la tabla P0, superficie superior T y
punta de mordaza J, en `contact_reference_20261102.json`. La coincidencia en píxeles no
resultó suficiente para confirmar contacto. La lectura electrónica de los pulsos tampoco
prueba movimiento real. La causa de la vibración sigue sin determinarse.

Validación: suite de 371 pruebas aprobada antes del bloqueo; 68 pruebas específicas de
utilidades e interbloqueo aprobadas después. Los resultados de software no validan el hardware.
Las secciones siguientes son históricas.

## Avance anterior: alineación elevada y primera aproximación, 2 de noviembre

El operador confirmó estabilidad tras los primeros pasos de base y codo; se guardó
**APPROACH_BASE_ELBOW_01**. Se continuó con cuatro pasos separados de base y uno de codo,
todos de 4 s, con imagen y lectura entre órdenes. Última lectura: base **1792**, hombro
**1372**, codo **1616**, pitch 1602, roll 1499 y pinza 1616 µs; MODE1=33, PRESCALE=121,
sin procesos del brazo y salidas mantenidas por el PCA.

La pinza quedó próxima a la esponja en la imagen, sin agarre. El análisis
`75581d9487d542b299857b5a67dc8e56` clasifica por primera vez el detalle de las mordazas como
**clear**; SAM segmenta el conjunto con guía de Muse y detecta la esponja por nombre.
Se espera una observación lateral del operador sobre alineación y separación física antes de
otro descenso: aún no hay profundidad o transformación cámara-robot calibrada.

El usuario preguntó por la lentitud. Se explicó que los 4 s son parámetros de prueba para
una trayectoria nueva sin realimentación de posición; no se cambiaron las velocidades.
Los desplazamientos en espacio libre podrán temporizarse después de validar las poses y rutas.
No hubo agarre ni transferencia. Evidencia: `inspection/pregrasp-clear-gripper-20261102.png`;
estado y ensayos en `runs/real/calibration/transfer_session_20261102.json`.

## Avance anterior: primeros pasos de base y codo, 2 de noviembre

El operador confirmó esponja colocada directamente sobre la tabla, zonas despejadas y manos
fuera del recorrido. Una imagen nueva y Muse/SAM localizaron la esponja completa: escena
`8ef96202c176454ba41924c58d977fec`. Su posición real queda parcialmente fuera del recuadro
propuesto, por lo que no se infiere aceptación de esas coordenadas de imagen.

Se ejecutaron dos pasos separados de 4 s, con la pinza elevada y abierta: base 1499→1559
(lectura 1558) y codo 1499→1559 (lectura 1558). Los otros registros no cambiaron. Hay imágenes
antes/después y ACK de cada orden. Muse dejó el codo como incierto; SAM, guiado por la misma
región seleccionada en ambos JPEG originales, segmentó el conjunto de pinza. La comparación
revisada visualmente dio desplazamiento del centro de máscara de -28.47,+50.08 píxeles.
Esto respalda movimiento en la imagen, sin medir distancia física ni validar la trayectoria.

Estado actual: base **1558**, hombro **1372**, codo **1558**, pitch 1602, roll 1499 y pinza
1616 µs. MODE1=33, PRESCALE=121, sin procesos del brazo y pulsos mantenidos. Se espera la
observación del operador sobre estabilidad/ruido antes de seguir. Próximo paso preparado,
todavía sin ejecutar: base 1558→1618 µs en 4 s. No hubo agarre ni transferencia.
Suite completa: **370 pruebas aprobadas**, una advertencia de deprecación de TestClient.
Detalle: `runs/real/calibration/transfer_session_20261102.json`.

## Avance previo: primera postura de aproximación, 2 de noviembre

El operador confirmó la base fijada a la mesa. Se probó solo el hombro: primero 1450→1430 µs
(lectura 1431), retorno y repetición solicitados por el operador. El cambio pequeño no se
distinguió en cámara. A petición del usuario se amplió a 1431→1370 µs en 4 s (lectura 1372).
La cámara y Muse confirmaron desplazamiento de la pinza hacia la izquierda y abajo en la
imagen; el operador confirmó movimiento suave y postura estable. Se guardó
**APPROACH_SHOULDER_01**, sin validar todavía una ruta de recogida.

Pulsos actuales: base 1499, hombro **1372**, codo 1499, pitch 1602, roll 1499 y pinza 1616 µs.
MODE1=33, PRESCALE=121; ningún proceso del brazo. El PCA sigue manteniendo los pulsos.
Se prepararon dos zonas en la interfaz para colocar la esponja directamente sobre la tabla y
despejar los cables. Falta la preparación física del operador antes de seguir acercándose.
No hubo agarre ni transferencia. Sesión: `runs/real/calibration/transfer_session_20261102.json`.
Validación posterior: suite completa de **349 pruebas aprobada**, con una advertencia de
deprecación de TestClient; 27 comprobaciones específicas de estas órdenes de hombro.

## Comprobación previa: vídeo y vista de pinza, 2 de noviembre

- Vídeo real en `/calibration`: **Go live**, 1280×720 a unos 8 fps, sin llamadas a Meta.
  **Refresh photo** y **Analyze scene** liberan el vídeo antes de capturar a 1920×1080.
  Los contornos se muestran sobre su foto analizada, nunca sobre vídeo posterior.
- Se ejecutaron solo giros de roll dentro del tramo ya observado, su retorno a 1499 µs y
  apertura de pinza a 1616 µs. El operador confirmó movimientos suaves y reposo estable.
  Base 1499, hombro 1450, codo 1499 y pitch 1602 µs sin cambios. Lectura final MODE1=33,
  PRESCALE=121 y ningún proceso del brazo; el PCA sigue manteniendo los pulsos.
- La búsqueda SAM por nombre dio cero pinzas. Se añadió una alternativa automática: Muse
  propone una región en píxeles de la foto original y SAM la segmenta. Prueba real:
  **una máscara parcial de las puntas de las mordazas**, una esponja, cuatro HTTP 200,
  coste estimado USD 0.0198975. La interfaz identifica el resultado como **model-guided**.
  El detalle sigue limitado; no se validó un agarre ni un recorrido.
- **Select gripper** permite una selección manual sobre la foto actual, identificada como
  **selected**, con hash y procedencia conservados. No sustituye una máscara ausente por una caja.
- Suite completa: **322 pruebas aprobadas**, con una advertencia de deprecación de TestClient.
  Informe: `runs/real/calibration/visibility_session_20261102.json`; escena automática:
  `runs/real/calibration/scenes/806e0cea686a4676b7c7856daf2d7230.json`.

Siguen pendientes la geometría cámara-robot, los umbrales visuales y las poses/transiciones de
aproximación, recogida, elevación y colocación. La propuesta de destino en la mesa no está
confirmada. No se ejecutó una transferencia. Las secciones siguientes son comprobaciones previas.

## Avance previo de calibración y visión real del 2 de noviembre

- Parada identificada por el operador: desenchufar la fuente externa de los servos de la corriente.
  Se registró el procedimiento; no se hizo una prueba de corte de potencia.
- El controlador se había reiniciado: MODE1=17, PRESCALE=30 y seis salidas desactivadas. Con la
  preparación física confirmada se restauró solo el HOME histórico, un canal cada 0.5 s. ACK
  correcto y lectura final MODE1=33, PRESCALE=121; pulsos 1499, 1450, 1499, 1602, 1499 y 1499 µs.
  El operador confirmó reposo estable. El proceso se cerró; el PCA mantiene los pulsos.
- Se registró **OBSERVE_C922** y se configuró como pose de observación, sin validar rutas.
- Nuevo **Analyze scene** en la interfaz: foto nueva, Muse Spark y dos consultas SAM, con
  contornos sobre la imagen correcta, evidencia y coste estimado persistentes. Una segunda
  solicitud concurrente se rechaza. Actualizar la foto retira las detecciones antiguas.
- Prueba real: tres HTTP 200; Muse reconoció brazo/esponja y señaló detalle limitado de pinza.
  SAM detectó una esponja y ninguna pinza. Coste estimado USD 0.01443775. Informe:
  `runs/real/calibration/scenes/b5ceeabe47314b518964c55e1f55095e.json`.
- Selección de zonas en la imagen implementada, con comprobación de límites, superposición,
  integridad y captura vigente. El destino elegido por el usuario es otra zona libre de la mesa.
  La propuesta está en `runs/real/calibration/workspace_proposal_20261102.json`, pendiente de
  revisión del operador. No son coordenadas del robot.
- Validación: suite completa de 294 pruebas aprobada; después se aprobaron las 25 pruebas de
  escena/regiones, incluidas dos nuevas sobre la propuesta persistente. Revisión visual con
  contornos visibles, borrador recuperable, bloqueo de confirmación y diseño de 390 px sin
  desborde. Evidencia: `inspection/workspace-proposal-20261102.png`.

Faltan las posturas y transiciones de aproximación, recogida, elevación y colocación; apertura
útil para esta esponja, umbrales de percepción y el backend autónomo. No se ejecutó ninguna
transferencia de objeto. Las secciones anteriores al 2 de noviembre que siguen son históricas.

## Comprobación inicial de cámara C922 del 2 de noviembre

La Logitech C922 Pro Stream está conectada a la Jetson en `/dev/video0`, con
controlador UVC. Se comprobó MJPEG 1920×1080 y modo anunciado/negociado de 30 fps;
esta prueba de fotos no mide rendimiento continuo de vídeo. El enfoque manual
funciona: se dejó `focus_auto=0`, `focus_absolute=30` tras comparar una región de
la pinza con el encuadre actual. Hay imagen del brazo completo y la mesa.
Tres capturas consecutivas desde `/calibration` se decodificaron y mostraron sin
errores. Última foto: `runs/real/captures/20261102-120803-c92e641b.jpg`;
evidencia de interfaz: `inspection/c922-interface-final.png`.
La interfaz muestra fotos con «Refresh photo»; no hay transmisión continua.
No se enviaron órdenes al brazo ni se hicieron llamadas a Meta en esta prueba.
La calibración geométrica, la verificación de movimientos y los umbrales visuales
siguen pendientes. El resultado anterior de Muse corresponde a la cámara antigua.

## Verificación y correcciones del 1 de noviembre

### Vista de pinza y análisis real con Muse, última comprobación

Se mejoró la vista con dos pasos pequeños de roll, se devolvió la pinza a 1499 µs
y se restauró un ajuste exploratorio de pitch. La lectura actual es HOME en base,
hombro, codo y pitch, roll 1655 y pinza 1499 µs; no quedan procesos del brazo,
pero el PCA mantiene los pulsos. Muse Spark recibió tres fotos reales y contexto
de la prueba: HTTP 200, 14.12 s y USD 0.018924 estimados. Dejó la verificación de
vista y cierre como incierta por el desenfoque. Se añadió visión multimodal,
comando `analyze-arm` y resultado guardado en la interfaz. Falta enfocar la cámara.

### Preparación real y Meta, actualización posterior

La Jetson volvió a conectarse tras el apagado. Se preparó `/calibration`, con
cámara real, consulta del controlador y registro de poses observadas. Tras la
confirmación del operador se inicializó HOME y se guardó su primera pose observada.
Después se ejecutó, con autorización, una prueba de pinza de 1499 a 1539 µs en
2 s. La lectura final es 1538 µs; las otras cinco articulaciones conservan los
pulsos de HOME. El operador no notó movimiento: la respuesta física quedó
inconclusa y no se guardó una pose nueva. La lectura posterior sigue igual. El
operador confirmó fuente encendida y pinza semiabierta. Se ejecutó una segunda
prueba autorizada solo de pinza (1538→1618 µs en 3 s). El controlador confirmó
la orden y la lectura final fue 1616 µs, con los otros cinco registros sin cambios.
El operador observó apertura suave. Se guardó `GRIPPER_OPEN_PROBE`; aumentar el
pulso abre en este tramo. No es apertura máxima ni valida cierre o agarre.
El controlador se cerró, pero el PCA9685 sigue activo a 50 Hz y los servos mantienen
los últimos pulsos. No se ejecutaron recorridos de recogida. Se
recuperaron seis referencias históricas de MindArm en microsegundos, separadas
de los valores del simulador y pendientes de revalidar. La exposición de cámara
mejoró; el enfoque y el encuadre siguen pendientes.

La clave de Meta ya está configurada localmente. Muse Spark, Muse Image y SAM
respondieron HTTP 200 en una prueba real acotada con imagen sintética (aprox.
USD 0.0138). La prueba confirma acceso, no rendimiento físico ni un bucle SAM
ya conectado al robot. 42 pruebas relevantes aprobadas. Detalle y propuesta de
primera postura: [CALIBRATION_SESSION.md](CALIBRATION_SESSION.md).

### Inspección anterior de la misma fecha

Jetson conectada por SSH (`abelbrayan-desktop`), cámara real 1920×1080 y cuatro scripts compilados
con Python 3.6.9 sin ejecutar programas de actuadores. El inventario se puede repetir con `premonition jetson-inspect`.

Estado actual del controlador: MODE1=17 (SLEEP activo), PRESCALE=30 y los seis canales liberados.
`first-motion-card` rechaza este estado correctamente. No reutilizar los pulsos o la tarjeta del
30 de octubre. No se escribieron registros ni se modificaron programas de la Jetson.

Corregidos: stop intermedio/éxito falso, planes incompletos o distintos al objetivo, arranques
concurrentes, rutas vacías y duraciones inválidas, reservas de API, integridad de evidencia y
calibración, y persistencia del bloqueo/reconciliación del agente. La interfaz permite seleccionar
Meta y A2/A3. Suite completa: **249 pruebas aprobadas**, con transporte falso y sin actuadores.
Queda una advertencia de deprecación de Starlette/TestClient por el adaptador HTTP utilizado.

En navegador: kit completo con A2, kit completo con A3 y replay; sin errores de consola ni
desborde horizontal a 390 px. La captura actual presenta 35.71 % de píxeles saturados y nitidez
14.77: iluminación y enfoque siguen pendientes. No hay clave de Meta en `.env` y no se hicieron
llamadas pagadas. El agente nuevo sigue sin instalar y no hay backend real de movimiento.

## Historial: entrega 1, software ejecutable sin movimientos

Terminada. El brazo no se movió y la aplicación no puede moverlo: no contiene ningún backend de
actuadores, y el agente de la Jetson solo admite `--backend fake`.

### Pruebas de la primera entrega (30 de octubre)

| Qué | Resultado |
| --- | --- |
| Suite de pruebas (`pytest`) | 225 de 225, con backends falsos. |
| Pruebas de agente y cliente, repetidas | 3 pasadas sin fallos (52 pruebas cada una). |
| Mutaciones de protecciones críticas | 33 de 33 detectadas, en una copia del proyecto. |
| Interfaz en Chrome | Todos los flujos, con clics reales; móvil de 390 px sin desborde. |
| Compilación de `agent/` con Python 3.6.9 en la Jetson | 3 de 3, sin ejecutar `main`. |
| Cámara real sin controlador de servos | Fotos de 1920×1080; unos 30 fps durante 6 s. |
| Lectura real de registros del PCA9685 | Sin escrituras; pulsos en [HARDWARE.md](HARDWARE.md). |
| Jetson tras las pruebas | Mismos hashes, sin directorios nuevos y sin procesos del brazo. |

### Simulado

- Las escenas, las piezas, la bandeja, el movimiento y los fallos están dibujados o inyectados por código.
- El planificador local reconoce solo un patrón de petición. La referencia es un dibujo del contrato.
- Los adaptadores de Meta solo se probaron con respuestas falsas, basadas en la documentación oficial.
- La comparación A2/A3 usa 10 ejecuciones y 54 ensayos sintéticos: 2 de 9 fallos aceptados en ambos
  métodos, 0 de 45 correctos rechazados y 2 de 54 abstenciones. **No es evidencia** de desempeño
  físico ni del aporte de la referencia. Esa referencia no aporta información nueva, así que el empate
  es lo esperable.

### Pendiente

- **Meta:** falta `MODEL_API_KEY`. No se hizo ninguna llamada, así que el acceso, la latencia y el
  coste reales están sin medir. SAM está integrado como adaptador, pero todavía no alimenta las medidas.
- **Física:** todo lo que lista `premonition gaps`: parada física, piezas, bandeja, regiones,
  umbrales y pose de observación. Las rutas se exigirán cuando existan piezas y destinos.
- **Cámara:** luz estable, encuadre y enfoque (ver [HARDWARE.md](HARDWARE.md)).
- **Agente:** backend real de I²C; instalación en `/home/abelbrayan/premonition_lab`.
- **Interfaz:** selectores Meta y A2/A3 implementados; falta probar Meta con acceso real.
- **Evaluación:** A1, ejecuciones reales y etiquetas del operador.

## Hallazgos que conviene recordar

- Un fallo real de agarre puede pasar A2: si se lleva la pieza equivocada, el origen queda vacío y
  el paso se acepta. Solo se detecta al colocarla. La pieza en la pinza no se mide directamente.
- La primera comparación mostró una ventaja falsa de A3 (0 de 9 frente a 2 de 9). Era un defecto
  al comparar regiones vacías, ya corregido y cubierto por pruebas. Conviene desconfiar de cualquier
  mejora de A3 hasta ver qué ensayos cambian y por qué.
- PowerShell quitó las comillas de un comando remoto y la `|` se ejecutó en la Jetson, que intentó
  lanzar `servo_test`. El comando no existía y no ocurrió nada, pero fue un error real. Por eso los
  scripts viajan por stdin.

## Siguiente paso

Revisar y guardar las zonas propuestas para la esponja y la colocación sobre la mesa. Con HOME
estable y OBSERVE_C922 registrados, enseñar aproximación, agarre, elevación y colocación con el
operador presente. Las regiones de imagen y las referencias históricas no validan esas rutas.
