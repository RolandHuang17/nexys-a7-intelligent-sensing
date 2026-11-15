set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
file mkdir $output
open_checkpoint $checkpoint
set outputs [get_ports {M_CLK M_LRSEL ACL_CSN ACL_SCLK ACL_MOSI UART_RXD_OUT}]
set_max_delay -datapath_only 20.0 -from [all_registers] -to $outputs
source [file join [file dirname [info script]] check_serial_timing.tcl]
report_timing -to $outputs -max_paths 6 -file $output/serial_outputs.rpt
report_exceptions -coverage -file $output/exception_coverage.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file $output/summary.rpt
puts CONSTRAINT_CHECK_DONE
