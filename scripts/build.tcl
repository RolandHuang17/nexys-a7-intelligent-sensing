set project_root [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
file mkdir $output
set_param general.maxThreads 8
read_verilog -sv [lsort [glob $project_root/rtl/*.sv]]
set_property include_dirs [list $project_root/rtl] [current_fileset]
read_xdc $project_root/constraints/nexys_a7_100t.xdc
set music_max_samples 160000
if {[llength $argv]>2} {set music_max_samples [lindex $argv 2]}
synth_design -top recorder_top -part xc7a100tcsg324-1 -generic MUSIC_MAX_SAMPLES=$music_max_samples
write_checkpoint -force $output/synth.dcp
report_utilization -file $output/utilization_synth.rpt
opt_design
place_design
phys_opt_design
write_checkpoint -force $output/placed.dcp
report_timing -from [all_registers] -to [all_registers] -max_paths 10 -nworst 1 -file $output/placed_paths.rpt
set placed_worst [get_timing_paths -quiet -delay_type max -max_paths 1]
if {[llength $placed_worst] && [get_property SLACK $placed_worst] < -1.0} {
    error "Structural setup deficit after placement; repair RTL using placed_paths.rpt before routing"
}
route_design
source $project_root/scripts/finalize.tcl
