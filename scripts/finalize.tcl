set preliminary [get_timing_paths -quiet -delay_type max -max_paths 1 -slack_lesser_than 0]
if {[llength $preliminary] && [get_property SLACK $preliminary] >= -0.5} {
    phys_opt_design -directive AggressiveExplore
    route_design -directive Explore
}
write_checkpoint -force $output/routed.dcp
report_utilization -file $output/utilization_routed.rpt
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $output/timing_summary.rpt
report_timing -from [all_registers] -to [all_registers] -max_paths 10 -nworst 1 -file $output/internal_paths.rpt
report_cdc -file $output/cdc.rpt
report_drc -file $output/drc.rpt
check_timing -verbose -file $output/check_timing.rpt
source $project_root/scripts/check_serial_timing.tcl
if {[llength [get_timing_paths -quiet -delay_type max -max_paths 1 -slack_lesser_than 0]] ||
    [llength [get_timing_paths -quiet -delay_type min -max_paths 1 -slack_lesser_than 0]]} {
    error "Timing closure failed; no acceptance bitstream emitted"
}
write_bitstream -force $output/recorder_top.bit
puts "BUILD_PASSED"
