puts "TOOL_VERSION:[version -short]"
puts "PARTS:[get_parts -quiet xc7a100tcsg324-1]"
open_hw_manager
set server_url [lindex $argv 0]
set rc [catch {
    connect_hw_server -url $server_url
    set targets {}
    for {set i 0} {$i < 3} {incr i} {
        refresh_hw_server
        set targets [get_hw_targets -quiet]
        puts "TARGET_COUNT:[llength $targets]"
        if {[llength $targets] != 0} {break}
        after 1000
    }
    foreach target $targets {puts "TARGET:$target"}
    if {[llength $targets] == 1} {
        current_hw_target [lindex $targets 0]
        open_hw_target
        foreach device [get_hw_devices -quiet] {
            puts "DEVICE:$device PART:[get_property PART $device]"
        }
        close_hw_target
    }
    disconnect_hw_server
} message]
close_hw_manager
if {$rc} {puts stderr "ENUMERATION_ERROR:$message"; exit 2}
exit 0
