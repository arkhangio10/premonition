# Dirección visual: Merkur + Job Hunt

Aplicación actual: 1 de noviembre de 2026, America/Lima.

- [Merkur Design](https://merkurdesign.com/?r=0): observación directa en navegador de la
  composición clara, tipografía extendida, puntos negros y espacio amplio. Se adapta su
  contraste gráfico y el marco de líneas finas, sin reutilizar logotipo, imágenes ni fuentes propietarias.
- [Job Hunt](https://jobhunt.asmcleod.com/): observación directa de una galaxia de datos
  interactiva sobre fondo oscuro, núcleo naranja, etiquetas y controles orbitales. Se adapta
  la exploración por arrastre y la relación entre nodos y detalle, reducida a las tres piezas del kit.
- [Unbounded, Google Fonts](https://github.com/google/fonts/tree/main/ofl/unbounded): fuente
  variable distribuida localmente con licencia SIL OFL, incluida en `static/unbounded-OFL.txt`.

La combinación usa papel claro, negro y naranja; una nube de puntos original en Canvas 2D;
etiquetas monoespaciadas y paneles de evidencia sin adornos. Se evita introducir una librería
3D en una consola que también puede visualizarse desde equipos modestos. El lienzo usa 2.000
puntos en escritorio y 1.000 en móvil, con actualización limitada a unos 30 fps. Se pausa al
ocultar la escena o la pestaña y respeta la preferencia de movimiento reducido.

El mapa se identifica como conceptual. Los estados proceden del run; sus posiciones son
gráficas y no describen el robot. Las imágenes de verificación no reciben texturas ni filtros.
No se copian datos, código ni recursos visuales de las referencias.

---

# Investigación anterior: laboratorio retro

Investigación y aplicación: 1 de noviembre de 2026, America/Lima.

## Referencias consultadas

| Referencia | Qué aporta a la interfaz |
| --- | --- |
| [Braun ET66, Museum Angewandte Kunst](https://sammlung-digital.museumangewandtekunst.de/detail/collection/8aaba9e5-2b9b-47ac-b304-11074467d180) | La ficha explica la simplificación de funciones, las teclas convexas y el color como guía de uso. Se aplica a botones de relieve discreto y un único acento fuerte para Run. |
| [Tektronix 545B, Science Museum Group](https://collection.sciencemuseumgroup.org.uk/objects/co8413355/model-545b-dual-beam-oscilloscope-oscilloscope) | Su fotografía muestra una carcasa clara, pantalla oscura y controles agrupados. Se aplica a un panel principal con pantalla empotrada y secciones delimitadas por función. |
| [Dieter Rams, Design Museum](https://designmuseum.org/designers/dieter-rams) | La exposición documenta una composición ordenada y legible de los controles. Se aplica a la alineación y la jerarquía entre escenario, ejecución y evidencia. |
| [OP–1 field, fabricante](https://teenage.engineering/products/op-1) | Referencia contemporánea de materialidad de instrumentos. Se usa para estudiar superficies y agrupación; no se reproduce su disposición ni se añaden controles musicales. |

Las fotografías se inspeccionaron como referencias visuales y no se incorporan como recursos de la aplicación.

## Criterio elegido

Retroindustrial de instrumentos de sobremesa: carcasa marfil sobre una mesa gris, tipografía
sans serif legible, leyendas monoespaciadas pequeñas, controles con relieve y pantalla oscura.
El naranja distingue la acción principal; verde y rojo indican resultados reales de la aplicación.
La forma de los elementos acompaña su función. No hay diales ni métricas decorativas.

La pantalla conserva las imágenes originales completas mediante `object-fit: contain`. El
toque retro está en el marco y los controles, sin modificar la evidencia que observa el usuario.

Se mantienen el inglés, los mensajes breves y los diagnósticos plegados de la versión anterior.

## Comprobación

- Navegador de escritorio: ejecución completa, parada y nueva ejecución confirmadas.
- Móvil: sin desborde a 320 y 390 px; Run visible y Settings dentro de la pantalla.
- Las tres imágenes cargan completas, sin recorte; idioma del documento `en`.
- Sin errores de consola en los flujos comprobados.
- Cambios limitados a HTML y CSS. El motor y el control físico no se modificaron.
