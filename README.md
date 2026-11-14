# Potz

Bot de Texas Hold’em No-Limit para PokerFight. Incluye un probador de jugadas,
un visor de partidas locales y memoria por rival.

## Probar una jugada

En Windows, instala Python 3.10 o posterior con Tkinter y abre
[Abrir probador.cmd](scripts/Abrir%20probador.cmd). Elige tus cartas, las cartas de la
mesa, el bote y cuánto cuesta igualar. Pulsa **Probar jugada** para ver qué haría
Potz, cuántas fichas pondría y cómo llegó a esa decisión.

## Jugar una partida local

Para jugar contra los bots de ejemplo necesitas Git y Go 1.26.10 o posterior.
Desde PowerShell, en una copia nueva de Potz, descarga la arena oficial y
aplica [el parche del visor](arena/arena-visor.patch).

```powershell
git clone https://github.com/aicspucp/pokerfight-arena-participantes.git arena/pokerfight-arena-participantes
git -C arena/pokerfight-arena-participantes checkout --detach 4de6164996796fd70f71f544688f791dcbbb36e0
git -C arena/pokerfight-arena-participantes apply ../arena-visor.patch
Push-Location arena/pokerfight-arena-participantes
go build -o bin/ ./cmd/arena ./bots/aleatorio ./bots/estadistico
Pop-Location
```

Abre [Jugar partida local.cmd](scripts/Jugar%20partida%20local.cmd). La mesa muestra las
cartas, las fichas de cada bot, la apuesta actual y el pozo. Puedes pausar,
retroceder y avanzar jugada por jugada. La partida termina cuando queda un
solo bot con fichas. [Ver partida local.cmd](scripts/Ver%20partida%20local.cmd) abre
la repetición de la última partida guardada.

## Cómo juega Potz

Potz simula repartos para estimar qué parte del pozo podría ganar y compara
esa estimación con lo que cuesta igualar. Una apuesta grande o una secuencia
de subidas puede hacer que dé más peso a las manos fuertes del rival.

El bot guarda las acciones observadas y las cartas que los rivales muestran
al terminar la mano en `datos/potz.sqlite`. Usa esas observaciones para
ajustar cómo interpreta futuras apuestas grandes del mismo rival. Si el
rival aparece con un alias nuevo, Potz empieza un perfil nuevo.

## Conectarse a la arena del torneo

Desde la carpeta de Potz, ejecuta el bot con la dirección y el token
entregados por la organización.

```powershell
python -B -m potz.bot_arena -addr HOST:PUERTO -token TU_TOKEN -ambito-memoria practica
```

Usa `-ambito-memoria practica` para el servidor de pruebas y
`-ambito-memoria campeonato-2026` para el torneo. Cada etiqueta mantiene
sus propios perfiles. Introduce el token al ejecutar el bot.

## Estructura del proyecto

| Carpeta | Contenido |
| --- | --- |
| [`potz/`](potz/) | Estrategia, memoria, conexión con la arena e interfaces. |
| [`arena/`](arena/) | Configuración de la partida y parche del visor. El kit oficial se instala dentro de esta carpeta. |
| [`scripts/`](scripts/) | Accesos de Windows para el probador, la mesa y la repetición. |
| `datos/` | Memoria local de los rivales. El bot crea esta carpeta al jugar. |

El [.gitignore](.gitignore) excluye la copia del kit oficial, sus resultados y
la base de datos local.
