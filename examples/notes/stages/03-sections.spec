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

# A flag is just a candidate that starts with a dash.
--help

# A [header] is a node: what to offer after `notes add`.
[add]
--priority

# After `notes list`. Lines starting with a dash are flags.
[list]
--tag
--sort
--json

# After `notes export`.
[export]
--format
--to
