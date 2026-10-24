# PakRoads annotation guide

1. **motorcycle** box covers both wheels and the body; riders get their own boxes.
2. **rider** = person controlling the bike; **pillion** = any other person seated on it.
   A person standing next to a stopped bike is a **pedestrian**.
3. **helmet / no_helmet** boxes go on the *head* of riders and pillions only.
4. **qingqi** = motorcycle rickshaw with passenger cabin behind; **rickshaw** = auto-rickshaw
   (three-wheeler, driver in front cabin); **loader_rickshaw** = open cargo bed.
5. Occlusion > 70 %: do not label. Truncated at the frame edge: label the visible part.
6. Reflections, posters and billboards are never labelled.
7. Night: label only what a human can identify without guessing.
8. Edge cases with example images live in `edge_cases/` (add one whenever the team disagreed).
