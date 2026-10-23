# Reading FishFinder without knowing Python

Start here, then read the large `READING THIS FILE` comment near the top of each
Python file. Those comments describe the job of the file and where to start.
Comments above functions describe their inputs, result and purpose; comments
inside the larger functions explain decisions and unusual steps.

This documentation release preserves executable Python behavior. It is not a
new flight model, a database migration, or a change to the tester website.

## The whole journey

1. A launcher chooses a Python environment, mode and database.
2. `FishFinder.py` starts the collector workers.
3. Stratux sends traffic messages and answers ownship-position requests.
4. The collector validates information and records accepted samples in SQLite.
5. A separate `traffic_display.py` process reads a recent snapshot.
6. Geometry functions convert positions into distances, motion and colors.
7. Tkinter draws the screen and waits for the next touch or scheduled update.
8. Background map work supplies a cached picture; it does not paint every map
   point in the touchscreen event handler.

The collector and display are separate programs. Closing the display does not
stop a collector service. Demo mode has a separate database and simulated input.

## A useful reading order

| Read | What it answers |
| --- | --- |
| `settings.py` | Which decisions are configurable, and what are their defaults? |
| `FishFinder.py`, starting at `main()` | What starts when the collector launches? |
| `identity()` and `record_traffic()` in that file | Why is a message identified, saved or rejected? |
| `record_ownship()` and `cleanup_once()` | Where does our position come from, and what history remains? |
| `traffic_display.py`, starting at `main()`, `Display.tick()` and `Display.draw()` | How does data become a screen? |
| `velocity()`, `assess()` and `vertical_clear()` in that file | What do the projections and colors actually mean? |
| `Display.tap()` and `Display.single_tap()` | How are touch gestures and crowded target choices handled? |
| `airport_data.py` and `airport_reference.py` | How are airport geometry, references and source dates presented? |
| `setup_screen.py` | How are user choices edited and saved? |
| `demo_traffic.py` | How do synthetic flights use the real collector pipeline? |
| `demo_ground.py`, then `tile_ground.py` | Why can the map move without blocking touch? |

Definitions often appear before their callers. Python reads those definitions
first; their bodies run later when called. Following startup from the bottom
of a file is therefore often easier than reading straight down from line one.

## A small Python vocabulary

- `#` starts a comment. Python ignores the rest of that line. It explains the
  program to a human; it does not execute an instruction.
- `"""..."""` is a docstring when placed first in a module, class or function.
  Unlike a comment it is also available to Python's help/introspection tools.
- `name = value` stores a value under a name. `==` asks whether two values match.
- `def name(...):` defines a function: a reusable group of steps.
- Indentation groups steps. Lines indented under `if`, `for`, `try` or `def`
  belong to that block. Avoid changing indentation as a cosmetic edit.
- `if` / `elif` / `else` choose a branch. Only the matching branch runs.
- `for item in items` repeats steps for each item. `while` repeats while a
  condition is true. `break` leaves a loop; `continue` skips to its next turn.
- `return value` finishes this function and hands a result to its caller.
  `return` alone finishes without a meaningful result (`None`).
- `None` means absent or unavailable. It is not the same as a measured zero.
  `True` and `False` are on/off values.
- A dictionary holds named values. `data['Lat']` requires the field to exist;
  `data.get('Lat')` returns `None` if it is missing unless given another default.
- A list holds an ordered sequence. `history[-1]` means the last item;
  `history[:-1]` means all items except that last one.
- A tuple groups values in a fixed order, such as `(east, north)`. If a function
  returns several values, the receiving names must respect that order.
- A comprehension such as `[p for p in history if condition]` builds a new list
  by keeping entries that meet the condition.
- `a if condition else b` is a compact way to choose one value.
- `try` / `except` handle an operation that might fail. `finally` runs cleanup
  whether it succeeded or failed. `raise` reports an error to the caller.
- `with` starts/ends a managed operation. Its exact cleanup depends on the
  object: a SQLite transaction and a file handle do different things.
- `class` groups related state and actions. `self` means this particular object;
  `self.radius_nm` is the range of this display, not every display everywhere.
- `@dataclass` supplies convenient record construction. It does not itself
  validate that received numbers are sensible.
- `f'Altitude {altitude}'` builds text with a value inserted. A format such as
  `:,.0f` means a rounded number with separators and no decimal places.
- `and` requires both conditions; `or` accepts either; `not` reverses a condition.
- `*` multiplies numbers, but `*relative` in a call expands a tuple into arguments.
- `lambda` is a small function used for a callback or sorting rule. A callback
  is handed to a library to be called later, for example on a button press.

Some existing statements use `;` to put short steps on one line. The comments
explain those steps without rewriting them as part of this behavior-preserving
pass. `if condition: return ...` is just a compact conditional return.

## Follow one traffic message

The network callback in `traffic_session_loop()` receives a text message.
`json.loads()` turns it into a dictionary. The callback puts that dictionary
and its receipt time in a queue. It does not pause to write the database.

`traffic_writer()` takes an item from the queue and calls `record_traffic()`.
`identity()` prefers the ICAO address as the stable key. The displayed
registration or airline callsign can change while that key stays the same.

The recorder checks coordinates, validity flags, speed, altitude and position
age. It also limits stored reports to one per second per aircraft. A usable
message arriving sooner still updates aircraft identity/last-seen information,
but does not add another trail row. The log's reason explains `saved=False`.

Estimated receiver positions can be accepted within a bounded age, but are
marked `estimated`. This permits smooth motion without presenting guesswork as
fresh observation. The display can draw the corresponding trail differently.

`cleanup_once()` keeps recent history bounded by age and row caps. Database
cleanup is not performed by touching or zooming the display.

## The database is a shared notebook

SQLite stores tables on disk. `aircraft` stores stable identities and names;
`reports` stores the traffic samples; `ownship` stores our position history;
`receiver_status` stores a single current availability/status slot.

- `SELECT` reads rows.
- `INSERT` adds a row; `UPDATE` changes one; `DELETE` removes matching rows.
- `WHERE` limits which rows match. `ORDER BY ... DESC` puts newest/highest first.
- An index is a lookup aid, reducing repeated scans.
- SQL `?` placeholders receive values from the separate tuple. They are not
  Python string substitutions and should not be replaced by concatenated data.
- `with conn:` commits successful changes or rolls them back after an error.
  It does not by itself close the connection. `closing(conn)` handles closure.
- WAL mode lets a reader coexist with a writer. Each worker still has its own
  connection. The display opens the database read-only.

The database's historical column name `tail` now holds an internal key such as
`icao:ABC123`. The readable name lives separately. The historical name `asl`
holds display altitude; it is not proof that every source uses the same altitude
reference. Comparison altitude and reference are separate fields.

## Distances, motion and uncertainty

Horizontal distances are nautical miles. A knot is one nautical mile per hour.
The motion functions divide by 3,600 when they need nautical miles per second.
Altitude is feet. Vertical rates are converted to feet per minute for display
where shown; internal rate calculations may use feet per second.

The local map uses east/north coordinates. The screen uses x/y pixels, with y
increasing downward. Rotation makes track-up possible; clipping trims drawing
to the circular display. Neither rotation nor zoom changes an aircraft's real
position in the database.

`velocity()` uses recent distinct observations for direction and the reported
speed for magnitude. One point cannot reliably establish a track. Small GPS
jitter and implausible jumps are rejected rather than assigned invented headings.

The projection line assumes the current velocity continues for the selected
number of minutes. The horizontal proximity model evaluates five minutes,
independently of the selected projection-line length. Its yellow turn-possibility
test is deliberately conservative; it does not model actual pilot intentions.

Vertical suppression requires fresh comparable pressure-altitude observations
and enough samples to estimate both vertical rates. Unknown is not equivalent
to level flight. A GPS altitude and pressure altitude must not simply be
subtracted as though their references were interchangeable.

## Why background work matters

A thread is a separate flow of work inside one program. A process is a separate
running program with its own memory. A queue passes work/results between them.
An Event is a shared stop signal. `join()` waits for a worker to finish.

The collector separates traffic reception from database work. The display
separates database reading from drawing. Map rasterization uses another process.
Tkinter itself remains on the window's main thread. Its `after()` scheduler asks
for a later callback, then returns control so touches can be processed.

Wall-clock time identifies when reports were received. Monotonic time measures
intervals and cannot jump when the system clock is corrected.

## Airport and map files

`airports.json` contains a dated reference snapshot. Updates combine general
OurAirports geometry/radios with current FAA US reference details. The updater
checks a candidate before atomically replacing the old complete file. Failed
updates keep the working baseline.

Runway extensions require actual endpoint positions. A schematic sketch is
insufficient. Pattern-altitude provenance and current-source checks remain
important even when the sketch looks plausible.

The richer world map lives in a separate `.pmtiles` archive, not in Git. The
legacy compact map uses SQLite; the small local demo uses JSON. Build tools
prepare these expensive datasets on the development computer. The Pi queries
and renders a bounded local view, not all world geometry every frame.

`vendor_pmtiles/` contains upstream third-party code and its license. It was
intentionally left unmodified by this commenting pass.

## Launch files and the browser demo

The four `.bash` files choose the virtual environment, mode, database and display
geometry. `Finder.bash`/`DemoFinder.bash` hold a lock to prevent duplicate collectors.
`Display.bash`/`DemoDisplay.bash` locate DSI-1 and map the touchscreen. Quoted file
paths and argument forwarding preserve spaces. `exec` makes Python become the
supervised process rather than hiding it behind an extra shell.

`configure_pi.py` previews configuration unless explicitly asked to install it.
It generates service/startup text; merely reading the generated text does not
run those commands. Installation permissions are separate from the ordinary user
account under which the application runs.

The iPad website uses JavaScript, not Python. Its Python export script prepares
synthetic trajectories and reference files beforehand. It is a usability demo,
not a live Stratux client. This commenting pass does not update the live site.

## Tests and safe reading edits

`test_*.py` files exercise behavior and failure cases. Assertions state what the
expected result must be; mocks replace a dependency temporarily. They let us
exercise stale GPS, database rules and touch decisions without a real flight.

For this pass, a structural comparison verifies that all 28 Python files have
identical executable syntax trees before/after commenting. Comments change line
numbers but not that structure. Tests provide an additional check. This is not
proof of aviation accuracy, and desktop tests are not Pi hardware validation.

If changing behavior later, start with the smallest relevant function and its
tests. Record what behavior changed; do not hide a logic change among comments.
