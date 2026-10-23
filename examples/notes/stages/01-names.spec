# notes: completion spec for examples/notes/bin/notes.
#
# Where it lives: .completions/notes, in the directory above the script's
# bin/. There is nothing to load; it is read afresh on every TAB.
#
# Comments: a line whose first character (after any spaces) is # is ignored,
# and so are blank lines. Comments must be on their own line.
#
# Lines above the first [header] belong to the root: what to offer straight
# after `notes`. One candidate per line, offered exactly as written.
# The subcommand names.
add
list
show
rm
import
export
remote
with
