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

# [node --flag]: the header says --priority takes a value.
# The lines under it are the values to offer.
[add --priority]
low
normal
high

# After `notes list`. Lines starting with a dash are flags.
[list]
--tag
--sort
--json

# --tag takes a value, but there is nothing fixed to suggest, so this
# section is empty. An empty header still declares the flag, so the
# word after --tag is read as its value.
[list --tag]

# Values for --sort.
[list --sort]
date
title

# After `notes export`.
[export]
--format
--to

# Values for --format.
[export --format]
md
txt
json

# @file offers files in the current directory. The kinds are @file,
# @dir (directories), @user (login names) and @host (hostnames).
[export --to]
@file
