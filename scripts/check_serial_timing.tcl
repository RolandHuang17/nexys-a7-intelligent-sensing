# Verify actual paths rather than trusting that a syntactically present XDC ran.
set serial_ports {M_CLK ACL_CSN ACL_SCLK ACL_MOSI UART_RXD_OUT TMP_SCL TMP_SDA}
set serial_log [open $output/serial_output_checks.txt w]
foreach name $serial_ports {
    set paths [get_timing_paths -quiet -delay_type max -to [get_ports $name] -max_paths 1]
    if {[llength $paths] != 1} { error "Missing timing path to serial output $name" }
    set path [lindex $paths 0]
    set requirement [get_property REQUIREMENT $path]
    set slack [get_property SLACK $path]
    puts $serial_log "$name requirement_ns=$requirement slack_ns=$slack"
    if {abs($requirement-20.0)>0.001 || $slack<0} {
        error "Serial output $name does not meet its explicit 20 ns propagation budget"
    }
}
close $serial_log
report_timing -to [get_ports $serial_ports] -max_paths 5 -file $output/serial_outputs.rpt
puts SERIAL_OUTPUT_CHECKS_PASSED
