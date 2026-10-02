# Original character identities

The client roster now retains sixteen source characters. Existing conversation
identities keep their stable IDs: `anime-chiffon` → Chiffon, `anime-ichigo` →
Ichigo, `anime-lime` → Lime, `anime-mafuyu` → Mafuyu, and `anime-plum` → Plum.
No new personas, voices or scenarios were created for the eleven previews.

Identity normalization runs after scenario overlays, so a translated name in
old authoring or history cannot replace the current name. Public cards and the
planner use the same names and revision `2026-10-02-original-names-v1`. Existing
personality, voice selection, scenario IDs, stored memories and conversations
remain attached to their original character IDs. Other server personas remain
available for a future client roster restoration.

Only twelve existing opening lines were re-recorded with their approved voices
to replace the spoken old names in Chiffon, Ichigo, Mafuyu and Plum. Their current
opening IDs use version 3; version 2 remains a legacy edition for historical
playback. Lime keeps its existing English version 2 recordings. Audio and
provider credentials remain private. Per-character content versions avoid
regenerating unchanged roles.

Validation: 28 tests passed across original identity, opening registration and
reset, scenario ownership/language, prepared response handoff and prepared goal
regression. The tests use fake providers and make no paid AI calls. The private
authoring check verifies 78 current/legacy clips for eleven existing server
personas. The client receives only its five conversational roles.
