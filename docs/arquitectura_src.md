---
title: "RockDove — Sistema de Transferencia P2P con Corrección de Errores"
subtitle: "Arquitectura del Sistema — Modelo C4"
author: "Grupo 1 — Redes de Datos II"
date: "2026"
lang: es
toc: true
toc-depth: 3
numbersections: true
geometry: margin=2.5cm
fontsize: 11pt
---

\newpage

# Introducción

La transferencia confiable de archivos sobre redes inestables presenta un desafío fundamental: el
protocolo UDP, elegido por su baja latencia y ausencia de sobrecarga de conexión, no garantiza
entrega ni orden de los datagramas. En redes con pérdida de paquetes, una transferencia sin
protección produce datos incompletos o corruptos. Las alternativas clásicas presentan limitaciones
importantes en este contexto:

| Alternativa | Limitación |
|---|---|
| TCP con retransmisión | Costo prohibitivo en enlaces de alta latencia o intermitentes; incompatible con links unidireccionales |
| Checksum y reenvío explícito | Requiere round-trips; imposible en topologías unidireccionales o con alta latencia |
| Ignorar la pérdida | Inaceptable para transferencia de archivos completos con verificación de integridad |

RockDove aborda este problema mediante **Forward Error Correction (FEC)**: el emisor agrega
redundancia matemática calculada sobre el contenido original antes de enviarlo. El receptor
reconstruye el archivo completo aunque lleguen menos paquetes de los enviados, sin necesidad de
contactar al emisor nuevamente. El nivel de redundancia se ajusta automáticamente en función de
la calidad de red medida en tiempo real, evitando que el usuario deba configurar parámetros
técnicos manualmente.

El presente informe describe la arquitectura del sistema siguiendo el **modelo C4** en sus
cuatro niveles: contexto del sistema, contenedores, componentes e implementación. El objetivo es
proporcionar una descripción completa y precisa del diseño, sus decisiones técnicas y los
compromisos que las motivan.

\newpage

# Descripción del Sistema

## Qué es RockDove

RockDove es una plataforma de transferencia de archivos entre pares (*peer-to-peer*) que aplica el
algoritmo de corrección de errores Reed-Solomon sobre UDP para garantizar la integridad de los
datos incluso en redes con pérdida de paquetes. El sistema está pensado para dos escenarios
complementarios:

- **Transferencia entre usuarios de escritorio:** dos o más miembros de una organización transfieren
  archivos directamente entre sus máquinas, con verificación criptográfica de integridad y
  autenticación federada opcional.
- **Ingesta a dispositivos edge e IoT:** un nodo con conectividad degradada (enlace celular,
  satelital o industrial) recibe datos con garantía de reconstrucción aunque se pierdan paquetes,
  sin retransmisión y sin intervención humana.

## Diseño de dos planos

La decisión de diseño más importante de RockDove es la separación estricta entre **plano de
control** y **plano de datos**. Ambos planos son independientes y comunican por interfaces bien
definidas:

**Plano de control — servidor central (una instancia en cloud):**
gestiona la identidad de los peers, su presencia en línea, la telemetría de red y las rutas de
relay. Responde exactamente a dos preguntas operativas: *"¿dónde está el peer B?"* y *"¿qué nivel
de redundancia conviene dado el estado actual de la red?"*. El servidor nunca accede al contenido
de los archivos transferidos.

**Plano de datos — agente local (uno por máquina):**
cada participante ejecuta un agente que realiza la codificación y decodificación Reed-Solomon,
maneja el socket UDP o QUIC, almacena archivos en el sistema de archivos local y mantiene el
historial de transferencias en una base de datos embebida.

La transferencia de datos es directa, máquina a máquina, sobre UDP. El servidor no interviene en
el flujo de datos en ningún momento.

Esta arquitectura es análoga al patrón de coordinación implementado por herramientas como
Tailscale o Syncthing: un servidor central facilita el descubrimiento de peers, pero la
comunicación efectiva ocurre de forma directa entre los endpoints.

![Diagrama de arquitectura general del sistema](img/architecture.png)

\newpage

# Nivel 1 — Contexto del Sistema

El nivel de contexto describe el sistema como una caja negra y sus relaciones con actores externos
y sistemas adyacentes.

![Diagrama de contexto C4 — Nivel 1](img/c4_context.png)

## Actores externos

**Usuario desktop:** desarrollador o usuario final con RockDove instalado en su computadora
personal. Interactúa con el sistema para enviar y recibir archivos, visualizar el estado de los
peers de su organización y configurar opciones de transporte y redundancia.

**Administrador de organización:** usuario privilegiado que gestiona la configuración
organizacional del sistema: define scopes de visibilidad entre grupos de peers, genera tokens de
dispositivo para nodos headless, administra políticas de transferencias entrantes y supervisa el
estado de salud de la red a través del panel de administración.

**Dispositivo edge / IoT:** nodo sin interfaz gráfica que se registra en el sistema mediante un
token de dispositivo autogenerado. Opera de forma completamente autónoma: se registra al arrancar,
mantiene su presencia mediante señales de vida periódicas y recibe transferencias UDP entrantes que
almacena en su sistema de archivos local.

## Sistemas externos

**Keycloak (opcional):** proveedor de identidad externo que implementa el protocolo OpenID Connect.
RockDove lo integra para la autenticación de usuarios humanos en entornos de producción. El servidor
central valida los tokens JWT emitidos por Keycloak para derivar la identidad del peer y su
pertenencia organizacional. La integración es opcional: el sistema puede operar en modo de
desarrollo sin proveedor de identidad externo.

## Relaciones principales

El usuario desktop utiliza RockDove para enviar y recibir archivos y para configurar opciones de
transporte. El administrador gestiona la organización y las políticas de acceso a través del panel
de administración embebido en la interfaz. El dispositivo edge se registra y transfiere archivos
usando un token de dispositivo como credencial. El sistema consulta a Keycloak para validar la
identidad de usuarios humanos cuando la autenticación OIDC está habilitada.

\newpage

# Nivel 2 — Contenedores

El nivel de contenedores describe las unidades desplegables del sistema, sus responsabilidades y
los flujos de comunicación entre ellas.

![Diagrama de contenedores C4 — Nivel 2](img/c4_containers.png)

## Contenedores del sistema

### Servidor de Coordinación

Proceso único desplegado en una instancia cloud, compartido por todos los peers de una
organización. Expone una API REST y un endpoint WebSocket en el puerto 8080 (TCP). Sus
responsabilidades son el registro y presencia de peers, la recolección y análisis de métricas de
red, el descubrimiento de rutas de relay y el control de acceso organizacional.

**Neo4j** actúa como base de datos de grafos para la persistencia del grafo de peers. Cada peer
se representa como un nodo con sus atributos de conectividad (`udp_host`, `api_url`, `transport_mode`).
Las relaciones `CONNECTS_TO` entre nodos almacenan los pesos de calidad del enlace (RTT, jitter y
tasa de pérdida), lo que permite al servidor calcular rutas óptimas de relay ponderadas por la
calidad de la conexión entre peers.

**Redis** gestiona el estado efímero y operacional: el buffer de métricas recientes de cada peer
(últimas 10 muestras), los device tokens con su TTL configurable, los scopes de visibilidad por
grupo, y la presencia de peers mediante claves con tiempo de expiración asociado al heartbeat.

**Keycloak** (opcional) provee identidad federada. El servidor valida los JWT emitidos por
Keycloak usando el endpoint JWKS del realm correspondiente.

### Agente Local

Proceso Python que se ejecuta en cada máquina participante. Expone el puerto 8000 (TCP) para la
API HTTP local y el puerto 9001 (UDP) para recibir bloques Reed-Solomon. Encapsula el motor de
codificación/decodificación RS, la capa de transporte conmutable (UDP/QUIC), el sistema de relay,
el almacenamiento local y el historial de transferencias.

**SQLite** (embebida en el proceso del agente) persiste el historial de transferencias con todos
sus metadatos: identificador, dirección, peer remoto, nombre de archivo, tamaño, estado, nivel de
redundancia efectivo, bloques recuperados, calidad de red y perfil de red utilizado.

### Shell de Escritorio (Electron)

Proceso que envuelve el agente Python y la interfaz web para usuarios desktop. Al iniciar, lanza
el agente Python como proceso hijo, espera a que su API de salud responda, carga la SPA React
desde recursos embebidos y expone la URL base del agente al contexto del renderer mediante el
mecanismo de aislación de contexto de Electron. La interfaz web no realiza llamadas directas al
servidor central en ningún momento; toda la comunicación pasa por el agente local.

### Interfaz Web (SPA)

Aplicación de página única construida con React. Implementa dos páginas principales: la página de
conexión inicial (configuración del servidor y autenticación) y el dashboard principal. El
dashboard integra la lista de peers en tiempo real recibida por WebSocket, el gestor de archivos
local, el diálogo de transferencia con selector de nivel de redundancia, el historial de
transferencias y el panel de administración. El panel de administración expone pestañas para la
gestión de scopes de visibilidad, generación de tokens de invitación, administración de device
tokens, configuración de relay, visualización del estado de salud de la red (gráficas SVG de
RTT/jitter/pérdida y tabla del grafo de red) y gestión de políticas de transferencias entrantes.

## Flujos de comunicación

La interfaz web se comunica con el agente local exclusivamente a través de HTTP sobre loopback
(`127.0.0.1:8000`). Para recibir actualizaciones en tiempo real de la lista de peers, la interfaz
mantiene una conexión WebSocket permanente con el servidor central. El agente local se comunica
con el servidor central mediante HTTPS para todas las operaciones de coordinación: registro,
señales de vida, resolución de dirección de peers, reporte de métricas y consulta de rutas de
relay. La transferencia de bloques Reed-Solomon entre agentes ocurre directamente sobre UDP (o
QUIC), sin pasar por el servidor.

\newpage

# Nivel 3 — Componentes

El nivel de componentes describe los módulos internos de los contenedores principales y sus
responsabilidades.

![Diagrama de componentes C4 — Nivel 3](img/c4_components.png)

## Componentes del Servidor de Coordinación

**Módulo de peers:** implementa el ciclo completo de vida de un peer en el sistema. Recibe las
solicitudes de registro con los atributos de conectividad del peer, persiste el nodo en Neo4j
y establece la clave de presencia en Redis con el TTL del heartbeat. Procesa señales de vida
periódicas que renuevan el TTL. Responde a consultas de resolución de dirección por identificador.
Gestiona el descubrimiento de peers con capacidad de relay y la configuración de políticas de
transferencias entrantes por peer. El endpoint WebSocket emite una instantánea actualizada de la
lista de peers a todos los clientes conectados cada vez que ocurre un cambio de estado.

**Módulo de métricas:** recibe reportes de telemetría de los agentes (RTT, jitter, tasa de
pérdida) y los almacena en el buffer por peer en Redis. Implementa el motor de recomendación de
redundancia: promedia las últimas muestras, clasifica la calidad de red según umbrales predefinidos
y devuelve el nivel de redundancia sugerido. Expone el historial de métricas por peer y la tabla
del grafo de red para visualización en el panel de administración.

**Módulo de device tokens:** genera tokens de alta entropía para dispositivos headless, los
persiste en Redis con TTL configurable y permite su revocación inmediata. Un token revocado es
rechazado en el siguiente request del dispositivo sin necesidad de reinicio del servidor.

**Módulo de invitaciones:** genera tokens de un solo uso que permiten la incorporación de nuevos
peers. Cada token es válido para un único proceso de registro; al ser consumido se invalida
automáticamente.

**Middleware de autenticación:** intercepta todas las solicitudes, extrae el JWT del encabezado
de autorización, valida la firma mediante el endpoint JWKS del proveedor de identidad o contrasta
el device token contra Redis, y derivar el `org_id` (del campo realm del JWT o del registro del
token) para aplicar el aislamiento organizacional en todas las consultas subsiguientes.

## Componentes del Agente Local

**Motor Reed-Solomon:** encapsula la lógica de codificación y decodificación. El codificador
recibe el archivo en memoria, calcula su resumen criptográfico, segmenta el contenido en bloques y
aplica aritmética de campo de Galois para generar los símbolos de paridad de cada bloque. El
decodificador colecta bloques indexados, identifica los ausentes, los reconstruye algebraicamente
y verifica la integridad del archivo reconstruido contra el resumen original.

**Capa de transporte:** presenta una interfaz abstracta unificada sobre dos implementaciones
concretas. La implementación UDP opera sobre un socket asíncrono sin estado de sesión. La
implementación QUIC establece una sesión cifrada con TLS 1.3 y transmite los bloques como frames
DATAGRAM sin retransmisión. Ambas implementaciones comparten el mismo puerto 9001. El transporte
activo es seleccionable sin reiniciar el agente.

**Motor de relay:** implementa el rol de intermediario cuando la transferencia directa no es
posible. Colecta bloques en memoria RAM, resuelve el peer destino y reenvía los bloques. Soporta
tres modalidades de operación (ephemeral, restricted, gateway) que se describen en detalle en la
sección de flujos de interacción.

**Cliente del servidor:** centraliza toda la comunicación HTTP con el servidor central. Abstrae
los detalles del protocolo y provee métodos de alto nivel para registro, señales de vida,
resolución de peers, reporte de métricas y consulta de recomendaciones.

**Sonda de métricas:** proceso en background que mide periódicamente la latencia de round-trip y
el jitter hacia los peers activos conocidos, y reporta los resultados al servidor para alimentar
el sistema de recomendación adaptativa.

**Gestión de almacenamiento:** persiste los archivos recibidos en el directorio configurado con un
índice de integridad SHA-256. El historial de transferencias se almacena en SQLite mediante acceso
asíncrono, permitiendo consultas sin bloquear la API del agente.

**Gestor del daemon:** implementa los comandos de instalación y control del servicio del sistema
operativo. Genera las unidades de servicio específicas de cada plataforma y gestiona el archivo de
variables de entorno del agente.

\newpage

# Nivel 4 — Código

El nivel de código describe la implementación de los componentes en términos de comportamiento y
algoritmos, sin referenciar nombres específicos de librerías, clases ni archivos.

![Flujo de transferencia C4 — Nivel 4](img/c4_code_transfer.png)

## Codificación y Decodificación Reed-Solomon

### Proceso de codificación

El proceso de codificación comienza al recibir el archivo completo en memoria. En primer lugar,
se calcula el resumen criptográfico SHA-256 del contenido original; este valor se transmitirá al
receptor para verificación de integridad posterior. A continuación, el archivo se divide en
segmentos de tamaño uniforme de `k` bytes; si el último segmento es más corto, se rellena con
ceros hasta alcanzar el tamaño estándar, y el tamaño original del archivo se registra en el
encabezado del primer bloque para que el receptor pueda eliminar el relleno al reconstruir.

Para cada segmento se aplica álgebra sobre el cuerpo de Galois GF(2^8^) para producir `n−k`
bytes adicionales de paridad. La propiedad fundamental de este proceso es que cualquier
subconjunto de `k` símbolos del total de `n` (originales y de paridad) permite reconstruir
el segmento completo sin pérdida de información. En el contexto de transmisión UDP, donde se
conoce con exactitud qué bloques llegaron y cuáles no (modelo de borrado o *erasure*), esta
propiedad se aprovecha al máximo.

Cada bloque codificado se empaqueta con un encabezado binario de 30 bytes que incluye: el
identificador único de la transferencia (16 bytes UUID), el índice del bloque, el total de bloques,
los parámetros `n` y `k`, indicadores de estado (último bloque, presencia de relleno) y, en el
primer bloque, el tamaño original del archivo.

Los parámetros `n` y `k` se derivan del nivel de redundancia seleccionado por el usuario o
recomendado por el servidor. Con `n` fijo en 32 y el nivel de redundancia `r` en el rango
`[0.05, 0.50]`:

```
k = round(n × (1 − r))
k = clamp(k, mín=4, máx=n−1)
```

| Nivel r | n | k | Paridad | Pérdida tolerable |
|---|---|---|---|---|
| 0.05 | 32 | 30 | 2 | 5% |
| 0.10 | 32 | 29 | 3 | 10% |
| 0.25 | 32 | 24 | 8 | 25% |
| 0.50 | 32 | 16 | 16 | 50% |

### Proceso de decodificación

El receptor colecta bloques a medida que llegan a través del socket. Al conocer el total esperado
de bloques (indicado en el encabezado de cualquier bloque recibido), el decodificador determina
con precisión qué índices están ausentes. Para cada bloque recibido, verifica su integridad
aplicando el proceso de decodificación RS estándar. Para cada bloque ausente, aplica decodificación
por borrado: utilizando el conjunto de bloques disponibles y las posiciones de los ausentes como
entrada, el algoritmo resuelve el sistema de ecuaciones sobre GF(2^8^) para reconstruir los datos
originales.

Una vez procesados todos los bloques, los segmentos se concatenan en orden y se elimina el relleno
del último segmento usando el tamaño original registrado en el encabezado. Se calcula el SHA-256
del archivo reconstruido y se contrasta contra el valor provisto por el emisor. El resultado de
la transferencia se determina según la siguiente tabla:

| Condición | Estado resultante |
|---|---|
| Sin pérdidas, SHA-256 coincide | `ok` |
| Pérdidas recuperadas por RS, SHA-256 coincide | `degraded` |
| Pérdidas superan capacidad RS, o SHA-256 no coincide | `failed` |
| Recibido a través de un peer intermediario | `relayed` |

![Flujo del algoritmo Reed-Solomon](img/rs_algorithm.png)

## Capa de Transporte UDP/QUIC

### Abstracción de transporte

Ambas implementaciones de transporte exponen la misma interfaz con cuatro operaciones: iniciar la
escucha en el puerto configurado, enviar un bloque a una dirección destino, colectar el siguiente
bloque recibido y detener el transporte. Esta abstracción permite al motor RS y al orquestador
de transferencias operar sin conocer los detalles del protocolo subyacente.

### Transporte UDP

La implementación UDP utiliza un socket de datagrama asíncrono. No hay estado de sesión: cada
bloque RS se transmite como un datagrama independiente sin handshake previo ni confirmación de
entrega. La ausencia de sobrecarga de conexión minimiza la latencia de inicio de transferencia.
La pérdida de datagramas es gestionada por el motor RS mediante el modelo de borrado.

### Transporte QUIC

La implementación QUIC establece una sesión cifrada con TLS 1.3 sobre el mismo puerto UDP. Los
bloques RS se transmiten como frames de tipo DATAGRAM definidos en el RFC 9221, que son frames
sin retransmisión dentro de una sesión QUIC. Esta característica es deliberada: si QUIC
retransmitiera automáticamente los frames perdidos, interferiría con el modelo de borrado de RS.
Al usar frames DATAGRAM, QUIC aporta cifrado y autenticación de la sesión sin alterar la
semántica de pérdida que RS requiere.

Al iniciarse en modo QUIC, el agente genera automáticamente un certificado TLS autofirmado cuyo
nombre común incluye el identificador único del peer. Este certificado se almacena de forma
persistente; si el identificador del peer cambia entre arranques, el certificado anterior se
descarta y se genera uno nuevo.

### Protocolo de identidad CERT_HELLO

Antes de enviar los bloques RS, el emisor transmite un frame especial denominado CERT_HELLO. Este
frame transporta la identidad criptográfica del emisor: un valor mágico de identificación de
protocolo, la versión del protocolo, el identificador del peer emisor, el identificador único de la
transferencia y el resumen SHA-256 del certificado TLS del emisor. El receptor identifica este
frame por el valor mágico y, antes de procesar cualquier bloque RS, registra la conexión como
pendiente con los metadatos extraídos.

El operador del peer receptor puede aprobar o rechazar la conexión entrante desde la interfaz antes
de que los bloques sean procesados. Si no hay interacción en 30 segundos, la conexión se aprueba
automáticamente para no bloquear transferencias en entornos desatendidos. Un rechazo descarta
todos los bloques recibidos y marca la transferencia como fallida.

## Sistema de Relay

Cuando el agente emisor no puede alcanzar directamente al receptor (falla de conectividad, NAT
simétrico, red segmentada), recurre a un peer intermediario con capacidad de relay.

El proceso de relay opera en tres etapas. En la primera, el emisor solicita al servidor la
identificación de un peer relay disponible, o consulta las rutas estáticas configuradas localmente.
En la segunda, el emisor establece contacto con el relay e inicia la transferencia indicando el
peer destino final. En la tercera, el relay colecta los bloques RS en memoria RAM, resuelve la
dirección del destino final y reenvía los bloques como si fuera el emisor original.

Los peers relay pueden operar en tres modalidades complementarias:

**Ephemeral:** los bloques se mantienen exclusivamente en memoria RAM durante el proceso de
reenvío. Si el proceso del relay se detiene antes de completar el reenvío, los bloques se pierden
y la transferencia falla. Esta modalidad prioriza la privacidad sobre la resiliencia.

**Restricted:** el relay solo acepta solicitudes de reenvío hacia peers incluidos en una lista
de destinos autorizados configurada explícitamente. Solicitudes hacia destinos no autorizados
son rechazadas con un error descriptivo.

**Gateway:** el relay resuelve destinos mediante rutas estáticas configuradas localmente, sin
necesidad de consultar al servidor central por TCP. Esta modalidad permite la operación del relay
en entornos sin conectividad al servidor, como redes industriales aisladas.

## Redundancia Adaptativa

El sistema ajusta dinámicamente el nivel de redundancia de cada transferencia en función de las
condiciones de red medidas en ambos extremos del enlace.

### Ciclo de medición

El agente ejecuta un proceso en background que, cada 60 segundos, mide la latencia de round-trip
y el jitter hacia cada peer activo conocido mediante múltiples sondas HTTP. Los resultados se
reportan al servidor, que los almacena en un buffer de las últimas 10 muestras por peer.
Adicionalmente, al finalizar cada transferencia, el agente calcula la tasa de pérdida real
observada (proporción de bloques que requirieron reconstrucción RS) y la reporta al servidor.

### Algoritmo de recomendación

Antes de iniciar una transferencia, el agente consulta al servidor la recomendación de redundancia
para ambos extremos del enlace en paralelo. El servidor promedia las muestras disponibles del
buffer de cada peer y clasifica la calidad del enlace según la siguiente tabla:

| Calidad | Pérdida | RTT | Jitter | Redundancia recomendada |
|---|---|---|---|---|
| Excellent | < 1% | < 50 ms | < 5 ms | 5% |
| Good | < 5% | < 150 ms | < 20 ms | 10% |
| Fair | < 15% | < 500 ms | < 80 ms | 25% |
| Poor | < 30% | < 1000 ms | < 200 ms | 40% |
| Critical | cualquier valor peor | — | — | 50% |

El agente emisor aplica el nivel de redundancia más alto entre las recomendaciones del emisor y
del receptor. Esta lógica garantiza que la protección se dimensiona según el enlace más débil:

```
redundancia_efectiva = max(recomendación_emisor, recomendación_receptor)
```

Si no hay muestras acumuladas para alguno de los peers (primer uso), el sistema utiliza el nivel
conservador del 25% como valor de referencia.

![Sistema de redundancia adaptativa](img/adaptive_redundancy.png)

## Control de Acceso y Autenticación

El sistema implementa tres modalidades de autenticación que pueden coexistir en el mismo
despliegue sin cambios de código.

### Modo de desarrollo

Cuando la integración con el proveedor de identidad externo está deshabilitada, cualquier peer
puede registrarse sin presentar credenciales. Todos los peers registrados pertenecen a la
organización de desarrollo y son visibles entre sí. Esta modalidad está destinada exclusivamente
a entornos de desarrollo local y pruebas de concepto.

### Autenticación federada con OIDC y PKCE

En entornos de producción con usuarios humanos, el sistema integra con un proveedor de identidad
externo mediante el protocolo OpenID Connect. El flujo utiliza la extensión PKCE (*Proof Key for
Code Exchange*), diseñada para aplicaciones de escritorio que no pueden guardar secretos de
cliente de forma segura.

El proceso completo se ilustra en el siguiente diagrama:

![Flujo de autenticación OIDC y device tokens](img/auth_flow.png)

El agente genera un par de valores criptográficos (verificador y desafío), construye la URL de
autorización incluyendo el desafío, y la abre en el navegador del sistema operativo. El usuario
se autentica en el proveedor de identidad. El navegador redirige a un endpoint local del agente
que recibe el código de autorización. El agente intercambia el código por un JWT presentando el
verificador. El JWT resultante contiene el identificador del usuario, el realm de origen (que
determina la organización a la que pertenece el peer) y los grupos del usuario. El agente usa este
JWT para registrarse en el servidor central y para todas las operaciones subsiguientes.

La aislación entre organizaciones se implementa a nivel de realm: el servidor extrae el realm del
campo `iss` del JWT y lo usa como `org_id` en todas las consultas. Los peers de distintos realms
son completamente invisibles entre sí aunque compartan el mismo servidor central.

### Device tokens para dispositivos headless

Para dispositivos IoT y nodos edge que operan sin usuario interactivo, el sistema provee tokens de
dispositivo: credenciales de alta entropía (256 bits, generadas con un generador de números
pseudoaleatorios criptográficamente seguro) con el prefijo visual `rd_`. El administrador genera
el token desde el panel de administración y lo entrega al operador del dispositivo, quien lo
configura como variable de entorno. El token solo se muestra en texto claro en el momento de su
creación; a partir de entonces, el servidor almacena únicamente su representación procesada para
verificación.

Los tokens pueden configurarse como temporales (con tiempo de expiración administrado por la base
de datos en memoria del servidor) o indefinidos. La revocación es inmediata: eliminar el token del
servidor hace que el siguiente request del dispositivo sea rechazado sin reinicio de ningún proceso.

### Política de transferencias entrantes

Cada peer puede configurar su política de recepción mediante la variable de entorno
`INCOMING_POLICY`: aceptar todas las transferencias, rechazar todas, mantener una lista de remitentes
aceptados o una lista de remitentes rechazados. El administrador de la organización puede
sobreescribir esta política para cualquier peer específico desde el servidor central, lo que permite
gestión centralizada de políticas de acceso.

## Servicio de Daemon y Modo Headless

### Daemon del agente

El agente puede instalarse como servicio del sistema operativo mediante comandos de gestión del
daemon. El proceso de instalación genera la unidad de servicio adecuada para la plataforma
detectada: una unidad de usuario de systemd en Linux, un agente de arranque por usuario en macOS,
o una tarea programada activada por inicio de sesión en Windows.

La configuración del agente (variables de entorno) se almacena en un archivo de entorno dedicado
cuya ubicación sigue las convenciones de cada plataforma. Esto permite actualizar la configuración
sin regenerar la unidad de servicio. En Linux, el archivo de entorno se ubica en el directorio de
configuración del usuario; en macOS, en el plist del agente de arranque.

| Plataforma | Mecanismo de daemon | Archivo de configuración |
|---|---|---|
| Linux | systemd `--user` unit | `~/.config/rockdove/agent.env` |
| macOS | LaunchAgent plist | Variables integradas en el plist |
| Windows | schtasks ONLOGON | Variables en la definición de la tarea |

### Agrupación por propietario

La variable de entorno `PEER_OWNER` permite agrupar visualmente múltiples peers pertenecientes al
mismo usuario o equipo en la interfaz. Esta capacidad es especialmente útil en organizaciones donde
un mismo usuario opera varios dispositivos (computadora de escritorio, laptop, servidor personal),
permitiendo identificar de un vistazo todos los peers de un propietario sin necesidad de
convenciones de nomenclatura en el identificador del peer.

\newpage

# Flujos de Interacción

Esta sección describe los flujos operativos principales del sistema, desde el registro inicial de
un peer hasta la transferencia de archivos con redundancia adaptativa.

## Registro y descubrimiento de peers

Al iniciar, el agente ejecuta el siguiente flujo de registro:

1. El agente verifica si dispone de credenciales válidas (JWT activo o device token configurado).
   Si no dispone de credenciales y la autenticación OIDC está habilitada, inicia el flujo PKCE.
2. El agente llama al endpoint de registro del servidor, presentando su identificador único, la
   URL HTTP por la que puede ser contactado, la dirección y puerto UDP por los que recibe bloques,
   el modo de transporte activo y el perfil de red configurado.
3. El servidor persiste el nodo del peer en el grafo y establece su clave de presencia con el TTL
   del heartbeat (30 segundos por defecto).
4. El servidor emite una actualización a todos los clientes WebSocket conectados, haciendo que el
   nuevo peer aparezca en los dashboards de los peers de la misma organización en tiempo real.
5. El agente inicia un proceso en background que envía señales de vida al servidor cada 15 segundos.
   Cada señal de vida renueva el TTL. Si el agente se detiene, el TTL expira y el peer desaparece
   automáticamente de la lista de peers activos.

![Flujo de descubrimiento de peers](img/peer_discovery.png)

## Transferencia P2P directa

El flujo completo de una transferencia directa entre dos peers comprende tres fases:

**Fase de preparación:** el agente emisor consulta al servidor la recomendación de redundancia para
ambos extremos del enlace en paralelo. Calcula el nivel efectivo como el máximo de las dos
recomendaciones. Consulta la dirección UDP del peer receptor. Codifica el archivo con el nivel de
redundancia efectivo y calcula el SHA-256 del contenido original.

**Fase de transferencia:** el emisor notifica al receptor de la transferencia entrante enviando los
metadatos (identificador de transferencia, total de bloques, parámetros RS, SHA-256 del archivo
y nombre del archivo). Si el receptor responde con aceptación, el emisor inicia el envío de los
bloques RS sobre UDP. Cada bloque se transmite como un datagrama independiente con su encabezado
de identificación y los `n` bytes de datos codificados.

**Fase de reconstrucción:** el receptor colecta los bloques durante el tiempo de espera configurado
(30 segundos). Al recibir el último bloque o al expirar el tiempo de espera, aplica el proceso de
decodificación RS, verifica la integridad con SHA-256 y almacena el archivo. El estado resultante
(`ok`, `degraded` o `failed`) se registra en el historial local y se comunica al emisor.

## Fallback a relay

Cuando el emisor no puede alcanzar directamente al receptor, el sistema ejecuta el siguiente flujo
de fallback:

1. El emisor intenta contactar al receptor; la solicitud falla con error de conectividad.
2. El emisor consulta al servidor la lista de peers con capacidad de relay activos en la misma
   organización, o consulta sus rutas estáticas locales.
3. El emisor selecciona un relay y le notifica la transferencia con el identificador del destinatario
   final.
4. El relay acepta la transferencia y resuelve la dirección del destinatario final consultando al
   servidor o sus rutas estáticas.
5. El emisor envía los bloques RS al relay. El relay los colecta en memoria y los reenvía al
   destinatario.
6. El destinatario recibe los bloques, reconstruye el archivo y registra la transferencia con el
   estado `relayed`.

\newpage

# Stack Tecnológico

La siguiente tabla lista todas las tecnologías utilizadas en el sistema, con su versión de
referencia y el rol que cumplen. Esta es la única sección del informe que hace referencia a nombres
específicos de tecnologías, librerías y frameworks.

| Capa | Tecnología | Versión | Rol |
|---|---|---|---|
| Servidor central | Python + FastAPI | 3.12 / 0.115 | API REST, WebSocket, validación de modelos |
| Grafo de red | Neo4j | 5 | Persistencia del grafo de peers y pesos de enlace |
| Estado operacional | Redis | 7 | Métricas, presencia de peers, device tokens, org scopes |
| Identidad federada | Keycloak | 24 | OIDC, multi-tenant, PKCE, gestión de realms y grupos |
| Agente local | Python + FastAPI | 3.12 / 0.115 | Motor RS, transporte UDP/QUIC, storage, daemon |
| Algoritmo FEC | reedsolo | 1.7 | Implementación Reed-Solomon sobre GF(2^8^) |
| Transporte QUIC | aioquic | 1.x | QUIC (RFC 9000) con extensión DATAGRAM (RFC 9221) |
| Certificados TLS | cryptography | 44 | Generación de certificados autofirmados para QUIC |
| Cliente HTTP agente | httpx | 0.28 | Comunicación asíncrona con el servidor central |
| Historial local | aiosqlite | 0.22 | Acceso asíncrono a SQLite para el historial |
| Shell de escritorio | Electron | 33 | Empaquetado de escritorio, spawn del agente |
| Interfaz de usuario | React + Vite + Tailwind CSS | 18 / 5 / 3 | SPA del dashboard y panel de administración |
| Empaquetado del agente | PyInstaller | 6 | Congela el agente Python en binario autocontenido |
| Empaquetado desktop | electron-builder | 25 | Genera AppImage (Linux), exe (Windows), dmg (macOS) |
| Gestión de dependencias | uv | latest | Lockfile reproducible para el entorno Python |
| Contenedores | Docker + Compose | 27 | Despliegue del servidor y nodos headless |

\newpage

# Infraestructura y Despliegue

## Perfiles de despliegue

### Desktop (Electron + agente embebido)

El perfil de escritorio distribuye un ejecutable autocontenido que incluye el shell Electron, la
SPA React compilada y el agente Python congelado. No requiere Python, Node.js ni ninguna
dependencia preinstalada en el dispositivo del usuario final. Los artefactos generados son:
`.AppImage` en Linux, instalador NSIS `.exe` en Windows y `.dmg` en macOS.

### Servidor (Docker Compose)

El servidor central se despliega como un conjunto de contenedores coordinados por Docker Compose:
el proceso de la API (Python + FastAPI), la base de datos de grafos (Neo4j), la base de datos en
memoria (Redis) y el proveedor de identidad (Keycloak, opcional). El despliegue completo se inicia
con un único comando desde el directorio del servidor.

### Nodo headless (Docker o binario)

Los nodos edge e IoT pueden desplegarse como contenedor Docker o como binario autocontenido. En
ambos casos, la configuración completa se provee mediante variables de entorno: identificador del
peer, URL del servidor, URL HTTP pública del agente y token de dispositivo. Una vez desplegado, el
nodo se registra automáticamente, mantiene su presencia y recibe transferencias sin necesidad de
intervención manual.

## Requisitos de red

El único puerto que requiere apertura en firewalls entre peers es el **9001 UDP** del agente
receptor. El servidor central solo necesita el puerto **8080 TCP** accesible desde los agentes.
El puerto 8000 TCP del agente es de uso exclusivamente local (loopback entre el shell Electron y
el agente Python).

Si existe NAT entre los peers, el puerto 9001 UDP debe ser accesible mediante reenvío de puertos
o ambos peers deben estar en la misma red (o conectados por VPN). Para entornos sin conectividad
UDP directa, el sistema de relay provee el mecanismo de fallback descrito en la sección anterior.

El stack de despliegue recomendado para producción combina RockDove con una VPN de nivel 3
(WireGuard, Tailscale o NetBird): la VPN resuelve la reachability, el traversal de NAT y el
cifrado a nivel de red, mientras que RockDove se encarga de la resiliencia de datos mediante FEC,
el descubrimiento de peers y la autenticación.

## Referencia de puertos

| Puerto | Protocolo | Componente | Requerimiento de acceso |
|---|---|---|---|
| 8080 | TCP | Servidor central | Accesible desde todos los peers (registro, heartbeat, métricas) |
| 8000 | TCP | Agente HTTP | Solo loopback local (Electron → agente) |
| 9001 | UDP | Agente UDP/QUIC | Accesible desde peers emisores (único puerto con requisito en firewall entre peers) |
| 7687 | TCP (Bolt) | Neo4j | Solo acceso interno desde el servidor |
| 6379 | TCP | Redis | Solo acceso interno desde el servidor |
| 8081 | TCP | Keycloak | Accesible desde agentes para validación JWKS (opcional) |

\newpage

# Conclusiones

RockDove implementa una arquitectura de dos planos que refleja una decisión de diseño deliberada:
separar la coordinación de la transferencia permite que el servidor central sea un componente
liviano y fácilmente escalable, mientras que el agente local concentra la complejidad del
procesamiento de datos. El servidor nunca accede al contenido de los archivos, lo que simplifica
los requisitos de privacidad y conformidad del componente centralizado y permite que la
transferencia continúe funcionando incluso con conectividad intermitente al servidor.

La elección de UDP como transporte base, complementada con Reed-Solomon como mecanismo de
corrección de errores, está motivada por los casos de uso de alta latencia y conectividad
intermitente. A diferencia de TCP, que retransmite automáticamente los segmentos perdidos con el
consiguiente costo de round-trip, RS permite al receptor reconstruir el archivo original a partir
de los bloques que llegaron, sin contactar al emisor. El costo es el overhead de los símbolos de
paridad, que el sistema dimensiona automáticamente según las condiciones de red observadas.
La redundancia adaptativa cierra el ciclo de retroalimentación: las métricas de las transferencias
previas alimentan la recomendación de la siguiente, haciendo que el sistema aprenda de las
condiciones del enlace con el tiempo.
