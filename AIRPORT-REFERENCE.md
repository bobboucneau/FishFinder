v0.4.18 changes pattern arrows to bright red and adds a persistent running-version label. Focused validation: 32 tests passed, including red-arrow rendering and version visibility with the map off and controls hidden.

v0.4.17 changes pattern symbols to brighter, thicker cyan U-shaped arrows. Each final leg aims toward its runway threshold. Eight airport-reference tests pass, including arrow direction/side checks for four headings; the native O22 preview was inspected. Pi touch/readability testing of this revision remains outstanding.

# Airport quick reference — v0.4.16

Tap an airport for a full-screen reference. Back to traffic returns to the scope.
The page emphasizes CTAF (or tower, where identified), weather radio, elevation,
pattern direction and altitude, and a north-up runway sketch. O22 has runway
selection buttons; KCPU opens on 13/31. Helipads do not count as fixed-wing
runways. Additional frequencies, source notes and pagination are under Radios / data.

## Pattern data and defaults

FAA NASR effective 2026-10-01 (expires 2026-10-29) enriches 11,766 matching US
airports in the supplied OurAirports cache. Matches require identifiers and
nearby coordinates. FAA field elevation supersedes the OurAirports value for
matched airports. Right traffic is read per runway end; a present FAA end record
without right traffic uses standard left traffic. Missing ends remain unknown.
FAA source URLs, effective dates and expiry are stored with the cache.

Pattern altitude is always feet MSL. Published AGL values are converted using
field elevation. This first version parses only the exact, runway-specific
remark form `TPA RWY 11/29 800 FT AGL.`; other altitude remarks are retained in
the data page and suppress an airport-wide assumption. A suitable non-towered
US airport with current FAA coverage but no applicable published altitude uses
field elevation + 1,000 ft, in amber with an asterisk and explanatory footnote.
That fallback is a light piston GA reference, not a verified local pattern
altitude or guidance for turbine/large aircraft. No generic fallback is applied
outside current verified coverage, or when an unparsed altitude exception exists.

The supplied source gives O22 17 Right / 35 Left and 11 Right / 29 Left; KCPU
13 Left / 31 Right. General structured TPA is blank at both. Using the current
FAA elevations gives standard-derived 3,121 ft MSL for O22 17/35 and 2,328 ft MSL
for KCPU. O22's 11/29 800 ft AGL remark converts to 2,921 ft MSL. These calculations
are shown as such; the rounded 2,300 ft value in the historical sample image
has not been substituted into the current data.

Arrows are omitted for towered airports at all hours: tower schedules are not
evaluated. Unknown tower/pattern status, expired FAA data, and unsupported data
also omit arrows. A large airport, more than two fixed-wing runways, multiple
CTAF/tower/ground assignments, closed or unsupported runway identifiers, or
recognized conditional pattern remarks produce a referral to the FAA airport
diagram/Chart Supplement (official publications outside the US). This rule is
not a complete assessment of every operational complexity. The sketch does
not include taxiways, obstacles, traffic-pattern tracks or all restrictions;
arrows do not imply permission to depart or replace published procedures.

## Combined updates every 28 days

The existing Update airports button now obtains OurAirports and current FAA
NASR enrichment as one candidate, validates both, and atomically installs the
combined cache. Preview/future FAA cycles are rejected. Failure keeps the old
cache, including its original dates. A file lock prevents concurrent updates.

While the display runs, it checks once a day whether the airport download is
28 days old or its FAA cycle has expired. A due update is attempted in a
background thread using the current network; no Wi-Fi switch is made. Offline
failure keeps the old cache and retries at the next daily check, at restart,
or through the manual button after joining internet Wi-Fi. It cannot obtain
fresh data without an internet connection. There is no Mac/chat automation
required for the Pi's updater. Source expiry is visible on the reference page;
expired pattern arrows/altitudes are suppressed while basic airport data remains.

Sources:
- https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/
- https://nfdc.faa.gov/webContent/28DaySub/TXT_to_CSV_Mapping.pdf
- https://www.faa.gov/air_traffic/publications/aim_html/chap4_section_3.html
- https://ourairports.com/data/

## Install / test

Extract FishFinder-v0.4.16.zip under /usr/local/FishFinder, preserving older
folders and copying your previous settings.json. Keep the supplied enriched
airports.json rather than copying an older cache over it. The world map file,
virtual environment and databases are reused. Use the new folder's launchers;
repoint the collector service with configure_pi.py as in SERVICES.md.

Mac validation: 66 automated tests passed; native full-screen O22/KCPU previews
were visually inspected. The Pi successfully downloaded and parsed the current
FAA enrichment independently without replacing its running cache. Physical
round-screen readability and touch testing of this new page remain outstanding.
The map-data copyright font also increases from 8 to 10 points at 800×800.
