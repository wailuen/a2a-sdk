---
id: LRN-231
title: Wave archive note verified against working tree, not the landed commit
category: ops
severity: high
source: redteam
date: 2026-09-03
---

## What happened
The commits landing w039 contain no CHANGELOG entry for GH-145/147/149/150
— `git show HEAD:CHANGELOG.md` still tops out at [0.5.44] — yet the wave
file was archived with a note claiming "All four ACs above landed in
code." The corrected CHANGELOG/DESIGN text existed only as an uncommitted
diff when the archive note was written.

## Root cause
The archival check read the working tree (where the fix looked done)
instead of the actual committed ref, so an uncommitted doc edit was
accepted as satisfying an acceptance criterion that names a file.

## Check
For any AC that names a doc file, run `git show <landed-sha>:<file>` (not
a plain file read) and grep it for the expected heading/content before
marking the AC met. `git status --short` must be clean for that file at
archive time.

## Prevention
When planning a wave's archive step, require the archiver to diff the
AC's target file against the commit that closes the wave, not the
working tree — an AC naming a file is unmet until `git show HEAD:<file>`
contains it.
