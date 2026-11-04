# Revisi?n de l?mites del brazo

2 de noviembre de 2026, America/Lima. Inspecci?n de archivos y registros, sin movimientos.

La fuente permanece conectada seg?n el operador. La vibraci?n sin movimiento mantiene suspendidas las pruebas. No se ha identificado qu? servo vibra.

| Articulaci?n | Canal | L?mite configurado (?s) | Pulsos de posturas guardadas y observadas (?s) | Tope f?sico revalidado |
| --- | --- | --- | --- | --- |
| Base | 0 | 1000?2000 | 1499, 1558 | Sin medir |
| Hombro | 1 | 1000?2000 | 1372, 1450 | Sin medir |
| Codo | 2 | 1000?2000 | 1499, 1558 | Sin medir |
| Inclinaci?n de mu?eca | 3 | 1180?1980 | 1602 | Sin medir |
| Giro de mu?eca | 4 | 1000?2000 | 1499 | Sin medir |
| Pinza | 5 | 1130?1950 | 1499, 1616 | Sin medir |

Los pulsos guardados pertenecen a vectores completos concretos. Sus m?nimos y m?ximos no forman un rango interpolable ni autorizan recorrerlos desde la postura actual. Los valores configurados tampoco son ?ngulos o distancias.

El historial documenta un atasco de la mu?eca pitch mientras sus pulsos segu?an cambiando. El ?ltimo comando actual modific? el codo, pero eso no identifica el origen de la vibraci?n: las otras articulaciones tambi?n mantienen esfuerzo.

La siguiente calibraci?n deber? determinar l?mites utilizables por articulaci?n, deteni?ndose antes de rozar, atascarse o vibrar, y despu?s comprobar combinaciones de posturas. No se buscan los topes haciendo fuerza contra ellos. Antes debe resolverse la vibraci?n actual, con el brazo apoyado y los servos sin alimentaci?n durante la revisi?n f?sica.

No hay todav?a un volumen de alcance medido en XYZ, ni geometr?a c?mara?robot calibrada. Referencia de imagen: `runs/real/calibration/contact_reference_20261102.json`. Registro de esta revisi?n: `runs/real/calibration/limits_audit_20261102.json`.
