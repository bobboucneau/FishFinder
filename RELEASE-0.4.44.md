# FishFinder 0.4.44 — Show on map

Airport information and its radio/data page include Show on map. It opens a
temporary north-up airport-centered view using the existing ground map renderer.
Ranges remain 2/5/10/20 NM. Back to airport restores the previous airport page and
scope range. This does not change settings, actual ownship position, the saved
airport, or the main scope's fallback/last-fix anchor.

With fresh ownship position, a light-blue line goes from the airport toward
ownship: to its actual local position if within view, or to the edge along the
great-circle initial bearing if farther away. The header explicitly labels the
bearing/distance TO the airport. The reciprocal line is a direct bearing reference,
not a runway-aligned approach or suggested flight path. Without fresh ownship
position there is no line, and position unavailability is explicit.

Ownship is drawn at its actual offset when within range; a center airport symbol
is not an ownship marker. Traffic proximity assessment remains referenced to real
ownship, not the airport. Other map objects in this inspection view are display
only; its touch controls are ranges and Back, avoiding accidental nested pages.

Tests cover temporary center/range restoration, preserving position/settings,
offset ownship drawing, fresh/stale/missing positions, true-bearing edge clipping,
and unchanged ownship-relative traffic assessment. Reuses the same map worker;
does not start a second map renderer. Actual touchscreen/ground-map behavior
requires user verification on the Pi.
