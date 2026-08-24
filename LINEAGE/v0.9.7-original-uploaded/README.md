# Original uploaded v0.9.7 reconstruction

Start from the current canonical tree, remove paths marked
`added_in_chat_worktree` in the recovery manifest, and replace the 17 paths
marked `baseline_modified_in_chat_worktree` with the corresponding files under
`modified-baseline/`.

The recovery manifest records the complete 3,226-file canonical recovery and
the origin classification of every path. This delta representation avoids
retaining 2,134 byte-identical duplicate files.
