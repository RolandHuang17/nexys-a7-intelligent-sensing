set project_root [file normalize [lindex $argv 0]]
set checkpoint [file normalize [lindex $argv 1]]
set output [file normalize [lindex $argv 2]]
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
source $project_root/scripts/finalize.tcl
