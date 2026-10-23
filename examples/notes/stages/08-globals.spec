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

# Global: merged into every node. Flags every command accepts go here.
[*]
--dir
-v

# Values for --dir, wherever it appears.
[* --dir]
@dir

# A [header] is a node: what to offer after `notes add`.
[add]
--priority

# [node --flag]: the header says --priority takes a value.
# The lines under it are the values to offer.
[add --priority]
low
normal
high

# `notes add TEXT`: free text.
[add #1]

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

# `notes show ID`: ids change, so a spec cannot list them.
[show #1]

# #* is every positional that has no #N of its own: `rm ID...`.
[rm #*]

# `notes import FILE...`: any number of files.
[import #*]
@file

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

# A subcommand's own names are literal lines in its parent: these are
# the words after `notes remote`.
[remote]
add
rm
list

# [node #N] is the Nth positional (a non-flag word), counted from 1.
# `notes remote add NAME HOST`: NAME is #1, a name you make up, so the
# section is empty. An empty slot still counts the word.
[remote add #1]

# HOST is #2.
[remote add #2]
@host

# `notes remote rm NAME`: free text.
[remote rm #1]
