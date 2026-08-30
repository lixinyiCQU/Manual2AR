# Bambu A1 mini pre-print plate inspection exemplars

This profile is intentionally **exemplar-guided**. The images under
`references/` are runtime prompt references, not an independent test set:

- `p2_clean_build_plate.jpg`: clean, printable reference state.
- `p1_foreign_object_and_residue.jpg`: one central orange foreign object and
  one thin orange residue strip at the lower plate edge.

The profile SHA-256 hashes are returned by the inspection API and written into
Unity evidence captures. Coordinates produced by Qwen may describe only the
first image in the ordered request: the current camera frame, followed by P2
and then P1.

